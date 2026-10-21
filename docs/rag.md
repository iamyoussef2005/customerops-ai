# Document-grounded company knowledge

The implemented RAG subsystem extracts PDF, Markdown and UTF-8 text, embeds chunks through
OpenAI, and searches a local persistent Chroma index. The four documents in `data/knowledge/`
are explicitly fictional Northstar Goods policies. They are **not ingested automatically**.
Real embeddings and answer generation require your OpenAI key and incur API costs.

## Enable and upload

Install the constrained dependencies with:

```sh
python -m pip install -c requirements.lock -e . --group dev
```

Set `OPENAI_API_KEY`, `CUSTOMEROPS_RAG_ENABLED=true`, and a JSON array of administrator
bearer-token SHA-256 fingerprints in `CUSTOMEROPS_AUTH_ADMIN_TOKEN_HASHES`. Customer tokens
remain separate in `CUSTOMEROPS_AUTH_TOKEN_CUSTOMERS`; customer authentication alone grants
no ingestion privileges. Generate a high-entropy admin token locally, keep the raw token
private, and hash it with SHA-256. Token provisioning/revocation is operator-managed; there
is no login endpoint. Never put raw tokens or a real API key in Git.

Start the development server from the repository root:

```sh
python -m uvicorn customerops_ai.main:app --reload --host 127.0.0.1 --port 8000
```

For Docker, use `docker compose up --build -d --wait` after setting the passwords described
in README. The backend mounts the `knowledge-data` named volume at `/app/.local/rag` and
runs as a non-root user. No separate Chroma server or network port is exposed. Configuration
for embeddings, chunking, retrieval and upload bounds is forwarded by Compose.

PowerShell upload example (set `$env:CUSTOMEROPS_ADMIN_TOKEN` privately first):

```powershell
curl.exe --fail-with-body -X POST http://127.0.0.1:8000/api/v1/admin/documents `
  -H "Authorization: Bearer $env:CUSTOMEROPS_ADMIN_TOKEN" `
  -F "file=@data/knowledge/return-policy.md;type=text/markdown" `
  -F "source_key=return-policy.md" -F "title=Fictional return policy" -F "category=policies"
