# Core customer support agent

`POST /api/v1/chat` uses the official asynchronous OpenAI SDK and Responses API. The model
requests six allowlisted functions; it cannot query SQL, select a customer identity, execute
code, issue refunds, or send external messages. WhatsApp is not implemented. The knowledge
search tool uses approved documents and verified source references; missing evidence yields
an explicit unknown-policy response. See [RAG setup and limits](rag.md).

## Real-key setup

Install with `python -m pip install -c requirements.lock -e . --group dev`, apply migrations,
and seed the fictional database using README. This phase uses existing tables; no migration
changes are needed. Set these values privately in `.env` or the process environment:

```dotenv
OPENAI_API_KEY=<your-key>
CUSTOMEROPS_AGENT_MODEL=<Responses-function-calling-model-available-to-your-project>
CUSTOMEROPS_AUTH_TOKEN_CUSTOMERS={"<sha256-token-fingerprint>":"<existing-customer-uuid>"}
```

No model is assumed. Choose an account-accessible model supporting strict function calling.
Empty model/key settings disable the agent without disabling health/readiness. Compose
forwards agent settings from `.env`; recreate the backend after changing them.

Generate a strong customer token and its mapping for the **first fictional seeded customer**:

```sh
python -c "import hashlib,json,secrets; from customerops_ai.seed import seed_id; t=secrets.token_urlsafe(32); print('Save customer bearer token privately:',t); print('CUSTOMEROPS_AUTH_TOKEN_CUSTOMERS='+json.dumps({hashlib.sha256(t.encode()).hexdigest():str(seed_id('customer:0'))}))"
```

Save the bearer token privately. Copy only its fingerprint mapping into the server configuration.
The API key and customer token are distinct: the API key belongs only to the backend.
Never commit either credential. This is real server-managed opaque-token authentication, not
a login, JWT issuer, or OAuth service. Issue random tokens out of band; rotate/revoke by changing
the mapping and restarting. Mapping keys are validated SHA-256 digests and mapped customers
must exist. Customer identity headers/body fields have no authority. Use HTTPS when exposing auth.

Start with `docker compose up --build -d --wait`, or the native development command:

```powershell
.\.venv\Scripts\python.exe -m uvicorn customerops_ai.main:app --reload --host 127.0.0.1 --port 8000
```

Chat requires PostgreSQL even for general questions because successful turns are persisted.

## API

```http
POST /api/v1/chat
Authorization: Bearer <customer-token>
Content-Type: application/json

{"message":"Find an in-stock desk accessory","conversation_id":null}
```

`message` requires 1–4000 non-whitespace characters. The optional conversation UUID must
belong to the authenticated customer. Extra input fields, including `customer_id`, are rejected.

Illustrative response shape, not a recorded live result:

```json
{
  "conversation_id": "<conversation-uuid>",
  "message": "<assistant answer based on tool results>",
  "tool_executions": [
    {"name":"search_products","status":"ok","duration_ms":4.2,"error_code":null}
  ]
}
```

Reuse the returned conversation ID for follow-ups. Order tools require an order UUID;
obtain a fictional fixture UUID with:

```sh
python -c "from customerops_ai.seed import seed_id; print(seed_id('order:0'))"
```

PowerShell full-stack example:

```powershell
$token = Read-Host "Customer bearer token"
$headers = @{Authorization = "Bearer $token"}
$reply = Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/chat -Method Post -Headers $headers -ContentType application/json -Body (@{message="Find an in-stock desk accessory"} | ConvertTo-Json)
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/chat -Method Post -Headers $headers -ContentType application/json -Body (@{message="Tell me more about the first product"; conversation_id=$reply.conversation_id} | ConvertTo-Json)
```

Failures use `{"error":{"code":"provider_timeout","message":"The assistant timed out. Please try again."}}`.
No SQL/provider exception text or validation input echoes are returned.

| HTTP status | Meaning |
| --- | --- |
| 401 | Missing/invalid bearer token or nonexistent configured customer |
| 404 | Missing or foreign conversation |
| 409 | Another turn is running; conversation closed/awaiting human |
| 422 | Invalid input, context limit, or iteration/tool budget exhausted |
| 502/503 | Provider error, unconfigured agent, or database unavailable |
| 504 | Provider or whole-turn timeout |

Tool errors are structured function results rather than necessarily HTTP failures. Foreign
and missing orders both return `not_found` to the model; chat can explain that with HTTP 200.
Ticket quota errors use `ticket_limit`. Response traces contain only known tool names, status,
duration, and safe error codes, not raw arguments or internal exception details.

## Boundaries and security

```text
API -> server bearer identity -> ChatService -> AgentOrchestrator -> LLMProvider
                                     |                |
                          conversation repository  ToolExecutor -> CustomerToolService
                                                                 -> repositories -> PostgreSQL
```

- `integrations/openai_provider.py` owns `AsyncOpenAI.responses.create`, error translation,
  response parsing, and stateless `store=False` requests. Lifespan creates/closes the SDK
  client. SDK automatic retries are disabled.
- The tool registry uses the SDK Pydantic helper for strict schemas: nested objects disallow
  extra properties and optional fields become required nullable fields. The executor independently
  validates JSON, duplicate keys, size, UUIDs, types, price bounds, extra fields, and ticket lengths.
