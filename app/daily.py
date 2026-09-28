"""One daily digest run: build with the agent, render, send, remember what was sent.

Shared by the CLI (run_digest.py) and the Cloud Scheduler endpoint
(POST /digest/send in fast_api_app.py). Sending lives here, outside the agent:
the recipient comes from the environment and the model has no way to change it.
"""

import logging
import time

from google.adk.runners import InMemoryRunner
from google.genai import types

from app import config
from app.agent import app as adk_app
from app.collect import local_today, record_seen, record_sent_headlines, sent_today
from app.mailer import send_digest
from app.render import to_html, to_markdown

log = logging.getLogger(__name__)


async def build_digest(prompt: str) -> dict:
    runner = InMemoryRunner(app=adk_app)
    session = await runner.session_service.create_session(
        app_name=adk_app.name, user_id="digest"
    )
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    async for _ in runner.run_async(
        user_id="digest", session_id=session.id, new_message=message
    ):
        pass
    session = await runner.session_service.get_session(
        app_name=adk_app.name, user_id="digest", session_id=session.id
    )
    return session.state.get("digest") or {}


async def run_daily(
    *, send: bool = True, fixture: str | None = None, force: bool = False
) -> dict:
    """Returns a summary dict. `status` is one of: sent, dry_run, skipped, failed."""
    if send and not force and sent_today():
        log.info("already sent today; skipping (pass force to override)")
        return {"status": "skipped", "reason": "already sent today"}

    prompt = (
        f"Build the digest fixture:{fixture}" if fixture else "Build today's digest."
    )
    started = time.monotonic()
    digest = await build_digest(prompt)
    log.info("digest built in %.0fs", time.monotonic() - started)
    if not digest:
        log.error("agent produced no digest")
        return {"status": "failed", "reason": "agent produced no digest"}
    if digest["dropped_ids"]:
        log.warning("dropped unknown ids from editor output: %s", digest["dropped_ids"])

    summary = {
        "items": digest["item_count"],
        "unavailable": digest["failed_feeds"],
        "html": to_html(digest) if digest["lead"] else "",
    }
    if not digest["sendable"]:
        log.warning(
            "only %d valid items (minimum %d); not sending",
            digest["item_count"],
            config.MIN_ITEMS_TO_SEND,
        )
        return {**summary, "status": "skipped", "reason": "too few items"}
    if not send or fixture:
        return {**summary, "status": "dry_run"}

    lead = digest["lead"]["headline"]
    subject = f"AI for PM Builders · {local_today():%b %-d} · {lead}"
    recipient = send_digest(subject, summary["html"], to_markdown(digest))
    all_items = [digest["lead"]] + [i for s in digest["sections"] for i in s["items"]]
    record_seen([i["url"] for i in all_items])
    record_sent_headlines([i["headline"] for i in all_items])
    log.info("sent %d items to %s", digest["item_count"], recipient)
    return {**summary, "status": "sent"}
