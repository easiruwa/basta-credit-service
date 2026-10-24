# Basta Credit Service

[![CI](https://github.com/easiruwa/basta-credit-service/actions/workflows/ci.yml/badge.svg)](https://github.com/easiruwa/basta-credit-service/actions/workflows/ci.yml)

An asynchronous service that credits a user's balance through a FastAPI endpoint, a Redis queue, and a Celery worker backed by MongoDB.

## Requirements

- [Docker](https://docs.docker.com/get-docker/) (Docker Desktop on macOS)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- `make`

## Quick start

From the repo root:

```bash
make setup   # install dependencies and the pre-commit hook
make up      # start the API, worker, MongoDB and Redis
make check   # run lint and tests
```

The API runs at http://localhost:8000, with interactive docs at http://localhost:8000/docs.

## Usage

Add credit to a user:

```bash
curl -X POST http://localhost:8000/credits \
  -H "Content-Type: application/json" \
  -d '{"user_id": "u_123", "amount": 50}'
```

```json
{"task_id": "…", "credit_id": "…", "status": "processing"}
```

A moment later, the worker has applied it:

```bash
curl http://localhost:8000/users/u_123
```

```json
{"user_id": "u_123", "balance": 50.0, "status": "processed", "created_at": 1792861072.96}
```

Other endpoints:

| Endpoint | Returns |
|---|---|
| `GET /credits/{credit_id}` | One credit and its status |
| `GET /users/{user_id}/credits` | The user's credits, newest first (up to 100) |
| `GET /metrics` | Credit counts by status, the number of users, and how long the oldest unprocessed credit has waited |
| `GET /health` | `200` if the API can reach MongoDB |

## Commands

Run `make` to list them all.

| Command | What it does |
|---|---|
| `make setup` | Install dependencies and the pre-commit hook |
| `make up` / `make down` | Start or stop all services |
| `make logs` | Follow the API and worker logs |
| `make test` | Run the tests (starts MongoDB if needed) |
| `make lint` / `make fmt` | Check or fix formatting and lint |
| `make check` | Lint and tests, as CI runs them |

## More

Design decisions, known gaps and troubleshooting notes are in [credit-service/NOTES.md](credit-service/NOTES.md).
