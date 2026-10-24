# Development notes

How the service is built, what's still missing, and problems I ran into along the way.

## Design decisions

### Two collections: `users` and `credits`

- `users` has one document per user: `{user_id, balance, status}`, as in the spec. It also has an `applied_credits` list, used to avoid double credits (see below). The API doesn't return that list.
- `credits` has one document per credit request: `{_id, user_id, amount, status, created_at}`.

The spec only asks for `users`. I added `credits` so every balance change has a record behind it. The worker also reads from it, and it's what the user's credit history endpoint lists.

### How a credit flows through the system

1. `POST /credits` checks the request, saves the credit as `processing`, and sets the user's status to `processing` (creating the user if needed). It queues a task and returns `202` with the task id and the credit id.
2. The worker gets only the `credit_id`. It reads the amount and user from Mongo, so the database is the only source of truth.
3. The worker updates the user in one step: add the amount to `balance`, set `status` to `processed`, and add the credit id to `applied_credits`. Then it marks the credit `processed`.

### Applying each credit only once

Celery can run the same task more than once. For example, with `acks_late` on, a task is retried if the worker crashes partway through. Without protection, a retry could credit the user twice.

The worker's user update only matches if the credit isn't already in `applied_credits`:

```python
db.users.update_one(
    {"user_id": user_id, "applied_credits": {"$ne": credit_id}},
    {"$inc": {"balance": amount}, "$set": {...}, "$push": {"applied_credits": credit_id}},
)
```

Mongo applies an update to a single document all at once, so the check and the balance change can't get separated. If the task runs again, the update matches nothing, and the worker just marks the credit `processed`. The worker logs a warning when that happens.

Other options I considered:

- **Mark the credit as taken first, then apply it.** A crash between the two steps would lose the credit.
- **A Mongo transaction.** This is the usual production answer, but it needs a replica set, and the Docker setup runs a single Mongo.

Downside: `applied_credits` grows with every credit. A very busy user could eventually hit Mongo's 16 MB document limit. At that point, switch to transactions or keep only recent ids.

### Updating the balance with `$inc`

`$inc` adds to the balance inside Mongo in one step. Two workers crediting the same user at the same time can't overwrite each other, which could happen with "read the balance, add, write it back". `$inc` also creates `balance` if it doesn't exist yet.

The API never writes `balance`. An early version set it to `0` on every request, which wiped out the user's balance. Now the API only sets `status`, and uses `$setOnInsert` for `created_at` so it's only written once.

### Request and response models

- `amount` must be greater than 0, and `user_id` can't be empty. FastAPI rejects bad requests with a `422` before any of my code runs.
- `Credit.id` reads Mongo's `_id` but is returned as `id`. It uses `validation_alias`, which only renames the field on the way in. A plain `alias` would also rename it on the way out and show `_id` to clients.
- Response models keep Mongo's internal `_id` (an `ObjectId`) out of responses. FastAPI can't turn it into JSON, and it caused a `500` before.
- `Status` is a string enum with lowercase values, matching the spec's example. It lives in `models.py` so `main.py` and `worker.py` can both import it without importing each other.

### What `POST /credits` returns

```json
{"task_id": "…", "credit_id": "…", "status": "processing"}
```

- `task_id` is the Celery task id. The spec asks for it, and it identifies the job inside Celery.
- `credit_id` is what clients use to check on the credit later with `GET /credits/{credit_id}`.

Both fields have clear names, so nobody has to guess which id is which.

### Credit history: `GET /users/{user_id}/credits`

- Returns `404` if the user doesn't exist, and an empty list if the user exists but has no credits.
- Sorted newest first.
- Capped at 100 results for now (see pagination under future work).

### Metrics come from Mongo

`GET /metrics` counts credits by status straight from the `credits` collection. I didn't use in-memory counters (like `prometheus_client`) because Celery runs tasks in several processes. Each would keep its own counts, and they'd reset on restart. Counting in Mongo is correct however many workers are running.

All the status counts come from one aggregation query, so they're taken at the same moment and always add up to the total. The user count is a second query, since it's a different collection.

### Docker: one image, two containers

The API and the worker share one image (`backend/Dockerfile`). `docker-compose.yml` starts it twice: once as the API, and once with the command changed to run Celery. Separate containers mean each can restart on its own, logs stay separate, and you can run more workers with `docker compose up --scale worker=3`.

- Containers reach each other by service name, so `MONGO_URL` and `REDIS_URL` point at `mongo` and `redis`.
- Mongo, Redis and the API have health checks. The API and worker wait until Mongo and Redis are actually ready, and `make up` waits until the API answers.
- Dependencies are installed before the code is copied in, so Docker can reuse that step and code changes rebuild quickly.
- The containers don't run as root.

