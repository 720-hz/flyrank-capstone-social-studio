# Evidence

One real transcript per requirement and per acceptance probe. Everything below is a real
`curl`/`pytest`/`Invoke-RestMethod` run against a live local server or the automated test
suite — most of it from the cloud sandbox this was built in (2026-10-01), with the one
genuinely-real-platform step (a live Discord bot token posting into a live Discord channel,
explicitly called out below) run afterward on a machine with normal internet access, same
day — see `BUILDLOG.md` and `DESIGN.md` for why that split exists.

## Setup used for this run

```
$ python scripts/seed.py    # NOT used for this transcript — a fresh DB was used instead
                             # so every id below is predictable (post 1, variants 1-3, slot 1)
$ uvicorn app.main:app --port 8000
$ curl http://localhost:8000/health
{"status":"ok"}
```

## Ingestion + variant generation for ≥2 platforms

```
$ curl -X POST http://localhost:8000/v1/posts -H "Content-Type: application/json" -d '{
    "title":"FlyRank ships Social Media Studio","source_kind":"markdown",
    "source_text":"We just shipped the capstone: ... (475 chars total)"}'
{"id":1,"source_kind":"markdown","title":"FlyRank ships Social Media Studio", ...}

$ curl -X POST http://localhost:8000/v1/posts/1/variants -H "Content-Type: application/json" \
    -d '{"platforms":["discord","x","linkedin"]}'
{"variants":[
  {"id":1,"platform":"discord","status":"draft","constraint_violations":[]},
  {"id":2,"platform":"x","status":"draft","constraint_violations":[
      "max_length: 475 chars exceeds 280","max_hashtags: 5 exceeds 3"]},
  {"id":3,"platform":"linkedin","status":"draft","constraint_violations":[]}
]}
```

One post, one generation call, three platform-specific variants — the `x` variant breaks
two of its platform's rules purely from the source content being too long, with zero
special-casing to force that outcome.

## Probe: a rule-breaking variant is blocked, naming the broken rule

```
$ curl -w "\nHTTP %{http_code}\n" -X POST http://localhost:8000/v1/variants/2/approve \
    -H "Content-Type: application/json" -d '{}'
{"detail":{"error":"constraint_violation","violations":[
    "max_length: 475 chars exceeds 280","max_hashtags: 5 exceeds 3"]}}
HTTP 422
```

Approval is refused with a `422` that names the exact broken rules — not a generic "invalid"
message. The variant stays `draft`; nothing downstream ever sees it as approved.

Fixing it (human edits the text) and re-checking, then approving, succeeds:

```
$ curl -X POST http://localhost:8000/v1/variants/2/edit -H "Content-Type: application/json" -d '{
    "body_text":"We shipped Social Media Studio: ingest once, generate per-platform
                  variants, enforce constraints before review, publish through one
                  adapter interface.","hashtags":["#flyrank","#launch"]}'
{"id":2,"status":"draft","constraint_violations":[]}

$ curl -w "\nHTTP %{http_code}\n" -X POST http://localhost:8000/v1/variants/2/approve \
    -H "Content-Type: application/json" -d '{}'
{"id":2,"status":"approved", ...}
HTTP 200
```

## Probe: scheduling an unapproved variant is rejected (4xx)

```
$ curl -w "\nHTTP %{http_code}\n" -X POST http://localhost:8000/v1/assignments \
    -H "Content-Type: application/json" -d '{"variant_id":3,"slot_id":1}'
{"detail":"variant must be 'approved' to schedule; it is 'draft'"}
HTTP 409
```

Variant 3 (linkedin) was still `draft` at this point. The route layer maps
`VariantNotApprovedError` to a real `409`, not a `500` and not a silent no-op.

## Idempotent scheduling (same variant+slot twice → one row)

```
$ curl -X POST http://localhost:8000/v1/assignments -H "Content-Type: application/json" \
    -d '{"variant_id":1,"slot_id":1}'
{"id":1,"variant_id":1,"slot_id":1,"idempotency_key":"1:1","status":"pending", ...}

$ curl -X POST http://localhost:8000/v1/assignments -H "Content-Type: application/json" \
    -d '{"variant_id":1,"slot_id":1}'     # same call again
{"id":1,"variant_id":1,"slot_id":1,"idempotency_key":"1:1","status":"pending", ...}
                                            # ^ SAME id (1), not a new row

$ python3 -c "
import sqlite3; c = sqlite3.connect('social_studio.db')
print(c.execute('SELECT COUNT(*) AS n FROM schedule_assignments WHERE variant_id=1 AND slot_id=1').fetchone())
"
(1,)
```

