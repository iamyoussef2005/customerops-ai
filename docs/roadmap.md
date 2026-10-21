# Implementation roadmap

Milestones 0, 1 (implementation), 4 (core agent), and 5 (RAG) are delivered. Authenticated business
tools and bounded conversation/ticket behavior from milestones 2/3 were explicitly requested
as prerequisites; standalone business REST and human-workflow APIs remain planned.
Container runtime verification may remain environment-blocked; see verification.md for actual evidence.
Models and fictional seeds originally planned later were explicitly requested in this phase.
Further business/integration milestones remain plans and require a new user
request. They are not authorization to continue. No later feature should be advertised as
working based on reserved packages or unit-test fakes.

## 0. Bootstrap — implemented

Acceptance criteria:

- Installable Python 3.12+ package with runtime and development dependency groups.
- Typed FastAPI app factory and `GET /api/v1/health` returning HTTP 200, `{"status":"ok"}`.
- Pydantic Settings reads environment variables with an optional safe `.env.example`.
- HTTP health and configuration tests; Ruff, strict mypy, and pytest configuration.
- README, Makefile, contributor instructions, architecture, and roadmap reflect actual scope.
- GitHub Actions workflow runs checks on Python 3.12 and 3.14; remote execution still needs
  a repository push. Local execution evidence is reported in the task handoff.
- No external service required to start or test the app.

## 1. Persistence and local infrastructure — implemented; verification in verification.md

Acceptance criteria:

- PostgreSQL, async SQLAlchemy 2.x session lifecycle, and Alembic migrations work against
  a real development database. Migrations upgrade an empty database and have a tested rollback.
- Dockerfile and Compose start API and database with documented commands and health checks.
- Resolved Python constraints and pinned container patch tags constrain local builds. Image
  digest/build-tool locking remains deferred; bit-for-bit reproducibility is not claimed.
- Validated database configuration, no committed secrets, separate liveness and readiness.
- Database integration tests run against isolated PostgreSQL; failure/rollback paths are tested.
- Includes Customer, Product, Order, OrderItem, Conversation, Message, and SupportTicket models.
- Fictional seeds insert 15 products, 5 customers, 10 orders, and 20 items idempotently.
- Redis is provisioned only. No application cache or standalone business REST APIs exist yet.

## 2. Product catalog and order services — tools delivered; standalone REST APIs planned

Acceptance criteria:

- Already delivered: products, stock, and orders have repeatable fictional fixtures and migrations.
- Delivered for chat: bounded product search/details/stock and owned-order status services/repositories.
- Server-managed bearer authentication and ownership protect tool access.
- Product search, stock lookup, and order tracking use routes -> services -> repositories.
- Authentication and object-level authorization prevent unauthorized order access.
- Pagination, validated filters, documented error responses, and query edge cases are tested.
- Real database tests demonstrate persistence and inventory/order consistency.

## 3. Conversation memory — delivered; full human workflow planned

Acceptance criteria:

- Delivered: authenticated chat with owned conversations, bounded history, serialized atomic
  turns, limited ticket opening, and suppression of replies while waiting for a human.
- Delivered: owned conversation APIs, persistent bounded context, extractive summaries, redacted
  tool audit projections, and configurable read/physical retention. See [memory.md](memory.md).
- Full human case ownership/resolution APIs remain planned.
- Concurrent customer turns are rejected with 409; successful-turn idempotency keys remain planned.
- Escalation creates a durable support case with pending/owned/resolved states.
- Human ownership suppresses automatic replies; state transitions and access rules are tested.
- Retention, redaction, and deletion rules are documented and enforced by tests.

## 4. OpenAI agent through REST — implemented; paid provider smoke is opt-in

Acceptance criteria:

- Async OpenAI Responses integration uses environment-based credentials and model selection.
- Typed, allowlisted product, stock, order, and escalation tools call existing services.
- Bounded turns/tool loops, timeouts, token budgets, safe retries, and unavailable-provider
  responses are implemented and tested without paid calls in CI.
- Conversation history is used under explicit context limits; secrets and private data are redacted.
- An opt-in real-provider smoke test is documented separately from mocked contract tests.
- Tool authorization cannot be overridden by a prompt; adversarial cases demonstrate this.
- `POST /api/v1/chat` uses a bounded orchestrator, strict tool registry, independently validated
  execution, and the official async Responses SDK. See agent.md for real-key setup/testing.
- Offline tests use explicit provider fakes and the real SDK with a mock transport. Paid
  provider success is not claimed unless the optional live smoke is executed successfully.

## 5. Documentation-grounded RAG — implemented; live quality evaluation pending

Administrator ingestion supports PDF/Markdown/text with bounded uploads, normalization,
overlap, duplicate detection, atomic generation publication, deletion and forced re-indexing.
The agent has a sixth knowledge-search tool and verified response source references. Four
fictional documents and a 24-question retrieval evaluation dataset are included. Offline
tests use real temporary Chroma and fake embeddings; real-key quality metrics remain
unmeasured. See [RAG design, setup and evaluation](rag.md) and [actual checks](verification.md).

Acceptance criteria:

- Approved fictional policy/product documents have repeatable chunking, embedding, and
  ChromaDB ingestion with stable source IDs and document version metadata.
- Retrieval returns evidence and source citations; missing evidence produces an honest fallback.
- Update/delete ingestion removes stale chunks; retrieval quality has a fixed evaluation set.
- Prompt injection in retrieved documents does not authorize tools or disclose private data.
- Answers about order status and inventory use business tools rather than stale document text.

## 6. Web chat channel — planned

Acceptance criteria:

- A minimal chat UI uses the same conversation service and authenticated API.
- Loading, errors, reconnect/retry, context continuity, citations, and human escalation are visible.
- CORS and rate limits are explicit; no provider secrets reach the browser.
- End-to-end tests cover a conversation, provider failure, and escalation handoff.

## 7. WhatsApp channel — planned

Acceptance criteria:

- A selected provider adapter verifies signatures and deduplicates webhook events.
- Inbound/outbound messages map to durable conversations with verified identity/ownership.
- Delivery failures, retries, and escalation ownership are handled with idempotency.
- Provider sandbox verification and required configuration are documented; mocked tests are
  clearly separated from confirmed external delivery.

## 8. Operational hardening and portfolio release — planned

Acceptance criteria:

- Structured redacted logs, request IDs, latency/errors, tool usage, and model cost metrics exist.
- Introduce Redis only for a documented cache/rate-limit/coordination need; test expiry and failure.
- CI includes real dependency integration checks, dependency auditing, and reproducible builds.
- Load/failure tests cover timeouts, concurrency, provider outages, and shutdown resource cleanup.
- Deployment, migration, backup/restore, and incident runbooks are executable and verified.
- Publish architecture tradeoffs, a demonstration with fictional data, and evaluation results;
  explicitly document limitations and which integrations were tested live.
