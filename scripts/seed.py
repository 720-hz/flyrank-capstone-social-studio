"""Idempotent demo seed: one post, variants for 3 platforms, one approved +
scheduled into a due slot so `POST /v1/publish-runs` has something to do
immediately after a fresh `uvicorn` start."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DB_PATH
from app.db import db, init_db
from app.lib.ingestion import ingest_post
from app.lib.review import approve_variant
from app.lib.scheduling import create_assignment, create_slot
from app.lib.variants import generate_variants, list_variants

DEMO_TITLE = "FlyRank ships Social Media Studio"
DEMO_BODY = (
    "We just shipped the capstone: ingest once, generate per-platform variants, "
    "enforce each platform's constraints before anyone reviews them, and publish "
    "through one adapter interface backed by a real Discord bot and mock adapters "
    "for X and LinkedIn."
)


def main():
    init_db()
    with db(DB_PATH) as conn:
        existing = conn.execute(
            "SELECT id FROM posts WHERE title = ?", (DEMO_TITLE,)
        ).fetchone()
        if existing:
            print(f"Demo post already seeded (post id {existing['id']}) — skipping.")
            return

        post = ingest_post(
            conn, source_kind="markdown", title=DEMO_TITLE, source_text=DEMO_BODY
        )
        variants = generate_variants(conn, post["id"], ["discord", "x", "linkedin"])

        clean = [v for v in variants if not v["constraint_violations"]]
        if not clean:
            print("No clean variant to auto-approve — seed left all in draft.")
            return

        approved = approve_variant(conn, clean[0]["id"])
        due_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        slot = create_slot(conn, label="demo-slot", scheduled_at=due_at)
        assignment = create_assignment(conn, variant_id=approved["id"], slot_id=slot["id"])

        print(f"Seeded post id={post['id']}, {len(variants)} variants generated:")
        for v in variants:
            flag = "CLEAN" if not v["constraint_violations"] else f"VIOLATES {v['constraint_violations']}"
            print(f"  - variant {v['id']} [{v['platform']}]: {flag}")
        print(f"Approved variant {approved['id']} ({approved['platform']}), "
              f"scheduled as assignment {assignment['id']} in a due slot.")
        print("Run: curl -X POST http://localhost:8000/v1/publish-runs -H 'Content-Type: application/json' -d '{}'")


if __name__ == "__main__":
    main()
