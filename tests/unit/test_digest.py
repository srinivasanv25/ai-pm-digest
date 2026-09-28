"""Code-correctness tests for the deterministic parts (no LLM calls)."""

from app.collect import clean_text, normalize_url
from app.digest import assemble_digest
from app.render import to_html, to_markdown

CANDIDATES = {
    "f1": {
        "id": "f1",
        "title": "Lab post",
        "url": "https://lab.example/news/model-2",
        "source": "Lab",
    },
    "f2": {
        "id": "f2",
        "title": "Press copy",
        "url": "https://www.lab.example/news/model-2/?utm_source=x",
        "source": "Press",
    },
    "f3": {
        "id": "f3",
        "title": "Tool",
        "url": "https://tool.example/launch",
        "source": "HN",
    },
    "s1": {
        "id": "s1",
        "title": "Search find",
        "url": "https://news.example/story",
        "source": "news.example",
    },
}


def _item(id_, section="builder"):
    return {
        "id": id_,
        "section": section,
        "headline": f"H {id_}",
        "summary": "S",
        "why_it_matters": "W",
    }


def test_normalize_url_strips_tracking_www_slash_fragment():
    assert (
        normalize_url("http://www.A.example/x/?utm_source=n&id=3#frag")
        == "https://a.example/x?id=3"
    )


def test_clean_text_strips_html_and_truncates():
    assert clean_text("<p>Hello&nbsp;<b>world</b></p>") == "Hello world"
    assert clean_text("word " * 200, 50).endswith("…")


def test_unknown_ids_are_dropped():
    d = assemble_digest(
        {"lead_id": "f1", "items": [_item("f1"), _item("f99"), _item("x")]},
        CANDIDATES,
        "Today",
        [],
    )
    assert d["item_count"] == 1
    assert d["dropped_ids"] == ["f99", "x"]


def test_same_story_url_variants_are_deduped():
    d = assemble_digest(
        {"lead_id": "f1", "items": [_item("f1"), _item("f2"), _item("f3")]},
        CANDIDATES,
        "Today",
        [],
    )
    assert [i["id"] for s in d["sections"] for i in s["items"]] == ["f3"]
    assert d["lead"]["id"] == "f1"


def test_lead_falls_back_to_first_item_and_urls_come_from_candidates():
    d = assemble_digest(
        {"lead_id": "nope", "items": [_item("s1", "models"), _item("f3")]},
        CANDIDATES,
        "Today",
        [],
    )
    assert d["lead"]["url"] == "https://news.example/story"


def test_min_items_gate():
    few = assemble_digest(
        {"lead_id": "f1", "items": [_item("f1"), _item("f3")]}, CANDIDATES, "Today", []
    )
    assert not few["sendable"]
    enough = assemble_digest(
        {"lead_id": "f1", "items": [_item("f1"), _item("f3"), _item("s1")]},
        CANDIDATES,
        "Today",
        [],
    )
    assert enough["sendable"]


def test_render_escapes_html_and_lists_unavailable_sources():
    editor = {
        "lead_id": "f1",
        "lead_blurb": "B",
        "items": [{**_item("f1"), "headline": "<script>x</script>"}, _item("f3")],
    }
    d = assemble_digest(editor, CANDIDATES, "Today", ["Google Search"])
    html = to_html(d)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "Unavailable today: Google Search" in html
    assert "https://tool.example/launch" in to_markdown(d)


def test_is_article_url_rejects_index_pages():
    from app.collect import is_article_url

    assert not is_article_url("https://venturebeat.com/category/ai")
    assert not is_article_url("https://example.com/")
    assert not is_article_url("https://news.example/tag/llm/")
    assert is_article_url(
        "https://www.theguardian.com/technology/2026/sep/25/openai-agents"
    )


def test_state_store_and_once_a_day_guard(tmp_path, monkeypatch):
    from app import collect, config

    monkeypatch.setattr(config, "STATE_URI", str(tmp_path / "state"))
    assert not collect.sent_today()
    assert collect.load_recent_headlines() == []

    collect.record_seen(["https://www.a.example/x/?utm_source=n"])
    collect.record_sent_headlines(["Lab ships model"])

    assert "https://a.example/x" in collect.load_seen()
    assert collect.load_recent_headlines() == ["Lab ships model"]
    assert collect.sent_today()