- Calls go only through business services. Customer/conversation identity is bound on the
  server and is absent from model argument schemas. Order and conversation queries include ownership.
- The orchestrator preserves all response output items, including encrypted reasoning, then
  appends `function_call_output` items with original call IDs. Calls execute sequentially;
  repeated IDs and excessive loops/batches are rejected. Tool text remains untrusted data.
- Search returns at most 10 active products and treats wildcard input literally. Details
  cap description size. Order results omit addresses and unrelated customer data.
- Ticket subjects require 3–120 characters and descriptions 10–2000. Existing open tickets
  in a conversation are reused. Each customer gets at most three new tickets per rolling hour
  by default. Ticket creation sets `waiting_human`, stopping later automated turns in that
  conversation. This queues a durable request; no live human connection/notification is claimed.
- Ticket intent is chosen by the model under explicit instructions, with an additional server
  check for a current customer request; old history or summaries cannot authorize a ticket.
  Authentication, ownership, supported operations, validation and quotas remain server-side.

## Transactions, memory, reliability

A successful turn commits user message, tool writes, and assistant message atomically.
Provider failure, cancellation, deadline, or loop exhaustion rolls everything back, including
tickets. Tools use savepoints so recoverable errors can be returned as structured results.
Failed turns do not enter history. Provider usage charges cannot be rolled back.

A NOWAIT customer row lock serializes concurrent turns and ticket quotas across processes.
Contention returns 409 before a provider call. This intentionally holds one transaction and
connection during the bounded provider turn; a later turn-state/job design can reduce pool
occupancy if load warrants it. There is no Redis-backed locking/cache claim.

History defaults to 20 recent user/assistant/human messages and an optional extractive note,
with 24,000 historical characters total; count, trimming, summary and retention are configurable.
Stored system/tool roles are not promoted into instructions. Within-turn provider context is capped
at 100,000 serialized characters, arguments at 8192 bytes, tool results at 16,000 characters,
and final text at 8000 characters. Hidden reasoning is not stored in conversation messages.
These are character limits, not exact token accounting. New-conversation POSTs are not HTTP
idempotent: do not blindly retry a lost successful ticket response. Ticket reuse and quotas
limit duplicates but do not provide general request idempotency.

| Environment variable | Default |
| --- | --- |
| `CUSTOMEROPS_AGENT_PROVIDER_TIMEOUT` | 20 seconds per SDK request |
| `CUSTOMEROPS_AGENT_TURN_TIMEOUT` | 45 seconds per whole turn |
| `CUSTOMEROPS_AGENT_TOOL_TIMEOUT` | 5 seconds per operation |
| `CUSTOMEROPS_AGENT_MAX_ITERATIONS` | 6 provider requests, including final answer |
| `CUSTOMEROPS_AGENT_MAX_TOOL_CALLS` | 12 attempts; at most 4 calls per response |
| `CUSTOMEROPS_AGENT_MAX_OUTPUT_TOKENS` | 1500 per response |
| `CUSTOMEROPS_AGENT_HISTORY_MESSAGES` | 20 |
| `CUSTOMEROPS_AGENT_TICKETS_PER_HOUR` | 3 |

Timing is recorded in response traces and `tool_execution` INFO log extras. Failures log safe
event codes or exception class names, without customer text, arguments/results, tokens, API
keys, or SQL/provider exception messages. Enable application INFO logging to collect success
events; failure events use WARNING/ERROR. OpenAI receives only scoped conversation/tool data,
not database access credentials.

## Offline tests and optional real API smoke

```sh
python -m pytest -m "not live"
python -m pytest -m "not live" --require-database
```

The second command requires the isolated test database URL described in README. FakeProvider
implements the explicit LLMProvider protocol. Business-tool unit tests label in-memory fakes;
integration tests use real PostgreSQL with only the LLM replaced. Adapter tests use an HTTPX2
mock transport with the real SDK to verify `/v1/responses`, schema submission, reasoning
preservation, parsing, provider errors, and timeouts. None proves paid-provider availability.

Opt into a real function-call round trip separately:

```powershell
# Supply OPENAI_API_KEY privately in this process; choose your account-accessible model.
$env:CUSTOMEROPS_AGENT_MODEL = "<your-responses-model>"
$env:CUSTOMEROPS_RUN_LIVE_SMOKE = "1"
.\.venv\Scripts\python.exe -m pytest tests/live/test_openai_smoke.py -m live -q
```

On POSIX export the same variables and use `python`. This makes two paid Responses calls:
a live function call and a follow-up with an explicitly **synthetic stock fixture**. It checks
the SDK/provider contract, not real inventory. The API examples above exercise real database
tools with a real key. The live test is skipped by default and excluded from CI/offline commands.

Official references: [OpenAI Python SDK](https://developers.openai.com/api/reference/python)
and [Responses function calling](https://developers.openai.com/api/docs/guides/function-calling).

## Persistent memory

Conversation list/detail/message APIs, deterministic extractive summaries, ordered tool audit
projections, redaction and configurable retention are implemented. See [memory design and
commands](memory.md) for current context budgets and failure/concurrency semantics. Ticket
authorization requires a request in the current customer message; history alone cannot grant it.
