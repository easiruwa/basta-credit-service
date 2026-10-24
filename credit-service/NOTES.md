# Development notes

Design decisions, known gaps, and issues hit while building the service.

## Design decisions

### Data model: a `users` document plus a `credits` ledger

- **`users`** holds one document per user, in the shape the spec asks for: `{user_id, balance, status}`. It answers "what does this user have now?"
- **`credits`** holds one document per credit request: `{_id, user_id, amount, status, created_at}`. It answers "what happened to this credit?" It's an audit trail, and it gives the worker a durable record to read from.

The spec only requires `users`. The ledger was added because a balance with no history can't be audited or reconciled. It's also what makes idempotency possible later (see known gaps).

### Request flow

1. `POST /credits` validates the body, inserts the credit as `processing`, and upserts the user with `status: processing`. It then queues the task and returns `202` with the credit id.
2. The worker receives only the `credit_id` and reads the amount and user from Mongo. The database stays the single source of truth, and a task message can't carry a different amount from what was stored.
3. The worker applies the credit with a single `update_one` on the user (`$inc` balance plus `$set` status), then marks the credit `processed`.

### Atomic balance updates with `$inc`

The balance is changed with `$inc`, not read-add-write. `$inc` runs inside Mongo as one atomic operation, so two workers crediting the same user at the same time can't overwrite each other's update. `$inc` also creates `balance` if it's missing, which covers spec step 4 without special cases.

The API never writes `balance`. An earlier version `$set` it to `0` on every request, which wiped the existing balance. The API now uses `$set` for `status` and `$setOnInsert` for `created_at`, so fields that should only be written once are never overwritten.

### Validation and response models (`models.py`)

- `CreditRequest.amount` uses `Field(gt=0)`, so FastAPI rejects zero and negative amounts with a `422` before any code runs. A missing `user_id` is rejected the same way.
- `Credit.id` uses `validation_alias="_id"`: the model reads Mongo's `_id` but returns `id` to clients. A plain `alias` would apply in both directions and leak `_id` into the API.
- Response models also keep Mongo's auto-generated `ObjectId` out of responses. FastAPI can't serialize it to JSON, which caused a `500` on `GET /users/{id}`.
- `Status` is a string enum (`"processing"`, `"processed"`, `"failed"`), so stored values match the spec's lowercase example. It lives in `models.py`, which imports neither `main` nor `worker`, to avoid a circular import between them.

### What `POST /credits` returns

The spec asks for "a task ID". The endpoint returns the **credit id**, because that's what clients can look up afterwards (`GET /credits/{id}`). The Celery task id is only meaningful inside Celery's result backend.

### Metrics derived from Mongo

`GET /metrics` computes counts from the `credits` collection rather than keeping in-memory counters (e.g. `prometheus_client`). Celery runs tasks in several child processes, each with its own memory, so in-process counters would be split across processes and reset on every restart. Deriving metrics from Mongo is correct however many workers run, and needs no new dependencies.

The per-status counts come from a **single aggregation** (`$group` by `status`) instead of four `count_documents` calls. That's one round-trip instead of four, and the counts all come from the same moment, so they always add up to `total_credits`. Previously they were taken at slightly different times and could disagree while the worker was busy. `total_users` is a second, separate query, since it reads a different collection.

### Docker: one image, two services

`backend/Dockerfile` builds one image. `docker-compose.yml` runs it twice: as `api` (the default command) and as `worker` (the command overridden to start Celery). One process per container lets Docker restart each one independently, keeps their logs separate, and allows scaling workers (`docker compose up --scale worker=3`).

- Inside Docker, services reach each other by service name (`mongo`, `redis`), so `MONGO_URL` and `REDIS_URL` are set in compose. `pydantic-settings` reads them into `config.Settings`.
- Mongo and Redis have health checks, and `api` and `worker` wait for `service_healthy`. Plain `depends_on` only waits for the containers to start, not for them to accept connections.
- Dependencies are installed with `uv sync --frozen --no-dev` before the code is copied. Docker caches that layer, so code changes rebuild in seconds.
- The container runs as a non-root user.

### Running locally

