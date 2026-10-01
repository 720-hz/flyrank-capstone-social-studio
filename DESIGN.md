# Design

## What this is

A pipeline from one piece of source content to multiple scheduled, platform-correct
social posts, published through a real adapter interface: ingest a post once → generate
per-platform variants → enforce each platform's constraints before a human ever reviews
them → a human approves/rejects/edits → approved variants get scheduled into time slots →
a durable worker publishes them idempotently, through adapters, with a full history.

Five real platforms are in scope by name: Discord (real), X, LinkedIn, Instagram, Mastodon.
Per the brief's own rule, Instagram/X/LinkedIn get **mock** adapters only — this build does
not publish to them for real. Discord is the one real integration: a real Discord bot token
posting into a real server channel via the Discord REST API.

## Data model

```
posts
  id, source_kind ('markdown' | 'url'), source_text, source_url, title, created_at

variants
  id, post_id, platform, body_text, hashtags (json array), status
      status: draft -> approved | rejected -> published
  constraint_violations (json array, empty when clean)
  rejection_reason, created_at, updated_at, reviewed_at

schedule_slots
  id, label, scheduled_at, created_at
  -- a slot is just a point on the calendar; many variants can share one

schedule_assignments
  id, variant_id, slot_id, idempotency_key, status, claimed_at, created_at
      status: pending -> processing -> published | failed
  UNIQUE(variant_id, slot_id)        -- scheduling the same variant into the
                                      -- same slot twice is a no-op, not a duplicate row
  -- only an APPROVED variant may get an assignment row at all (enforced in lib, not
  -- just by convention) — that's what makes the 4xx-on-unapproved-schedule rule real

publish_attempts
  id, assignment_id, platform, attempt_number, outcome ('success' | 'failure'),
  external_id, raw_response (json), error, attempted_at
  -- append-only audit log; this is "publish history"

batch_jobs
  id, status, total, processed, started_at, finished_at, last_error
  -- one row per worker run over a batch of due assignments, same shape as
  -- capstone 3's background-job table
```

## Constraint profiles (enforced before a variant can leave `draft`)

Each platform has a small, fully deterministic rule set in `app/config.py`. A variant that
breaks a rule is generated but stays `draft` with `constraint_violations` populated naming
the exact rule — it is never silently fixed or silently allowed through.

