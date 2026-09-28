"""Code metric: every link in the digest must come from the fixture's candidates (1 = pass).

Self-contained on purpose: agents-cli exec's metric files without __file__,
so they can't import shared helpers. Keep the helpers in sync across metrics.
"""

import json
import re
from pathlib import Path

FIXTURES = Path("tests/eval/fixtures")  # eval runs from the project root
_FIXTURE_RE = re.compile(r"fixture:([\w\-]+)")
_LINK_RE = re.compile(r"\]\((https?://[^)\s]+)\)")


def _text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(
            p.get("text", "") for p in value.get("parts", []) if isinstance(p, dict)
        )
    return str(value or "")


def evaluate(instance):
    m = _FIXTURE_RE.search(_text(instance.get("prompt")))
    if not m:
        return {"score": 0, "explanation": "no fixture in prompt"}
    fixture = json.loads((FIXTURES / f"{m.group(1)}.json").read_text())
    allowed = {i["url"] for i in fixture["feed_items"]}
    found = _LINK_RE.findall(_text(instance.get("response")))
    if not found:
        return {"score": 0, "explanation": "digest has no links"}
    bad = [u for u in found if u not in allowed]
    if bad:
        return {
            "score": 0,
            "explanation": f"{len(bad)} link(s) not in candidates: {bad[:3]}",
        }
    return {"score": 1, "explanation": f"all {len(found)} links grounded"}
