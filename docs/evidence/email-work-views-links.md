# Email work views and safe links — evidence

## Contract mapping

| Contract | Implementation | Automated proof | Browser proof |
| --- | --- | --- | --- |
| `Por caixa` is the first/default view | Server defaults to `mailbox`; rows are grouped by canonical `EmailChannel` | `test_email_work_views_group_without_duplicates_and_mine_stays_scoped` | Local HTTP first entry showed `data-email-work-view=mailbox`; exact channel totals and no duplicate rows |
| `Minhas` is scoped to the current user | Server adds `EmailThread.assigned_to_id == user_id`; groups by status | Same test includes another user's assignment and excludes it | Local HTTP showed two assigned conversations in two status groups; the unassigned conversation was absent |
| `Todas` is flat and never the first default | Explicit `all` renders one table without work groups | Same test checks the flat marker and hidden view value | Local HTTP showed one table, zero groups, three unique rows |
| Remember the last view per user | Signed session stores `{user_id, view}` only after an explicit valid selection | Same test changes to `mine` and verifies a later request without `view` restores it | Local HTTP request without `view` restored `mine` and its two rows |
| Preserve filters | View is included in metric, navigation, filter and clear URLs | Route test checks rendered hidden view and scoped response | Status `all` remained active while switching work views |
| Useful preview without an empty reserved pane | Existing responsive preview behavior is retained; desktop uses the contextual panel and mobile the dialog | Existing preview regression suite plus focus contract assertion | Preview opened, closed and Escape returned focus to `Abrir`; document horizontal overflow was zero |
| Safe legitimate links | Sanitizer permits absolute HTTP(S), `mailto`, anchors and `/v2-clean/` internal routes | `test_email_body_keeps_safe_links_and_removes_active_content` | External link had `_blank` and `noopener noreferrer`; internal link stayed same-context |
| Fail closed on active/unsafe content | Event attributes and `javascript:`/`data:` URLs are rejected; blocked element contents are removed | Same sanitizer test | Iframe body contained zero script/style/iframe/object/embed nodes and no event attribute |

## Browser geometry

- Desktop: 1440 × 731, document horizontal overflow `0`.
- Mobile: 390 × 844, document and body horizontal overflow `0`.
- Mobile mailbox grouping rendered exact totals: Caixa geral `2 novas / 2 por tratar / 2 total`; Multas `0 novas / 1 por tratar / 1 total`.
- Mobile preview closed by visible control and Escape; focus returned to the invoking `Abrir` button after the deferred focus restoration.

## Data and safety

- Browser evidence used an isolated local SQLite fixture with three synthetic conversations only.
- The temporary seed helper was removed before commit.
- No production/Green service, real message, Email flag, Postmark/webhook setting, schema or nominal RBAC was changed.
- The current model has no Email follower/accompaniment relation. Per the approved decision, `Minhas` therefore means only conversations assigned to the signed-in user.

## Validation results

- Focused Email suite: `50 passed`.
- Canonical CI test selection: `237 passed`.
- Integral differential: base `44 failed / 924 passed`; candidate `44 failed / 927 passed`. The same 44 pre-existing failures remain and the candidate adds three passing regressions, with zero additional failures.
- Compile/import, canonical Ruff selection, frozen architecture baseline and Alembic graph (`fff6ab1c2d3e`) passed.
- Independent review initially found two P1 issues (group truncation/counts and trigger preservation). Both were corrected; renewed review result: zero P0/P1.
- A local PostgreSQL migration cycle could not authenticate to the host's existing PostgreSQL service with the CI-only credentials. This diff has no migration; the published CI PostgreSQL service remains the authoritative upgrade/downgrade/upgrade gate.
