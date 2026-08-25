# Email main-view width audit — PASS

- Green deploy: `d59ca4e28486d2ff6d711fb951e59e89689f9fbe`
- Functional PR: #47, CI PASS
- Asset: `visual-v2.css?v=20260825-email2`
- Browser zoom: 100% (`visualViewport.scale = 1`)
- Blue: untouched

## Direct 1440 × 900 viewport measurements

| Element | X | Width | Share of useful main width | max-width | Font |
| --- | ---: | ---: | ---: | --- | --- |
| Viewport | 0 | 1440 px | — | — | — |
| `.visual-email-center` | 208 px | 1217 px | 100% | none | 14 px |
| `.visual-email-overview` | 232 px | 1169 px | 96.1% | none | 14 px |
| `.visual-email-workbench` | 232 px | 1169 px | 96.1% | none | 14 px |
| `.visual-email-table-wrap` | 233 px | 1167 px | 95.9% | none | 14 px |
| `.visual-email-table` | 233 px | 1180 px | 97.0% | none | cells 13 px / headers 11 px |

The workbench uses essentially the complete area between the 208 px sidebar and the 24 px content gutters. There is no unused right-hand region approaching the audit's 35% limit.

## Tablet and mobile

| Viewport | Main | Workbench | Table container | Global overflow |
| --- | ---: | ---: | ---: | --- |
| 768 × 1024 | 689 px | 641 px | 639 px | `753 / 753` |
| 390 × 844 | full available width | full available width | local table scroll | `375 / 375` |

Tablet therefore uses the entire useful width after its 64 px collapsed sidebar. Mobile remains the approved vertical flow.

## Evidence

- `email-viewport-desktop-1440x900.png` — direct viewport capture, not full-page and not resized.
- `email-viewport-tablet-768x1024.png` — direct viewport capture.
- `email-viewport-mobile-390x844.png` — direct viewport capture.

## Verification

- 48 focused Email, Postmark and visual regression tests: PASS.
- 13 final visual/asset contract tests: PASS.
- Preview/conversation markup and composition were not changed.
