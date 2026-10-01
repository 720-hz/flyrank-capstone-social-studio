from fastapi import APIRouter, HTTPException

from app.config import DB_PATH, DEFAULT_VARIANT_PLATFORMS
from app.db import db
from app.lib.ingestion import get_post, ingest_post
from app.lib.variants import generate_variants, list_variants
from app.schemas import GenerateVariantsRequest, IngestPostRequest

router = APIRouter()


@router.post("/v1/posts")
def create_post(body: IngestPostRequest):
    try:
        with db(DB_PATH) as conn:
            post = ingest_post(
                conn,
                source_kind=body.source_kind,
                title=body.title,
                source_text=body.source_text,
                source_url=body.source_url,
            )
        return post
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/v1/posts/{post_id}")
def read_post(post_id: int):
    with db(DB_PATH) as conn:
        post = get_post(conn, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="post not found")
    return post


@router.post("/v1/posts/{post_id}/variants")
def create_variants(post_id: int, body: GenerateVariantsRequest):
    platforms = body.platforms or DEFAULT_VARIANT_PLATFORMS
    try:
        with db(DB_PATH) as conn:
            variants = generate_variants(conn, post_id, platforms)
        return {"variants": variants}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/v1/posts/{post_id}/variants")
def read_variants(post_id: int):
    with db(DB_PATH) as conn:
        return {"variants": list_variants(conn, post_id=post_id)}
