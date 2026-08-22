# Phase 3 — visual foundation and post-action contract

Status: implementation slice for review. It is gated, reversible and does not change production.

## Scope and evidence

**FACT:** the Phase 2 baseline contains 440 routes and 773 template action points. The
Administration Evolution surfaces already combine a filterable table, create/edit forms,
status, comments, linked documents and history. They are Core-owned and have existing
characterization coverage.

**DECISION:** this slice therefore applies the transversal foundation to:

- `/v2-clean/admin/evolution` — filters, table and create form;
- `/v2-clean/admin/evolution/{id}` — form/action bar, comments/documents split panel and history.

No operational domain is moved or re-owned. URLs, stored values, permissions and the
default save destination remain compatible.

## Visual contract

`app/static/css/foundation.css` defines semantic CSS Custom Properties for colour,
typography, a 4 px spacing scale, control heights, content widths, radii, elevation,
motion and breakpoints. `app/templates/_ui_primitives.html` supplies compatible Jinja
macros for page headers, breadcrumbs, buttons, status, feedback, tables, split panels,
fields, dialogs and previews.

The target is WCAG 2.2 AA. Controls use a 44 px minimum target, focus is visible,
keyboard navigation remains native, motion is suppressed when requested, and migrated
surfaces must not produce body overflow at 320 px. Wide tables scroll inside their own
container.

The stylesheet and migrated markup are enabled only by
`VISUAL_FOUNDATION_ENABLED=true`; the default is `false`. Disabling the flag restores
the legacy stylesheet/markup path without a data migration.

## ReturnContext v1

`app/core/return_context.py` issues a versioned, HMAC-SHA256 signed context containing
only an internal path, query, optional anchor and issue time. Resolution rejects invalid
signatures, unsupported versions, expired/future tokens, schemes, hosts, protocol-relative
paths, backslashes/control characters and paths outside the route-specific allow-list.

On the gated Evolution slice:

- **Guardar** remains on the detail record;
- **Guardar e fechar** returns to the signed logical list/filter context;
- **Cancelar/Voltar** returns without a write;
- creation keeps its origin and can return to the originating filtered list;
- an absent or invalid context falls back to `/v2-clean/admin/evolution`.

Server-side permission checks remain authoritative and unchanged.

## Verification and measurements

Automated tests cover signature tampering, external return attempts, expiry/future time,
route authorization, deterministic post-actions, gate-off compatibility, tokens/primitives,
focus, reduced motion and the 320 px overflow contract. Browser measurements used the
running local application, the gated stylesheet and a synthetic SQLite installation.

| Surface | Viewport/client | Document/body scroll | Body overflow | Local component | DOM elements |
|---|---:|---:|---|---|---:|
| Evolution list | 320 / 305 px | 305 / 305 px | no | table 247 client / 720 scroll | 529 |
| Evolution list | 1440 / 1425 px | 1425 / 1425 px | no | table 1083 client / 1083 scroll | 529 |
| Evolution detail | 320 / 305 px | 305 / 305 px | no | split panel collapsed to one 277 px column | 509 |

The 15 px difference is browser chrome/scrollbar allocation, not page overflow. The list
table intentionally overflows only inside `.ui-table-container` at 320 px. Captures are:

- `evidence/phase3-evolution-list-320.png`;
- `evidence/phase3-evolution-list-1440.png`;
- `evidence/phase3-evolution-detail-320.png`.

Synthetic data only was used. No production URL, database, document or integration was
accessed to produce this evidence.

## Migration gate for further pages

A page can migrate only when it has:

1. characterized URLs, permissions, actions, destinations and persisted fields;
2. an explicit logical origin and route-specific ReturnContext allow-list;
3. primitive coverage without new page-specific layout CSS;
4. 320/768/1440 px evidence, keyboard/focus and reduced-motion checks;
5. differential tests proving gate-off legacy behaviour;
6. an independent rollback by flag, with no destructive schema or data dependency.

Recommended next low-risk candidates are Core Administration settings/roles and audit
lists. Operational Documents, Service Desk, Automotive, Stock and Partners surfaces stay
out of scope until their domain characterization and ownership gates are approved.

## Risks

- Some legacy templates contain fixed widths outside the migrated container; migrate only
  after page-specific measurement.
- ReturnContext is intentionally route-authorized; each new consumer needs a narrow prefix
  list and permission-aware destination handling.
- CSS tokens coexist with legacy variables, so removal of legacy CSS is not authorized.
- Visual regression screenshots are evidence, not a replacement for keyboard and semantic
  accessibility review.
