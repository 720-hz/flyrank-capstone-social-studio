"""Per-platform variant generation from a post's source text, template-based
(no model call — the brief's own scope note: 'you're testing the pipeline,
not prose quality'). Every generated variant is immediately constraint-checked
and the result is stored; nothing downstream re-checks it."""
import json
import re
from datetime import datetime, timezone

from app.lib.constraints import check_variant
from app.lib.ingestion import get_post

_WORD_RE = re.compile(r"[A-Za-z]{4,}")


def _derive_hashtags(title: str, limit: int = 5) -> list[str]:
    seen = []
    for word in _WORD_RE.findall(title):
        tag = "#" + word.lower()
        if tag not in seen:
            seen.append(tag)
        if len(seen) >= limit:
            break
    return seen


def _render_body(title: str, source_text: str) -> str:
    """The template: title, blank line, full source text. Deliberately NOT
    truncated to any platform's limit here — that's the point: a post whose
    full text doesn't fit a tighter platform (e.g. 'x') is exactly the case
    constraint checking exists to catch, rather than silently clipping it."""
    return f"{title}\n\n{source_text}".strip()


def generate_variants(conn, post_id: int, platforms: list[str]) -> list[dict]:
    post = get_post(conn, post_id)
    if post is None:
        raise ValueError(f"no post with id {post_id}")

    body_text = _render_body(post["title"], post["source_text"] or "")
    hashtags = _derive_hashtags(post["title"])
    now = datetime.now(timezone.utc).isoformat()

    created = []
    for platform in platforms:
        violations = check_variant(platform, body_text, hashtags)
        cur = conn.execute(
            """INSERT INTO variants
                   (post_id, platform, body_text, hashtags, status,
                    constraint_violations, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)""",
            (
                post_id,
                platform,
                body_text,
                json.dumps(hashtags),
                json.dumps(violations),
                now,
                now,
            ),
        )
        created.append(get_variant(conn, cur.lastrowid))
    return created


def get_variant(conn, variant_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM variants WHERE id = ?", (variant_id,)).fetchone()
    if row is None:
        return None
    v = dict(row)
    v["hashtags"] = json.loads(v["hashtags"])
    v["constraint_violations"] = json.loads(v["constraint_violations"])
    return v


def list_variants(conn, *, post_id: int | None = None, status: str | None = None) -> list[dict]:
    query = "SELECT id FROM variants WHERE 1=1"
    params: list = []
    if post_id is not None:
        query += " AND post_id = ?"
        params.append(post_id)
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id"
    rows = conn.execute(query, params).fetchall()
    return [get_variant(conn, row["id"]) for row in rows]
