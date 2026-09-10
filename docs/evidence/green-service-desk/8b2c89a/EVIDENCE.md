# Green Service Desk — evidence

- Green deploy: `8b2c89a786ed6358449d339f7e139db153637b86`
- Service: `srv-da5dk9bm8hqs73camds0`
- URL: `https://carfast-green.onrender.com/v2-clean/tasks`
- Asset contract: `visual-v2.css?v=20260825-service-desk2` and `visual-v2.js?v=20260825-service-desk2`
- PRs: #38 (tranche) and #39 (focus-return correction)
- CI: 1/1 PASS on both PRs
- Focused tests: 39 PASS
- Independent review: PASS

## Screenshots

- `service-desk-desktop-1440x900.png`
- `service-desk-tablet-768x1024.png`
- `service-desk-mobile-390x844.png`
- `service-desk-desktop-drawer-1440x900.png`

All screenshots are authenticated, unmasked viewport captures of the deployed Green application.

## Acceptance matrix

| Criterion | Result | Direct evidence |
| --- | --- | --- |
| Approved shell preserved | PASS | CarFast shell and navigation unchanged; only cache key updated |
| Material Service Desk composition | PASS | New hero, 5 KPIs, queue workbench, tabs, filters, dense table and drawer |
| Real data/URLs/permissions preserved | PASS | Existing task records and guarded actions rendered; no schema or route replacement |
| Desktop 1440 | PASS | 5 KPI columns; table fits 1152/1152; no global overflow |
| Tablet 768 | PASS | 3 KPI columns; table overflow local 624/1040; no global overflow |
| Mobile 390 | PASS | 2 KPI columns; table overflow local 326/1040; 48 px controls; no global overflow |
| Filter endpoint | PASS | `?q=Campanha` returned 2 records from 11 without mutation |
| Drawer/detail | PASS | 1040 px desktop drawer; initial focus inside; Escape closes |
| Focus return | PASS | After Escape, focus returned to the originating `Abrir Campanha pendente` button |
| Guardar / Guardar e fechar | PASS | Integration tests prove stay reopens and close removes `open_task`; no real record mutated for evidence |
| Feature flag OFF | PASS | Legacy label, single Save action and markup retained |
| Blue isolation | PASS | Only Green service received manual deploys |

## Honest limitations

- Save actions were verified by integration tests rather than mutating migrated Green records for a screenshot.
- The dense table deliberately uses local horizontal scrolling on tablet/mobile; the page itself has no horizontal overflow.
- The fifth KPI occupies the first cell of the last mobile row because the approved 5-card set is retained.
