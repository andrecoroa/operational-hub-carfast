#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python scripts/check_migration_heads.py
python -m alembic upgrade head
python -m scripts.bootstrap_installation
python -m scripts.check_clean_install
python scripts/create_admin.py

mkdir -p /workspaces/.carfast-data/documents/inbox /workspaces/.carfast-data/email

echo "CarFast ready. Start with: python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
