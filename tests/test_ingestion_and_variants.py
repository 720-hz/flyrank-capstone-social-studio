import pytest

from app.lib.ingestion import ingest_post
from app.lib.variants import generate_variants, get_variant


def test_ingest_markdown_post(conn):
    post = ingest_post(conn, source_kind="markdown", title="Hello", source_text="World")
    assert post["title"] == "Hello"
    assert post["source_text"] == "World"
    assert post["source_kind"] == "markdown"


def test_ingest_markdown_requires_source_text(conn):
    with pytest.raises(ValueError):
        ingest_post(conn, source_kind="markdown", title="Hello", source_text="")


def test_ingest_url_uses_fetcher(conn):
    post = ingest_post(
        conn,
        source_kind="url",
        title="Fetched",
        source_url="https://example.com/post",
        url_fetcher=lambda url: f"fetched content from {url}",
    )
    assert post["source_text"] == "fetched content from https://example.com/post"


def test_generate_variants_creates_one_per_platform(conn):
    post = ingest_post(conn, source_kind="markdown", title="Short", source_text="A tiny post.")
    variants = generate_variants(conn, post["id"], ["discord", "x", "linkedin"])
    assert len(variants) == 3
    assert {v["platform"] for v in variants} == {"discord", "x", "linkedin"}
    for v in variants:
        assert v["status"] == "draft"


def test_rule_breaking_variant_is_flagged_but_still_created(conn):
    long_body = "word " * 100  # ~500 chars, well over x's 280
    post = ingest_post(conn, source_kind="markdown", title="Long post", source_text=long_body)
    [variant] = generate_variants(conn, post["id"], ["x"])
    assert variant["status"] == "draft"
    assert any("max_length" in v for v in variant["constraint_violations"])


def test_generate_variants_unknown_post_raises(conn):
    with pytest.raises(ValueError):
        generate_variants(conn, 9999, ["discord"])
