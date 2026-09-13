# Admin table and matrix contract evidence

This evidence runs against the isolated synthetic admin preview. It covers every
administrative route and every classification view at 1440, 1024, 678 and 390
CSS pixels.

Run after starting `scripts/task_center_preview.py`:

```powershell
node scripts/admin_table_contract_browser_evidence.mjs
```

The browser check fails when a table lacks a keyboard-focusable local scroll
region, escapes the viewport, or loses its narrow-screen scroll hint and sticky
context column. Representative Roles and Email matrix screenshots plus the full
geometry report are written to `browser/`.
