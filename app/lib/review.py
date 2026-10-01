"""The review state machine: draft -> approved | rejected -> published.

Every transition here is enforced in code, not just assumed by whatever UI
calls it — approve/reject both check the variant's CURRENT status before
moving it, and approve additionally refuses a variant with any stored
constraint_violations, naming the broken rule(s) in the raised error."""
import json
from datetime import datetime, timezone

from app.lib.errors import ConstraintViolationError, InvalidTransitionError, VariantNotFoundError
from app.lib.variants import get_variant


def _require_variant(conn, variant_id: int) -> dict:
    variant = get_variant(conn, variant_id)
    if variant is None:
        raise VariantNotFoundError(f"no variant with id {variant_id}")
    return variant


def approve_variant(conn, variant_id: int, *, edited_body_text: str | None = None) -> dict:
    variant = _require_variant(conn, variant_id)
    if variant["status"] != "draft":
        raise InvalidTransitionError(variant["status"], "approved")
    if variant["constraint_violations"]:
        raise ConstraintViolationError(variant["constraint_violations"])

    now = datetime.now(timezone.utc).isoformat()
    if edited_body_text is not None:
        conn.execute(
            """UPDATE variants
               SET status='approved', body_text=?, updated_at=?, reviewed_at=?
               WHERE id=?""",
            (edited_body_text, now, now, variant_id),
        )
    else:
        conn.execute(
            "UPDATE variants SET status='approved', updated_at=?, reviewed_at=? WHERE id=?",
            (now, now, variant_id),
        )
    return get_variant(conn, variant_id)


def reject_variant(conn, variant_id: int, *, reason: str) -> dict:
    variant = _require_variant(conn, variant_id)
    if variant["status"] != "draft":
        raise InvalidTransitionError(variant["status"], "rejected")

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE variants
           SET status='rejected', rejection_reason=?, updated_at=?, reviewed_at=?
           WHERE id=?""",
        (reason, now, now, variant_id),
    )
    return get_variant(conn, variant_id)


def edit_variant(conn, variant_id: int, *, body_text: str, hashtags: list[str] | None = None) -> dict:
    """Edit a draft variant's text (e.g. to fix a constraint violation) and
    re-check constraints against the NEW text — editing doesn't bypass the
    rules, it's how a human satisfies them."""
    from app.lib.constraints import check_variant  # local import avoids a cycle

    variant = _require_variant(conn, variant_id)
    if variant["status"] != "draft":
        raise InvalidTransitionError(variant["status"], "edited")

    new_hashtags = hashtags if hashtags is not None else variant["hashtags"]
    violations = check_variant(variant["platform"], body_text, new_hashtags)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE variants
           SET body_text=?, hashtags=?, constraint_violations=?, updated_at=?
           WHERE id=?""",
        (body_text, json.dumps(new_hashtags), json.dumps(violations), now, variant_id),
    )
    return get_variant(conn, variant_id)
