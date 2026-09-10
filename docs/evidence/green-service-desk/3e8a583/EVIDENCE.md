# Service Desk visual polish — Green

- Green deploy: `3e8a5839b8642c0fff5523bc6da8ebc182b3bf90`
- Asset: `visual-v2.css?v=20260825-service-desk4`
- Page: `https://carfast-green.onrender.com/v2-clean/tasks`
- Blue: untouched

## Audit result

| Criterion | Result | Direct evidence |
| --- | --- | --- |
| Notification label, count and explanation separated | PASS | DOM text is emitted as three distinct elements; desktop capture shows `Notificações`, badge `1`, and explanatory copy with spacing. |
| Legacy brown actions removed | PASS | `Filtrar`, `Guardar contexto`, and `Guardar e fechar` compute to `rgb(29, 94, 216)`; secondary actions compute to white. |
| Canonical role label | PASS | Visual flag renders `Coordenador de Equipa`; persisted legacy taxonomy is unchanged. |
| Drawer labels and checkbox spacing | PASS | Collaboration values use separate elements; checkbox has an explicit text span and fixed 18 px control width. |
| `Abrir` remains legible | PASS | Computed `white-space: nowrap` and `min-width: 72px` on desktop. |
| Notification/filter rhythm | PASS | Desktop screenshot shows the compact notification row, KPI strip, filters, and table as separate visual bands. |
| Responsive drawer | PASS | Desktop, tablet, and mobile captures are present; measured drawer `clientWidth === scrollWidth` at 1440, 768, and 390 widths. |

## Runtime measurements

| Viewport | Global overflow | Drawer overflow | Result |
| --- | ---: | ---: | --- |
| 1440 × 900 | `1440 / 1440` | `1038 / 1038` | PASS |
| 768 × 1024 | `753 / 753` | `734 / 734` | PASS |
| 390 × 844 | `373 / 373` | `388 / 388` | PASS |

Values are `clientWidth / scrollWidth`. No viewport has global horizontal overflow and the drawer does not conceal content horizontally.

## Screenshots

- `service-desk-desktop-1440x900.png`
- `service-desk-drawer-desktop-1440x900.png`
- `service-desk-tablet-768x1024.png`
- `service-desk-drawer-tablet-768x1024.png`
- `service-desk-mobile-390x844.png`
- `service-desk-drawer-mobile-390x844.png`

## Functional regression evidence

- 39 focused Service Desk tests passed for the deployed correction.
- PR #41 and PR #42 CI passed before merge.
- Drawer open/close, Escape focus return, focus containment, ReturnContext, filter state, canonical role presentation, and responsive overflow are covered by the focused suite.
- No schema, persisted role value, URL, permission rule, or Blue deployment was changed.

## Residual limitations

- This is the accepted Service Desk visual tranche only; Email has deliberately not started while this polish gate was open.
- The drawer remains vertically scrollable by design on tablet/mobile; its horizontal layout is fully contained.
