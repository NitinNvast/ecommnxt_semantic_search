# Xirify Semantic Search

A FastAPI microservice that provides **hybrid semantic search** over services. It combines OpenAI vector embeddings (via Qdrant) with Node.js API full-text search, fuses the two result sets with Reciprocal Rank Fusion (RRF), then reranks by geographic proximity and quality signals.

## Architecture Overview

```
Client → FastAPI (port 8005)
           ├── /search          → Search Engine ─┬─ Qdrant (vector search)
           │                                     ├─ Node.js API (text search)
           │                                     ├─ RRF fusion + rerank
           │                                     └─ Redis (query-embedding cache)
           ├── /health          → Node.js API + Qdrant + Redis + outbox depth
           └── /internal/*       → Reindex & embedding-status APIs

Background Worker (APScheduler)
  ├── poll_outbox     (every OUTBOX_POLL_INTERVAL s)
  │     └── Node.js embeddingOutbox → OpenAI Embeddings → Qdrant
  └── reconcile_all   (daily at RECONCILE_HOUR:00)
        └── diff Node.js IDs vs Qdrant points → repair missing / delete orphans
```

**Tech stack:** FastAPI · Uvicorn · Node.js API (HTTP) · Qdrant · Redis · OpenAI API · APScheduler · python-jose (JWT)

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | |
| Node.js backend | — | Provides entity data and outbox via HTTP |
| Qdrant | 1.9+ | Run locally via Docker |
| Redis | 7.x | Run locally via Docker |
| OpenAI API key | — | `text-embedding-3-small` model |

---

## Local Setup

### 1. Clone & navigate

```bash
cd ecommnxt_semantic_search
```

### 2. Create a virtual environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Start Qdrant and Redis via Docker

```bash
# Qdrant (vector DB)
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 \
  -v qdrant_storage:/qdrant/storage \
  qdrant/qdrant:v1.9.1

# Redis (query-embedding cache)
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

### 5. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in the required values:

```env
# Node.js backend
NODE_API_URL=http://localhost:8000
NODE_SERVICE_TOKEN=your-service-token-here

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333

# OpenAI — required for generating embeddings
OPENAI_API_KEY=sk-...

# Auth
JWT_SECRET=your-jwt-secret-here
INTERNAL_API_KEY=internal-secret-here

# Worker tuning (defaults are fine for local dev)
OUTBOX_POLL_INTERVAL=5       # seconds between outbox polls
RECONCILE_HOUR=3             # hour-of-day (server TZ) for the nightly reconcile job
EMBEDDING_BATCH_SIZE=96      # max embeddings per batch
LOG_LEVEL=INFO
SERVICE_PORT=8005
```

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_API_URL` | _(required)_ | Base URL of the Node.js backend |
| `NODE_SERVICE_TOKEN` | _(required)_ | Service token for Node.js API calls |
| `REDIS_HOST` / `REDIS_PORT` | `localhost` / `6379` | Redis connection |
| `QDRANT_HOST` / `QDRANT_PORT` | `localhost` / `6333` | Qdrant connection |
| `OPENAI_API_KEY` | _(required)_ | OpenAI key for embeddings |
| `JWT_SECRET` | _(required)_ | HS256 secret for verifying `/search` Bearer tokens |
| `INTERNAL_API_KEY` | _(required)_ | Shared key for `/internal/*` endpoints |
| `OUTBOX_POLL_INTERVAL` | `5` | Seconds between outbox polls |
| `RECONCILE_HOUR` | `3` | Hour (0–23, server TZ) to run the nightly reconcile |
| `EMBEDDING_BATCH_SIZE` | `96` | Max embeddings per OpenAI batch |
| `LOG_LEVEL` | `INFO` | Python log level |
| `SERVICE_PORT` | `8005` | Service port (informational) |

---

## Running the App

### Development (with auto-reload)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8005 --reload
```

The API will be available at `http://localhost:8005`.

Interactive docs: `http://localhost:8005/docs`

