"""Calendar slots + idempotent assignment creation.

Scheduling a variant into a slot is the FIRST idempotency guarantee (see
DESIGN.md): schedule_assignments.UNIQUE(variant_id, slot_id) is the actual
race guard, exactly like capstone 3's usage_events/webhook_events — calling
create_assignment() twice for the same (variant, slot) returns the SAME row,
never a duplicate, via the same try/insert/except-IntegrityError/re-read
pattern already proven there."""
import sqlite3
from datetime import datetime, timezone

from app.lib.errors import VariantNotApprovedError, VariantNotFoundError
from app.lib.variants import get_variant


def create_slot(conn, *, label: str, scheduled_at: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO schedule_slots (label, scheduled_at, created_at) VALUES (?, ?, ?)",
        (label, scheduled_at, now),
    )
    return get_slot(conn, cur.lastrowid)


def get_slot(conn, slot_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM schedule_slots WHERE id = ?", (slot_id,)).fetchone()
    return dict(row) if row else None


def create_assignment(conn, *, variant_id: int, slot_id: int) -> dict:
    variant = get_variant(conn, variant_id)
    if variant is None:
        raise VariantNotFoundError(f"no variant with id {variant_id}")
    if variant["status"] != "approved":
        raise VariantNotApprovedError(variant["status"])

    idempotency_key = f"{variant_id}:{slot_id}"
    now = datetime.now(timezone.utc).isoformat()
    try:
        cur = conn.execute(
            """INSERT INTO schedule_assignments
                   (variant_id, slot_id, idempotency_key, status, created_at)
               VALUES (?, ?, ?, 'pending', ?)""",
            (variant_id, slot_id, idempotency_key, now),
        )
        return get_assignment(conn, cur.lastrowid)
    except sqlite3.IntegrityError:
        existing = conn.execute(
            "SELECT * FROM schedule_assignments WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            return dict(existing)
        raise


def get_assignment(conn, assignment_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM schedule_assignments WHERE id = ?", (assignment_id,)
    ).fetchone()
    return dict(row) if row else None


def list_assignments(conn, *, status: str | None = None) -> list[dict]:
    query = "SELECT * FROM schedule_assignments WHERE 1=1"
    params: list = []
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]
