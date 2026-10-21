# Persistent conversation memory

PostgreSQL is the source of truth for conversation memory. A new chat request creates a
conversation owned by the server-authenticated customer. Passing its returned ID restores
that conversation's committed text on subsequent requests, including after application
restart. There is no process-global transcript or OpenAI conversation-state dependency.
The existing Responses adapter continues to use `store=False`.

## Migration and HTTP usage

Apply the new `0002_memory` revision before starting this version:

```sh
python -m alembic upgrade head
# Docker alternative:
docker compose run --rm migrate
```

The migration adds message ordering/metadata, last conversation activity, and extractive
summary fields to the existing tables. It backfills existing messages in `(created_at, id)`
order and then enables a PostgreSQL identity sequence. Tied historical timestamps can only
be ordered by their existing UUIDs; the new sequence makes future ordering unambiguous.
Readiness now requires revision `0002_memory`. Downgrade drops the new memory/audit fields
and sequence, retaining the original text rows; those new fields cannot survive a downgrade.

Every route requires the existing customer bearer token. Administrator tokens alone do not
grant customer access. Identity never comes from a request body, conversation ID or model call.

| Endpoint | Contract |
| --- | --- |
| `POST /api/v1/chat` | `{ "message": "My lamp is blue" }` creates a conversation |
| `POST /api/v1/chat` | `{ "message": "What color did I describe?", "conversation_id": "<returned UUID>" }` resumes it |
| `GET /api/v1/conversations?limit=50&offset=0` | `{ "items": [...], "next_offset": null }`, ordered by last activity, then UUID descending |
| `GET /api/v1/conversations/{id}` | Owned ID, status, channel, creation/update and last-activity timestamps |
| `GET /api/v1/conversations/{id}/messages?limit=50&after=0` | `{ "items": [...], "next_after": null }`, ordered by ascending message sequence |

Page limits are 1–100. Follow a non-null `next_offset`/`next_after` until null. Message cursors
are sequence numbers, not counts; gaps are normal after rollbacks and retention. Offset-based
conversation pages can shift as new activity arrives. A message has `id`, `sequence`, `role`,
redacted `content`, `metadata`, `created_at` and `updated_at`. Tool records use role `tool` and
an audit label as content; their structured projection lives in metadata. `turn_id` groups a
user message, tool records and assistant response. Raw summaries and internal summary cursors
are not exposed by the read APIs.

PowerShell example (supply `$env:CUSTOMEROPS_CUSTOMER_TOKEN` privately):

```powershell
$headers = @{ Authorization = "Bearer $env:CUSTOMEROPS_CUSTOMER_TOKEN" }
$reply = Invoke-RestMethod http://127.0.0.1:8000/api/v1/chat -Method Post -Headers $headers -ContentType application/json -Body '{"message":"My lamp is blue"}'
Invoke-RestMethod http://127.0.0.1:8000/api/v1/chat -Method Post -Headers $headers -ContentType application/json -Body (@{message="What color did I describe?";conversation_id=$reply.conversation_id} | ConvertTo-Json)
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/conversations/$($reply.conversation_id)/messages" -Headers $headers
```

## Context trimming and summaries

The memory service queries only customer-owned text messages from the requested conversation
within the retention window. System messages and historical tool records are never replayed
to the model. User rows retain their role; assistant/human-support rows become assistant text.
The most recent messages are kept first under a count and character budget. Individual long
rows are truncated for model context, while their stored redacted transcript is preserved.

For older messages, the service builds an **extractive summary**: a bounded list of recent
customer excerpts with source message IDs, sequence numbers and timestamps. It does not call
another model, infer preferences, summarize tool results, or generate new facts. The oldest
excerpts are dropped when space runs out. Incremental processing uses a persisted sequence
cursor and bounded scan; backlogs beyond that scan can be skipped in favor of newer excerpts.
The summary is intentionally lossy and does not promise recall of every earlier detail.

The note is inserted as clearly labeled, untrusted historical data in an assistant-role item,
never as a system/developer instruction. Older customer text may contain prompt injection;
neither the note nor a previous request authorizes a new side effect. Ticket authorization
checks the **current customer message**, and fresh business/RAG tools remain authoritative for
orders, stock, prices and policies. These rules limit the authority of memory; they do not
prove that a language model will semantically interpret every historical statement correctly.

Excerpts expire with their source-message retention window. Invalid or unsupported summary
formats are discarded and rebuilt from owned rows. Widening the history window removes any
summary overlap. Disabling history or summary replay clears the conversation's derived summary
on the next successful turn. Changes to summaries commit atomically with the chat response.

| Environment variable | Default / meaning |
| --- | --- |
| `CUSTOMEROPS_AGENT_HISTORY_MESSAGES` | 20 recent user/assistant/human rows; 0 disables all replay |
| `CUSTOMEROPS_MEMORY_HISTORY_MAX_CHARACTERS` | 24,000 characters across historical text and optional summary |
| `CUSTOMEROPS_MEMORY_HISTORY_MESSAGE_CHARACTERS` | 4,000 characters per historical row |
| `CUSTOMEROPS_MEMORY_SUMMARY_ENABLED` | `true` |
| `CUSTOMEROPS_MEMORY_SUMMARY_MAX_CHARACTERS` | 2,000 for the serialized model note, capped at one-third of history budget |
| `CUSTOMEROPS_MEMORY_SUMMARY_MAX_EXCERPTS` | 8 older customer excerpts |
| `CUSTOMEROPS_MEMORY_SUMMARY_EXCERPT_CHARACTERS` | 200 characters per excerpt |
| `CUSTOMEROPS_MEMORY_SUMMARY_SCAN_MESSAGES` | 200 older text rows per turn |
| `CUSTOMEROPS_MEMORY_PERSIST_TOOL_AUDIT` | `true`; disable structured tool audit persistence if unnecessary |

