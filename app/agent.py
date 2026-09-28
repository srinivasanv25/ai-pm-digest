# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""AI PM Digest: collect → scout → edit → assemble.

Pipeline (SequentialAgent "ai_pm_digest"):
  before_agent: collect_candidates  Python, pulls RSS feeds into state["feed_items"]
  scout_agent                       google_search for big stories the feeds missed
      after_agent: collect_scout_sources  grounding metadata → state["scout_items"]
  editor_agent                      picks + writes, cites candidate ids only
  DigestAssembler                   Python, ids → URLs, drops anything unknown

Sending email is NOT part of the agent. run_digest.py reads state["digest"]
after the run and sends it, so the model can never choose a recipient.

Eval / offline mode: a message containing "fixture:<name>" loads
tests/eval/fixtures/<name>.json instead of live feeds and skips the scout.
"""

import asyncio
import datetime
import json
import logging
import re
from typing import AsyncGenerator
from zoneinfo import ZoneInfo

import httpx
from google.adk.agents import Agent, BaseAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.apps import App
from google.adk.events import Event, EventActions
from google.adk.models import Gemini, LlmRequest, LlmResponse
from google.adk.tools import google_search
from google.genai import types

from app import config
from app.collect import (
    clean_text,
    collect_feeds,
    is_article_url,
    load_recent_headlines,
    load_seen,
    normalize_url,
)
from app.digest import EditorDigest, assemble_digest
from app.render import to_markdown

log = logging.getLogger(__name__)

MODEL = "gemini-3.8-flash"

_FIXTURE_RE = re.compile(r"fixture:([\w\-]+)")


def _model(attempts: int = 6) -> Gemini:
    # Unattended daily job: ride out 429/503 spikes with longer backoff than chat would.
    return Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(
            attempts=attempts, initial_delay=5, max_delay=60
        ),
    )


def _today_label() -> str:
    return datetime.datetime.now(ZoneInfo("America/Los_Angeles")).strftime(
        "%A, %B %-d, %Y"
    )


def _message_text(ctx: ReadonlyContext) -> str:
    content = ctx.user_content
    if not content or not content.parts:
        return ""
    return " ".join(p.text for p in content.parts if p.text)


def _format_candidates(items: list[dict]) -> str:
    lines = []
    for it in items:
        lines.append(
            f"[{it['id']}] {it['title']} | {it['source']} | {it.get('published', '')}\n"
            f"    {it.get('summary', '')}"
        )
    return "\n".join(lines) or "(none)"


# --- Step 1: collect (Python) ----------------------------------------------


async def collect_candidates(callback_context: CallbackContext) -> None:
    state = callback_context.state
    state["date_label"] = _today_label()
    fixture = _FIXTURE_RE.search(_message_text(callback_context))
    if fixture:
        data = json.loads(
            (config.FIXTURES_DIR / f"{fixture.group(1)}.json").read_text()
        )
        for i, item in enumerate(data["feed_items"], start=1):
            item["id"] = f"f{i}"
        state["feed_items"] = data["feed_items"]
        state["failed_feeds"] = data.get("failed_feeds", [])
        state["date_label"] = data.get("date_label", state["date_label"])
        state["recent_headlines"] = data.get("recent_headlines", [])
        state["offline"] = True
        return
    items, failed = await collect_feeds(load_seen())
    state["feed_items"] = items
    state["failed_feeds"] = failed
    state["recent_headlines"] = load_recent_headlines()
    state["offline"] = False
    log.info("collected %d feed candidates (%d feeds failed)", len(items), len(failed))


# --- Step 2: scout (LLM + Google Search) -------------------------------------


def _recent_headlines(ctx: ReadonlyContext) -> str:
    return (
        "\n".join(f"- {h}" for h in ctx.state.get("recent_headlines", [])) or "(none)"
    )


def scout_instruction(ctx: ReadonlyContext) -> str:
    titles = "\n".join(
        f"- {i['title']} ({i['source']})" for i in ctx.state.get("feed_items", [])
    )
    return f"""You scout AI news for a product manager who builds with AI. Today is {ctx.state.get("date_label")}.

We already have these stories from RSS feeds:
{titles or "(none)"}

These stories were already sent in recent digests (skip them, even from other outlets):
{_recent_headlines(ctx)}

