# Data lifecycle and installation paths

This document establishes Phase 0 rules. It does not authorize a production migration.

## Formal data classes

Every table and seed must be classified before modular restructuring:

| Class | Definition | Examples | New-installation rule |
|---|---|---|---|
| Schema | tables, constraints, indexes and migration metadata | Alembic revisions | always created by migrations |
| Reference data | versioned codes required for deterministic application behaviour | canonical permissions, module catalogue, fixed statuses | seeded explicitly and idempotently |
| Installation configuration | tenant/company identity, enabled modules, branding, endpoints, local settings | organisation, module selection, sandbox endpoints | created by onboarding; never hard-coded for CarFast |
| Operational data | business activity and evidence | users beyond bootstrap admin, vehicles, suppliers, tasks, processes, emails, documents, stock, events and audit | absent from a clean installation |

The current `seed_initial_data` predates this classification. During modular work, each seeded row must receive an explicit owner/class before it is retained in the reusable baseline.

## Path A — Existing CarFast

The operational migration must preserve documents, attachments, processes, tasks, email, states, links, users, permissions, events and audit evidence. In-progress processes must preserve phase, assignees, dates and context.

Before any production cutover:

1. inventory tables, row counts, document metadata and physical objects;
2. take recoverable database and storage backups;
3. restore an isolated PostgreSQL copy and isolated document storage;
4. run idempotent migrations there;
5. reconcile pre/post row counts, relationship counts, file counts, sizes and cryptographic hashes;
6. open representative current and historical processes and their documents;
7. verify authorization, audit continuity and in-progress workflow actions;
8. rehearse rollback and record timing/results;
9. obtain functional approval before production execution.

No legacy element is removed without inventory, evidence of use/obligation, functional approval and reconciliation.

## Path B — Reusable clean installation

A new installation is created from the same code and Alembic chain on an empty PostgreSQL database. It is never derived by cleaning or anonymizing production.

The allowed sequence is:

1. `python -m alembic upgrade head`;
2. `python -m scripts.bootstrap_installation` for versioned reference data;
3. onboarding creates company/tenant, first administrator and initial module selection;
4. installation-specific branding, domains, endpoints, storage and sandbox integrations are configured outside source control.

Until onboarding and a module catalogue are implemented under a later approval, `bootstrap_installation.py` seeds only canonical permissions, roles and generic catalogues. CI runs `check_clean_install.py` to prove that representative operational and installation-specific tables remain empty. The existing `seed_initial_data` is intentionally not used because it currently contains CarFast-specific organisation, mailbox and operational defaults.

## Required future tests

### Preservation suite

- row and relationship reconciliation by domain;
- document metadata-to-object accessibility and SHA-256 checks;
- current process state/phase/responsible/date continuity;
- historical links, audit order and actor preservation;
- idempotent rerun with no duplicate or destructive effects;
- rollback restoration rehearsal.

### Clean-installation suite

- empty PostgreSQL upgrade from base to head;
- explicit reference seeds are idempotent;
- no operational records/files are created;
- onboarding creates a distinct tenant and administrator;
- application starts with supported active/inactive module combinations;
- branding, storage, endpoints and secrets remain installation-configurable;
- disabled integrations degrade safely without outbound traffic.

These suites become release gates before the modular version can replace production or be reused for another company.
