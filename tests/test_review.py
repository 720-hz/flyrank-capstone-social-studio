import pytest

from app.lib.errors import ConstraintViolationError, InvalidTransitionError
from app.lib.ingestion import ingest_post
from app.lib.review import approve_variant, edit_variant, reject_variant
from app.lib.variants import generate_variants


def _make_variant(conn, platform="discord", body="A clean short post."):
    post = ingest_post(conn, source_kind="markdown", title="T", source_text=body)
    [variant] = generate_variants(conn, post["id"], [platform])
    return variant


def test_approve_clean_variant(conn):
    variant = _make_variant(conn)
    approved = approve_variant(conn, variant["id"])
    assert approved["status"] == "approved"
    assert approved["reviewed_at"] is not None


def test_approve_rule_breaking_variant_is_blocked_naming_the_rule(conn):
    variant = _make_variant(conn, platform="x", body="word " * 100)
    with pytest.raises(ConstraintViolationError) as exc_info:
        approve_variant(conn, variant["id"])
    assert any("max_length" in v for v in exc_info.value.violations)


def test_cannot_approve_twice(conn):
    variant = _make_variant(conn)
    approve_variant(conn, variant["id"])
    with pytest.raises(InvalidTransitionError):
        approve_variant(conn, variant["id"])


def test_reject_then_cannot_approve(conn):
    variant = _make_variant(conn)
    reject_variant(conn, variant["id"], reason="not on brand")
    with pytest.raises(InvalidTransitionError):
        approve_variant(conn, variant["id"])


def test_edit_fixes_a_violation_so_it_can_then_be_approved(conn):
    variant = _make_variant(conn, platform="x", body="word " * 100)
    assert variant["constraint_violations"] != []

    fixed = edit_variant(conn, variant["id"], body_text="A short fixed post.", hashtags=[])
    assert fixed["constraint_violations"] == []

    approved = approve_variant(conn, fixed["id"])
    assert approved["status"] == "approved"