The venv and `pyproject.toml` live in `backend/`, so commands run from there, and modules import each other directly (`from config import settings`, not `from backend.config ...`).

## Known gaps and future work

- **Idempotency.** Celery delivers tasks at least once. If the worker crashes after the `$inc` but before marking the credit `processed`, a retry credits the user twice. Fix: have the worker atomically claim the credit (only proceed if its status is still `processing`), or apply both writes in a Mongo transaction.
- **Write succeeds, publish fails.** If Mongo accepts the credit but publishing to Redis fails, the credit stays `processing` forever. The outbox pattern, or a sweeper that re-queues stale `processing` credits, would close this.
- **Per-user status with concurrent credits.** If two credits for one user are in flight, the first to finish sets the user to `processed` while the second is still pending. The per-credit status in `credits` is accurate.
- **Money as floats.** `0.1 + 0.2 != 0.3`. Production code should use integer cents or `Decimal128`.
- **No failure handling yet.** No retries, and nothing sets the `failed` status.
- **Indexes.** `users.user_id` should have a unique index, and `credits.status` an index for the metrics aggregation as the collection grows.
- **Backlog age.** `/metrics` doesn't yet report how long the oldest `processing` credit has waited, which is the number to alert on if the worker is down.
- **Test coverage.** `backend/tests/` covers the API, the worker and the full flow against a real Mongo test database. Not covered yet: running through a real Celery worker and Redis, and concurrent credits for the same user.

## Testing approach

Tests run against a **real MongoDB** (a separate `credit_test` database, dropped after each test) rather than a mock, because the important behaviour is in the Mongo operations themselves (`$inc`, `$setOnInsert`, upserts, the metrics aggregation). A mock would only check that the code calls Mongo, not that the updates are right.

Celery isn't needed. API tests replace `process_credit.delay` with a mock and check what would have been queued, and worker tests call `process_credit(...)` directly as a plain function. `test_flow.py` joins the two: it posts credits, runs whatever the API queued, then checks the user document matches the spec.

```bash
docker compose up -d mongo   # from credit-service/
uv run pytest                # from backend/
```

If Mongo isn't reachable, the tests are skipped with a message rather than failing.

## Celery worker fails on macOS: `not enough values to unpack (expected 3, got 0)`

**Symptom.** The worker starts and receives tasks, but every task fails before any task code runs:

```
Task handler raised error: ValueError('not enough values to unpack (expected 3, got 0)')
  File ".../celery/app/trace.py", in fast_trace_task
    tasks, accept, hostname = _loc
```

The worker log shows the pool processes as `SpawnPoolWorker-N`.

**Cause.** A version mismatch between Celery and billiard, the library Celery uses to run its worker processes:

- billiard 4.3 changed its default process start method on macOS from `fork` to `spawn` (see [celery/celery#9894](https://github.com/celery/celery/issues/9894)).
- Celery 5.6.3's prefork pool still assumes `fork`. A forked child inherits the task setup (`_loc`) that the main process prepared. A spawned child starts as a fresh Python process, so `_loc` is empty and the first task fails.

This is unrelated to the application code. It only affects macOS: on Linux, including inside Docker, billiard still uses `fork`.

**Fix.** Set `FORKED_BY_MULTIPROCESSING=1` when starting the worker. This tells Celery to rebuild its task setup in each child process:

```bash
FORKED_BY_MULTIPROCESSING=1 uv run celery -A worker worker --loglevel=info
```

Alternatives:

- `--pool=solo`: runs tasks in a single process. Fine for local development, but no concurrency.
- Pin `billiard<4.3`: restores the old `fork` default, at the cost of holding back a dependency.

**Verified** with Python 3.12.15, Celery 5.6.3, billiard 4.3.1 and kombu 5.6.2 on macOS (arm64).

## Python version

The project targets Python 3.12 (`backend/.python-version`). Homebrew's default `python3` is now 3.15, but Celery 5.6.3 only lists support up to 3.13. If `uv` builds the venv with the wrong version, recreate it:

```bash
cd backend
uv python pin 3.12
rm -rf .venv && uv sync
```

The spec requires Python 3.11+, so `requires-python` in `pyproject.toml` is `>=3.11`.
