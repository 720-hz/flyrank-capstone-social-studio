# Social Media Studio

Ingest one piece of content once, generate per-platform variants, enforce each platform's
constraints before anyone reviews them, run them through a human approve/reject workflow,
then schedule and publish them idempotently through a single `SocialPublisher` interface —
one real adapter (a Discord bot) and mock adapters for the platforms the brief requires be
mocked (X, LinkedIn).

Full design rationale: [`DESIGN.md`](./DESIGN.md). Proof for every requirement and
acceptance probe, with real transcripts: [`EVIDENCE.md`](./EVIDENCE.md). What went into
building this, honestly: [`BUILDLOG.md`](./BUILDLOG.md).

## Architecture

```
POST /v1/posts (markdown or URL)
       │
       ▼
  ingest_post()  → posts (single source of truth)
       │
       ▼
POST /v1/posts/{id}/variants  → generate_variants()  (app/lib/variants.py)
       │  renders one body per requested platform, then IMMEDIATELY
       │  check_variant() against that platform's constraint profile
       ▼
  variants (status='draft', constraint_violations=[...] if any)
       │
       ├─ POST /v1/variants/{id}/edit     → re-checks constraints on the new text
       ├─ POST /v1/variants/{id}/approve  → 409 if not draft, 422 naming the
       │                                     broken rule(s) if constraint_violations
       │                                     is non-empty
       └─ POST /v1/variants/{id}/reject   → 409 if not draft
       ▼
  variants (status='approved')
       │
       ▼
POST /v1/assignments {variant_id, slot_id}
       │  create_assignment(): 409 if the variant isn't 'approved';
       │  UNIQUE(variant_id, slot_id) makes a duplicate call a no-op (same row back)
       ▼
  schedule_assignments (status='pending')
       │
       ▼
POST /v1/publish-runs  → run_batch()  (app/lib/publishing.py, the durable worker)
       │  1. reclaim any 'processing' row whose claim is older than the
       │     timeout (an abandoned claim from a crashed worker)
       │  2. for each due, pending assignment: atomically claim it
       │     (`UPDATE ... WHERE status='pending'`, commit immediately)
       │  3. look up registry[variant.platform] (app/adapters/registry.py)
       │     and call .publish() — the worker never names a concrete class
       │  4. log the attempt to publish_attempts, then mark the assignment
       │     published/failed — same commit
       ▼
  publish_attempts (full history) + variants.status='published' on success

GET /v1/publish-history   ← publish_attempts, newest first
GET /v1/mock-log?platform= ← what a mock adapter WOULD have posted
```

Layering matches capstones 2 and 3: `app/routes/*.py` is HTTP-only; all real logic —
constraints, the review state machine, scheduling, the publish worker, every adapter —
lives in `app/lib/*.py` and `app/adapters/*.py` against a plain `sqlite3.Connection`, so
`tests/` calls the exact same functions the live API runs.

## The `SocialPublisher` interface

```python
class SocialPublisher(Protocol):
    platform: str
    def publish(self, *, body_text: str, hashtags: list[str]) -> PublishResult: ...
```

| Adapter | Real or mock | How |
|---|---|---|
| `DiscordBotPublisher` | **Real** | `POST /channels/{id}/messages` via the Discord Bot API, `Authorization: Bot <token>` |
| `MockXPublisher` | Mock (required by brief) | Records to `mock_publish_log`, returns a fabricated id |
| `MockLinkedInPublisher` | Mock (required by brief) | Same |
| `MockInstagramPublisher` | Mock | Same |
| `MockMastodonPublisher` | Mock | Same |

`app/adapters/registry.py::build_registry()` is the ONLY place that names a concrete
adapter class. `tests/test_publishing.py::test_adapter_is_swappable_via_registry_with_no_worker_code_change`
swaps in a throwaway third implementation and proves the worker never notices.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env
```

## Run it

```bash
python scripts/seed.py           # idempotent — one demo post, 3 variants, 1 approved+scheduled
uvicorn app.main:app --reload    # http://localhost:8000
pytest tests/ -v                 # 30 tests, fully offline, ~0.5s
```

Try the whole pipeline with no Discord setup at all — the seeded demo variant targets
`discord`, but you can exercise the mock platforms end to end immediately:

```bash
curl -X POST http://localhost:8000/v1/posts -H "Content-Type: application/json" \
  -d '{"title":"Hello","source_kind":"markdown","source_text":"A short demo post."}'
# => {"id": 1, ...}

curl -X POST http://localhost:8000/v1/posts/1/variants -H "Content-Type: application/json" \
  -d '{"platforms":["x","linkedin"]}'
# => variants, each with its own constraint_violations

curl -X POST http://localhost:8000/v1/variants/1/approve -H "Content-Type: application/json" -d '{}'

curl -X POST http://localhost:8000/v1/slots -H "Content-Type: application/json" \
  -d '{"label":"now","scheduled_at":"2020-01-01T00:00:00+00:00"}'   # a slot in the past = already due

