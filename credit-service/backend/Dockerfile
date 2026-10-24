# One image for both the API and the Celery worker.
# docker-compose.yml picks which process each container runs.
FROM python:3.12-slim

# uv is copied in as a single binary from Astral's image, pinned to the version
# that produced uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies before copying the code. Docker caches each step, so
# editing a .py file reuses this layer instead of reinstalling everything.
# --frozen: install exactly what uv.lock says, and fail if it's out of date.
# --no-dev: skip pytest/httpx, which the running service doesn't need.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Put the venv's executables (fastapi, celery) on the PATH.
ENV PATH="/app/.venv/bin:$PATH"

# Don't run as root inside the container.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Default command starts the API. `fastapi run` is the production mode
# (no auto-reload) and listens on 0.0.0.0 so it's reachable from outside
# the container. The worker service overrides this command in compose.
CMD ["fastapi", "run", "main.py", "--port", "8000"]
