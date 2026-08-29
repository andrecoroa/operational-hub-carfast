# Centro de Tarefas v3 — matriz contrato → prova

Contrato congelado: `carfast-task-center-v3-proposal.html`
SHA-256: `D0AE9B2B33F6BF7C44202392A47AF1733D661E72F7428CA5C71C5AFF14678FB1`

Esta matriz é o índice de aceitação da primeira tranche. Todos os dados usados nas
provas browser são sintéticos e email permanece desativado.

| Contrato | Prova server-side | Prova browser / artefacto |
|---|---|---|
| Uma fila de cada vez; `Tarefas e Suporte` por defeito; sem agregação | `test_queue_and_view_contract_rejects_aggregation_and_silent_fallback` | `runtime-evidence.json`: `queue`, `aggregationRejected` |
| Vistas Minhas / Por assumir / Da equipa persistentes e sem fallback | testes de fila/vista e incompatibilidades | percurso `viewPersistence`; screenshot `01-default-1440x731.png` |
| Presets incompatíveis impedidos | `test_incompatible_team_to_mine_and_closed_risk_filters_fail_closed` | percurso `negativeFilters` |
| Pesquisa, seleção e ReturnContext preservados | suite aprovada + suporte transacional | percurso `returnContext` |
| Ordenação explícita com critério e direção | `test_sort_contract_is_explicit_and_reflected_in_the_surface` | `runtime-evidence.json`: `sort` |
| Fila e workbench no mesmo UI, tabs e próxima ação | suite aprovada | screenshots `02-workbench-1440x731.png`, `03-tabs-1440x731.png` |
| Criação/edição partilham contrato; três modelos | suite aprovada | percurso `creationModels` |
| Estado `Suporte solicitado`, anterior, motivo, prazo e auditoria | `test_support_request_is_transactional_audited_and_preserves_return_context` | percurso `supportRequest` |
| Suporte duplicado/fora de âmbito falha fechado | `test_duplicate_and_out_of_scope_support_requests_fail_closed` | percurso `supportNegative` |
| Comentário obrigatório, auditado e sem mudança de estado | teste de comentário vazio + suite de notificações | percurso `emptyComment` |
| Loading, vazio, erro, sem permissão, espera, atraso, risco e concluído | asserts de marcadores de estado | screenshots de estados e `runtime-evidence.json` |
| Teclado, foco e zero overflow a 1440×731 | — | `keyboard`, `focus`, `geometry` em `runtime-evidence.json` |

## Comandos de reprodução

```powershell
python -m pytest -q tests/test_task_center_approved_contract.py tests/test_task_center_access_notifications.py tests/test_task_center_v3_contract.py
python scripts/task_center_preview.py
node scripts/task_center_actions_browser_evidence.mjs
```

O gate browser falha perante overflow horizontal, viewport diferente de 1440×731,
perda de foco/ReturnContext, fallback de vista, agregação, combinações incompatíveis,
suporte duplicado/fora de âmbito ou comentário vazio aceite.
