# Green Dashboard pilot — quality gate

- Canonical mockup: `carfast-sistema-visual.png`
- Green service: `srv-da5dk9bm8hqs73camds0`
- Green URL: `https://carfast-green.onrender.com/v2-clean`
- Live deploy SHA: `43314602c2ca30995f8f7f8a4cf27c70ea6287c5`
- Asset loaded: `/static/css/visual-v2.css?v=20260825-dashboard-pilot4`
- Capture: authenticated viewport, uncropped, no masking

| Evidence | Viewport | Global overflow |
| --- | ---: | ---: |
| `green-dashboard-1440x900.png` | 1440 × 900 | 0 px |
| `green-dashboard-tablet-768x1024.png` | 768 × 1024 | 0 px |
| `green-dashboard-mobile-390x844.png` | 390 × 844 | 0 px |

## Independent NO-GO closure

| Criterion | Result | Direct evidence |
| --- | --- | --- |
| CarFast identity | PASS | Same shield/wordmark system; tablet uses shield rail, mobile shows `CarFast` + `Visão geral`. |
| Icon family | PASS | Placeholder diamonds/glyphs replaced by one stroke-SVG family. |
| Sidebar footer | PASS | Auxiliary actions are transparent, compact and subordinate to navigation/status. |
| Mobile density | PASS | KPI grid computed as two columns (`166.5px 166.5px`); work begins at 632px. |
| Tablet table | PASS | Essential columns fit locally: table 639px inside card 641px; non-essential State hidden. |
| Desktop KPI density | PASS | Four KPI cards in one row, measured 108px high. |
| Topbar alert | PASS | Bell SVG with `Notificações` accessible label and tooltip. |
| Contrast | PASS | Sidebar secondary/status colors raised; no low-contrast legacy artifact remains. |
| Mobile context | PASS | Topbar exposes identity and current page together. |
| Functional evidence | PASS with stated limit | KPI link opened `/v2-clean/fleet` and returned to `/v2-clean`; drawer `aria-expanded` true→false, Escape restored focus to the menu button; KPI routes are `/fleet`, `/tasks`, `/workshop`, `/processes`; permission guards and search route are covered by focused tests. The browser-control API did not synthesize native Enter/Tab defaults, so search submission and full tab traversal are evidenced by the JS contract tests rather than claimed as an observed native-key event. |

## Validation

- Focused suite: 38 passed; subsequent responsive identity contract: 8 passed.
- Architecture baseline: matches.
- GitHub CI: PR #35 and PR #36 `fast-checks` passed.
- Independent code review: PASS after feature-gate, legacy fallback, responsive rail and 48px mobile targets were corrected.
- Feature flag OFF retains legacy markup/CSS behavior; visual markup and assets remain gated.
- Blue was not deployed or mutated.

This evidence establishes technical/visual readiness of the pilot. It does not record André's visual acceptance, which remains an explicit separate gate.