### Production (no reload)

```bash


```

### Via Docker

```bash
# Build image
docker build -t xirify/semantic-search .

# Run container
docker run -p 8005:8005 --env-file .env xirify/semantic-search
```

---

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | None | Health check (Node.js API, Qdrant, Redis, outbox queue depth, dead-letter count) |
| `POST` | `/search` | JWT Bearer | Hybrid semantic search for services |
| `POST` | `/internal/reindex/service/{entity_id}` | X-Internal-Key | Reindex a single service |
| `POST` | `/internal/reindex/business/{business_id}/services` | X-Internal-Key | Fan-out reindex of all services for a business |
| `POST` | `/internal/bulk-reindex` | X-Internal-Key | Bulk reindex all services |
| `GET` | `/internal/embedding-status/service/{entity_id}` | X-Internal-Key | Check a vector's sync status in Qdrant |

### Auth headers

```
# Search endpoint (HS256 JWT, verified against JWT_SECRET)
Authorization: Bearer <jwt-token>

# Internal endpoints
X-Internal-Key: <value-of-INTERNAL_API_KEY>
```

### Example: health check

```bash
curl http://localhost:8005/health
```

```json
{
  "status": "ok",
  "nodeApi": "ok",
  "qdrant": "ok",
  "redis": "ok",
  "queueDepth": 0,
  "deadLetterCount": 0
}
```

### Example: semantic search

```bash
curl -X POST http://localhost:8005/search \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "best pizza near me",
    "page": 1,
    "limit": 10
  }'
```

**Request fields**

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `query` | string | _(required)_ | 1–500 chars |
| `entities` | `["service"]` | `["service"]` | Entity types to search |
| `page` | int ≥ 1 | 1 | |
| `limit` | int 1–100 | 20 | Page size |

**Response shape**

```json
{
  "results": [
    {
      "entityType": "service",
      "id": "<mongoId>",
      "serviceId": "<serviceId>"
    }
  ]
}
```

---

## How Search Works

1. **Normalize** the query — lowercase, collapse whitespace, and expand a small set of Hinglish synonyms (e.g. `chemist → pharmacy medicine`, `thali → meal platter set`).
2. **Embed** the normalized query with `text-embedding-3-small`. The query vector is cached in Redis (key `emb:<sha256>`, 7-day TTL) so repeat queries skip the OpenAI call.
3. Run **two searches**:
   - **Vector search** in Qdrant (top 40, score threshold 0.3).
   - **Full-text search** via Node.js API (top 40).
4. **Fuse** the two lists with Reciprocal Rank Fusion (RRF, `k=60`), keyed on the Mongo `_id` carried in each Qdrant payload.
5. **Rerank** with a weighted score:
   `0.4·vector + 0.3·rrf + 0.2·proximity + 0.1·quality`
   - **proximity** — exponential distance decay (2 km half-life).
   - **quality** — boosts for `xirifyAssured`, `topRated`, `popular`, `isnew`, and `overallRating`.
6. **Paginate** and return results.

---

## Background Workers

On startup, APScheduler registers two jobs.

### 1. Outbox processor (`poll_outbox`)

Runs every `OUTBOX_POLL_INTERVAL` seconds (default 5s):

1. Claims `PENDING` events from the Node.js outbox (batch of 50).
2. Fetches service entity data from the Node.js API.
3. Skips add-on and non-default-variation services.
4. Builds the source text and its SHA-256 hash:
   - **Hash unchanged** → payload-only update in Qdrant (no re-embedding, no OpenAI cost).
   - **Hash changed** → generate a new embedding via OpenAI and upsert the vector + payload into Qdrant.
5. Acknowledges `DONE` or marks `FAILED` on error.

`DELETE` operations remove the corresponding Qdrant point.

> Entity vectors are stored only in Qdrant. Redis caches **query** embeddings, not entity embeddings.

### 2. Reconcile (`reconcile_all`)

Runs daily at `RECONCILE_HOUR:00` (server TZ, default 03:00) as an eventual-consistency safety net for dropped outbox events:

