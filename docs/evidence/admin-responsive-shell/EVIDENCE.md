# Admin responsive shell evidence

The browser evidence uses the isolated synthetic preview from
`scripts/task_center_preview.py`; it never connects to production data.

Run:

```powershell
python scripts/task_center_preview.py
node scripts/admin_responsive_shell_browser_evidence.mjs
```

The script checks Overview, Roles and Email channels at 1440, 1024, 678 and
390 CSS pixels. It fails on page-level horizontal overflow, nested vertical
scrolling, or a master/detail layout that does not collapse at the responsive
breakpoint. Screenshots and exact geometry are written to `browser/`.
