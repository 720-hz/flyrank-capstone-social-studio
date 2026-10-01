"""Turn a pasted markdown blob OR a URL into one 'posts' row — the single
source of truth every variant is generated from."""
import re
from datetime import datetime, timezone

import httpx

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    text = _TAG_RE.sub(" ", html)
    text = _WS_RE.sub(" ", text).strip()
    return text


def fetch_url_text(url: str, *, client: httpx.Client | None = None) -> str:
    """Fetches a URL and returns a plain-text approximation of its body.
    A real browser-grade readability extraction is out of scope; this is
    intentionally simple (strip tags, collapse whitespace)."""
    owns_client = client is None
    client = client or httpx.Client(timeout=10.0, follow_redirects=True)
    try:
        resp = client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "html" in content_type:
            return _strip_html(resp.text)
        return resp.text
    finally:
        if owns_client:
            client.close()


def ingest_post(
    conn,
    *,
    source_kind: str,
    title: str,
    source_text: str | None = None,
    source_url: str | None = None,
    url_fetcher=fetch_url_text,
) -> dict:
    if source_kind not in ("markdown", "url"):
        raise ValueError(f"source_kind must be 'markdown' or 'url', got {source_kind!r}")

    if source_kind == "markdown":
        if not source_text or not source_text.strip():
            raise ValueError("source_text is required for source_kind='markdown'")
    else:
        if not source_url:
            raise ValueError("source_url is required for source_kind='url'")
        source_text = url_fetcher(source_url)

    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO posts (source_kind, source_text, source_url, title, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (source_kind, source_text, source_url, title, now),
    )
    return get_post(conn, cur.lastrowid)


def get_post(conn, post_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    return dict(row) if row else None
