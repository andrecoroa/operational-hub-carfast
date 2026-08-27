# Front A FUR desktop — local gate evidence

- Branch: `codex/front-a-fur-desktop`
- Base: `integration/modular-architecture@1083b400`
- Viewport contract: `1440x731`, zoom 100%
- External effects: disabled; validation used synthetic SQLite only
- Remote environments: Blue and Green untouched

## Gate status

| Gate | Local evidence | Status |
|---|---|---|
| 1 Sidebar | direct canonical labels, stable scrollbar gutter, one-line ellipsis and updated inventory tests | PASS (code/tests) |
| 2 Oficina / Stock | both are direct global destinations; workshop states remain local; configuration removed from operational navigation | PASS (code/tests) |
| 3 Actions | shared 32px compact control and `nowrap`; single primary workshop action | PASS (code/tests) |
| 4 Oficina first fold | compact header, scope, filters and rows implemented | PENDING browser geometry capture |
| 5 Administration | supplier navigation removed; directory and residual navigation are mutually exclusive | PASS (code/tests) |
| 6 Email / Documentation | queue remains the initial view; explicit selection opens preview/treatment in the same page | PASS (code/tests), PENDING browser interaction capture |
| 7 Server RBAC | existing `TaskCreationCapabilityResolver` exercised by focused adversarial tests | PASS |
| 8 Transitions | existing workshop/task/document transition tests preserve separate fail-closed actions | PASS |
| 9 Effects/audit | outbound remains false and focused audit tests pass | PASS |

## Commands and results

```text
python -m pytest -q tests/test_front_a_fur_desktop_gate.py tests/test_visual_workshop.py tests/test_visual_surface_inventory.py tests/test_visual_document_workbench.py tests/test_clean_admin.py tests/test_task_process_templates.py tests/test_clean_workshop_v2_flow.py tests/test_email_triage_preview.py
76 passed, 5 third-party deprecation warnings
```

The in-app browser could not reach the synthetic localhost server through either
`127.0.0.1` or `host.docker.internal`; both attempts timed out before any page was
loaded. No screenshot was fabricated. PR/merge/deploy remain blocked until the
1440x731 geometry and interaction evidence is captured through a working browser
channel.