### Tooling

- `make` commands at the repo root cover setup, running, testing and formatting. Run `make` to list them.
- `ruff` formats and lints the code. A pre-commit hook runs it on every commit, and CI checks it on every push.
- CI runs lint, the tests (against a real Mongo) and a Docker build.
- Commands run from `backend/`, where the venv and `pyproject.toml` live. Modules import each other directly (`from config import settings`).

## Future work

- **Pagination.** `GET /users/{user_id}/credits` returns at most 100 credits, and there's no way to get older ones. Next step: a `limit` parameter, plus a cursor such as `?before=<created_at>` to fetch the next page. A cursor holds up better than page numbers when new credits keep arriving.
- **Retries on errors.** The task has `max_retries=5`, but nothing triggers a retry yet, and nothing sets the `failed` status. Next step: `autoretry_for` with backoff, then mark the credit `failed` once retries run out.
- **Client retries.** If a client's request times out and they send it again, two credits are created. An `Idempotency-Key` header, saved on the credit with a unique index, would let the API return the original credit instead (Stripe's API works this way).
- **Saved but never queued.** If the credit is saved but sending the task to Redis fails, the credit stays `processing` forever. Fix with the outbox pattern, or a job that re-queues old `processing` credits.
- **User status with several credits at once.** If two credits for the same user are processing, the first one to finish sets the user to `processed` while the other is still running. Each credit's own status is always correct.
- **Whitespace in `user_id`.** `"   "` and `" u_123 "` are accepted. The second would create a separate user from `"u_123"`. Next step: strip whitespace before validating.
- **Money as floats.** `0.1 + 0.2` doesn't equal `0.3` in floating point. Production code should store whole cents or use `Decimal128`.
- **Indexes.** A unique index on `users.user_id`, and indexes on `credits.user_id` (credit history) and `credits.status` (metrics).
- **Backlog age in metrics.** `/metrics` doesn't show how long the oldest `processing` credit has been waiting. That's the number to alert on if the worker goes down.
- **More tests.** Not covered yet: running through a real Celery worker and Redis, and many credits for one user at the same time.

## Testing

Tests use a real MongoDB with a separate `credit_test` database, emptied before and after each test. The important logic lives in the Mongo updates (`$inc`, `$setOnInsert`, upserts, the aggregation), and a fake database wouldn't show whether those are right.

Celery and Redis aren't needed:

- API tests replace `.delay()` with a fake that records what would have been queued.
- Worker tests call `process_credit(...)` directly.
- The idempotency tests use a database wrapper that crashes on the first write to `credits`, to simulate a worker dying halfway through.
- `test_flow.py` runs the whole thing: post credits, run the queued tasks, check the user matches the spec.

Run them with `make test`. Locally, the tests are skipped if Mongo isn't running. In CI they fail instead, so a broken setup can't pass.

## Troubleshooting

### Celery worker fails on macOS: `not enough values to unpack (expected 3, got 0)`

The worker starts and receives tasks, but every task fails before any of my code runs:

```
Task handler raised error: ValueError('not enough values to unpack (expected 3, got 0)')
  File ".../celery/app/trace.py", in fast_trace_task
    tasks, accept, hostname = _loc
```

The worker log shows `SpawnPoolWorker-N`.

**Cause.** billiard, the library Celery uses to start worker processes, switched macOS from `fork` to `spawn` in version 4.3 ([celery/celery#9894](https://github.com/celery/celery/issues/9894)). Celery 5.6.3 still expects `fork`. A forked process gets a copy of the setup Celery already did. A spawned one starts empty, so the first task fails. Linux, including Docker, still uses `fork`, so this only happens on macOS.

**Fix.** Set `FORKED_BY_MULTIPROCESSING=1` when starting the worker. It tells Celery to redo its setup in each process:

```bash
FORKED_BY_MULTIPROCESSING=1 uv run celery -A worker worker --loglevel=info
```

Other options: `--pool=solo` (one process, fine for local work), or pin `billiard<4.3`.

Tested with Python 3.12.15, Celery 5.6.3, billiard 4.3.1 and kombu 5.6.2 on macOS (arm64).

### Wrong Python version

The project uses Python 3.12 (`backend/.python-version`). Homebrew's default `python3` is now 3.15, but Celery 5.6.3 only supports up to 3.13. If the venv was built with the wrong version, rebuild it:

```bash
cd backend
uv python pin 3.12
rm -rf .venv && uv sync
```

`pyproject.toml` requires Python 3.11 or newer, as the spec does.