curl -X POST http://localhost:8000/v1/assignments -H "Content-Type: application/json" \
  -d '{"variant_id":1,"slot_id":1}'

curl -X POST http://localhost:8000/v1/publish-runs -H "Content-Type: application/json" -d '{}'

curl http://localhost:8000/v1/mock-log?platform=x        # see what "would have" posted
curl http://localhost:8000/v1/publish-history
```

## Discord bot setup (real, free — no server owner permissions beyond your own test server needed)

Needed only for publishing to `discord` for real; everything else (ingestion, variants,
constraints, review, mock platforms, idempotent scheduling) works with zero Discord setup.

1. Create a free Discord account if you don't have one, and a server you own (or have
   "Manage Webhooks"/admin on) to post test messages into — [discord.com](https://discord.com).
2. Go to the [Discord Developer Portal](https://discord.com/developers/applications) →
   **New Application** → name it anything → **Bot** tab → **Reset Token** → copy it into
   `.env`'s `DISCORD_BOT_TOKEN`.
3. Under **Bot**, make sure **Message Content Intent** isn't required for this (we only
   *send*, never read) — no privileged intents needed.
4. **OAuth2 → URL Generator** → scopes: `bot` → bot permissions: `Send Messages` → open the
   generated URL in a browser and invite the bot to your server.
5. In Discord, enable **Developer Mode** (User Settings → Advanced), then right-click the
   text channel you want it posting into → **Copy Channel ID** → put it in `.env`'s
   `DISCORD_CHANNEL_ID`.
6. Restart the app (`.env` changes need a restart), then run the seeded demo (it already
   scheduled a `discord` variant into a due slot):
   ```bash
   python scripts/seed.py
   curl -X POST http://localhost:8000/v1/publish-runs -H "Content-Type: application/json" -d '{}'
   ```
   The message should appear in your Discord channel within a second or two.

## Endpoints

| Endpoint | What it does |
|---|---|
| `POST /v1/posts` | Ingest a post (pasted markdown or a URL) |
| `GET /v1/posts/{id}` | Inspect a post |
| `POST /v1/posts/{id}/variants` | Generate per-platform variants, constraint-checked |
| `GET /v1/posts/{id}/variants` | List a post's variants |
| `GET /v1/variants?status=` | List all variants, optionally by status |
| `GET /v1/variants/{id}` | Inspect one variant |
| `POST /v1/variants/{id}/edit` | Edit a draft variant's text/hashtags, re-checks constraints |
| `POST /v1/variants/{id}/approve` | draft → approved (409 if not draft, 422 if rule-breaking) |
| `POST /v1/variants/{id}/reject` | draft → rejected (409 if not draft) |
| `POST /v1/slots` | Create a calendar time slot |
| `POST /v1/assignments` | Schedule an approved variant into a slot (409 if not approved) |
| `GET /v1/assignments?status=` | List schedule assignments |
| `POST /v1/assignments/{id}/retry` | Move a 'failed' assignment back to 'pending' |
| `POST /v1/publish-runs` | Run the durable worker over all due, pending assignments |
| `GET /v1/publish-history` | Append-only log of every publish attempt |
| `GET /v1/mock-log?platform=` | What a mock adapter recorded as "published" |
| `GET /health` | Liveness |

## Known limitations

- **Template-based variant copy, not AI-written.** Per the brief's own scope note — the
  point is proving the pipeline (ingestion → constraints → review → adapters → idempotent
  scheduling), not prose quality. The template is title + full source text, deliberately
  NOT pre-truncated to a platform's limit, so a post that doesn't fit a tighter platform
  (e.g. `x`'s 280 chars) is caught by constraint checking rather than silently clipped.
- **One real platform (Discord).** Per the brief: "Do not publish to Instagram, X, or
  LinkedIn. For those platforms, you write mock adapters." X, LinkedIn, Instagram, and
  Mastodon all have mock adapters here; Mastodon's real API was not implemented since
  Discord was chosen as the one real target.
- **Simple URL ingestion.** `fetch_url_text()` strips HTML tags and collapses whitespace —
  it is not a readability/boilerplate-removal engine; feeding it a heavy, JS-rendered page
  will include nav/footer text. Markdown ingestion has no such limitation.
- **No real-time webhooks from Discord back to this app** (e.g. reactions, delivery
  receipts beyond the initial HTTP response) — out of scope per the brief's stretch-goals
  section.

## Sandbox network note

This project was built in a cloud sandbox whose outbound network is limited to package
registries and a short allow-list — `discord.com` returns a proxy `403` from inside it
(confirmed directly; see `BUILDLOG.md`), the same shape of restriction capstone 3 hit with
`api.stripe.com`. `DiscordBotPublisher` is built and tested against a fake HTTP transport
(`tests/test_discord_adapter.py`) that proves its request-building and response-parsing for
real, without needing the network. The one thing that does need it — a live bot token
posting into a live Discord channel — was run on a machine with normal internet access;
transcript in `EVIDENCE.md`.
