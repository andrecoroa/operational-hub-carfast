# Remote development

## Purpose

This repository can be developed in GitHub Codespaces, GitHub Actions and repository-connected Codex tasks without depending on a personal workstation. GitHub is canonical. The current Render service remains production and is outside this setup.

## Codespaces

1. Open the repository in GitHub and choose **Code → Codespaces → Create codespace** on the intended branch.
2. Wait for `.devcontainer/post-create.sh` to install dependencies and migrate the isolated PostgreSQL database.
3. Start the app:

   ```bash
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

4. Open forwarded port 8000. Create only synthetic users/data.

The container uses disposable development credentials, a private PostgreSQL service and named volumes for local development documents/email. Email delivery and inbound handling are disabled. No GitHub secret is required for the base environment.

After the clean-installation check, the development container creates a development-only administrator (`admin@carfast.local`, password `LocalDevelopment123!`) and the current compatibility defaults required by the existing application. This happens only in the private container database and is separate from the reusable clean-installation path. These credentials must never be used in staging or production.

## Local equivalent

Use Python 3.13 and PostgreSQL 17. Copy `.env.example` to `.env`, replace development-only placeholders, create the database, then run:

```bash
python -m pip install -r requirements-dev.txt
python scripts/check_migration_heads.py
python -m alembic upgrade head
python -m scripts.bootstrap_installation
python -m scripts.check_clean_install
python -m pytest -q
python -m uvicorn app.main:app --reload
```

## Environments

| Environment | Database | Storage | Integrations | Deployment |
|---|---|---|---|---|
| Development/Codespaces | isolated container PostgreSQL | private named volume | disabled/mocked | manual preview only |
| CI | fresh PostgreSQL service per job | runner temporary directory | disabled | none |
| Staging (proposed) | separate managed PostgreSQL | separate persistent disk/bucket | sandbox credentials only | separate Render service |
| Production | current managed PostgreSQL | current persistent storage | production credentials | current Render service |

Never reuse a database, disk, bucket, secret or inbound endpoint between these environments.

## Branch and PR flow

- `v2/production`: protected production branch; PR-only, required CI and review, no force-push or deletion.
- `integration/modular-architecture`: proposed long-running integration branch for the approved modular programme.
- `codex/<objective>` (or another agreed prefix): short branch with one objective, normally based on its intended target.
- Critical fixes: branch from `v2/production`, merge there after validation, then forward-port deliberately into the integration branch. Migration commits must be reconciled, never blindly cherry-picked.

Creating the integration branch and changing GitHub branch protection are external state changes and require explicit approval.

## CI and migration policy

Every pull request installs dependencies, compiles/imports the application, verifies one Alembic head, upgrades a clean PostgreSQL 17 database and runs the essential stable test set. A migration PR must also document data preservation, downgrade/rollback constraints and backfill behaviour.

The complete baseline suite currently has known production-branch debt (498 passing and 23 failing tests on 2026-08-22), including stale migration-head expectations and legacy-flow expectations. Those failures are documented rather than hidden; correcting them requires separate functional scope. The required CI gate therefore uses 44 stable foundation, RBAC, email and Service Desk tests until that debt is resolved.

The two mandatory data paths—preserving the existing CarFast and creating a reusable empty installation—are defined in `docs/DATA_LIFECYCLE_AND_INSTALLATIONS.md`.

Before merging concurrent migration work:

1. update from the target branch;
2. inspect both revision graphs and business intent;
3. produce a deliberate merge/replacement migration when needed;
4. confirm one head with `python scripts/check_migration_heads.py`;
5. apply the full chain to an empty PostgreSQL database and, when authorized, an anonymized representative copy.

## Secrets and data

- `.env.example` documents names only; `.env` is ignored.
- Codespaces secrets are needed only for approved sandbox integrations, never for the base setup.
- Do not copy production secrets or real data into Codespaces or CI.
- If representative data is required, obtain authorization and use an anonymized, minimized dataset with a documented expiry.

## Proposed staging (not created)

Create a separate Render web service, PostgreSQL database, persistent storage and hostname. Use distinct secrets and sandbox integration accounts. Keep automatic production deployment tied only to the approved production branch. This proposal may incur cost and must be approved before resources are created.