The current request is additional to historical limits and retains its existing 4,000-character
API bound. A request therefore includes at most the configured recent-row count, one optional
summary item, and the current message before the bounded agent tool loop adds its results.
These are conservative character budgets, not a tokenizer-specific context guarantee. The
agent's total-context, iteration, output-token, tool and whole-turn bounds still apply.

## Atomicity, concurrency and isolation

A request-scoped async session owns one database transaction for the entire turn. It locks
the customer row with `FOR UPDATE NOWAIT`, verifies owned conversation/status/expiry, builds
memory, and writes user text before tools run. Successful completion commits the user,
assistant, useful tool audit records, business side effects, summary and last-activity update
together. Provider failure, timeout, loop exhaustion or cancellation rolls the whole turn back.
Failed requests do **not** leave partial user messages, summaries or audit rows. Safe error
codes remain in logs; raw provider exceptions and failed raw prompts are not retained.

Concurrent turns for the same customer receive HTTP 409 `conversation_busy` before a second
provider call; this also serializes different conversations belonging to that customer. After
the successful turn commits, retrying a rejected request sees the committed context. Other
customers use independent locks. There is no automatic retry or idempotency key for a response
lost after commit: check history before resubmitting to avoid a duplicate successful turn.
The customer lock remains held during bounded provider I/O, as in the existing implementation.

Customer filters are included in message queries as well as conversation lookup. Missing,
expired and foreign conversations return the same 404. Conversation IDs are never permission
tokens. Summaries, provider instances and history are not shared across conversations, including
two conversations owned by the same customer. Read APIs do not require an available LLM key.

## Data minimization and retention

Before storage and model submission, best-effort deterministic redaction removes common email,
credential, payment-number and formatted phone patterns. Assistant output is redacted before
both persistence and return. Legacy transcript rows are redacted on context/API reads but are
not rewritten by this migration. Patterns do not reliably identify arbitrary names, addresses,
unformatted phone numbers, every language, or all secrets; do not treat them as a complete DLP
system. A customer may need to provide an order UUID, which remains available for scoped tools.

Tool metadata retains known tool name, bounded call ID, status, duration, safe error code,
validated identifier arguments, and selected identifier/count/status/stock result fields.
Free-form queries, ticket subjects/descriptions, document excerpts, raw malformed arguments,
hidden reasoning, credentials and full provider responses are not copied into audit rows.
Business services still own their necessary order/customer/support-ticket records separately.

| Environment variable | Default / expiration rule |
| --- | --- |
| `CUSTOMEROPS_MEMORY_MESSAGE_RETENTION_DAYS` | 30 days from each non-tool message's creation |
| `CUSTOMEROPS_MEMORY_TOOL_RETENTION_DAYS` | 7 days from each tool audit's creation |
| `CUSTOMEROPS_MEMORY_CONVERSATION_RETENTION_DAYS` | 90 days since last successful chat activity |

API reads and model context enforce these windows immediately. Expired inactive conversations
cannot be resumed. Physical cleanup is explicit; configure the operator's scheduler to invoke:

```sh
python -m customerops_ai.retention --apply --batch-size 50
# Docker alternative:
docker compose exec backend python -m customerops_ai.retention --apply
# Make alternative:
make retention
```

The CLI requires configured database credentials and deletes real expired data. It processes
1–100 customers per transaction, skips customer rows locked by active turns, and prints only
aggregate counts. Skipped customers are eligible on the next invocation. Completed batches
remain committed if a later batch fails; rerunning is safe. Matching expired text/audits are
deleted, and summary caches are cleared for processed customers so their contents cannot
outlive removed source text. Future turns rebuild summaries from retained messages.

Inactive conversations without tickets are deleted with their remaining messages. Conversations
referenced by support tickets retain an empty/expired conversation shell when their transcript
expires; the read APIs still hide expired conversations. The command does not delete customers,
orders, support tickets, external provider data, logs or database backups. Those require separate
operational retention policies. No automatic scheduling, background deletion task, or legal
compliance guarantee is included. Backups can retain deleted bytes until their own expiry.

## Verification

```sh
python -m pytest tests/test_memory_privacy.py tests/integration/test_memory.py --require-database
python -m pytest --require-database
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pip check
```

Set the isolated `_test` database URL documented in README. Tests use real PostgreSQL migrations
and sessions, replacing only the provider with explicit fakes. Restart tests create a new app,
provider and request-session lifecycle against the same database. The migration is tested both
on empty tables and pre-existing transcript rows, including downgrade/upgrade and model parity.
Summary tests are deterministic correctness checks, not a claim of measured model recall quality.
