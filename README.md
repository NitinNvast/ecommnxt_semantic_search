# Xirify Semantic Search

A FastAPI microservice that provides **hybrid semantic search** over businesses and services. It combines OpenAI vector embeddings (via Qdrant) with MongoDB full-text search, fuses the two result sets with Reciprocal Rank Fusion (RRF), then reranks by geographic proximity and quality signals.

## Architecture Overview

```
Client → FastAPI (port 8001)
           ├── /search          → Search Engine ─┬─ Qdrant (vector search)
           │                                     ├─ MongoDB ($text search)
           │                                     ├─ RRF fusion + rerank
           │                                     └─ Redis (query-embedding cache)
           ├── /health          → MongoDB + Qdrant + Redis + outbox depth
           └── /internal/*       → Reindex & embedding-status APIs

Background Worker (APScheduler)
  ├── poll_outbox     (every OUTBOX_POLL_INTERVAL s)
  │     └── MongoDB embeddingOutbox → OpenAI Embeddings → Qdrant
  └── reconcile_all   (daily at RECONCILE_HOUR:00)
        └── diff Mongo _ids vs Qdrant points → repair missing / delete orphans
```

**Tech stack:** FastAPI · Uvicorn · MongoDB (Motor) · Qdrant · Redis · OpenAI API · APScheduler · python-jose (JWT)

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | |
| MongoDB | 6.x | Remote dev instance available (see `.env.example`) |
| Qdrant | 1.9+ | Run locally via Docker |
| Redis | 7.x | Run locally via Docker |
| OpenAI API key | — | `text-embedding-3-small` model |

> **Note:** Hybrid search relies on MongoDB **text indexes** on the `businesses` and `services` collections. The `$text` queries (`text_search_businesses` / `text_search_services`) require a text index to exist on the searchable fields; without one, MongoDB returns an error and only the vector half of the search contributes.

---

## Local Setup

### 1. Clone & navigate

