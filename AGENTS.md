# CarFast repository instructions

## Source of truth

- GitHub is canonical. Start from the current remote target branch; do not rely on local-only files.
- Production is `v2/production` and the existing Render service. Never deploy or mutate production unless the task explicitly authorizes it.
- Use one objective per short-lived branch/worktree. Default task branches use `codex/<objective>`.
- Structural work targets `integration/modular-architecture` after that branch is approved and created. Critical production fixes start from `v2/production` and must be synchronized deliberately into the integration branch.

## Setup and validation

```bash
python -m pip install -r requirements-dev.txt
python scripts/check_migration_heads.py
python -m alembic upgrade head
python -m scripts.bootstrap_installation
python -m scripts.check_clean_install
python -m compileall -q app scripts
python -c "from app.main import app; assert app.title"
python -m pytest -q
```

Start development with:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Codespaces supplies isolated PostgreSQL and safe storage paths. Keep email inbound/outbound disabled and do not configure live Postmark, webhooks or integration keys.

## Safety

- Never commit `.env`, credentials, tokens, production URLs containing credentials, or real customer/vehicle/document data.
- Never point development or CI at production databases or storage.
- Keep the existing-CarFast migration path separate from the reusable clean-installation bootstrap. A clean installation must originate from migrations and explicit seeds, never from a sanitized production copy.
- Do not delete or rewrite documents, attachments, history or audit evidence.
- Do not mechanically cherry-pick divergent Alembic migrations. Reconcile intent, verify exactly one head, and test the complete upgrade on PostgreSQL.
- Do not clean branches or worktrees without confirming integration and backup.
- Do not refactor module boundaries unless an approved strategy handoff explicitly authorizes it.

## Handoff

Every completed task reports: changed files, commits, tests, migrations, deployment, risks and pending decisions.
