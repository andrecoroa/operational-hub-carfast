# Email visual tranche — Green

- Green deploy: `cd1d733d3633caa2d059ee1b20ca6a87cbd4d350`
- Functional tranche: PR #44 (`20ff7753`), CI PASS
- Visual action polish: PR #45 (`1a41081b`), CI PASS
- Asset: `visual-v2.css?v=20260825-email1`
- URL: `https://carfast-green.onrender.com/v2-clean/email`
- Blue: untouched

## Acceptance matrix

| Criterion | Result | Evidence |
| --- | --- | --- |
| Approved shell and hierarchy | PASS | Canonical topbar/sidebar, page heading and blue primary action are rendered. |
| Mailboxes and status navigation | PASS | Scroll-safe mailbox tabs and compact status chips preserve existing filter URLs. |
| Operational priorities | PASS | Five real counters compose the priority strip and remain navigable. |
| Dense list and filters | PASS | Unified inbox workbench, seven controls and compact eight-column table use local horizontal overflow only. |
| Conversation preview and triage | PASS | Authenticated preview renders conversation and triage panels together with attachments, actions and task creation. |
| Action hierarchy | PASS | Save computes to `rgb(29, 94, 216)`, completion to `rgb(8, 122, 114)`, secondary actions remain white. |
| Keyboard and ReturnContext | PASS | Rows open with Enter/Space; closing preview restores focus to the originating trigger; full-page link carries a local allowlisted return context. |
| Permissions and external effects | PASS | Existing route/channel permission checks remain unchanged; outbound integrations remain OFF. |
| Responsive | PASS | Desktop, tablet and mobile base/preview captures present; no global or dialog horizontal overflow. |

## Runtime measurements

| Viewport | Body client/scroll | Preview client/scroll | Result |
| --- | --- | --- | --- |
| 1440 × 900 | `1425 / 1425` | `1120 / 1120` | PASS |
| 768 × 1024 | `753 / 753` | `736 / 736` | PASS |
| 390 × 844 | `375 / 375` | `390 / 390` | PASS |

All five preview footer actions measure 48 px on mobile. The wide table scrolls inside its own workbench and never widens the page.

## Screenshots

- `email-desktop-1440x900.png`
- `email-preview-desktop-1440x900.png`
- `email-tablet-768x1024.png`
- `email-preview-tablet-768x1024.png`
- `email-mobile-390x844.png`
- `email-preview-mobile-390x844.png`

## Tests

- 48 focused Email, Postmark, visual foundation and Service Desk regression tests: PASS.
- 13 final visual contract tests after action-hierarchy polish: PASS.
- Compileall and `git diff --check`: PASS.

## Honest limits

- This tranche preserves the existing Email domain behavior and data model; it does not activate outbound delivery or introduce schema changes.
- The desktop table intentionally uses local horizontal overflow below its intrinsic width; mobile exposes the approved “deslize” affordance.
