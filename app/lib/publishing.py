"""The durable, resumable publish worker. This is the SECOND idempotency
guarantee (see DESIGN.md): claiming an assignment is a conditional UPDATE
(`WHERE status='pending'`), committed immediately and independently of
publishing it — so a crash between 'claimed' and 'published' leaves the
assignment in 'processing' rather than silently re-publishing or silently
losing it. A 'processing' assignment older than ASSIGNMENT_CLAIM_TIMEOUT_SECONDS
is treated as abandoned by a dead worker and reclaimed (back to 'pending')
by the NEXT run before it claims anything new. Every attempt — success or
failure — is logged to publish_attempts before the assignment's terminal
status is written, in the same commit, so the two can never disagree."""
import json
from datetime import datetime, timedelta, timezone

from app.adapters.registry import build_registry
from app.config import ASSIGNMENT_CLAIM_TIMEOUT_SECONDS
from app.db import get_connection


def _reclaim_stale(conn, now_iso: str, timeout_seconds: int) -> int:
    cutoff = (
        datetime.fromisoformat(now_iso) - timedelta(seconds=timeout_seconds)
    ).isoformat()
    cur = conn.execute(
        """UPDATE schedule_assignments SET status='pending', claimed_at=NULL
           WHERE status='processing' AND claimed_at < ?""",
        (cutoff,),
    )
    return cur.rowcount


def _due_pending_assignment_ids(conn, now_iso: str, limit: int) -> list[int]:
    rows = conn.execute(
        """SELECT sa.id FROM schedule_assignments sa
           JOIN schedule_slots ss ON ss.id = sa.slot_id
           WHERE sa.status = 'pending' AND ss.scheduled_at <= ?
           ORDER BY ss.scheduled_at ASC, sa.id ASC
           LIMIT ?""",
        (now_iso, limit),
    ).fetchall()
    return [r["id"] for r in rows]


def _claim_one(conn, assignment_id: int, now_iso: str) -> bool:
    cur = conn.execute(
        """UPDATE schedule_assignments SET status='processing', claimed_at=?
           WHERE id=? AND status='pending'""",
        (now_iso, assignment_id),
    )
    return cur.rowcount == 1


def _publish_one(conn, assignment_id: int, registry: dict) -> dict:
    row = conn.execute(
        """SELECT sa.id AS assignment_id, sa.variant_id,
                  v.platform, v.body_text, v.hashtags
           FROM schedule_assignments sa
           JOIN variants v ON v.id = sa.variant_id
           WHERE sa.id = ?""",
        (assignment_id,),
    ).fetchone()

    attempt_count = conn.execute(
        "SELECT COUNT(*) AS n FROM publish_attempts WHERE assignment_id = ?",
        (assignment_id,),
    ).fetchone()["n"]
    attempt_number = attempt_count + 1

    publisher = registry[row["platform"]]
    hashtags = json.loads(row["hashtags"])
    result = publisher.publish(body_text=row["body_text"], hashtags=hashtags)

    now = datetime.now(timezone.utc).isoformat()
    outcome = "success" if result["success"] else "failure"
    conn.execute(
        """INSERT INTO publish_attempts
               (assignment_id, platform, attempt_number, outcome, external_id,
                raw_response, error, attempted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            assignment_id,
            row["platform"],
            attempt_number,
            outcome,
            result["external_id"],
            json.dumps(result["raw_response"]),
            result["error"],
            now,
        ),
    )

    if result["success"]:
        conn.execute(
            "UPDATE schedule_assignments SET status='published' WHERE id=?",
            (assignment_id,),
        )
        conn.execute(
            "UPDATE variants SET status='published', updated_at=? WHERE id=?",
            (now, row["variant_id"]),
        )
    else:
        conn.execute(
            "UPDATE schedule_assignments SET status='failed' WHERE id=?",
            (assignment_id,),
        )

    return {"assignment_id": assignment_id, "outcome": outcome, "error": result["error"]}


def retry_assignment(conn, assignment_id: int) -> dict:
    """Manually move a 'failed' assignment back to 'pending' so the next
    batch run picks it up again."""
    conn.execute(
        "UPDATE schedule_assignments SET status='pending', claimed_at=NULL "
        "WHERE id=? AND status='failed'",
        (assignment_id,),
    )
    row = conn.execute(
        "SELECT * FROM schedule_assignments WHERE id=?", (assignment_id,)
    ).fetchone()
    return dict(row) if row else None


def run_batch(
    db_path: str,
    *,
    now: str | None = None,
    limit: int = 50,
    registry_factory=build_registry,
) -> dict:
    """Entry point for the worker. Opens its OWN connection and commits after
    every individual claim and every individual publish — not once at the end
    — so that killing the process at any point between two assignments loses
    no committed work and double-publishes nothing. Safe to call repeatedly
    (e.g. on a schedule, or by hand after a crash)."""
    conn = get_connection(db_path)
    try:
        now_iso = now or datetime.now(timezone.utc).isoformat()

        _reclaim_stale(conn, now_iso, ASSIGNMENT_CLAIM_TIMEOUT_SECONDS)
        conn.commit()

        job_started = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "INSERT INTO batch_jobs (status, total, processed, started_at) "
            "VALUES ('running', 0, 0, ?)",
            (job_started,),
        )
        job_id = cur.lastrowid
        conn.commit()

        due_ids = _due_pending_assignment_ids(conn, now_iso, limit)
        conn.execute(
            "UPDATE batch_jobs SET total=? WHERE id=?", (len(due_ids), job_id)
        )
        conn.commit()

        registry = registry_factory(conn)
        processed = 0
        last_error = None
        for assignment_id in due_ids:
            if not _claim_one(conn, assignment_id, now_iso):
                conn.commit()
                continue  # another worker run already claimed it
            conn.commit()

            try:
                outcome = _publish_one(conn, assignment_id, registry)
                conn.commit()
                if outcome["outcome"] == "failure":
                    last_error = outcome["error"]
            except Exception as exc:  # noqa: BLE001 — log and keep going
                conn.rollback()
                last_error = str(exc)

            processed += 1
            conn.execute(
                "UPDATE batch_jobs SET processed=? WHERE id=?", (processed, job_id)
            )
            conn.commit()

        conn.execute(
            "UPDATE batch_jobs SET status='completed', finished_at=?, last_error=? "
            "WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), last_error, job_id),
        )
        conn.commit()

        return {"job_id": job_id, "total": len(due_ids), "processed": processed}
    finally:
        conn.close()
