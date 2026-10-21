# Verification history


## Latest phase: persistent conversation memory

Verified locally on 2026-10-21 using Python 3.14.4 and isolated native PostgreSQL 18.4.

| Check | Actual result |
| --- | --- |
| Full `python -m pytest --require-database -q` | 142 passed; 1 paid smoke skipped |
| Final focused agent/privacy rerun after audit guard refinement | 38 passed |
| `python -m ruff check .` | Passed |
| `python -m ruff format --check .` | Passed; 91 files |
| `python -m mypy` | Passed; 79 source files |
| `python -m pip check` | No broken requirements |
| Migration upgrade/downgrade and ORM schema parity | Passed against real PostgreSQL |
| Migration of pre-existing transcript rows | Passed; content/order preserved and identity advances |
| Retention CLI `--help` | Passed; destructive execution requires `--apply` |
| Compose config with memory settings | Validated successfully |
| Docker runtime | Unavailable: Docker Desktop Linux engine named pipe missing |
| Paid OpenAI requests / remote GitHub Actions | Not executed |

The full suite used `python .local/with_test_database.py -m pytest --require-database -q`;
the ignored helper supplies generated credentials for a disposable `_test` database without
printing them. For another environment, export `CUSTOMEROPS_TEST_DATABASE_URL` and run pytest
directly. All schema-changing checks stayed inside isolated test schemas. No migration or
retention purge was applied to development data. The disposable test cluster was stopped.

New coverage includes new/continued conversations, a new application/provider/session lifecycle
restoring committed context, customer and same-customer cross-conversation isolation, API/message
pagination, deterministic summaries and trimming bounds, redaction/configuration, audit payload
projection, provider rollback, concurrent same-conversation rejection/retry, expiry visibility,
physical retention, shorter conversation TTLs, support-ticket preservation, locked-customer
skipping and repeatable cleanup. Summaries cannot authorize actions, and corrupt formats are
rejected. Summary recall and semantic answer quality are not measured by these correctness tests.

The first migration downgrade test caught a double-prefixed constraint name; using Alembic's
final-name marker fixed it. A privacy test caught non-idempotent credential placeholders; stable
placeholders fixed repeated redaction. Subsequent full runs passed. See [memory.md](memory.md)
for settings, API examples, retention commands and the documented limitations.

## Previous phase: persistent RAG

Verified on 2026-10-21 with Python 3.14.4, native PostgreSQL 18.4, ChromaDB 1.5.9,
pypdf 6.21.1 and OpenAI SDK 3.35.1 on Windows. No paid OpenAI request was made.

| Check | Actual result |
| --- | --- |
| `python -m pytest --require-database -q` with isolated PostgreSQL | 106 passed; 1 paid smoke skipped |
| RAG cases within that suite | 30 passed with real temporary Chroma and fake embeddings |
| `python -m ruff check .` | Passed |
| `python -m ruff format --check .` | Passed; 78 files |
| `python -m mypy` | Passed; 67 source files |
| `python -m pip check` | No broken requirements |
| `python -m pip install -c requirements.lock -e . --group dev` | Passed |
| Linux CPython 3.12 binary dependency dry-run against updated constraints | Resolved successfully; not executed on Linux |
| `docker compose config --quiet` using the installed Compose executable | Passed |
| Docker engine check | Failed: `dockerDesktopLinuxEngine` named pipe does not exist |
| Evaluation CLI `--help` | Passed; paid requests require explicit opt-in flag |
| Real-key RAG retrieval/answer evaluation | Not run; no measured live quality metrics |

Full tests were executed through the ignored local credential helper:
`python .local/with_test_database.py -m pytest --require-database -q`. It sets an isolated
test database URL without printing its generated password. For another environment, set
`CUSTOMEROPS_TEST_DATABASE_URL` to your separate `_test` database and run pytest directly.
The disposable cluster was stopped after checks.

RAG coverage includes PDF text/metadata, no-OCR/encrypted-file rejection, normalization,
overlap, deterministic IDs, duplicate ingestion, model changes, forced re-indexing,
stale-vector retirement, deletion, metadata filters, absent evidence, bad vectors,
embedding timeout/failure, failed Chroma publication, concurrent deletion during embedding,
administrator/customer separation, upload bounds/path rejection, verified citations,
unknown-policy fallback, document-triggered ticket denial, and application resource lifecycle.
The composed HTTP test uses the real OpenAI SDK with a mock transport and real Chroma storage.
Evaluation arithmetic is tested with synthetic embeddings; its numbers are not real retrieval
quality measurements. Dataset structure and expected sample source files are checked offline.

Chroma 1.5.9 calls the deprecated `asyncio.iscoroutinefunction` alias on Python 3.14. A
module-specific pytest warning filter covers that upstream warning; other warnings still fail.
The initial run exposed unclosed local SQLite connections; explicit connection cleanup fixed
that issue, and subsequent full runs passed with warnings treated as errors.

Container build/startup, actual mounted-volume permissions, live Redis, Python 3.12 execution,
and remote GitHub Actions remain unverified. Start Docker Desktop's Linux engine, then follow
README's Compose commands. Embedded Chroma supports one worker per persistence directory;
citation checks verify provenance rather than semantic entailment. See [RAG setup and
evaluation method](rag.md) for real-key commands and operational limits.

## Earlier database/infrastructure verification