- Diffs live Node.js service IDs against Qdrant points.
- **Missing** entities are re-embedded and upserted.
- **Orphaned** points (in Qdrant but no longer in Node.js) are deleted.

---

## Running Tests

```bash
# Run all tests
pytest

# With verbose output
pytest -v
```

Tests use mocked versions of Node.js API, Qdrant, Redis, and OpenAI — no live services needed. `pytest.ini` enables `asyncio_mode = auto`.

Test suite:

```
tests/
├── conftest.py
├── test_api.py
├── test_embedder.py
├── test_outbox_processor.py
├── test_qdrant.py
├── test_reconcile.py
├── test_reranker.py
└── test_search_engine.py
```

---

## Project Structure

```
ecommnxt_semantic_search/
├── app/
│   ├── main.py              # FastAPI app, lifespan hooks, router wiring
│   ├── config.py            # Pydantic settings (reads .env)
│   ├── api/
│   │   ├── search.py        # /search endpoint + JWT verification
│   │   ├── reindex.py       # /internal/* endpoints + internal-key auth
│   │   └── health.py        # /health endpoint
│   ├── core/
│   │   ├── embedder.py      # OpenAI client, source-text builders, semantic fields
│   │   ├── search_engine.py # Query normalization + hybrid search orchestration
│   │   └── reranker.py      # RRF fusion + proximity + quality scoring
│   ├── db/
│   │   ├── node_api.py      # HTTP client to Node.js backend (entities, outbox)
│   │   ├── qdrant.py        # Qdrant client, collections, reconcile scroll
│   │   └── redis.py         # Async Redis client (query-embedding cache)
│   ├── models/
│   │   ├── search.py        # Request/response schemas
│   │   ├── outbox.py        # Outbox event schema
│   │   └── vectors.py       # Qdrant payload schemas
│   └── worker/
│       ├── outbox_processor.py  # Embedding pipeline logic
│       ├── backfill.py          # Day-zero batch embedding
│       ├── reconcile.py         # Nightly Node.js↔Qdrant reconciliation
│       └── scheduler.py         # APScheduler setup (both jobs)
├── tests/                   # pytest test suite (fully mocked)
├── docs/                    # Postman collection
├── k8s/                     # Kubernetes manifests
├── Dockerfile
├── requirements.txt
├── pytest.ini
└── .env.example
```

---

## Kubernetes Deployment

```bash
# Deploy Qdrant (StatefulSet with PVC)
kubectl apply -f k8s/qdrant-statefulset.yaml

# Deploy the semantic search service
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

---

## Qdrant Collections

The app auto-creates the collection on startup if it doesn't exist, along with payload indexes on `mongoId` and `serviceId`:

| Collection | Dimensions | Distance | Entities |
|------------|-----------|----------|---------|
| `service_vectors` | 1536 | Cosine | Services |

Vector model: `text-embedding-3-small` (OpenAI, 1536-dim). Embedding version tag: `v1-te3s`.

> Qdrant point ids are deterministic UUID5 values derived from each Mongo `_id` (Qdrant rejects raw 24-char ObjectId hex). The original Mongo `_id` is preserved in `payload.mongoId` for hydration and reconciliation.

---

## Troubleshooting

**Qdrant connection refused**
```bash
docker ps | grep qdrant   # confirm container is running
curl http://localhost:6333/healthz
```

**Redis connection refused**
```bash
docker ps | grep redis
redis-cli ping            # should return PONG
```

**OpenAI quota / key errors** — check `OPENAI_API_KEY` in `.env` and your API quota.

**Node.js API unreachable** — check `NODE_API_URL` and `NODE_SERVICE_TOKEN` in `.env`. The `/health` endpoint shows `nodeApi: error` when the upstream is down.

**Outbox not processing** — set `LOG_LEVEL=DEBUG` and look for scheduler logs on startup. Check `/health` for `queueDepth` and `deadLetterCount`.
