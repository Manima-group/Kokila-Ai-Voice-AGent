#!/usr/bin/env bash
# Developer helper. Usage: scripts/dev.sh <command>
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-help}" in
  install)   (cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]") && (cd frontend && npm ci) ;;
  up)        docker compose up -d --build ;;
  migrate)   docker compose run --rm migrate ;;
  seed)      docker compose run --rm api python -m app.cli seed-dev ;;
  superadmin) docker compose run --rm -e SUPERADMIN_PASSWORD api python -m app.cli create-superadmin --email "${2:?email}" ;;
  test)      (cd backend && .venv/bin/pytest -q) ;;
  lint)      (cd backend && .venv/bin/ruff check app tests && .venv/bin/mypy app) && (cd frontend && npm run lint && npm run typecheck) ;;
  build)     (cd frontend && npm run build) ;;
  logs)      docker compose logs -f --tail=200 "${2:-api}" ;;
  reset-db)  read -r -p "Delete ALL local data? type yes: " ok; [ "$ok" = yes ] && docker compose down -v ;;
  *) echo "commands: install up migrate seed superadmin test lint build logs reset-db" ;;
esac