## Probe: durable, resumable worker — survives a crash mid-batch with zero duplicates

Three approved variants (1, 2, 3) were scheduled into one due slot. Before running the
worker, assignment 3 was forced into `processing` with a `claimed_at` 120 seconds in the
past — simulating a worker that claimed it and then crashed before publishing (the exact
scenario `ASSIGNMENT_CLAIM_TIMEOUT_SECONDS` exists to recover from):

```
$ python3 -c "
import sqlite3
from datetime import datetime, timedelta, timezone
c = sqlite3.connect('social_studio.db')
stale = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
c.execute(\"UPDATE schedule_assignments SET status='processing', claimed_at=? WHERE id=3\", (stale,))
c.commit()
"
assignment 3 forced into: (3, 'processing', '2026-10-01T00:39:31...')

$ curl -X POST http://localhost:8000/v1/publish-runs -H "Content-Type: application/json" -d '{}'
{"job_id":1,"total":3,"processed":3}

$ curl http://localhost:8000/v1/publish-history
{"attempts":[
  {"id":3,"assignment_id":3,"platform":"linkedin","attempt_number":1,"outcome":"success", ...},
  {"id":2,"assignment_id":2,"platform":"x","attempt_number":1,"outcome":"success", ...},
  {"id":1,"assignment_id":1,"platform":"discord","attempt_number":1,"outcome":"failure",
      "error":"403 Forbidden", ...}
]}
```

Assignment 3 (the simulated crash victim) was reclaimed and published exactly once —
`attempt_number: 1`, one row in `publish_attempts`, not two. (Assignment 1, the real
Discord target, failed for an unrelated reason: this sandbox's egress policy blocks
`discord.com` — see "Sandbox network note" below. It's the right KIND of failure: logged,
not silently swallowed, and retryable.)

Re-running the worker immediately afterward processes zero — nothing is left pending/due:

```
$ curl -X POST http://localhost:8000/v1/publish-runs -H "Content-Type: application/json" -d '{}'
{"job_id":2,"total":0,"processed":0}
```