| Platform | Max length | Max hashtags | Tone rule |
|---|---|---|---|
| `discord` (real) | 2000 chars (Discord's hard message limit) | 10 | none |
| `x` (mock) | 280 chars | 3 | none |
| `linkedin` (mock) | 3000 chars | 5 | no ALL-CAPS "shouting" word of 4+ letters |
| `instagram` (mock) | 2200 chars | 30 | none |
| `mastodon` (mock) | 500 chars | 5 | none |

Rules are checked in `app/lib/constraints.py::check_variant()`, which returns a list of
violated rule names (empty = clean). Nothing downstream (review, scheduling, publishing)
re-derives or re-checks these — it only ever reads the stored `constraint_violations`.

## The `SocialPublisher` interface

```python
class PublishResult(TypedDict):
    success: bool
    external_id: str | None
    raw_response: dict
    error: str | None

class SocialPublisher(Protocol):
    platform: str
    def publish(self, *, body_text: str, hashtags: list[str]) -> PublishResult: ...
```

Three implementations, one real:

- `DiscordBotPublisher` (`app/adapters/discord_bot.py`) — real. `POST
  https://discord.com/api/v10/channels/{channel_id}/messages` with `Authorization: Bot
  {token}`. Needs `DISCORD_BOT_TOKEN` + `DISCORD_CHANNEL_ID` in `.env`.
- `MockXPublisher`, `MockLinkedInPublisher` (`app/adapters/mocks.py`) — record the post to
  a `mock_publish_log` table (platform, body, hashtags, posted_at) and return a
  deterministic success with a fabricated `external_id`; a preview is just reading that
  table back.

`app/adapters/registry.py` builds `{"discord": DiscordBotPublisher(...), "x":
MockXPublisher(), "linkedin": MockLinkedInPublisher(), ...}` once from config at startup.
Everything upstream (the publish worker) calls `registry[variant.platform].publish(...)`
and has no branch anywhere that names a specific platform — swapping Discord for, say, a
second mock in tests is a one-line change to the registry, never a change to
`app/lib/publishing.py`. That's what Probe 6 (adapter-swap test) actually exercises.

## Idempotent, durable scheduling

Two separate idempotency guarantees, because two separate things can be retried:

1. **Scheduling is idempotent.** `schedule_assignments.UNIQUE(variant_id, slot_id)` — the
   same database-level guard pattern as capstone 3's `usage_events` and `webhook_events`:
   the constraint is the actual race guard, not an application-level check-then-insert.
   Calling "schedule variant V into slot S" twice produces one row, not two.

2. **Publishing is resumable without duplicates.** The worker claims due, pending
   assignments with a conditional update —
   `UPDATE schedule_assignments SET status='processing', claimed_at=? WHERE id=? AND
   status='pending'` — and only proceeds if that update actually affected a row. This is
   the same "let the database decide who wins" idea as the UNIQUE-constraint pattern,
   applied to a claim instead of an insert: two workers (or one worker and its own crashed
   predecessor) racing to claim the same assignment can't both win.

   A `processing` assignment whose `claimed_at` is older than a timeout is treated as
   abandoned (its owner crashed mid-publish) and becomes reclaimable — which is what makes
   "kill the worker mid-batch, restart it, assert zero duplicate posts and zero skipped
   posts" (Probe 5) provable rather than assumed. Each publish attempt is also logged to
   `publish_attempts` before the assignment's terminal status is written, so the history
   table and the assignment status can never disagree about whether a publish happened.

## Review workflow

`draft -> approved -> published`, with `rejected` as a terminal dead end off of `draft`.
Enforced in `app/lib/review.py`, not just by UI convention:

- `approve_variant()` / `reject_variant()` only accept a variant currently in `draft`.
- `create_schedule_assignment()` only accepts a variant currently `approved` — attempting
  to schedule a `draft` or `rejected` variant raises `VariantNotApprovedError`, which the
  route layer turns into a 409 (not 500, not silently ignored).
- A variant moves to `published` only when its (sole, due to the UNIQUE guard above)
  assignment's publish attempt succeeds — set in the same transaction as the
  `publish_attempts` insert and the assignment's `status='published'` update.

## Layering

Same split as capstones 2 and 3: `app/routes/*.py` is HTTP-only (parse → call a `lib`
function → map the result/exception to a status code); all real logic — constraints,
review state machine, scheduling, the publish worker — lives in `app/lib/*.py` against a
plain `sqlite3.Connection`, so `tests/` exercises the exact same functions the live API
runs, no server needed.

## What's explicitly out of scope (brief Section 7 / stretch goals)

Real OAuth login flows for X/LinkedIn/Instagram (mocked instead, as required), AI-written
variant copy (templates are enough to prove the constraint/adapter/scheduling machinery;
an optional `--ai` flag could call a model for copy but doesn't change any of the above),
analytics/engagement tracking, multi-user auth.

## Known sandbox constraint (same shape as capstones 2 and 3)

This cloud sandbox's egress policy blocks `discord.com` directly (confirmed: a direct
`curl` to `https://discord.com/api/v10/gateway` gets a proxy `403`, same as
`api.stripe.com` did in capstone 3). `DiscordBotPublisher` is built and unit-tested against
a fake HTTP transport in the sandbox; the one genuinely-real step — a live bot token
posting into a live Discord channel — runs on a machine with normal internet access, same
pattern as capstone 3's real Stripe Checkout. Transcript in `EVIDENCE.md`.
