# Task Center inline preview toggle

- Base: `67d7ec82d6df08b316709df2a5c3267003b7b313`.
- Branch: `codex/fix-task-preview-toggle`.
- Scope: preview/workbench only; no schema, RBAC, Email or data changes.

## Contract and proof

- Repeated click closes the selected preview: browser gate in Lista, Por caso and Por categoria.
- Selecting another task moves the sole preview below that task and clears the prior selection.
- The explicit close button and Escape close the preview, clear the hash and restore focus.
- Query/ReturnContext is preserved; only the `#task-*` fragment changes while open.
- Desktop and 390x844 mobile keep one preview and no uncontained horizontal overflow.
- Reproducible test: `scripts/task_preview_toggle_browser_evidence.mjs`.

## Green containment

The PR #102 deploy `dep-da9qlhe7bikc73a8ru6g` was not accepted as Live after this
finding. Synthetic fixtures were removed and the exact baseline was restored
(`270 tasks, 0 cases, 13 users, 11 roles`, zero `SMOKE-PR102` residue). Green was
contained through a configuration-preserving deploy of the previous SHA
`5e2b7a64ecfd37aa2e1b3f57a9e4ddc3cd0c4170`, deploy
`dep-da9qpgqjnfac73el3ca0`.
