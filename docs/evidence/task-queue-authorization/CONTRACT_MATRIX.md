# Task queue authorization forward fix

Base: `2fd0b26fc2d9250946d956337f0482895b4d4800`

This is an application-only forward fix. It adds no migration and remains compatible with the Green database already at `fff6ab1c2d3e`. A destructive downgrade is neither required nor supported.

| Contract | Server proof | Automated proof |
|---|---|---|
| Default is one `tasks_support` queue | `authorized_task_queue` defaults to `tasks_support` | `test_audit_alias_never_exposes_administration_queue_web_api_or_resolver`; browser `activeQueue=tasks_support` |
| Audit access does not expose Administration | Administration checks persisted direct grants, not expanded aliases | negative web/API/resolver matrix |
| Administration requires explicit `tasks.administration.read/write` | `resolve_task_queue_capabilities` | positive direct-grant matrix |
| Administration read never authorizes writes | every mutation requires `capability.can_write` | global `tasks.write` + direct administration read: GET 200, POST/PATCH 403 |
| Unknown task types fail closed | task-type allow-list resolves no implicit fallback | list/create/update with `forged`: 400 |
| Unknown/aggregate queues are never accepted | canonical queue allow-list plus existing aggregate guard | web/API 400 tests |
| Forged Administration/audit values fail closed | one resolver used by web and REST list | web/API/browser 403 tests |
| Cases remain usable in the operational queue | grouping surface stays permission/flag gated independently | 11 case tests, including all three transactional flows |
| Desktop/mobile do not overflow | real Chromium at 1440×731 and 390×844 | `browser/result.json` and screenshots |

## Focused evidence

- Combined queue authorization, cases, Task Center UI and classification regression: 34 passed.
- Browser: only `Tarefas e Suporte`; forged `administration` and legacy `audit` both 403; widths 1440/1440 and 390/390.
- Compileall: PASS.
- Alembic single head: `fff6ab1c2d3e`.
- Independent review: zero P0/P1 after two P1 findings were corrected and re-reviewed.
- Repository-wide local run: 827 passed, 45 failed. The failures are baseline-contract drift outside this patch (including tests pinning pre-`fff6ab1c2d3e` migration heads, stale visual snapshots and legacy `/tasks` session routing); the focused changed surfaces remain green. CI is the publication gate.

## Runtime safety

- No Green mutation was performed.
- `TASK_CASES_ENABLED` remains absent/OFF on Green from the prior containment.
- Email configuration was not read or changed in this corrective tranche.
