# Email mobile preview focus — forward fix

## Release context

- Corrective branch base: merge `d61fd167cf31581b361fe5b7237cd0767667fd29` (PR #113).
- Green remains contained on `a491f52ce73779030873ecfab5958f98c2d290c5` after the failed mobile-focus gate and rollback.
- Safe release strategy: deploy the eventual merge containing both the PR #113 tree and this forward fix as one immutable SHA. Do not redeploy `d61fd167` alone.
- No schema, migration, Email flag, RBAC, external integration or real-data change is included.

## Cause and correction

On mobile, closing the native Email preview dialog left `is-preview-open` on the list/preview shell. The invoking `Abrir` button therefore remained hidden while focus restoration ran, so focus fell back to `body`. The fix:

1. intercepts the dialog `cancel` event and routes Escape through the existing controlled close path;
2. removes `is-preview-open` synchronously from the shell in the dialog `close` event;
3. then restores focus to the preserved invoking trigger;
4. renews the `email.js` cache key in inbox and full-thread surfaces so already-open clients receive the corrected script.

## Browser proof — isolated HTTP fixture

The browser gate used an isolated disposable SQLite database with one synthetic Email message. Inbound, outbound and external integrations were disabled. The helper, database and server were removed after the gate.

| Gate | Result |
| --- | --- |
| Mobile 390×844, Escape | Dialog closed; `is-preview-open` removed; active element was the same `Abrir` button; zero horizontal overflow |
| Mobile 390×844, visible close | Same focus restoration and zero overflow |
| Desktop 1440×731 | Preview opened and closed; focus returned to `Abrir`; ReturnContext retained; zero overflow |
| Work views and filters | `Por caixa`, `Minhas`, `Todas` and `status=triage` retained their explicit URL/view |
| Safe links | External link rendered with `_blank` and `noopener noreferrer`; active message content remained sandboxed/sanitized |

## Automated gates

- Focused Email: `50 passed`.
- Exact canonical CI test selection: `237 passed`.
- Compile/import: PASS.
- Canonical Ruff selection: PASS.
- Frozen architecture baseline: PASS.
- Alembic graph: one head, `fff6ab1c2d3e`.
- Integral differential: base tree `d61fd167` = `45 failed / 929 passed`; candidate = `45 failed / 929 passed`. Failure set unchanged; zero additional regressions.
- Independent review: zero P0/P1. P2 observation: source-contract assertions are complemented by the real browser gate above.

## Publication gate

This evidence supports a Draft PR only. Ready, merge and deploy require a separate explicit authorization and renewed remote CI/head/base/mergeability checks.
