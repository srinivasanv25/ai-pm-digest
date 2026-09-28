"""Turn an assembled digest into Markdown (agent reply, plain-text email) and HTML (email body)."""

from html import escape


def to_markdown(d: dict) -> str:
    if not d.get("lead"):
        return f"# AI for PM Builders · {d['date']}\n\nNothing worth sending today."
    lines = [f"# AI for PM Builders · {d['date']}", ""]
    if d.get("slow_day_note"):
        lines += [f"_{d['slow_day_note']}_", ""]
    lead = d["lead"]
    lines += [
        "## If you read one thing",
        f"**[{lead['headline']}]({lead['url']})** · {lead['source']}",
        "",
        d["lead_blurb"] or lead["summary"],
        "",
        f"**Why it matters:** {lead['why_it_matters']}",
        "",
    ]
    for section in d["sections"]:
        lines += [f"## {section['title']}", ""]
        for i in section["items"]:
            lines += [
                f"- **[{i['headline']}]({i['url']})** · {i['source']}  ",
                f"  {i['summary']}  ",
                f"  _Why it matters:_ {i['why_it_matters']}",
                "",
            ]
    if d.get("failed_feeds"):
        lines += [f"_Feeds unavailable today: {', '.join(d['failed_feeds'])}_"]
    return "\n".join(lines).rstrip() + "\n"


# Email clients ignore <style> blocks and most modern CSS, so everything is inline.
_INK, _MUTED, _ACCENT, _RULE, _BG, _CARD = (
    "#1a1a1a",
    "#5f6368",
    "#1a56db",
    "#e6e6e6",
    "#f5f5f2",
    "#ffffff",
)
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"


def _item_html(i: dict, big: bool = False) -> str:
    size = "19px" if big else "16px"
    return f"""
<tr><td style="padding:0 0 20px 0;">
  <a href="{escape(i["url"], quote=True)}" style="font-size:{size};font-weight:600;line-height:1.35;color:{_INK};text-decoration:none;">{escape(i["headline"])}</a>
  <div style="font-size:12px;color:{_MUTED};padding:3px 0 6px 0;letter-spacing:.02em;">{escape(i["source"])}</div>
  <div style="font-size:15px;line-height:1.55;color:{_INK};">{escape(i["summary"])}</div>
  <div style="font-size:14px;line-height:1.5;color:{_INK};padding-top:6px;"><span style="color:{_ACCENT};font-weight:600;">Why it matters</span> · {escape(i["why_it_matters"])}</div>
</td></tr>"""


def to_html(d: dict) -> str:
    lead = d["lead"]
    parts = [
        f"""<!doctype html><html><body style="margin:0;padding:0;background:{_BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_BG};"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:{_CARD};border-radius:10px;font-family:{_FONT};">
<tr><td style="padding:28px 28px 8px 28px;">
  <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:{_MUTED};">{escape(d["date"])} · {d["item_count"]} picks</div>
  <div style="font-size:24px;font-weight:700;color:{_INK};padding-top:4px;">AI for PM Builders</div>
</td></tr>"""
    ]
    if d.get("slow_day_note"):
        parts.append(
            f'<tr><td style="padding:4px 28px 0 28px;font-size:14px;font-style:italic;color:{_MUTED};">{escape(d["slow_day_note"])}</td></tr>'
        )
    parts.append(
        f"""<tr><td style="padding:20px 28px 4px 28px;">
  <div style="border-left:3px solid {_ACCENT};padding:2px 0 2px 16px;">
    <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:{_ACCENT};font-weight:700;padding-bottom:8px;">If you read one thing</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{_item_html({**lead, "summary": d["lead_blurb"] or lead["summary"]}, big=True)}</table>
  </div>
</td></tr>"""
    )
    for section in d["sections"]:
        rows = "".join(_item_html(i) for i in section["items"])
        parts.append(
            f"""<tr><td style="padding:24px 28px 0 28px;">
  <div style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;font-weight:700;color:{_MUTED};border-bottom:1px solid {_RULE};padding-bottom:8px;margin-bottom:16px;">{escape(section["title"])}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table>
</td></tr>"""
        )
    footer = "Curated by your ADK digest agent from RSS feeds and Google Search."
    if d.get("failed_feeds"):
        footer += f" Unavailable today: {escape(', '.join(d['failed_feeds']))}."
    parts.append(
        f"""<tr><td style="padding:12px 28px 28px 28px;font-size:12px;line-height:1.5;color:{_MUTED};border-top:1px solid {_RULE};">{footer}</td></tr>
</table></td></tr></table></body></html>"""
    )
    return "".join(parts)
