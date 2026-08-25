# Green Gestão Documental — evidence

- Runtime deploy: `aab4625c06fb4c43167e26d3996d69593ca246e1`
- Functional PR: #49; mobile correction PR: #50
- Asset: `visual-v2.css?v=20260825-documents2`
- Blue: untouched

## Viewports

- `document-workbench-1440x900.png`: desktop, full three-pane workbench.
- `document-preview-tablet-1024x768.png`: tablet portrait, URL-backed preview view.
- `document-validation-mobile-390x844.png`: mobile, URL-backed validation view.

## Measurements

- Desktop: body `1425/1425`, main `1217px`, workbench `1169px`, panes `281/518/351px`.
- Tablet: body `1009/1009`; only preview pane visible for `view=preview`.
- Mobile: body `375/375`, main `375px`, context `343px`; only review pane visible for `view=validation`; action targets `44px`.

## Gate

| Criterion | Result |
| --- | --- |
| Queue + preview + OCR/matching + association/audit | PASS |
| Real preview/detail/decision routes preserved | PASS |
| Server-side selected document allowlist | PASS |
| Filters and pagination preserve context | PASS |
| Tablet/mobile distinct URL-backed views | PASS |
| ReturnContext/scroll restoration, 8h | PASS |
| Feature flag OFF legacy fallback | PASS |
| No global overflow at 1440/1024/390 | PASS |
| Frozen architecture baseline | PASS |
| Focused tests | PASS — 70 |
| Independent review | PASS |

Residual: the iframe preview depends on the browser's native rendering for the selected file type; the original file remains available through the explicit link.
