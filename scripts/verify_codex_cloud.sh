#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPOSITORY_ROOT"

mode="${1:-}"
if [[ -n "$mode" && "$mode" != "--postgresql" && "$mode" != "--full" ]]; then
    echo "Usage: $0 [--postgresql|--full]" >&2
    exit 2
fi

python_command="python"
if [[ -x .venv/bin/python ]] && [[ "$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" == "3.13" ]]; then
    python_command=".venv/bin/python"
fi

"$python_command" -c 'import sys; assert sys.version_info[:2] == (3, 13), sys.version'

export APP_ENV="${APP_ENV:-test}"
export APP_SECRET_KEY="${APP_SECRET_KEY:-codex-cloud-test-only}"
export EMAIL_INBOUND_ENABLED="${EMAIL_INBOUND_ENABLED:-false}"
export EMAIL_OUTBOUND_ENABLED="${EMAIL_OUTBOUND_ENABLED:-false}"
export WEBHOOKS_ENABLED="${WEBHOOKS_ENABLED:-false}"
export SCHEDULED_JOBS_ENABLED="${SCHEDULED_JOBS_ENABLED:-false}"
export PORTALS_ENABLED="${PORTALS_ENABLED:-false}"
export EXTERNAL_INTEGRATIONS_ENABLED="${EXTERNAL_INTEGRATIONS_ENABLED:-false}"
export POSTMARK_SERVER_TOKEN="${POSTMARK_SERVER_TOKEN:-}"
export INTEGRATION_API_KEY="${INTEGRATION_API_KEY:-}"
export WEBHOOK_SIGNING_SECRET="${WEBHOOK_SIGNING_SECRET:-}"
export DOCUMENT_FIXTURES_ONLY="${DOCUMENT_FIXTURES_ONLY:-true}"
export REAL_DATA_ALLOWED="${REAL_DATA_ALLOWED:-false}"
export DOCUMENT_ARCHIVE_ROOT="${DOCUMENT_ARCHIVE_ROOT:-/tmp/carfast-codex-documents}"
export DOCUMENT_INVOICE_INBOX_PATH="${DOCUMENT_INVOICE_INBOX_PATH:-/tmp/carfast-codex-documents/inbox}"
export EMAIL_STORAGE_ROOT="${EMAIL_STORAGE_ROOT:-/tmp/carfast-codex-email}"

if [[ "$mode" != "--postgresql" ]]; then
    export DATABASE_URL="sqlite+pysqlite:///:memory:"
fi

mkdir -p "$DOCUMENT_INVOICE_INBOX_PATH" "$EMAIL_STORAGE_ROOT"

"$python_command" scripts/check_migration_heads.py
"$python_command" -m compileall -q app scripts
"$python_command" -c 'from app.main import app; assert app.title'

if [[ "$mode" == "--postgresql" ]]; then
    if [[ -z "${DATABASE_URL:-}" ]]; then
        echo "DATABASE_URL is required for --postgresql and must target an isolated local *_test database." >&2
        exit 2
    fi

    "$python_command" -m scripts.validate_isolated_environment
    "$python_command" - <<'PY'
import os

import psycopg

database_url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
with psycopg.connect(database_url) as connection:
    server_version = connection.info.server_version
if not 170000 <= server_version < 180000:
    raise SystemExit(f"PostgreSQL 17 is required; server_version={server_version}")
print(f"PostgreSQL server_version={server_version}")
PY
    "$python_command" -m alembic upgrade head
    "$python_command" -m scripts.bootstrap_installation
    "$python_command" -m scripts.check_clean_install
    "$python_command" -m alembic current --check-heads
fi

if [[ "$mode" == "--full" ]]; then
    "$python_command" -m pytest -q
else
    "$python_command" -m pytest -q \
        tests/test_foundation_api.py \
        tests/test_navigation_rbac.py \
        tests/test_task_center_approved_contract.py \
        tests/test_task_center_access_notifications.py \
        tests/test_task_center_v3_contract.py \
        tests/test_task_center_v3_ui_contract.py \
        tests/test_task_cases.py \
        tests/test_email_postmark.py \
        tests/test_invoice_service_history.py \
        tests/test_service_desk_operations.py \
        tests/test_modular_foundation.py \
        tests/test_visual_foundation.py \
        tests/test_partners_boundary.py \
        tests/test_documents_boundary.py \
        tests/test_service_desk_boundary.py \
        tests/test_stock_boundary.py \
        tests/test_automotive_boundary.py \
        tests/test_legacy_consolidation.py \
        tests/test_phase10_rehearsal.py \
        tests/test_isolated_environment.py
fi
