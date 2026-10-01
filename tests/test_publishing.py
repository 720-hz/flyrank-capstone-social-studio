"""Proves the two durability/idempotency guarantees from DESIGN.md, plus the
adapter-swap guarantee (Probe 6): the worker never imports a concrete adapter
class, only ever reaches it through the registry it's handed."""
import json
from datetime import datetime, timedelta, timezone

from app.adapters.base import PublishResult
from app.adapters.registry import build_registry
from app.lib.ingestion import ingest_post
from app.lib.publishing import run_batch
from app.lib.review import approve_variant
from app.lib.scheduling import create_assignment, create_slot
from app.lib.variants import generate_variants


def _due_assignment(conn, *, platform="x", body="A short clean post."):
    post = ingest_post(conn, source_kind="markdown", title="T", source_text=body)
    [variant] = generate_variants(conn, post["id"], [platform])
    approved = approve_variant(conn, variant["id"])
    due_at = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    slot = create_slot(conn, label="due-now", scheduled_at=due_at)
    assignment = create_assignment(conn, variant_id=approved["id"], slot_id=slot["id"])
    conn.commit()  # run_batch opens a SEPARATE connection, so this must be durable
    return assignment, approved


def test_run_batch_publishes_a_due_assignment(conn, db_path):
    assignment, variant = _due_assignment(conn)
    conn.close()  # run_batch opens its own connection against db_path

    result = run_batch(db_path, limit=10)
    assert result["processed"] == 1

    from app.db import get_connection

    check = get_connection(db_path)
    row = check.execute(
        "SELECT status FROM schedule_assignments WHERE id=?", (assignment["id"],)
    ).fetchone()
    assert row["status"] == "published"

    attempts = check.execute(
        "SELECT COUNT(*) AS n FROM publish_attempts WHERE assignment_id=?",
        (assignment["id"],),
    ).fetchone()["n"]
    assert attempts == 1

    mock_log = check.execute(
        "SELECT COUNT(*) AS n FROM mock_publish_log"
    ).fetchone()["n"]
    assert mock_log == 1
    check.close()


def test_run_batch_is_safe_to_call_repeatedly(conn, db_path):
    _due_assignment(conn)
    conn.close()

    first = run_batch(db_path, limit=10)
    second = run_batch(db_path, limit=10)
    assert first["processed"] == 1
    assert second["processed"] == 0  # nothing new is due


def test_crash_mid_batch_is_resumed_without_duplicate_publish(conn, db_path):
    """Simulates a worker crash: an assignment gets claimed ('processing')
    but the process dies before publishing. A LATER run_batch call must
    reclaim it (the claim is older than the timeout) and publish it exactly
    once — not skip it, not publish it twice."""
    assignment, _ = _due_assignment(conn)

    stale_claim_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    conn.execute(
        "UPDATE schedule_assignments SET status='processing', claimed_at=? WHERE id=?",
        (stale_claim_time, assignment["id"]),
    )
    conn.commit()
    conn.close()

    result = run_batch(db_path, limit=10)
    assert result["processed"] == 1

    from app.db import get_connection

    check = get_connection(db_path)
    row = check.execute(
        "SELECT status FROM schedule_assignments WHERE id=?", (assignment["id"],)
    ).fetchone()
    assert row["status"] == "published"

    attempts = check.execute(
        "SELECT COUNT(*) AS n FROM publish_attempts WHERE assignment_id=?",
        (assignment["id"],),
    ).fetchone()["n"]
    assert attempts == 1  # exactly one attempt — the reclaim did not double-publish
    check.close()


def test_still_processing_and_not_yet_stale_is_left_alone(conn, db_path):
    """A 'processing' assignment claimed recently (not past the timeout) is
    assumed to have a live owner — a second run_batch call must NOT touch it."""
    assignment, _ = _due_assignment(conn)
    recent_claim = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE schedule_assignments SET status='processing', claimed_at=? WHERE id=?",
        (recent_claim, assignment["id"]),
    )
    conn.commit()
    conn.close()

    result = run_batch(db_path, limit=10)
    assert result["processed"] == 0

    from app.db import get_connection

    check = get_connection(db_path)
    row = check.execute(
        "SELECT status FROM schedule_assignments WHERE id=?", (assignment["id"],)
    ).fetchone()
    assert row["status"] == "processing"
    check.close()


class _SpyPublisher:
    """A throwaway third implementation of SocialPublisher, used only to prove
    the worker can't tell adapters apart — swapping one in is a registry-level
    change, nothing in app/lib/publishing.py changes."""

    platform = "x"

    def __init__(self):
        self.calls = []

    def publish(self, *, body_text: str, hashtags: list[str]) -> PublishResult:
        self.calls.append((body_text, hashtags))
        return PublishResult(
            success=True, external_id="spy-1", raw_response={"spy": True}, error=None
        )


def test_adapter_is_swappable_via_registry_with_no_worker_code_change(conn, db_path):
    assignment, _ = _due_assignment(conn, platform="x")
    conn.close()

    spy = _SpyPublisher()

    def registry_factory(c):
        return build_registry(c, overrides={"x": spy})

    result = run_batch(db_path, limit=10, registry_factory=registry_factory)
    assert result["processed"] == 1
    assert len(spy.calls) == 1  # the worker called OUR adapter, not MockXPublisher