Use Google Search to find up to 5 genuinely important AI stories from the last 24-36 hours
that are NOT already covered above. Prioritise: new model releases or pricing/API changes from
major labs, significant developer tools or agent frameworks, notable AI product launches or
business moves, and widely discussed research. Skip funding rounds under $100M, opinion pieces,
listicles, rumours, and anything older than 3 days.

For each story write one line: the headline, the publisher, and one sentence on what happened.
If nothing important is missing, say "Nothing major missing." Do not invent stories."""


async def skip_scout_offline(callback_context: CallbackContext) -> types.Content | None:
    if callback_context.state.get("offline"):
        callback_context.state["scout_items"] = []
        return types.Content(
            role="model", parts=[types.Part(text="Scout skipped (offline fixture).")]
        )
    return None


async def scout_failed(
    callback_context: CallbackContext, llm_request: LlmRequest, error: Exception
) -> LlmResponse:
    """Search is optional: if it errors (e.g. no search quota), continue feeds-only."""
    log.warning(
        "scout search unavailable, continuing with feeds only: %s", str(error)[:120]
    )
    callback_context.state["scout_error"] = str(error)[:200]
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(text="Search unavailable; feeds only today.")],
        )
    )


_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']|<title[^>]*>([^<]+)</title>',
    re.IGNORECASE,
)


async def _resolve(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    """Follow Google's grounding redirect to the publisher URL and read the article's real title.

    Grounding can attach a claim to the wrong page, so the editor compares the
    claim against this title before trusting a search candidate.
    """
    try:
        resp = await client.get(url)
    except httpx.HTTPError:
        return url, ""
    match = _TITLE_RE.search(resp.text[:200_000]) if resp.is_success else None
    title = clean_text(next((g for g in match.groups() if g), ""), 200) if match else ""
    return str(resp.url), title


async def collect_scout_sources(callback_context: CallbackContext) -> None:
    """Adapted from deep-search's collect_research_sources_callback."""
    session = callback_context._invocation_context.session
    raw: dict[str, dict] = {}
    for event in session.events:
        gm = event.grounding_metadata
        if event.author != "scout_agent" or not (gm and gm.grounding_chunks):
            continue
        claims: dict[int, list[str]] = {}
        for support in gm.grounding_supports or []:
            for idx in support.grounding_chunk_indices or []:
                if support.segment and support.segment.text:
                    claims.setdefault(idx, []).append(support.segment.text.strip())
        for idx, chunk in enumerate(gm.grounding_chunks):
            if not chunk.web or not chunk.web.uri:
                continue
            entry = raw.setdefault(
                chunk.web.uri,
                {
                    "title": chunk.web.title or chunk.web.domain or "",
                    "domain": chunk.web.domain or "",
                    "claims": [],
                },
            )
            entry["claims"].extend(claims.get(idx, []))

    async with httpx.AsyncClient(
        timeout=10, follow_redirects=True, headers={"User-Agent": config.USER_AGENT}
    ) as client:
        resolved = await asyncio.gather(*(_resolve(client, u) for u in raw))

    feed_urls = {
        normalize_url(i["url"]) for i in callback_context.state.get("feed_items", [])
    }
    seen = load_seen()
    scout_items, used = [], set()
    for (uri, meta), (url, page_title) in zip(raw.items(), resolved, strict=True):
        key = normalize_url(url)
        if (
            "grounding-api-redirect" in url
            or not is_article_url(url)
            or key in feed_urls
            or key in seen
            or key in used
        ):
            continue
        used.add(key)
        scout_items.append(
            {
                "id": f"s{len(scout_items) + 1}",
                "title": page_title or meta["title"],
                "url": url,
                "source": meta["domain"] or meta["title"],
                "summary": "Search claim: "
                + clean_text(" ".join(dict.fromkeys(meta["claims"]))),
            }
        )
        if len(scout_items) >= config.MAX_SCOUT_SOURCES:
            break
    callback_context.state["scout_items"] = scout_items
    log.info("scout done: %d search sources kept of %d", len(scout_items), len(raw))


scout_agent = Agent(
    name="scout_agent",
    # Search is optional, so fail fast (e.g. no search quota) and fall back to feeds.
    model=_model(attempts=2),
    instruction=scout_instruction,
    tools=[google_search],
    include_contents="none",
    before_agent_callback=skip_scout_offline,
    after_agent_callback=collect_scout_sources,
    on_model_error_callback=scout_failed,
    output_key="scout_notes",
)


