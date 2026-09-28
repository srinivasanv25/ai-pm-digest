"""Editor output schema and the code-side checks applied to it.

The editor cites candidates by id (f3, s2, …). `assemble_digest` maps ids back
to real URLs; anything that doesn't resolve is dropped, so the email can only
ever link to something a feed or a Google Search result actually returned.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app import config
from app.collect import normalize_url

Section = Literal["models", "builder", "strategy", "research"]


class EditorItem(BaseModel):
    id: str = Field(description="Candidate id exactly as given, e.g. 'f12' or 's3'.")
    section: Section = Field(description="Which digest section this item belongs in.")
    headline: str = Field(
        description="Plain, specific headline. No clickbait, max ~12 words."
    )
    summary: str = Field(description="1-2 sentences: what happened, in your own words.")
    why_it_matters: str = Field(
        description="One sentence on why a PM who builds with AI should care or what they could do with it."
    )


class EditorDigest(BaseModel):
    lead_id: str = Field(
        description="Id of the single most important item today; must also appear in items."
    )
    lead_blurb: str = Field(
        description="2-3 sentences: why this is the one thing to read today."
    )
    items: list[EditorItem] = Field(
        description="8-12 items on a normal day, fewer on a slow day. Most important first within each section."
    )
    slow_day_note: str | None = Field(
        default=None,
        description="Only if fewer than 6 items are worth sending: one short sentence saying so.",
    )


def assemble_digest(
    editor: dict, candidates: dict[str, dict], date_label: str, failed_feeds: list[str]
) -> dict:
    """Validate editor output against the candidate list and build the final digest."""
    items, used_urls, dropped = [], set(), []
    for raw in editor.get("items", []):
        cand = candidates.get(str(raw.get("id", "")).strip())
        if cand is None:
            dropped.append(raw.get("id"))
            continue
        key = normalize_url(cand["url"])
        if key in used_urls:
            continue
        used_urls.add(key)
        items.append(
            {
                "id": cand["id"],
                "section": raw.get("section")
                if raw.get("section") in config.SECTIONS
                else "builder",
                "headline": (raw.get("headline") or cand["title"]).strip(),
                "summary": (raw.get("summary") or "").strip(),
                "why_it_matters": (raw.get("why_it_matters") or "").strip(),
                "url": cand["url"],
                "source": cand["source"],
            }
        )
        if len(items) >= config.MAX_ITEMS:
            break

    lead = next(
        (i for i in items if i["id"] == editor.get("lead_id")),
        items[0] if items else None,
    )
    sections = [
        {
            "key": key,
            "title": title,
            "items": [i for i in items if i["section"] == key and i is not lead],
        }
        for key, title in config.SECTIONS.items()
    ]
    return {
        "date": date_label,
        "lead": lead,
        "lead_blurb": (editor.get("lead_blurb") or "").strip() if lead else "",
        "sections": [s for s in sections if s["items"]],
        "item_count": len(items),
        "slow_day_note": editor.get("slow_day_note"),
        "failed_feeds": failed_feeds,
        "dropped_ids": [d for d in dropped if d],
        "sendable": len(items) >= config.MIN_ITEMS_TO_SEND,
    }