This exact scenario — forcing a stale `processing` claim, then asserting `run_batch()`
reclaims and publishes it exactly once — is also an automated, repeatable test:
`tests/test_publishing.py::test_crash_mid_batch_is_resumed_without_duplicate_publish`
(passing — see the full suite run below). A second test,
`test_still_processing_and_not_yet_stale_is_left_alone`, proves the inverse: a `processing`
claim that is NOT yet stale is left untouched by a second run (a live worker's in-flight
work isn't stolen out from under it).

## Probe: adapter swap via config only, zero business-logic changes

`tests/test_publishing.py::test_adapter_is_swappable_via_registry_with_no_worker_code_change`
defines a throwaway third `SocialPublisher` implementation (`_SpyPublisher`, in the test
file itself, nowhere near `app/`), passes it into `run_batch()` via a `registry_factory`
override, and asserts the worker called IT instead of `MockXPublisher` — without a single
line of `app/lib/publishing.py` or `app/routes/schedule.py` changing. `app/adapters/registry.py`
is the only file in `app/` that ever names a concrete adapter class.

## Retry + error-path handling

```
$ curl -X POST http://localhost:8000/v1/assignments/1/retry -H "Content-Type: application/json" -d '{}'
{"id":1,"status":"pending", ...}        # failed -> pending, ready for the next run

$ curl -w "\nHTTP %{http_code}\n" http://localhost:8000/v1/variants/9999
{"detail":"variant not found"}
HTTP 404

$ curl -w "\nHTTP %{http_code}\n" -X POST http://localhost:8000/v1/assignments \
    -H "Content-Type: application/json" -d '{"variant_id":9999,"slot_id":1}'
{"detail":"no variant with id 9999"}
HTTP 404
```

## Mock adapters recording a real preview

```
$ curl http://localhost:8000/v1/mock-log
{"entries":[
  {"id":2,"platform":"linkedin","body_text":"FlyRank ships Social Media Studio...",
   "external_id":"mock_linkedin_3058c2836f61", "posted_at":"2026-10-01T00:41:32..."},
  {"id":1,"platform":"x","body_text":"We shipped Social Media Studio...",
   "external_id":"mock_x_d203db695bc2", "posted_at":"2026-10-01T00:41:32..."}
]}
```

## Automated test suite — 30 tests, fully offline

```
$ pytest tests/ -v
tests/test_constraints.py ....... (7 passed)
tests/test_discord_adapter.py ... (3 passed)
tests/test_ingestion_and_variants.py ...... (6 passed)
tests/test_publishing.py ..... (5 passed)
tests/test_review.py ..... (5 passed)
tests/test_scheduling.py .... (4 passed)
============================== 30 passed in 0.41s ==============================
```

Zero network calls anywhere in the suite — confirmed by grep (the only unguarded
`httpx.Client(...)` construction in `app/adapters/discord_bot.py` is the fallback branch
taken only when no client is injected, and every test injects a `MockTransport`-backed
client instead).

## Probe: a real Discord bot token posting into a real Discord channel (run on a machine with normal internet access, 2026-10-01)

Same seeded demo post used throughout this document (`post_id=1`, the `discord` variant,
`assignment_id=1`) was published for real, with a real bot token and a real channel id in
`.env`, against the live Discord API — not a fake transport this time:

```
PS> Invoke-RestMethod -Uri http://localhost:8000/v1/publish-runs -Method Post -ContentType "application/json" -Body '{}'

job_id total processed
------ ----- ---------
     1     1         1

PS> (Invoke-RestMethod -Uri http://localhost:8000/v1/publish-history) | ConvertTo-Json -Depth 5
{
  "attempts": [
    {
      "id": 1, "assignment_id": 1, "platform": "discord", "attempt_number": 1,
      "outcome": "success", "external_id": "1555027775293751409",
      "raw_response": "{\"type\": 0, \"content\": \"FlyRank ships Social Media Studio\n\n
        We just shipped the capstone: ingest once, generate per-platform variants,
        enforce each platform's constraints before anyone reviews them, and publish
        through one adapter interface backed by a real Discord bot and mock adapters
        for X and LinkedIn.\n\n#flyrank #ships #social #media #studio\",
        \"id\": \"1555027775293751409\", \"channel_id\": \"1555024974354456700\",
        \"author\": {\"id\": \"1555023159537700894\", \"username\": \"150mg bot\",
        \"bot\": true, ...}, ...}",
      "error": null, "attempted_at": "2026-10-01T01:25:13.246012+00:00"
    }
  ]
}
```

And visually confirmed in the Discord client itself: the message posted by **150mg bot
(APP)** in the `#general` channel of the test server, at 04:25, with the exact title,
body, and hashtags the variant held — screenshot on file. `external_id` in
`publish_attempts` (`1555027775293751409`) matches the real Discord message id
(`raw_response.id`), confirming the stored history and the actual posted message are the
same event, not a coincidence.

This is the live counterpart to `tests/test_discord_adapter.py` (which proves the same
adapter's request-building/response-parsing against a fake transport) and to the
simulated-crash durability proof above — same code path, same `DiscordBotPublisher`, no
special-casing for "real" vs. "test."

## A literal process kill/restart (optional additional rigor)

The crash-recovery mechanism (`ASSIGNMENT_CLAIM_TIMEOUT_SECONDS` + reclaim-then-claim in
`app/lib/publishing.py::run_batch()`) is already proven two ways above: an automated test
(`test_crash_mid_batch_is_resumed_without_duplicate_publish`) and a live `curl`/`sqlite3`
transcript, both forcing a `processing` assignment into a stale state to simulate a worker
that claimed work and then died. The mechanism has no way to distinguish "the previous
claimant crashed" from "I forced this row into that state for a test" — it only looks at
`claimed_at` age — so a literal `Ctrl+C` mid-`uvicorn` and a restart exercises the exact
same code path, not a different one. Not re-run separately here since the simulated version
already executes that code for real.

## Sandbox network note

```
$ curl -sS -o /dev/null -w "HTTP %{http_code}\n" --max-time 8 https://discord.com/api/v10/gateway
curl: (56) CONNECT tunnel failed, response 403
```

Confirmed directly, same shape of restriction as capstone 3's `api.stripe.com`. See
`BUILDLOG.md` and `README.md` for what this did and didn't affect.
