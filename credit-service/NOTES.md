# Development notes

Issues hit while building the service, and how they were fixed.

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

The spec requires Python 3.11+, so `requires-python` in `pyproject.toml` should be `>=3.11`.
