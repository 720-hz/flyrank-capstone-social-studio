from fastapi import APIRouter, HTTPException

from app.config import DB_PATH
from app.db import db
from app.lib.errors import ConstraintViolationError, InvalidTransitionError, VariantNotFoundError
from app.lib.review import approve_variant, edit_variant, reject_variant
from app.lib.variants import get_variant, list_variants
from app.schemas import ApproveVariantRequest, EditVariantRequest, RejectVariantRequest

router = APIRouter()


@router.get("/v1/variants")
def list_all_variants(status: str | None = None):
    with db(DB_PATH) as conn:
        return {"variants": list_variants(conn, status=status)}


@router.get("/v1/variants/{variant_id}")
def read_variant(variant_id: int):
    with db(DB_PATH) as conn:
        variant = get_variant(conn, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="variant not found")
    return variant


@router.post("/v1/variants/{variant_id}/edit")
def put_edit(variant_id: int, body: EditVariantRequest):
    try:
        with db(DB_PATH) as conn:
            return edit_variant(conn, variant_id, body_text=body.body_text, hashtags=body.hashtags)
    except VariantNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/v1/variants/{variant_id}/approve")
def post_approve(variant_id: int, body: ApproveVariantRequest):
    try:
        with db(DB_PATH) as conn:
            return approve_variant(conn, variant_id, edited_body_text=body.edited_body_text)
    except VariantNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ConstraintViolationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "constraint_violation", "violations": exc.violations},
        )


@router.post("/v1/variants/{variant_id}/reject")
def post_reject(variant_id: int, body: RejectVariantRequest):
    try:
        with db(DB_PATH) as conn:
            return reject_variant(conn, variant_id, reason=body.reason)
    except VariantNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
