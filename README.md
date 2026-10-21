# CustomerOps AI

A production-oriented Python backend portfolio project for a fictional e-commerce support
and sales agent. Implemented: FastAPI health/readiness, validated settings, async PostgreSQL,
seven relational models, Alembic migrations, deterministic fictional seeds, Docker Compose,
an authenticated, bounded tool-using OpenAI Responses agent, and persistent ChromaDB RAG.

`POST /api/v1/chat` supports product search/details/stock, owned order status, and support
tickets. Server-managed bearer tokens identify customers. Standalone business REST APIs,
login/OAuth, WhatsApp, and a web UI remain planned. Redis is provisioned only.
See [agent setup](docs/agent.md), [persistent memory and retention](docs/memory.md),
and [RAG setup, administrator APIs, and evaluation](docs/rag.md).

## Local stack with Docker

Requires Docker with Linux containers and Compose v2+. Run from the repository root.

1. Copy `.env.example` to `.env` without overwriting existing settings.
2. Set `CUSTOMEROPS_DATABASE_PASSWORD` and `CUSTOMEROPS_TEST_DATABASE_PASSWORD` to separate
   generated local passwords. Both are needed for Compose interpolation. If Python is
   available, generate each with `python -c "import secrets; print(secrets.token_hex(24))"`.
   Never commit `.env`; it is also excluded from Docker builds.
3. Start and seed:

```sh
docker compose config --quiet
docker compose up --build -d --wait
docker compose exec backend python -m customerops_ai.seed --confirm-fictional-data
```

Compose waits for PostgreSQL health, applies migrations with a one-shot `migrate` service,
then starts the backend after migrations succeed and Redis is healthy. Only the backend is
published, on **127.0.0.1:8000**. Development PostgreSQL and Redis have no host ports.