```

Repeat for `shipping-policy.md`, `warranty-faq.md`, and `store-information.md`, preserving
their filenames as source keys for evaluation. A Bash shell uses `curl` and backslash line
continuations. The admin APIs work without PostgreSQL or an agent model; `/chat` still
requires its existing database, customer token, and Responses model configuration.

| Endpoint | Behavior |
| --- | --- |
| `POST /api/v1/admin/documents` | Multipart upload: `file`, optional `source_key`, `title`, `category`, `custom` JSON object |
| `GET /api/v1/admin/documents` | Active document metadata, versions, model and dimensions |
| `PUT /api/v1/admin/documents/{document_id}` | Replace content/metadata using multipart; preserve source key |
| `POST /api/v1/admin/documents/{document_id}/reindex` | Re-extract retained raw bytes and force a fresh index with current settings |
| `DELETE /api/v1/admin/documents/{document_id}` | Remove active manifest entry, retained raw bytes, and its vector collection |
| `POST /api/v1/admin/documents/search` | JSON `{ "query": "return window", "top_k": 4, "filters": { "category": "policies" } }` |

All endpoints require an administrator bearer token. Filters support `document_id`,
`source_key`, and `category`; omitted filters search all approved documents. `custom` accepts
up to 10 bounded string values and is preserved on the document record. PDF metadata is
also retained. Listing returns the complete local corpus; it is intended for a small
administrator-managed knowledge base.

## Processing and persistence

- Filenames are display metadata only, restricted to plain names with `.pdf`, `.md`, or
  `.txt`. Paths, unsupported types, invalid UTF-8, encrypted PDFs, and empty text are rejected.
  Image-only PDFs report that OCR is unavailable. No remote URLs, links, scripts, attachments,
  or document instructions are executed.
- Authentication precedes multipart parsing. The entire body is bounded to the configured
  file limit plus 16 KiB multipart overhead, with one file and four optional fields. Defaults:
  5 MiB upload, 100 PDF pages, 200,000 extracted characters and 500 chunks. PDF decompression
  is handled in-process; hostile decompression bombs are not sandboxed. Restrict deployment
  to trusted administrators and apply infrastructure resource limits.
- NFKC normalization standardizes line endings/whitespace. Character windows default to
  1,000 characters with 150 overlap, never crossing PDF pages. Page and character offsets
  refer to normalized page text, not original PDF byte locations. This deterministic approach
  does not parse Markdown heading hierarchy or perform OCR.
- UUID5 IDs derive from the stable source key. SHA-256 of normalized content detects copies
  even with different filenames. Same-source changes create a new generation. New-source
  duplicates return the canonical existing record without another embedding request. Replacing
  an existing document with another document's content returns a conflict and preserves both.
- Fingerprints include content, metadata, filename, chunking settings, model, dimensions and
  pipeline version. Citation IDs derive from document ID, fingerprint and chunk index.
- Embedding requests use `AsyncOpenAI.embeddings.create`, explicit model/dimensions, batches
  of 16 by default, timeouts and no automatic retries. Vector counts, indices, dimensions,
  finite values and nonzero vectors are validated. Character and batch bounds conservatively
  stay below embedding token limits even for multi-byte UTF-8 text. Nonstandard configured
  embedding models must support the `dimensions` parameter.
- Raw source bytes and the active-version manifest live in local SQLite beside Chroma, under
  `.local/rag` by default. No uploaded filename becomes a path. Source bytes are private
  operator data retained only to permit re-indexing, never exposed as filesystem references.
- Chroma collections are immutable document generations with explicit embeddings and cosine
  distance. A file lock serializes local readers/publication/deletion. SQLite atomically
  selects the active generation only after every chunk has been stored. Compare-and-swap
  prevents an in-flight update from resurrecting a deleted/replaced document.
- Embedding/publication failure leaves the previous generation available. Readers never search
  retired generations, even if physical cleanup fails. Normal updates/deletes retire the old
  collection; leftover collections from interrupted writes are cleaned on the next startup.
  Deletion is logical removal, not forensic erasure from filesystem snapshots/backups.
- Blocking extraction, SQLite, filesystem and Chroma calls run through `asyncio.to_thread`.
  Chroma clients and OpenAI clients are closed at application shutdown. Cancellation cannot
  forcibly terminate an already running extraction or atomic publication thread; retry/list
  after a disconnected upload to determine its outcome.

This embedded Chroma deployment supports **one backend worker per persistence directory**.
Run the evaluation CLI with the backend stopped; it opens that same embedded directory.
Multi-process/server deployment, backup/restore tooling and tenant-private knowledge are not
implemented. All approved documents are company-wide customer-visible knowledge. Keep customer
PII, credentials and internal-only procedures out of this corpus. `.local`, common upload/index
directories and SQLite files are Git-ignored; custom storage paths must also be ignored and
excluded from Docker build contexts. Back up the entire persistence directory consistently.

## Agent behavior and source contract

`search_knowledge_base(query)` goes through `KnowledgeService`, not direct model storage access.
With RAG enabled the server pre-retrieves on each turn using the last 500 characters of recent
customer messages. This adds one bounded tool trace. The model may perform more knowledge
searches through the normal bounded tool loop. User text, document text, metadata, and tool
outputs are always untrusted data; documents cannot authorize refunds or database operations.
Ticket execution additionally requires ticket/escalation/human-assistance keywords in the current customer
message; retrieved documents alone cannot satisfy that server-side authorization check.
Prices, stock and order status must still use the existing business tools.

Search returns text, cosine distance and a source object containing document/source IDs,
title, filename, page, chunk number, offsets, and `citation_id`. The assistant cites policy
claims using `[KB:<chunk-id>]`. `ChatResponse.sources` contains only matching references actually
retrieved in that turn. Server checks reject absent/invented citations on recognized policy
questions or explicitly requested knowledge searches, returning an honest unknown-policy
fallback. The policy recognizer uses English keywords; system instructions also require
retrieval for all company-policy answers. This is a citation provenance guard, **not a proof
of semantic entailment**. Prompt injection resistance and unsupported-claim detection are not
guaranteed by citation existence. Review live answers and adversarial prompts before exposure.

Top-k defaults to 4 (maximum 8). Results above cosine distance 0.35 are excluded. A distance
cutoff is a heuristic, not calibrated confidence or a guarantee that evidence answers a question.
Knowledge tool results are bounded to 32,000 characters; other business tool results retain
their 16,000-character bound. The existing total turn, iteration and tool-call budgets apply.
The prompt requires an explicit unknown when evidence is irrelevant, contradictory or missing.
Embedding model/dimension mismatches fail closed with `reindex_required`; re-index affected
documents after changing embedding settings. RAG-disabled or unconfigured applications retain
existing product/order/ticket functionality and acknowledge unknown policies.

## Offline verification and real-key evaluation

```sh
python -m pytest tests/test_rag.py -q
python -m pytest -m "not live" --require-database
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pip check
```

The full suite's database URL must name an isolated test database as described in README.
RAG tests use **real temporary persistent Chroma with deterministic fake embeddings**, plus
the real OpenAI SDK over a mock HTTP transport. These verify behavior, not real embedding
quality. No paid API call or answer-quality metric is implied by offline success.

The 24-question `data/rag-evaluation.jsonl` dataset contains five answerable questions per
sample document and four intentionally unknown questions. Each row has an ID, question and
expected source filenames. To measure retrieval with a real key, upload all four sample files,
stop the backend, retain the same environment/storage settings, then explicitly opt in:

```sh
python -m customerops_ai.rag.evaluate --allow-paid-requests
```

`make evaluate-rag` runs that same paid command. The CLI uses real query embeddings against the
existing index and writes `.local/rag-evaluation.json`. It reports source-document hit@k and
mean reciprocal document rank for answerable questions, and the empty-retrieval rate for unknown
questions. Document ranks deduplicate chunk hits in retrieval order. Reports include each
question's actual sources, model, dimensions, cutoff, chunking and document fingerprints.
Provider failures abort the run rather than being counted as correct abstentions. Freeze corpus
changes during evaluation. There is no automatic comparison to an asserted target score.

For answer evaluation, restart the backend and submit these questions to `/api/v1/chat` with
a customer bearer token. Inspect each policy claim against its cited excerpt and separately
record correctness, coverage, citation support, unknown responses and injected-document behavior.
The CLI measures retrieval only; it does not grade answer faithfulness, guarantee hallucination
prevention, or measure customer outcomes. No live RAG metrics have been measured in this phase.