Verified locally on 2026-10-21 with Python 3.14.4 and native PostgreSQL 18.4 on Windows.
Database verification used a newly initialized, password-authenticated disposable cluster
bound to loopback, with generated credentials kept only in ignored `.local` files. The
existing PostgreSQL service on port 5432 was not used for application/schema changes.
The disposable verification cluster has been stopped. Generated verification credentials
remain only in ignored `.local` files: automatic policy review rejected their cleanup command
with "blocked by policy" and no further reason. No credentials were added to tracked sources.

## Previous phase: core AI agent

The core agent phase was verified with Python 3.14.4, PostgreSQL 18.4, and OpenAI SDK 3.35.1.
No paid OpenAI request was made during offline verification.

| Check | Actual result |
| --- | --- |
| Full offline suite with required isolated PostgreSQL | 76 passed; 1 live smoke excluded |
| `python -m ruff check .` | Passed |
| `python -m ruff format --check .` | Passed, 65 Python files |
| `python -m mypy` | Passed, 59 source files |
| `python -m pip check` | Passed |
| Constrained editable install including SDK 3.35.1 | Passed |
| Compose configuration including agent environment | Validated successfully |
| Linux CPython 3.12 binary dependency resolution for SDK 3.35.1 | Passed; not an execution test |
| Optional paid OpenAI smoke | Not executed; explicit opt-in required |

The suite includes normal/single-tool/sequential/multi-call conversations, strict schemas,
malformed/missing/oversized/duplicate arguments, unsupported tools, order/conversation ownership,
provider/tool timeouts, sanitized failures, loop/call limits, preserved reasoning items, durable
history, ticket validation/reuse/quotas, atomic rollback, and concurrent customer turn rejection.
Provider-contract tests run the real SDK on an HTTPX2 mock transport; integration tests run
real PostgreSQL services with only the LLM boundary faked. RAG was added in the subsequent phase.

Reproduce using an isolated test database URL:

```sh
python -m pytest -m "not live" --require-database
```

See [agent setup and manual real-key tests](agent.md). A successful mock-backed test is not
evidence that a selected model or API key has live access. Python 3.12 execution and remote CI
remain unexecuted locally; CI is configured for 3.12 and 3.14 without paid calls.

## Previous infrastructure phase results

| Check | Result |
| --- | --- |
| Editable installation with `-c requirements.lock -e . --group dev` | Passed |
| `python -m ruff check .` | Passed |
| `python -m ruff format --check .` | Passed, 40 Python files |
| `python -m mypy` | Passed, 36 source files |
| `python -m pip check` | Passed |
| `python -m pytest --require-database` with isolated test URL | 27 passed, including 16 database cases |
| `python -m pytest` with no test URL | 11 passed, 16 explicitly skipped |
| Real Alembic CLI `upgrade head` | Passed against an empty disposable database |
| Real Alembic CLI `check` | Passed, no metadata drift |
| Real Alembic CLI `downgrade base`, then `upgrade head` | Passed |
| Alembic offline SQL generation | Passed; includes tables and timestamp triggers |
| Seed CLI invoked twice | Passed; tests additionally assert 15/5/10/20 rows and preserved stock changes |
| Configured readiness/liveness over TestClient | Both returned HTTP 200 |
| Readiness after schema downgrade | HTTP 503; liveness remained HTTP 200 |
| Readiness with deliberately invalid test credentials | Sanitized HTTP 503 |
| Compose `config --quiet` | Passed with generated environment passwords |
| Linux CPython 3.12 runtime binary dependency resolution | Passed; includes manylinux 2.28 wheels |
| Docker Compose `up --build -d --wait` | Blocked by unavailable Docker Linux daemon |

Integration tests apply actual migrations into a distinct random schema for each test.
They cover migration rollback/re-upgrade, all seven models' relationships, database FK/unique/
CHECK constraints, enum values, Decimal precision, timestamp triggers, item deletion cascade,
restricted parent deletion, repeated seeds, transaction rollback, and the reusable request
session dependency's explicit-commit behavior. They do not mock PostgreSQL or replace it
with SQLite. Additional safety tests reject development/unsupported database targets.

## Reproduce

Install the project as described in README, start the optional isolated test PostgreSQL
service, set `CUSTOMEROPS_TEST_DATABASE_URL` in the process environment, then run:

```sh
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest --require-database
python -m pip check
```

Migrations/seeding use normal `CUSTOMEROPS_DATABASE_*` component settings; integration tests
use the separate test URL. Do not point the test URL at development or production data.

## Environment limitations

The `docker` command on PATH resolves to a zero-byte file. A working CLI exists at
`C:\Program Files\Docker\Docker\resources\bin\docker.exe` (29.3.1), and Compose exists at
`C:\Program Files\Docker\Docker\resources\cli-plugins\docker-compose.exe` (5.1.1).
Compose configuration validation succeeded using that executable. Docker Desktop was
launched, but its Linux daemon remained unavailable. The actual startup attempt failed with:

```text
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine
The system cannot find the file specified.
```

Therefore image build/pull, container startup, container health transitions, and live Redis
are not verified. Once Docker Desktop's Linux engine is running and the real CLI is on PATH,
rerun `docker compose config --quiet` and `docker compose up --build -d --wait` using local
passwords in `.env`, then seed with the README command. No Docker success is inferred from
native database tests or Compose parsing.

Python 3.12 execution and GitHub Actions have not run locally/remotely. Linux 3.12 dependency
resolution is not an execution test; the CI matrix is configured to execute both 3.12 and
3.14 against its own PostgreSQL. Container patch tags are pinned, while image digests and
the build backend's transitive dependencies are not fully locked. The core AI/chat layer is
verified in the agent-phase section above. WhatsApp, Redis-backed behavior, and UI
remain unimplemented. See the RAG phase verification below.
