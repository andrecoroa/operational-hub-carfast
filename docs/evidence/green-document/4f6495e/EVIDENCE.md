# Green Gestão Documental — final visual evidence

- Runtime: `4f6495e9e4ca820ef0ce939e840a794348ab237b`
- Asset: `visual-v2.css?v=20260825-documents3`
- CI: PASS; independent structural review: PASS
- Blue: untouched

## Captures and observed values

- `document-workbench-1440x900.png`: body `1425/1425`; filter button canonical blue `rgb(29, 94, 216)`.
- `document-preview-tablet-1024x768.png`: body `1009/1009`; URL-backed preview view.
- `document-validation-mobile-390x844.png`: body `375/375`; context `341/341`; received date fully visible (`10/08/2026`); both navigation rows report `scrollbar-width: none`; local first-nav scroll `419/343`; filter button canonical blue.

## Final audit matrix

| Criterion | Result |
| --- | --- |
| Desktop three-pane workbench | PASS |
| Real preview and OCR/decision composition | PASS |
| Tablet distinct view without global overflow | PASS |
| Mobile navigation accessible without visible scrollbar | PASS |
| Mobile context grid without clipped date | PASS |
| Canonical blue filter hierarchy | PASS |
| Global overflow 1440/1024/390 | PASS |
| Feature flag OFF and ReturnContext 8h | PASS |
| Blue untouched | PASS |
