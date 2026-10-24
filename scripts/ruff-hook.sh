#!/usr/bin/env bash
# Pre-commit hook: lint and format staged Python files, and explain how to fix
# anything that blocks the commit.
set -u

ruff() { uv run -q --project credit-service/backend ruff "$@"; }

if ruff check "$@" >/dev/null && ruff format --check "$@" >/dev/null; then
  exit 0
fi

ruff check --fix "$@"
lint_status=$?
ruff format "$@" >/dev/null

echo
if [ "$lint_status" -ne 0 ]; then
  echo "Commit blocked: ruff found problems it can't fix automatically (listed above)."
  echo "Fix them by hand, then git add and commit again."
else
  echo "Commit blocked: ruff fixed formatting and lint issues in your staged files."
  echo "Review the changes, then git add them and commit again."
fi
echo
echo "To format everything yourself:"
echo "make fmt"
exit 1
