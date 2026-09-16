# Task toolbar responsive hotfix

- Candidate commit rendered locally with the repository's isolated synthetic preview fixture.
- Desktop: 1440 × 900; document width 1440; toolbar, navigation, queue chips and actions remain in the approved desktop row.
- Mobile: 373 × 844; document width 373. Toolbar bounds are 16–357 px; navigation 16–357 px; actions 16–357 px; queue chips 16–357 px.
- Browser automation fails if the document or any toolbar block exceeds the 373 px viewport.

Artifacts and exact geometry are in `browser/`; reproduction script: `scripts/task_toolbar_responsive_browser_evidence.mjs`.
