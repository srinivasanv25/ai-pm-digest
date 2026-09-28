"""LLM-as-judge: editorial quality of the digest for a PM builder (1-5).

Self-contained on purpose: agents-cli exec's metric files without __file__,
so they can't import shared helpers. Keep the helpers in sync across metrics.
"""

import json
import re
import threading
from pathlib import Path

from google import genai
from google.genai import types
from pydantic import BaseModel

FIXTURES = Path("tests/eval/fixtures")  # eval runs from the project root
_FIXTURE_RE = re.compile(r"fixture:([\w\-]+)")
_local = threading.local()


def _text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(
            p.get("text", "") for p in value.get("parts", []) if isinstance(p, dict)
        )
    return str(value or "")


class _Verdict(BaseModel):
    dedup: int
    relevance: int
    faithfulness: int
    why_it_matters: int
    score: int
    explanation: str


def _client() -> genai.Client:
    client = getattr(_local, "client", None)
    if client is None:
        client = _local.client = genai.Client()
    return client


RUBRIC = """You are grading a daily AI-news email for product managers who build with AI.
Score each dimension 1-5 (5 = excellent):
- dedup: no story appears twice; when several candidates cover one story, the most primary source was chosen.
- relevance: the picks are the candidates most useful to a PM builder; junk (memecoins, job posts,
  minor funding, fluff) is excluded; ranking puts the most consequential item first.
- faithfulness: headlines and summaries say nothing the candidate text doesn't support; no overclaiming.
- why_it_matters: each line is specific and actionable for a PM builder, not generic filler or speculation.
score = the minimum of the four. Be strict: 5 means you would not change anything.
{note}
CANDIDATES:
{candidates}

DIGEST:
{digest}
"""


def evaluate(instance):
    m = _FIXTURE_RE.search(_text(instance.get("prompt")))
    if not m:
        return {"score": 0, "explanation": "no fixture in prompt"}
    fixture = json.loads((FIXTURES / f"{m.group(1)}.json").read_text())
    candidates = "\n".join(
        f"- {i['title']} | {i['source']} | {i['url']}\n  {i.get('summary', '')}"
        for i in fixture["feed_items"]
    )
    note = fixture.get("expect", {}).get("note", "")
    prompt = RUBRIC.format(
        note=f"Case note: {note}" if note else "",
        candidates=candidates,
        digest=_text(instance.get("response")),
    )
    result = _client().models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=_Verdict,
        ),
    )
    v = result.parsed
    if v is None:
        return {"score": 0, "explanation": result.text or ""}
    detail = f"dedup={v.dedup} relevance={v.relevance} faithfulness={v.faithfulness} why={v.why_it_matters}. "
    return {"score": max(1, min(5, v.score)), "explanation": detail + v.explanation}