```bash
cd semantic-search
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
# MongoDB — use shared dev instance or point to your own
MONGODB_URL=mongodb://devuser:password@<host>:27018/dev
MONGODB_DB=dev

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333

# OpenAI — required for generating embeddings
OPENAI_API_KEY=sk-...

# Auth — must match values used by the Node.js backend
JWT_SECRET=your-jwt-secret-here
INTERNAL_API_KEY=internal-secret-here

# Worker tuning (defaults are fine for local dev)
OUTBOX_POLL_INTERVAL=5       # seconds between outbox polls
RECONCILE_HOUR=3             # hour-of-day (server TZ) for the nightly reconcile job
EMBEDDING_BATCH_SIZE=96      # max embeddings per batch
LOG_LEVEL=INFO
SERVICE_PORT=8001
```

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGODB_URL` | _(required)_ | MongoDB connection string |
| `MONGODB_DB` | `dev` | Database name |
| `REDIS_HOST` / `REDIS_PORT` | `localhost` / `6379` | Redis connection |
| `QDRANT_HOST` / `QDRANT_PORT` | `localhost` / `6333` | Qdrant connection |
| `OPENAI_API_KEY` | _(required)_ | OpenAI key for embeddings |
| `JWT_SECRET` | _(required)_ | HS256 secret for verifying `/search` Bearer tokens |
| `INTERNAL_API_KEY` | _(required)_ | Shared key for `/internal/*` endpoints |
| `OUTBOX_POLL_INTERVAL` | `5` | Seconds between outbox polls |
| `RECONCILE_HOUR` | `3` | Hour (0–23, server TZ) to run the nightly reconcile |
| `EMBEDDING_BATCH_SIZE` | `96` | Max embeddings per OpenAI batch |
| `LOG_LEVEL` | `INFO` | Python log level |
| `SERVICE_PORT` | `8001` | Service port (informational) |

---

## Running the App

### Development (with auto-reload)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

The API will be available at `http://localhost:8001`.

Interactive docs: `http://localhost:8001/docs`

### Production (no reload)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### Via Docker

```bash
# Build image
docker build -t xirify/semantic-search .

# Run container
docker run -p 8001:8001 --env-file .env xirify/semantic-search
```

---

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | None | Health check (MongoDB, Qdrant, Redis, outbox queue depth, dead-letter count) |
| `POST` | `/search` | JWT Bearer | Hybrid semantic search for businesses & services |
| `POST` | `/internal/reindex/{entity_type}/{entity_id}` | X-Internal-Key | Reindex a single entity |
| `POST` | `/internal/reindex/business/{business_id}/services` | X-Internal-Key | Fan-out reindex of all services for a business |
| `POST` | `/internal/bulk-reindex` | X-Internal-Key | Bulk reindex with a Mongo filter |
| `GET` | `/internal/embedding-status/{entity_type}/{entity_id}` | X-Internal-Key | Check a vector's sync status in Qdrant |

`{entity_type}` is one of `business` or `service`.

### Auth headers

```
# Search endpoint (HS256 JWT, verified against JWT_SECRET)
Authorization: Bearer <jwt-token>

# Internal endpoints
X-Internal-Key: <value-of-INTERNAL_API_KEY>
```

### Example: health check

```bash
curl http://localhost:8001/health
```

```json
{
  "status": "ok",
  "mongo": "ok",
  "qdrant": "ok",
  "redis": "ok",
  "queueDepth": 0,
  "deadLetterCount": 0
}
```

### Example: semantic search

The request body is structured — geo and filters are **nested objects**, not flat fields:

```bash
curl -X POST http://localhost:8001/search \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "best pizza near me",
    "entities": ["business", "service"],
    "geo": { "lat": 18.5204, "lng": 73.8567, "radiusKm": 5 },
    "filters": { "category": "<categoryId>" },
    "page": 1,
    "limit": 10
  }'
```

**Request fields**

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `query` | string | _(required)_ | 1–500 chars |
| `entities` | `["business","service"]` | both | Which collections to search |
| `geo` | `{lat, lng, radiusKm}` | none | `radiusKm` defaults to 5; omit to skip geo filtering |
| `filters` | object | none | `category` is applied as a Qdrant filter |
| `page` | int ≥ 1 | 1 | |
| `limit` | int 1–100 | 20 | Page size |

**Response shape**

```json
{
  "results": [
    {
      "entityType": "business",
      "id": "<mongoId>",
      "score": 0.8123,
      "distanceKm": 1.24,
      "business": { "id": "...", "name": "...", "rating": 4.5, "xirifyAssured": true },
      "highlight": { "name": "...", "price": null, "description": "..." }
    }
  ],
  "fallbackUsed": false,
  "total": 12,
  "tookMs": 87
}
```

`fallbackUsed` is `true` when no result cleared the relevance threshold and the engine returned the top matches anyway.

---

## How Search Works

1. **Normalize** the query — lowercase, collapse whitespace, and expand a small set of Hinglish synonyms (e.g. `chemist → pharmacy medicine`, `thali → meal platter set`).
2. **Embed** the normalized query with `text-embedding-3-small`. The query vector is cached in Redis (key `emb:<sha256>`, 7-day TTL) so repeat queries skip the OpenAI call.
3. For each entity type, run **two searches in parallel**:
   - **Vector search** in Qdrant (top 40), filtered to `APPROVED` + available entities, optional geo-radius, and optional category.
   - **Full-text search** in MongoDB via `$text` (top 40).
4. **Fuse** the two lists with Reciprocal Rank Fusion (RRF, `k=60`), keyed on the Mongo `_id` carried in each Qdrant payload.
5. **Rerank** with a weighted score:
   `0.4·vector + 0.3·rrf + 0.2·proximity + 0.1·quality`
   - **proximity** — exponential distance decay (2 km half-life) using the Haversine distance to the consumer.
   - **quality** — boosts for `xirifyAssured`, `topRated`, `popular`, `isnew`, and `overallRating`.
6. Drop results below the score threshold (`0.05`); if none survive, fall back to the top 20 and flag `fallbackUsed`.
7. **Hydrate** surviving ids from MongoDB (and parent businesses for service results), merge both entity types, sort by score, and paginate.

---

## Background Workers

On startup, APScheduler registers two jobs.

### 1. Outbox processor (`poll_outbox`)

Runs every `OUTBOX_POLL_INTERVAL` seconds (default 5s):

1. Queries `embeddingOutbox` for `PENDING` **and** `FAILED` events (oldest first, batch of 50). Re-polling `FAILED` lets transient OpenAI/Qdrant blips recover instead of stranding the event.
2. Fetches entity data from MongoDB (`businesses` or `services`), resolving taxonomy names (categories/brands) for businesses and the parent business (for geo) for services.
3. Skips add-on and non-default-variation services.
4. Builds the source text and its SHA-256 hash:
   - **Hash unchanged** → payload-only update in Qdrant (no re-embedding, no OpenAI cost).
   - **Hash changed** → generate a new embedding via OpenAI and upsert the vector + payload into Qdrant.
5. When a business `address` changes, fans the new geo out to all of its service vectors.
6. Marks the event `DONE`, or `FAILED`/`DEAD` on error — events are dead-lettered (`DEAD`) once `retryCount` reaches 5.

`DELETE` operations remove the corresponding Qdrant point.

> Entity vectors are stored only in Qdrant. Redis caches **query** embeddings, not entity embeddings.

### 2. Reconcile (`reconcile_all`)

Runs daily at `RECONCILE_HOUR:00` (server TZ, default 03:00) as an eventual-consistency safety net for dropped outbox events or writes that bypassed the Mongoose hooks:

- For `business` and `service`, it diffs live Mongo `_id`s against the Qdrant points.
- **Missing** entities are re-embedded and upserted.
- **Orphaned** points (in Qdrant but no longer in Mongo) are deleted.

---

## Running Tests

```bash
# Run all tests
pytest

# With verbose output
pytest -v

# Run a specific test file
pytest tests/test_search_engine.py -v

# Run a specific test
pytest tests/test_reranker.py -v
```

Tests use mocked versions of MongoDB, Qdrant, Redis, and OpenAI — no live services needed. `pytest.ini` enables `asyncio_mode = auto`.

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
semantic-search/
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
│   │   ├── mongo.py         # Async MongoDB (Motor): outbox, text search, hydration
│   │   ├── qdrant.py        # Qdrant client, collections, geo filter, reconcile scroll
│   │   └── redis.py         # Async Redis client (query-embedding cache)
│   ├── models/
│   │   ├── search.py        # Request/response schemas
│   │   ├── outbox.py        # Outbox event schema
│   │   └── vectors.py       # Qdrant payload schemas
│   └── worker/
│       ├── outbox_processor.py  # Embedding pipeline logic
│       ├── reconcile.py         # Nightly Mongo↔Qdrant reconciliation
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

The app auto-creates these collections on startup if they don't exist, along with payload indexes on `businessId`, `businessStatus`, `isAvailable`, `isEnabled`, `isDisplay`, and `location` (geo):

| Collection | Dimensions | Distance | Entities |
|------------|-----------|----------|---------|
| `business_vectors` | 1536 | Cosine | Businesses |
| `service_vectors` | 1536 | Cosine | Services/products |

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

**Text-search results missing** — ensure a MongoDB `$text` index exists on the `businesses` and `services` collections; without it the `$text` queries fail and only vector results contribute.

**Outbox not processing** — set `LOG_LEVEL=DEBUG` and look for scheduler logs on startup. Check `/health` for `queueDepth` and `deadLetterCount`; events with `status: DEAD` have exhausted their 5 retries.
# ecommnxt_semantic_search
