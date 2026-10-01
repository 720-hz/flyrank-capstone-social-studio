from fastapi import APIRouter, HTTPException

from app.config import DB_PATH
from app.db import db
from app.lib.errors import VariantNotApprovedError, VariantNotFoundError
from app.lib.publishing import retry_assignment, run_batch
from app.lib.scheduling import create_assignment, create_slot, list_assignments
from app.schemas import CreateAssignmentRequest, CreateSlotRequest, RunBatchRequest

router = APIRouter()


@router.post("/v1/slots")
def post_slot(body: CreateSlotRequest):
    with db(DB_PATH) as conn:
        return create_slot(conn, label=body.label, scheduled_at=body.scheduled_at)


@router.post("/v1/assignments")
def post_assignment(body: CreateAssignmentRequest):
    try:
        with db(DB_PATH) as conn:
            return create_assignment(conn, variant_id=body.variant_id, slot_id=body.slot_id)
    except VariantNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except VariantNotApprovedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/v1/assignments")
def get_assignments(status: str | None = None):
    with db(DB_PATH) as conn:
        return {"assignments": list_assignments(conn, status=status)}


@router.post("/v1/assignments/{assignment_id}/retry")
def post_retry(assignment_id: int):
    with db(DB_PATH) as conn:
        result = retry_assignment(conn, assignment_id)
    if result is None:
        raise HTTPException(status_code=404, detail="assignment not found or not 'failed'")
    return result


@router.post("/v1/publish-runs")
def post_publish_run(body: RunBatchRequest):
    return run_batch(DB_PATH, limit=body.limit)


@router.get("/v1/publish-history")
def get_publish_history():
    with db(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT * FROM publish_attempts ORDER BY id DESC LIMIT 200"
        ).fetchall()
        return {"attempts": [dict(r) for r in rows]}


@router.get("/v1/mock-log")
def get_mock_log(platform: str | None = None):
    with db(DB_PATH) as conn:
        if platform:
            rows = conn.execute(
                "SELECT * FROM mock_publish_log WHERE platform = ? ORDER BY id DESC",
                (platform,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mock_publish_log ORDER BY id DESC"
            ).fetchall()
        return {"entries": [dict(r) for r in rows]}
