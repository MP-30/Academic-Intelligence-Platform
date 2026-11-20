# Academic Intelligence Platform

[![CI](https://github.com/MP-30/Academic-Intelligence-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/MP-30/Academic-Intelligence-Platform/actions/workflows/ci.yml)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/)

RAG application that answers questions over academic PDFs with page citations. A Strands agent uses MCP tools over streamable HTTP to search private documents and the web. Rolling summaries bound conversation history, and a RAGAS suite evaluates answer quality.

**Deployment status.** The AWS deployment was retired on November 20, 2026. The hosted UI and API are offline. Use the [local quickstart](#quickstart-local-development) to try the application, or follow the [infrastructure setup](https://github.com/MP-30/academic-intelligence-platform-terraform#configure-terraform) to create a fresh deployment.

**Recorded baseline (November 11, 2026).** Faithfulness 0.90 · context precision 0.98 · citation page overlap 0.75 · answer relevancy 0.84. The [checked-in reference](./tests/evals/baseline.reference.json) records nine scored questions from that run.

---

## What It Does

1. **Upload a PDF** (syllabus, lecture notes, paper) — stored in S3, ingestion queued in SQS
2. **Worker processes it** — page-aware chunking → Bedrock Titan v2 embeddings → stored in pgvector
3. **Ask a question** — hybrid search (vector similarity + full-text) fused via Reciprocal Rank Fusion
4. **Get a cited answer** — the LLM synthesizes a response citing exact page numbers (`[Doc p.3]`)
5. **Agent decides what to search** — routes between your documents and the live web (Tavily) based on the question
6. **Multi-turn conversations stay bounded** — after more than 5 turns, older messages are summarized while recent messages are retained
7. **Tools exposed via MCP** — compatible clients can connect over streamable HTTP when configured with the required user-context headers and network access
8. **Evaluate answers** — run RAGAS against a running API and compare scores with the recorded baseline

The assistant is instructed to cite PDF pages and web sources. Citation grounding currently depends on model behavior.

Once the local app is running, upload [the sample curriculum PDF](./tests/fixtures/Curriculum_SrSec_2025-26.pdf) in **Upload & Ingest** and use **Check Status** until it shows **READY**. In **Chat**, ask “What elective areas are offered?” Page 3 is the expected citation. Use **Search** to inspect the retrieved passages.

---

## Architecture

The original AWS deployment ran on ECS Fargate with separate UI, API, and worker tasks. An ALB routed HTTPS traffic by hostname, and a scheduled GitHub Actions workflow ran evals against the deployed API.

```mermaid
flowchart TB
    User((User))
    Internet["Internet"]
    ALB["Application Load Balancer<br/>HTTPS · ACM · 180s idle"]

    User --> Internet --> ALB

    subgraph AWS["AWS Cloud"]
        direction TB

        subgraph Ingress["Ingress · Host-Based Routing"]
            direction LR
            UI_Route["ai.adityalive.tech"]
            API_Route["api.adityalive.tech"]
        end

        subgraph ECS["Amazon ECS · Fargate"]
            direction LR

            subgraph UI["UI Task"]
                Gradio["Gradio<br/>:7860"]
            end

            subgraph API["API Task"]
                FastAPI["FastAPI<br/>:8000"]
                Agent["Strands Agent"]
                Client["MCP Client"]
                Compactor["BackgroundTask<br/>Rolling Summary"]

                FastAPI --> Agent --> Client
                FastAPI -.->|"fires at turn 6"| Compactor

                subgraph Sidecars["MCP Sidecars"]
                    direction TB
                    DocMCP["Document MCP<br/>:8001"]
                    WebMCP["Web MCP<br/>:8002"]
                end

                Client --> DocMCP
                Client --> WebMCP
            end

            subgraph Worker["Worker Task"]
                Consumer["SQS Consumer"]
                Embed["Document Parsing<br/>& Embedding"]
                Consumer --> Embed
            end
        end

        subgraph AWSServices["AWS Managed Services"]
            direction LR
            Cognito["Cognito<br/>JWT Auth"]
            S3[("S3<br/>PDF Storage")]
            SQS[("SQS<br/>Ingestion Queue")]
            Bedrock["Bedrock<br/>LLM + Embeddings"]
            RDS[("RDS PostgreSQL 18<br/>pgvector + Full Text Search")]
        end
    end

    subgraph Evals["Nightly Evals · GitHub Actions"]
        Runner["runner.py<br/>10 Q → /agent"]
        Scorer["ragas_scorer.py<br/>RAGAS + Bedrock judge"]
        Compare["compare.py<br/>vs frozen reference"]
        Runner --> Scorer --> Compare
    end

    Evals -.->|"hits prod /agent"| ALB

    ALB --> UI_Route --> Gradio
    ALB --> API_Route --> FastAPI
    Gradio -->|"HTTPS API requests"| ALB

    FastAPI -.-> Cognito

    FastAPI -->|"Store PDF"| S3
    FastAPI -->|"Publish ingestion job"| SQS
    SQS --> Consumer
    Embed -->|"Generate embeddings"| Bedrock
    Embed -->|"Store chunks + vectors"| RDS

    FastAPI -->|"Documents and conversations"| RDS
    DocMCP -->|"Query embedding"| Bedrock
    DocMCP -->|"Hybrid Retrieval"| RDS
    Agent -->|"LLM Inference"| Bedrock
    Compactor -->|"Summarize"| Bedrock
    Compactor -->|"Persist summary"| RDS
    WebMCP -->|"Web Search"| Tavily["Tavily API"]

    classDef ingress fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef app fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef mcp fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef aws fill:#f3e8ff,stroke:#9333ea,color:#581c87
    classDef eval fill:#fce7f3,stroke:#db2777,color:#831843

    class ALB,UI_Route,API_Route ingress
    class Gradio,FastAPI,Agent,Client,Consumer,Embed,Compactor app
    class DocMCP,WebMCP mcp
    class Cognito,S3,SQS,Bedrock,RDS aws
    class Runner,Scorer,Compare eval
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Language** | Python 3.14 |
| **API** | FastAPI · Pydantic v2 |
| **Database** | PostgreSQL 18 + pgvector + tsvector |
| **ORM** | SQLAlchemy 2.x (asyncpg locally; psycopg for ECS and the worker) |
| **Migrations** | Alembic |
| **Embeddings** | Amazon Bedrock Titan v2 (1024-dim, normalized) |
| **LLM** | Amazon Bedrock Mistral Large 3 |
| **Agent SDK** | AWS Strands |
| **Tools protocol** | MCP SDK v2 (`mcp.server.MCPServer`) |
| **Web search** | Tavily API |
| **Auth** | AWS Cognito (JWT via JWKS) |
| **UI** | Gradio |
| **Async queue** | Amazon SQS (+ DLQ, maxReceiveCount=5) |
| **Evals** | RAGAS · LLM-as-judge via Bedrock |
| **Container** | Docker (Python 3.14-slim · uv · psycopg) |
| **Orchestration** | ECS Fargate (3 tasks) |
| **Infra** | Terraform (see [infra repo](https://github.com/MP-30/academic-intelligence-platform-terraform)) |
| **CI/CD** | GitHub Actions · OIDC (zero stored AWS keys) |

---

## Quickstart (Local Development)

### Prerequisites

- Python 3.14+, [uv](https://docs.astral.sh/uv/), Docker Compose, AWS CLI, and `jq`
- LocalStack available at `http://localhost:4566`; the Makefile uses the `lstk` CLI
- An AWS profile with access to Titan v2 embeddings and the configured Mistral model in `us-east-1`
- A Cognito user pool and app client supporting `USER_PASSWORD_AUTH`, plus a user with a permanent password
- A Tavily API key for web search

Local development uses PostgreSQL and LocalStack on your machine, with real AWS Cognito, Bedrock, and Tavily calls. Those external services require credentials and can incur charges.

### Setup

```bash
git clone https://github.com/MP-30/Academic-Intelligence-Platform.git
cd Academic-Intelligence-Platform
uv sync --frozen
```

Create `.env` from the following template and replace the credential placeholders. The checked-in `.env.example` is currently empty. The database password below is an example for local development. Keep your real `.env` private. Run the shell examples with Bash. The default dev servers and Compose database ports are reachable on network interfaces, so use a trusted development machine and network.

```dotenv
POSTGRES_USER=academic
POSTGRES_PASSWORD=localdevpassword
POSTGRES_DB=academic_db
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://academic:localdevpassword@localhost:5432/academic_db
AWS_REGION=us-east-1
AWS_PROFILE=your-bedrock-profile
S3_ENDPOINT_URL=http://localhost:4566
SQS_ENDPOINT_URL=http://localhost:4566
S3_BUCKET=academic-docs-local
SQS_QUEUE_NAME=ingestion-jobs
COGNITO_REGION=us-east-1
COGNITO_USER_POOL_ID=your-user-pool-id
COGNITO_CLIENT_ID=your-app-client-id
TAVILY_API_KEY=your-tavily-key
API_BASE_URL=http://localhost:8000
USE_MCP_TOOLS=true
DOC_MCP_URL=http://localhost:8001/mcp
WEB_MCP_URL=http://localhost:8002/mcp
```

Start PostgreSQL and LocalStack, then create the bucket and both queues. The `test` credentials in this block apply only to the LocalStack CLI calls.

```bash
docker compose up -d --wait
lstk start --persist

(
  export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
  unset AWS_PROFILE AWS_SESSION_TOKEN
  aws --endpoint-url=http://localhost:4566 s3 mb s3://academic-docs-local
  DLQ_URL=$(aws --endpoint-url=http://localhost:4566 sqs create-queue \
    --queue-name ingestion-jobs-dlq --query QueueUrl --output text)
  DLQ_ARN=$(aws --endpoint-url=http://localhost:4566 sqs get-queue-attributes \
    --queue-url "$DLQ_URL" --attribute-names QueueArn --query Attributes.QueueArn --output text)
  QUEUE_ATTRIBUTES=$(jq -nc --arg arn "$DLQ_ARN" '{
    VisibilityTimeout: "300",
    ReceiveMessageWaitTimeSeconds: "20",
    RedrivePolicy: ({deadLetterTargetArn: $arn, maxReceiveCount: "5"} | tojson)
  }')
  aws --endpoint-url=http://localhost:4566 sqs create-queue \
    --queue-name ingestion-jobs --attributes "$QUEUE_ATTRIBUTES"
)

uv run alembic upgrade head
make dev
```

Open <http://localhost:7860> and log in with your Cognito user. To create a user, call `POST /auth/register` using the interactive API docs at <http://localhost:8000/docs>. Registration requires AWS credentials with Cognito admin permissions. The UI currently provides login only.

`make dev` starts the API, worker, UI, and enabled MCP servers whose URLs point to localhost. Stop them with Ctrl+C. `docker compose down` stops PostgreSQL and `lstk stop` stops LocalStack.

### Local testing with AWS storage

For a separate configuration, copy your local `.env` to `.env.aws`, set `S3_ENDPOINT_URL` and `SQS_ENDPOINT_URL` to empty strings, and use a dedicated development bucket and queue. Give each database its own ingestion queue so workers write to the intended database. Clear or update `SQS_QUEUE_URL` if it was set. Keep `DATABASE_URL` pointed at a database reachable from your machine.

```bash
make dev ENV_FILE=.env.aws
```

The API and worker must use the same database, bucket, and queue. Run a local worker when ingestion writes to your local database.

### Running evals locally

The eval suite calls `/agent` on a running API and scores the responses with RAGAS. It requires Bedrock access for the judge model and embeddings. Upload the curriculum fixture using your eval account, copy `tests/evals/dataset.yaml` to a local file, and update its workspace IDs to the workspace that owns the fixture. The default upload workspace is your authenticated user ID.

```bash
export EVAL_API_BASE=http://localhost:8000
export EVAL_DATASET_PATH=/path/to/your/local-eval-dataset.yaml
export EVAL_USER_EMAIL=your-eval-user@example.com
read -rsp "Eval user password: " EVAL_USER_PASSWORD
printf '\n'
export EVAL_USER_PASSWORD
make evals
```

Configure AWS credentials for the Bedrock judge, using `EVAL_JUDGE_PROFILE` for a named profile. `make evals` writes `tests/evals/baseline.json` and compares it with the committed reference. Keep the question IDs unchanged so the comparison can find the expected per-question scores.

---

## Endpoints

The `/documents`, `/search`, `/ask`, and `/agent` routes require an `Authorization: Bearer <jwt>` header. `/health`, `/auth/*`, and the default FastAPI documentation routes are public.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness probe (ALB health check) |
| `POST` | `/auth/register` | Create Cognito user |
| `POST` | `/auth/login` | Authenticate → returns `{id_token, access_token, refresh_token}` |
| `POST` | `/documents` | Upload PDF + enqueue ingestion job (no `workspace_id` required — defaults to `user_id`) |
| `GET` | `/documents/{doc_id}` | Return document status, job status, page count, and last job error |
| `POST` | `/search` | Hybrid RRF search — returns raw chunks with page citations |
| `POST` | `/ask` | LLM answer over retrieved chunks (no tool routing) |
| `POST` | `/agent` | Strands agent — routes between doc search and web search via MCP tools; supports multi-turn via `conversation_id`; returns `contexts` + `citations` |

### Example: `/agent` call

```bash
# Log in using /docs or your API client, then paste the returned id_token.
API_BASE=http://localhost:8000
read -rsp "Cognito ID token: " TOKEN; echo

# Send the token through curl's stdin config, avoiding shell history and argv.
printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" | \
  curl --fail-with-body --silent --show-error --config - \
    -X POST "$API_BASE/agent" \
    -H 'Content-Type: application/json' \
    -d '{"message": "What elective areas are offered?"}' | jq
unset TOKEN
```

**Illustrative response**

```json
{
  "conversation_id": "d8e5d422-07e8-4b8c-916d-2f12eb76ee9e",
  "response": "The elective areas are:\n- **Languages** (Hindi, English, other languages) [Doc p.3]\n- **Sciences** (Biology, Chemistry, Physics) [Doc p.3]...",
  "tool_calls": [
    {"tool": "search_course_documents", "args": {"query": "elective areas"}}
  ],
  "citations": [
    {"source": "document", "page_number": 3, "document_id": null, "url": null, "title": null}
  ],
  "contexts": [
    " understanding about core business disciplines... Visual; Performing and Creative Arts...",
    " Skill Electives help in development of professional competencies..."
  ]
}
```

**Multi-turn:** pass the `conversation_id` from the previous response to continue the same session. After more than 5 turns, older messages are eligible to be compacted into a rolling summary (see [Memory Compaction](#memory-compaction)).

**`contexts`** contains the actual retrieved chunk text — useful for transparency (UI displays them in a collapsible inspector) and required for eval scoring (`faithfulness`, `context_precision`).

---

## How It Works

### Ingestion Pipeline

```text
PDF upload → S3 → SQS job → Worker (ECS Fargate)
                                │
                                ├─ Download PDF from S3
                                ├─ Parse page-by-page (pypdf)
                                ├─ Chunk: 600 tokens / 100 overlap (tiktoken)
                                ├─ Embed each chunk (Bedrock Titan v2, 1024-dim, normalized)
                                ├─ Bulk insert into document_chunks
                                └─ Update documents.processing_status = 'READY'
```

Chunk insertion deduplicates by `(document_id, chunk_index)` using `ON CONFLICT DO NOTHING`. Completed jobs are acknowledged without reprocessing. Redrive is configured with `maxReceiveCount=5`. Concurrent deliveries can still repeat embedding work; the database commit and queue publication are separate operations.

### Hybrid Retrieval (RRF)

Two retrievers run **in a single SQL query**:

1. **Semantic** — `embedding <=> query_embedding` (cosine distance via pgvector HNSW index)
2. **Keyword** — `search_vector @@ plainto_tsquery('english', query)` (tsvector GIN index)

Results are fused via **Reciprocal Rank Fusion**:

```sql
COALESCE(1.0 / (60 + semantic_rank), 0.0) + COALESCE(1.0 / (60 + keyword_rank), 0.0)
```

The `FULL OUTER JOIN` keeps chunks found by **either** retriever, so a chunk found only by keyword (an exact match like "CS-401") still survives. The constant 60 dampens the impact of rank differences — the standard RRF formulation (Cormack et al., 2009).

### Agent + MCP

`/agent` runs a **Strands orchestrator** (Mistral Large 3) with two tools:

- `search_course_documents(query)` — MCP tool on the `doc-mcp` sidecar (`:8001`)
- `search_web(query)` — MCP tool on the `web-mcp` sidecar (`:8002`)

The prompt asks the LLM to choose tools as follows. Actual tool calls depend on the model response.

| Question type | Tool selected |
|---|---|
| "What's in my syllabus?" | `search_course_documents` |
| "Latest RAG research?" | `search_web` |
| "Compare my syllabus to industry" | **both** |

**Multi-turn memory** persists user + assistant turns in the `messages` table and a rolling summary in `conversations.rolling_summary`.

**Security:** The API derives the user ID from the verified JWT and passes it through an `X-User-Id` MCP header. The tool schema does not ask the model to supply a user ID. Retrieval SQL scopes queries to that user. Document MCP trusts these headers and is intended for the private API-sidecar connection. Tenant isolation is tested in CI (attacker user + real workspace → 0 rows).

### Memory Compaction

Long conversations without compaction blow up the LLM context window and cause request timeouts. This project uses **rolling summary compaction**:

```text
Turn 5  ──────────►  [10 messages unsummarized]  no compaction (below trigger)
Turn 6  ──────────►  [12 messages]  →  compact 4 into summary, keep 8 verbatim
Turn 7  ──────────►  [10 unsummarized]  no-op
Turn 8  ──────────►  [12 unsummarized]  →  compact 4 more into rolling summary
Turn 9  ──────────►  [10 unsummarized]  no-op
...
After compaction: rolling summary + 8 recent messages
```

**Key properties**

- **Background task** — compaction is scheduled after the response through FastAPI `BackgroundTasks`. Its synchronous Bedrock call can still block the API event loop and delay other requests
- **History retention** — `messages.summarized = TRUE` preserves history for analytics; context loading filters on this flag
- **Rolling summary** — each compaction merges new turns into the existing summary (prompt: *"merge new turns into previous summary, don't repeat"*). Successful compaction keeps the recent-message tail bounded; failed summarization leaves history available for a later retry
- **Configurable trigger** — `summary_trigger_turns = 5`, `recent_messages_keep = 8` (messages, not turns). The trigger counts stored messages; it does not enforce a request time limit

Trade-off: compaction loses some verbatim detail from older turns. The nightly dataset uses independent questions. Multi-turn compaction is checked by the manual smoke test described in [Testing](#testing).

### Evals

The eval suite historically ran nightly against the hosted API. `make evals` runs the same runner, scorer, and comparison against a configured endpoint. Deployment and evaluation use independent workflows. The suite records four metrics.

| Metric | What it measures | Judge |
|---|---|---|
| **faithfulness** | Do the answer's claims appear in the retrieved chunks? (hallucination) | RAGAS LLM |
| **answer_relevancy** | Does the answer actually address the question? (verbosity) | RAGAS embeddings |
| **context_precision** | Are the retrieved chunks relevant to the ground truth? (retrieval quality) | RAGAS LLM |
| **citation_accuracy** | Does at least one cited page overlap `expected_pages`? (custom) | Deterministic |

**How it works:**

```text
tests/evals/dataset.yaml     ← 10 questions (doc/mixed/web/refusal)
              │
              ▼
tests/evals/runner.py        ← POST /agent, capture response + contexts
              │
              ▼
tests/evals/ragas_scorer.py  ← RAGAS evaluate() with Bedrock judge
              │
              ▼
tests/evals/baseline.json    ← latest run (gitignored)
              │
              ▼
tests/evals/compare.py       ← vs baseline.reference.json, exit 1 if metric drops >0.05
```

The comparison fails when a tracked score drops by more than 0.05. Repeated runs help measure judge variance.

**Current scoring limits**

- Rows with no retrieved contexts are excluded before RAGAS scoring.
- Each judged metric needs at least 80% non-NaN results among the retained rows.
- The comparison allows a count difference of two and skips missing metrics.
- Citation accuracy measures page overlap and does not verify document identity or complete citation coverage.
- The comparison checks context precision on the document and mixed questions. Web-only context precision is reported for reference.

**The eval found a real bug at v0.7 ship:** the initial `faithfulness = 1.0` was a fake metric. `/agent` wasn't returning retrieved chunk text, so RAGAS fell back to comparing the answer against itself. Fixing it required adding a `contexts` field to `AgentResponse` — an API change, not an eval change. Returning the retrieved contexts made the faithfulness score meaningful.

---

## Testing

Use a migrated development or test database. The tenant-isolation fixture commits seed rows and deletes them during cleanup. Check `DATABASE_URL` before running database tests.

```bash
# Full test suite
uv run pytest tests/ -v

# Just tenant isolation (the critical test)
uv run pytest tests/test_tenant_isolation.py -v
```

**What's covered:**

- **`test_parser.py`** — page-aware chunking on a fixture PDF (multi-page, contiguous `chunk_index`)
- **`test_tenant_isolation.py`** — three assertions:
  1. Attacker user + real workspace → **0 chunks**
  2. Real user + wrong workspace → **0 chunks**
  3. Real user + real workspace → **>0 chunks** (control — proves isolation isn't blocking everything)

**Manual verification of compaction:** `tests/manual/test_compaction.py` inserts 12 turns, mocks Bedrock, asserts history trims to summary + 8 messages. Run with `uv run python -m tests.manual.test_compaction`.

**Evals:** see [Evals](#evals) above. Run with `make evals`.

CI runs the automated suite, import smoke tests, and a Docker build on pushes and pull requests targeting `main` (see `.github/workflows/ci.yml`). The RAGAS workflow is configured separately and needs a running API and AWS credentials.

---

## Deployment

For a fresh deployment, follow the [Terraform setup](https://github.com/MP-30/academic-intelligence-platform-terraform#configure-terraform) and update the AWS account, ECR repository, cluster and service names, and API hostname in [the deploy workflow](./.github/workflows/deploy.yml). Configure a new GitHub OIDC deploy role and set `AWS_DEPLOY_ROLE_ARN`. For hosted evals, also set the new API endpoint in [the eval workflow](./.github/workflows/evals.yml) and configure the eval account and its dataset workspace.

### Manual deploy (`deploy.yml`)

1. Open <https://github.com/MP-30/Academic-Intelligence-Platform/actions/workflows/deploy.yml>
2. Click **Run workflow**
3. Select service: `all` / `api` / `worker` / `ui`
4. Click **Run workflow**

**What it does:**

1. Assumes the role configured by `AWS_DEPLOY_ROLE_ARN` via **OIDC** (short-lived AWS credentials)
2. Builds the Docker image (`linux/amd64`, matching ECS)
3. Pushes to ECR as `:latest`
4. Triggers `aws ecs update-service --force-new-deployment`
5. Waits for `aws ecs wait services-stable`
6. Polls `/health` on the configured API hostname until it returns `200` (retries 10×)

**Recovery:** rebuild the intended earlier revision and redeploy it. The current workflow publishes `:latest` and has no explicit commit-SHA input or automated rollback step. Its health check verifies API liveness; verify login, ingestion, and document search separately after a release.

### Scheduled and manual evals (`evals.yml`)

The workflow YAML still defines a nightly schedule. Its original AWS role and API endpoint were retired with the stack. With a fresh deployment and credentials configured, the workflow follows these steps.

1. Triggers at **03:00 UTC daily** or on demand
2. Calls the configured `/agent` endpoint with 10 test questions
3. Scores with RAGAS (Bedrock judge)
4. Compares against `baseline.reference.json`
5. Exits 1 on regression >0.05 → **eval workflow fails on quality regression**

On failure, the workflow dumps AWS identity, env vars (masked), and available Bedrock models — so the next red run is self-diagnosing instead of a guessing game.

### Infrastructure

AWS resource configuration and operator-managed prerequisites are documented in the Terraform repo: [academic-intelligence-platform-terraform](https://github.com/MP-30/academic-intelligence-platform-terraform)

See [Cost](#cost) for the scope and limitations of the historical deployment estimate.

---

## Project Structure

```text
.
├── src/academic_ai/
│   ├── api/              FastAPI routers
│   │   ├── auth.py       /auth/register, /auth/login
│   │   ├── documents.py  /documents upload + status
│   │   ├── search.py     /search hybrid RRF
│   │   ├── ask.py        /ask LLM synthesis
│   │   ├── agent.py      /agent Strands + MCP + compaction background task
│   │   └── schemas.py    Pydantic request/response (contexts field)
│   │
│   ├── auth/             Cognito client + JWT verification
│   │   ├── cognito_client.py
│   │   └── dependencies.py  (JWKS verify)
│   │
│   ├── agents/           Strands orchestrator
│   │   ├── orchestrator.py  Agent factory + system prompt
│   │   ├── mcp_client.py    MCPClient factory per request
│   │   ├── context_manager.py  load_history + save_turn + compact_if_needed
│   │   ├── prompts/
│   │   │   └── summary.md   Rolling summary prompt
│   │   └── tools/        (v0.4 in-process fallback path)
│   │
│   ├── mcp_servers/      Sidecar containers
│   │   ├── doc_server.py    search_course_documents (:8001)
│   │   └── web_server.py    search_web (:8002)
│   │
│   ├── ingestion/        Ingestion pipeline
│   │   ├── parser.py        page-aware chunking
│   │   ├── embeddings.py    Bedrock Titan v2
│   │   ├── s3_service.py    upload/download
│   │   ├── queue.py         SQS client + helpers
│   │   ├── producer.py      enqueue_ingestion_job
│   │   ├── worker.py        polling loop + handle_message
│   │   └── __main__.py      worker entrypoint
│   │
│   ├── retrieval/        Retrieval + synthesis
│   │   ├── hybrid_search.py  RRF SQL
│   │   └── ask.py            LLM synthesis
│   │
│   ├── db/               SQLAlchemy
│   │   ├── models.py     Document, DocumentChunk, Conversation, Message, IngestionJob
│   │   └── session.py    async engine + get_db
│   │
│   ├── ui/               Gradio app (uses /agent, multi-turn)
│   │   └── app.py
│   │
│   ├── config.py         Pydantic settings (compaction trigger, eval judge)
│   └── main.py           FastAPI app + routers
│
├── alembic/              Migrations
├── docs/adr/             Architecture decision record
├── tests/
│   ├── evals/            RAGAS eval suite
│   │   ├── dataset.yaml          10 questions
│   │   ├── runner.py             POST /agent, capture responses
│   │   ├── ragas_scorer.py       RAGAS evaluate() with guards
│   │   ├── compare.py            vs frozen reference
│   │   ├── baseline.json         latest run (gitignored)
│   │   └── baseline.reference.json   frozen baseline
│   ├── manual/
│   │   └── test_compaction.py    Mocked-Bedrock compaction test
│   ├── test_parser.py
│   ├── test_tenant_isolation.py
│   └── conftest.py
│
├── scripts/
│   └── ecs_entrypoint.sh  5-mode dispatch (worker/api/ui/mcp-doc/mcp-web)
│
├── .github/workflows/
│   ├── ci.yml            Lint + test + Docker build
│   ├── deploy.yml        Manual deploy (OIDC)
│   └── evals.yml         Nightly RAGAS eval gate
│
├── docker-compose.yml    Postgres for local dev
├── Dockerfile            Single image, 5 entrypoint modes
├── Makefile              dev, test, evals, psql, urls, build-image
└── pyproject.toml        uv dependencies + ruff config
```

---

## Design Decisions

### Why Bedrock?

- **Model hosting** — generation and embeddings use Bedrock. Web search sends queries to Tavily
- **IAM auth** — no API keys to rotate for LLM/embeddings
- **Cost visibility** — one line item in AWS Cost Explorer

### Why pgvector?

- **One database** — relational + vectors + full-text + JSONB
- **Hybrid search in one query** — RRF fusion is a single SQL statement
- **No extra bill** — no separate vector DB to pay for
- **Indexing** — HNSW and GIN indexes support vector and full-text retrieval; capacity needs workload testing

### Why ECS Fargate?

- **Deployment fit** — a persistent SQS worker and colocated HTTP MCP sidecars fit the current ECS task model
- **EC2-free** — no instance patching
- **Sidecar support** — MCP servers share the API task’s allocated CPU and memory
- **Shared image** — one image supports the API, UI, worker, and MCP entrypoints

### Why MCP?

- **Transport** — streamable HTTP exposes tools to compatible clients. External clients need the required headers and an authorized network path
- **Reusability** — the same server can be consumed by multiple agents
- **Future reuse** — agents can share the document and web tools through MCP

### Why nightly evals?

The historical nightly schedule limited recurring Bedrock judge calls. Run `make evals` manually against a running API when changing prompts or retrieval. Measure repeated runs before treating a score difference as a stable signal.

### Why rolling summaries?

- **Rolling** bounds retained history by combining an updated summary with recent messages
- **Implementation** is prompt engineering: each compaction gets `previous_summary + new_turns` and merges. The rolling prompt has 3 cases to handle (first compaction, merge new turns, dedup redundant content)
- **Trade-off** — summarization loses some verbatim detail from older turns; multi-turn quality needs separate evaluation

### Why a 180-second ALB timeout?

The ALB idle timeout is configured to 180 seconds for requests that include multiple model or tool calls. The UI's agent request timeout is also 180 seconds, while the eval runner uses 90 seconds. These are configured limits; latency measurements are needed to establish typical and worst-case behavior.

---

## Roadmap

**Recently shipped:**

- ✅ **v0.9** — Memory compaction (rolling summary, background task)
- ✅ **v0.7** — Evals (RAGAS) with a separate nightly workflow
- ✅ **v0.6** — CI/CD pipelines (GitHub Actions + OIDC)
- ✅ **v0.5** — MCP servers as sidecar containers
- ✅ **v0.4** — Strands agent with tool routing

**Ideas for a future release.**

- 📋 **v0.7.1** — Eval polish (30-question dataset, citation completeness metric)
- 📋 **v0.10** — Multi-agent A2A (HTTP, not AgentCore)
- 📋 **v0.8** — Observability (deferred — will revisit with v0.12 EKS)

---

## Documentation

- [Architecture decision record](./docs/adr/001-modular-monolith-strands-jsonb.md)
- [Infrastructure and deployment setup](https://github.com/MP-30/academic-intelligence-platform-terraform)
- [Application configuration](./src/academic_ai/config.py)
- [CI workflow](./.github/workflows/ci.yml)
- [Nightly eval workflow](./.github/workflows/evals.yml)

## Current limitations

- PDF parsing extracts embedded text. Image-only PDFs need OCR; the worker currently can report `READY` with zero chunks.
- Document tool selection and citation grounding depend on model behavior. Prompt instructions are the current model guardrails.
- Automated tenant tests exercise retrieval SQL. An upload-to-answer API integration test is still needed.
- Failed ingestion jobs stay at `RETRY` in the database even if SQS later moves them to the DLQ.

---

## Cost

The original deployment estimate was approximately **$63/month** for ECS tasks, ALB, Bedrock usage including nightly evals, and storage/logging, assuming an RDS billing credit. This is an undated project estimate. Actual charges depend on account credits, region, runtime, traffic, and token usage. Check AWS Cost Explorer for a dated total before using this estimate for budgeting.

## License

A license file has not been added to this repository.