- [Liveness](http://127.0.0.1:8000/api/v1/health): HTTP 200 with `{"status":"ok"}`,
  independent of database availability.
- [Readiness](http://127.0.0.1:8000/api/v1/ready): HTTP 200 only with database connectivity
  and the expected Alembic revision; otherwise sanitized HTTP 503.
- [API documentation](http://127.0.0.1:8000/docs).

```sh
docker compose run --rm migrate       # apply pending migrations explicitly
docker compose logs backend migrate   # troubleshoot startup
docker compose down                   # keep development data volumes
```

Seeds are opt-in **fictional** Northstar Goods fixtures: 15 products (including an
out-of-stock item), 5 customers using reserved `.example` emails, 10 orders spanning seven
statuses, and 20 items. UUIDv5 IDs and fixed times make inserts deterministic. One transaction
and an advisory lock serialize runs; ID conflicts preserve existing rows and changed stock.
Unrelated uniqueness conflicts fail the transaction. Seeding refuses `production` settings.
Seeds do not implement stock reservations, payments, or order workflows.

PostgreSQL and Redis data persist in named volumes. PostgreSQL initializes passwords only on
first startup: changing `.env` does not rotate a password in an existing volume. This is a
local stack, not a hardened production deployment. Container patch tags and Python package
versions are pinned; image digests and OS/build-tool dependencies are not fully locked.

## Python development

Requires Python 3.12+ and pip 25.1+. `.python-version` selects 3.12. Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade "pip>=25.1"
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -e . --group dev
.\.venv\Scripts\python.exe -m uvicorn customerops_ai.main:app --reload --host 127.0.0.1 --port 8000
```

On Linux/macOS use `python3 -m venv .venv`, activate with `. .venv/bin/activate`, and replace
the Windows interpreter path with `python`. Commands below assume an activated environment;
on Windows without activation use `.\.venv\Scripts\python.exe` instead of `python`.

For native PostgreSQL, create a dedicated database/user, configure the component settings
below, then run:

```sh
python -m alembic upgrade head
python -m alembic check
python -m customerops_ai.seed --confirm-fictional-data
```

With no configured database password, the app still serves liveness and returns 503 for
readiness. A blank password in `.env` fails validation: set a local password or remove the
line to disable database access. Startup never creates tables or seeds data. The engine
pool belongs to app lifespan and is disposed on shutdown; connections are lazy.

## Configuration

Pydantic Settings reads `CUSTOMEROPS_` environment variables and optional `.env`. Constructor
values override environment values; environment overrides `.env`. SQLAlchemy URL construction
handles reserved characters in password components without manual escaping. Secret settings
and URL string representations redact passwords.

| Setting suffix | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` | `CustomerOps AI` | Nonempty OpenAPI title |
| `ENVIRONMENT` | `development` | `development`, `test`, or `production` |
| `DATABASE_HOST` | `localhost` | Compose overrides to `postgres` |
| `DATABASE_PORT` | `5432` | PostgreSQL port |
| `DATABASE_NAME` | `customerops` | Database identifier |
| `DATABASE_USER` | `customerops` | PostgreSQL role |
| `DATABASE_PASSWORD` | unset | Required for database access |
| `DATABASE_POOL_SIZE` | `5` | Persistent pool size |
| `DATABASE_MAX_OVERFLOW` | `5` | Additional temporary connections |
| `DATABASE_TIMEOUT` | `5` | Connect/query/pool wait timeout in seconds |

`CUSTOMEROPS_TEST_DATABASE_PASSWORD` configures only the Compose test PostgreSQL service.
`CUSTOMEROPS_TEST_DATABASE_URL` is a separate **process environment** variable used by tests;
it is deliberately not loaded automatically from `.env`. URLs require `postgresql+asyncpg`,
a database name ending in `_test`, and a name different from the development database.

## Tests and checks

```sh
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest
python -m pip check
```

Without a test URL, integration tests are explicitly skipped. Require real database tests:

```powershell
docker compose --profile test up -d --wait test-postgres
$testPassword = Read-Host "Local test password from .env"
$encodedPassword = [uri]::EscapeDataString($testPassword)
$env:CUSTOMEROPS_TEST_DATABASE_URL = "postgresql+asyncpg://customerops_test:${encodedPassword}@127.0.0.1:55432/customerops_test"
.\.venv\Scripts\python.exe -m pytest --require-database
docker compose --profile test stop test-postgres
```

On POSIX export the equivalent test URL and run `python -m pytest --require-database`.
The test service is a separate PostgreSQL instance on **127.0.0.1:55432**, with temporary
storage. Each test creates a random schema, applies real migrations, and drops only its own
schema. No development tables are truncated or dropped, and SQLite is not substituted.
`--require-database` fails for missing configuration; configured connection failures always
fail tests. A crashed test can leave `test_*` schemas; stopping the temporary service discards
its storage. No manual test migrations are needed.

Tests cover migration up/down/up, metadata drift, relationships, seed repeatability, database
constraints, decimal prices, raw SQL timestamp updates, delete policies, and rollback. CI
starts its own PostgreSQL with a generated password and requires integration tests on Python
3.12/3.14. Remote CI success is confirmed only by an actual GitHub run.

Agent tests cover conversation/tool sequencing, malformed arguments, identity injection,
owned-order lookup, provider/tool failures, timeouts, loop limits, ticket rollback, and concurrent
turn rejection. Run `python -m pytest -m "not live" --require-database` for the full offline suite
with the isolated test database. The paid smoke is opt-in; see [agent testing](docs/agent.md).

Optional Make targets: `install`, `dev`, `check`, `up`, `down`, `migrate`, `seed`, `test-db`,
and `test-integration`. The integration target requires the test URL environment variable.
Additional targets: `test-offline`, `test-rag`, `retention`, and the explicitly opt-in
`smoke-agent` / paid `evaluate-rag`.
Dependency groups `test`, `lint`, and `typing` remain separate from runtime dependencies;
`dev` includes all three. Install with `-c requirements.lock` to apply resolved constraints.
To refresh constraints, resolve a clean environment from `pyproject.toml`, review changed
pins, and rerun all checks on supported platforms/Python versions. Build tooling is only
range-constrained separately and is not fully locked.

## Structure

```text
src/customerops_ai/
  main.py                  App composition and lifespan
  api/v1/routes/           Health, chat, owned conversations and knowledge administration
  schemas/                 HTTP contracts
  core/config.py           Validated environment settings
  models/                  Seven entities, status enums, UUID/timestamp base
  infrastructure/          Async engine/session lifecycle and dependency
  seed.py                  Fictional deterministic inserts
  services/, repositories/ Authenticated customer operations and data access
  agents/                  Bounded orchestration, registry, validation, execution
  integrations/            OpenAI Responses provider adapter
  rag/                     Extraction, chunking, embeddings, Chroma storage and evaluation
alembic/                   Async migration environment and explicit revisions
tests/integration/         Isolated real PostgreSQL tests
compose.yaml               Backend, migrations, PostgreSQL, Redis, optional test database
Dockerfile                 Non-root backend image
docs/                      Architecture, roadmap, verification
```

Read [AGENTS.md](AGENTS.md), [architecture](docs/architecture.md),
[roadmap](docs/roadmap.md), [agent guide](docs/agent.md), and
[verification notes](docs/verification.md) before extending.
