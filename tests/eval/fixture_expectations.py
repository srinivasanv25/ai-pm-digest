"""Code metric: per-fixture expectations (item count, must/must-not links, slow-day note). 1 = all pass.

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
    response = _text(instance.get("response"))
    exp = fixture.get("expect", {})
    found = _LINK_RE.findall(response)
    unique = list(dict.fromkeys(found))
    failures = []

    if len(unique) != len(found):
        failures.append("same link appears twice")
    lo, hi = exp.get("min_items", 1), exp.get("max_items", 12)
    if not lo <= len(unique) <= hi:
        failures.append(f"{len(unique)} items, expected {lo}-{hi}")
    for url in exp.get("must_include_urls", []):
        if url not in unique:
            failures.append(f"missing required {url}")
    for url in exp.get("must_not_include_urls", []):
        if url in unique:
            failures.append(f"included forbidden {url}")
    if exp.get("require_slow_day_note"):
        # The slow-day note renders as an italic line between the title and the lead.
        head = response.split("## If you read one thing")[0]
        if not re.search(r"^_.+_$", head, re.MULTILINE):
            failures.append("no slow-day note")
    why_count = len(re.findall(r"why it matters", response, re.IGNORECASE))
    if why_count < len(unique):
        failures.append(
            f"only {why_count} 'why it matters' lines for {len(unique)} items"
        )

    if failures:
        return {"score": 0, "explanation": "; ".join(failures)}
    return {"score": 1, "explanation": f"{len(unique)} items, all expectations met"}
