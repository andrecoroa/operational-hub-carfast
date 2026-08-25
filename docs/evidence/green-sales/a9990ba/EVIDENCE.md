# Green Sales runtime evidence — a9990bae

Status: **BLOCKED (external screenshot capture tooling)**

The Sales tranche is deployed and its authenticated runtime smoke passed, but this evidence package does not claim visual acceptance. The in-app browser accepted exact viewport overrides and DOM inspection, while every native screenshot call failed with `Unable to capture screenshot` / `Page.captureScreenshot` timeout. Reinitialising the browser controller, opening a fresh tab, claiming a visible authenticated tab, and retrying viewport-only capture did not restore image capture. No synthetic, reconstructed, cropped, or resized screenshot was substituted.

## Immutable runtime

- Green deployment: `a9990baec321d84ced109c356a1536977dd387a6`
- Integration branch: `integration/modular-architecture`
- Functional source commit: `633a31a7`
- Canonical asset: `/static/css/visual-v2.css?v=20260825-convergence1`
- Browser zoom: `1` (100%)
- Device pixel ratio: `1`
- Fonts: `loaded` for every observation
- Blue: untouched

## Authenticated surfaces

| Surface | URL |
|---|---|
| Processos de venda | `/v2-clean/fleet/sales/proposals` |
| Clientes/comerciantes | `/v2-clean/fleet/sales/opportunities` |
| Publicações | `/v2-clean/fleet/sales/publications` |
| Detalhe MVP | `/v2-clean/fleet/sales/528?return_to=%2Fv2-clean%2Ffleet%2Fsales` |

## Exact viewport and overflow observations

All values below were read from the live authenticated Green DOM after `domcontentloaded`, font readiness, and a render-settle wait.

| Viewport | Surface | inner | body client/scroll | document client/scroll | Global overflow |
|---|---|---:|---:|---:|---|
| 1440x900 | Processos | 1440x900 | 1425/1425 | 1425/1425 | PASS |
| 1440x900 | Clientes | 1440x900 | 1425/1425 | 1425/1425 | PASS |
| 1440x900 | Publicações | 1440x900 | 1440/1440 | 1440/1440 | PASS |
| 1440x900 | Detalhe | 1440x900 | 1425/1425 | 1425/1425 | PASS |
| 1024x900 | Processos | 1024x900 | 1009/1009 | 1009/1009 | PASS |
| 1024x900 | Clientes | 1024x900 | 1009/1009 | 1009/1009 | PASS |
| 1024x900 | Publicações | 1024x900 | 1024/1024 | 1024/1024 | PASS |
| 1024x900 | Detalhe | 1024x900 | 1009/1009 | 1009/1009 | PASS |
| 390x844 | Processos | 390x844 | 375/375 | 375/375 | PASS |
| 390x844 | Clientes | 390x844 | 375/375 | 375/375 | PASS |
| 390x844 | Publicações | 390x844 | 375/375 | 375/375 | PASS |
| 390x844 | Detalhe | 390x844 | 375/375 | 375/375 | PASS |

The 15 px difference on pages other than Publicações is the vertical scrollbar gutter, not horizontal overflow.

## Functional evidence already passed

- 31 focused Sales tests: PASS
- 80 selected cross-module/regression tests: PASS
- 20 adversarial and contract tests: PASS
- Architecture baseline, compile and Alembic head: PASS
- Independent code review: PASS
- Authenticated Green smoke for all four surfaces: PASS
- Document authorization: same-vehicle, non-archived, explicit opt-in only
- Public snapshot: no storage paths, filenames, secrets, internal cost/debt/margin or internal notes
- Return context present on detail route
- 52-route transversal inventory/regression covered

## Capture attempts and stopping condition

Attempted, without changing application code or deployment:

1. Native in-app browser screenshot on existing authenticated tabs.
2. Browser controller reinitialisation and fresh authenticated tab.
3. Explicit viewport reset/set followed by reload.
4. Claimed user-visible authenticated tab.
5. Browser visibility capability.
6. Read-only inspection for a reusable external CDP endpoint; none was exposed.

The OS/window fallback was not used because the app pane could not prove an exact content viewport without chrome/cropping. Using it would violate the evidence requirement. The screenshot gate therefore remains blocked externally; runtime smoke and measurements are preserved without visual PASS.
