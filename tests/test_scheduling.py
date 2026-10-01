import pytest

from app.lib.errors import VariantNotApprovedError
from app.lib.ingestion import ingest_post
from app.lib.review import approve_variant
from app.lib.scheduling import create_assignment, create_slot
from app.lib.variants import generate_variants


def _make_approved_variant(conn):
    post = ingest_post(conn, source_kind="markdown", title="T", source_text="A clean short post.")
    [variant] = generate_variants(conn, post["id"], ["discord"])
    return approve_variant(conn, variant["id"])


def _make_draft_variant(conn):
    post = ingest_post(conn, source_kind="markdown", title="T", source_text="A clean short post.")
    [variant] = generate_variants(conn, post["id"], ["discord"])
    return variant


def test_scheduling_an_unapproved_variant_is_rejected(conn):
    draft = _make_draft_variant(conn)
    slot = create_slot(conn, label="slot-1", scheduled_at="2026-01-01T00:00:00+00:00")
    with pytest.raises(VariantNotApprovedError):
        create_assignment(conn, variant_id=draft["id"], slot_id=slot["id"])


def test_scheduling_an_approved_variant_succeeds(conn):
    approved = _make_approved_variant(conn)
    slot = create_slot(conn, label="slot-1", scheduled_at="2026-01-01T00:00:00+00:00")
    assignment = create_assignment(conn, variant_id=approved["id"], slot_id=slot["id"])
    assert assignment["status"] == "pending"
    assert assignment["variant_id"] == approved["id"]
    assert assignment["slot_id"] == slot["id"]


def test_scheduling_same_variant_slot_twice_is_idempotent(conn):
    approved = _make_approved_variant(conn)
    slot = create_slot(conn, label="slot-1", scheduled_at="2026-01-01T00:00:00+00:00")
    first = create_assignment(conn, variant_id=approved["id"], slot_id=slot["id"])
    second = create_assignment(conn, variant_id=approved["id"], slot_id=slot["id"])
    assert first["id"] == second["id"]

    count = conn.execute(
        "SELECT COUNT(*) AS n FROM schedule_assignments WHERE variant_id=? AND slot_id=?",
        (approved["id"], slot["id"]),
    ).fetchone()["n"]
    assert count == 1


def test_different_variants_can_share_one_slot(conn):
    slot = create_slot(conn, label="shared-slot", scheduled_at="2026-01-01T00:00:00+00:00")
    v1 = _make_approved_variant(conn)
    v2 = _make_approved_variant(conn)
    a1 = create_assignment(conn, variant_id=v1["id"], slot_id=slot["id"])
    a2 = create_assignment(conn, variant_id=v2["id"], slot_id=slot["id"])
    assert a1["id"] != a2["id"]
