# Build log

Honest AI-usage log, per the brief's rule: "keep BUILDLOG.md honest: where AI helped, where
it was wrong, what you changed."

## A note on which version of this capstone this is

FlyRank's intern team updated this capstone after some interns had already started the
older "Multi-Platform Social Campaign Publisher" brief, which referenced a planned fake
platform server (`starters/challenge-5-social/`) that was never built and never will be.
This build is the current, correct version — **Social Media Studio** — where the one
missing piece (a fake platform server) is replaced by writing mock adapters plus one real
free platform, per the update's own three listed acceptable approaches. No work existed on
the old version before this one started; this was built directly against the Social Media
Studio brief from the first line of code.

## How this was built

Built with Claude as the pair-programmer, same approach as capstones 2 and 3: design doc
first (`DESIGN.md`), confirm the one real open choice that only a human could make (which
real platform — Discord was chosen), then build in the brief's own dependency order:
constraints → ingestion/variants → review workflow → adapters → idempotent
scheduling/durable worker → tests → docs, checking each piece against its own acceptance
probe before moving to the next.

## A real environment constraint, worked around transparently

Same shape of constraint as capstone 3, different host:

```
$ curl -sS -o /dev/null -w "HTTP %{http_code}\n" --max-time 8 https://discord.com/api/v10/gateway
curl: (56) CONNECT tunnel failed, response 403
```

This cloud sandbox's egress policy blocks `discord.com` directly. This meant:

- **All core logic — constraint checking, the review state machine, idempotent
  scheduling, the durable publish worker, and the real Discord adapter's request-building
  and response-parsing — was built and proven with real function calls and a real
  `httpx.MockTransport` in this sandbox.** None of it needs Discord's actual API, only
  `discord`-shaped HTTP responses. `tests/test_discord_adapter.py` asserts the exact
  request the adapter builds (URL, `Authorization: Bot <token>` header, JSON body) against
  a fake transport, and separately asserts its parsing of both a success and a failure
  response — real verification of real code, without a network call.
- **The one thing that genuinely needs Discord's real API — a live bot token posting into
  a live channel and someone watching the message actually appear (Probe 4), plus killing
  and restarting the worker process against a real, persistent database file on a real
  machine (Probe 5) — has to run somewhere with normal internet access and a long-lived
  filesystem.** The application code has no knowledge of this constraint; `DiscordBotPublisher`
  just calls `httpx` normally when no fake client is injected. It only affected *where* that
  physical step could happen. Transcript in `EVIDENCE.md`.

## Where AI helped

- Recognizing that scheduling and publishing need **two separate** idempotency guarantees,
  not one. Scheduling the same (variant, slot) pair twice and a worker crashing mid-publish
  are different failure modes with different fixes: the first is a UNIQUE constraint (the
  same `usage_events`/`webhook_events` pattern from capstone 3 — the database decides who
  wins, not a check-then-insert in Python); the second needs a *claim* step (a conditional
  `UPDATE ... WHERE status='pending'`) that's independently committed from the actual
  publish, so a crash between the two leaves recoverable state instead of an ambiguous one.
- The abandoned-claim design: a `processing` assignment older than a timeout is reclaimed
  by the NEXT worker run rather than requiring a human to notice and fix it — this is what
  makes "kill the worker mid-batch, restart it, prove zero duplicates and zero skips"
  (Probe 5) something a test can actually assert (`test_crash_mid_batch_is_resumed_without_duplicate_publish`),
  not just something that's claimed in prose.
- Deliberately NOT pre-truncating generated variant text to a platform's `max_length`
  before storing it. An earlier instinct was to have the generator clip the body to fit —
  but that would make constraint checking pointless (nothing could ever violate a length
  rule the generator already enforced). Generating the FULL text and only THEN checking it
  is what makes `test_rule_breaking_variant_is_flagged_but_still_created` a real test of
  real blocking behavior, and it's also just a more honest design: a human should decide
  whether to trim a 500-character post for `x`, not have it silently cut mid-sentence.
- The registry indirection (`app/adapters/registry.py`) as the ONE place allowed to name a
  concrete adapter class, specifically so a test (`test_adapter_is_swappable_via_registry_with_no_worker_code_change`)
  could prove Probe 6 (adapter swap, zero business-logic changes) rather than just asserting
  it by code review.

## Where it was wrong, and what I changed

- **A real test-fixture bug, caught by running the suite, not by inspection.** The first
  version of `tests/test_publishing.py`'s durability tests created an assignment on the
  `conn` fixture, then immediately called `conn.close()` without committing — because
  `run_batch()` deliberately opens its OWN connection against the database *file* (that's
  the whole point: it has to survive the original process dying), the uncommitted insert
  was never actually on disk, so `run_batch()` saw zero due assignments and every assertion
  failed. The fix: commit before closing the setup connection in the helper that builds a
  due assignment (`_due_assignment()` in `tests/test_publishing.py`). This was a bug in the
  test harness, not in `app/lib/publishing.py` — the crash-recovery test that *did* commit
  before closing passed on the first run, which is what pointed at the missing commit
  rather than the worker logic.

No other functional bug turned up — constraint checking, the review state machine, the
UNIQUE-constraint scheduling guard, and the Discord adapter's request/response handling all
passed their tests on the first run, because (as in capstone 3) the patterns were chosen up
front specifically because they're hard to get subtly wrong, not discovered empirically.

## What I'd explain if asked about any 2-3 lines

- `app/lib/publishing.py::run_batch()` commits after EVERY individual claim and EVERY
  individual publish, not once at the end of the batch — a batch of 50 due assignments is
  50+ small transactions, not one big one. That's deliberate: it's what makes "the process
  dies after assignment #23" leave assignments #1-23 durably published and #24-50 durably
  untouched, instead of risking a half-committed batch or re-publishing #1-23 on restart.
- `_reclaim_stale()` runs ONCE at the start of every `run_batch()` call, before any new
  claims — so a worker that starts up after a crash always checks for abandoned work from
  its predecessor before doing anything else, rather than only reclaiming lazily if it
  happens to collide with a specific stale row.
- `approve_variant()`'s constraint check happens BEFORE the status-transition check would
  matter in practice (a `draft` variant is the only one that could have violations — an
  `approved` one, by construction, never does) — but it's still checked explicitly and
  raises a typed `ConstraintViolationError` carrying the exact violated rule strings, rather
  than relying on "it can't happen" being true forever as the code evolves.