# --- Step 3: editor (LLM, structured output) ---------------------------------


def editor_instruction(ctx: ReadonlyContext) -> str:
    return f"""You are the editor of "AI for PM Builders", a daily email for product managers who
build with AI (they prototype with coding agents, ship LLM features, and track the model landscape).
Today is {ctx.state.get("date_label")}.

Pick the 8-12 most useful items from the CANDIDATES below and write the digest.

Rules:
- Cite each item by its id exactly as shown in brackets (e.g. f7, s2). Only use ids from the list.
- Merge duplicates: if several candidates cover the same story, include it ONCE, citing the most
  primary source (the lab or company's own post beats press coverage; press beats aggregators).
- Sections: models = new models, pricing, API or capability changes from labs;
  builder = tools, frameworks, coding agents, launches a builder could use this week;
  strategy = product/business moves, PM craft, adoption, essays with a clear takeaway;
  research = at most 2 papers or technical ideas, explained without math.
- Rank by impact on someone building AI products, not by hype. Prefer concrete news over opinion.
- Skip: minor funding news, generic "AI will change X" takes, pure crypto, job posts, anything
  you cannot tell what it is from the candidate text.
- Write summaries in your own words. Do not add facts that are not in the candidate text.
- "why_it_matters" must be specific and actionable for a PM builder (what it changes, what to try,
  what decision it affects) — never generic like "this is important for AI". Ground it in what the
  candidate says happened; don't predict what companies will do next.
- Headlines must match the source's claim: no stronger wording than the candidate text supports.
- Search candidates show the article's real page title plus a "Search claim". If the claim is not
  clearly about the same story as the title, skip that candidate.
- ALREADY SENT stories must be skipped, even when a different outlet covers them. Only include one
  if the candidate reports a genuinely new development, and say what is new in the headline.
- lead_id is the single item most worth reading today; it must also be in items.
- lead_blurb follows the same rules as why_it_matters: say what happened and why it matters now;
  no forecasts ("will likely", "expect").
- On a slow day return fewer items (minimum 3 if possible) and set slow_day_note. Never pad.

ALREADY SENT in recent digests:
{_recent_headlines(ctx)}

CANDIDATES (RSS feeds):
{_format_candidates(ctx.state.get("feed_items", []))}

CANDIDATES (Google Search scout):
{_format_candidates(ctx.state.get("scout_items", []))}
"""


editor_agent = Agent(
    name="editor_agent",
    model=_model(),
    instruction=editor_instruction,
    include_contents="none",
    output_schema=EditorDigest,
    output_key="editor_digest",
    generate_content_config=types.GenerateContentConfig(temperature=0.3),
)


# --- Step 4: assemble (Python) ----------------------------------------------


class DigestAssembler(BaseAgent):
    """Maps editor ids back to real URLs, drops unknown ids, emits the final digest."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        editor = state.get("editor_digest") or {}
        if isinstance(editor, str):
            editor = json.loads(editor)
        candidates = {
            i["id"]: i
            for i in state.get("feed_items", []) + state.get("scout_items", [])
        }
        unavailable = list(state.get("failed_feeds", []))
        if state.get("scout_error"):
            unavailable.append("Google Search")
        log.info("editor done: %d items proposed", len(editor.get("items", [])))
        digest = assemble_digest(
            editor, candidates, state.get("date_label", ""), unavailable
        )
        yield Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            content=types.Content(
                role="model", parts=[types.Part(text=to_markdown(digest))]
            ),
            actions=EventActions(state_delta={"digest": digest}),
        )


root_agent = SequentialAgent(
    # Keep in sync with agents-cli-manifest.yaml: agents-cli derives this name
    # from the project `name:` recorded there, and telemetry reports it as
    # gen_ai.agent.name. Renaming the agent only here makes the two disagree,
    # and anything selecting traces by name stops finding this agent's.
    name="ai_pm_digest",
    description="Builds a daily AI news digest for product managers who build with AI.",
    sub_agents=[scout_agent, editor_agent, DigestAssembler(name="digest_assembler")],
    before_agent_callback=collect_candidates,
)

app = App(
    root_agent=root_agent,
    name="app",
)
