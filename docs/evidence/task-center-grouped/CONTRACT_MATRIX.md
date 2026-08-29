# Centro de Tarefas agrupado/casos — matriz contrato→prova

## Referência e base

- Standalone SHA-256: `76C518085A6A7BC4A266D81D2F3D38942B65B01226E67633A9E4AB6CB2E46D94`.
- Fragmento SHA-256: `BD9BC6A3975947DAAA427EB763A627FEAE8E488F9354A095B5AA3FBC01B3A4D6`.
- Base canonical: `7aadc5a49e8be0bc21ef03e1334cb9bb49f1b9b4`.
- Branch isolada: `codex/task-center-grouped-cases`.

| Contrato | Implementação | Prova |
|---|---|---|
| `TaskCase` separado; caso não conta | `task_cases` e `Task.case_id` anulável | `test_case_is_not_a_task_and_state_is_calculated` |
| Um nível | Caso não possui `parent_case_id`; associação única em `Task` | `test_three_atomic_case_flows_and_one_level_rule` |
| Três fluxos manuais | Serviço transacional e três endpoints web | teste acima + `test_grouped_web_flow_preserves_filters_and_exposes_preview` + browser local PostgreSQL: três fluxos PASS |
| Atomicidade | Savepoint, rollback e lock pessimista com refresh da identity map | `test_failed_related_flow_rolls_back_new_task`; revisão independente |
| `cases.*` sem grants | Migration cataloga read/create/update sem `role_permissions` | `test_migration_is_additive_and_downgrade_fails_closed` |
| Downgrade não destrutivo | Bloqueia se houver casos/grants; retém permissões de origem incerta | teste estático da migration |
| Categoria/caso/lista | Modos persistidos em GET; filtros aplicados antes do aggregate | `test_grouped_web_flow_preserves_filters_and_exposes_preview` |
| Contagem/estado corretos além da página | Aggregates SQL sobre todos os filhos autorizados e filtrados | `test_group_summary_counts_all_filtered_children_across_pages` |
| Preview na linha | Filhos agrupados selecionam o workbench existente | teste web agrupado |
| Linha operacional completa | referência, prioridade, assunto, categoria, criação, responsável, prazo e estado | teste web agrupado |
| Scope/Administração | Caso só é mutável através de filho visível; create/update do workspace verificados | `test_add_to_case_fails_closed_outside_task_scope`; revisão independente |
| ReturnContext | Query e fragmento preservados; flags inseridas antes de `#` | teste web agrupado |
| Estado do caso calculado | completed/overdue/support_requested/at_risk/active derivados dos filhos | `test_calculated_case_state_uses_worst_child_condition` |
| Auditoria | `TaskHistory(case_id)` e `AuditLog(task_case.*)` | teste de contagem/auditoria |
| Feature flag OFF | `task_cases_enabled=False` por defeito; UI/endpoints fechados | `test_feature_flag_off_hides_surface_and_blocks_endpoint` |
| Permissões UI alinhadas | create e update separados | `test_case_surface_separates_create_and_update_capabilities` |
| Performance | índices em `tasks.case_id`, workspace/queue; aggregates SQL, sem N+1 por grupo | migration + revisão de query |

## Gates executados

- Testes novos: 11 PASS.
- Regressão focada Centro de Tarefas: 70 PASS.
- Lista exata do CI após todas as correções: 168 PASS em 102,25 s.
- Compilação/import: PASS.
- Baseline arquitetural: PASS.
- Alembic graph: uma head, `fff6ab1c2d3e`.
- PostgreSQL 17 isolado: upgrade vazio→head, downgrade `fff6ab1c2d3e`→`fff59a0b1c2d`, upgrade→head e `current --check-heads`: PASS. O primeiro upgrade identificou uma ambiguidade de parâmetro PostgreSQL no seed de permissões; a transação reverteu integralmente, a migration foi corrigida para `SELECT`/`INSERT` separados e o ciclo completo passou.
- Bootstrap da instalação sintética: PASS.
- Browser real local, apenas com dados sintéticos e feature flags locais: três fluxos completos PASS; agrupamento/preview/workbench PASS; seleção por teclado com `Enter` PASS; foco inicial e sequência `Tab` no modal PASS.
- Geometria 1440×731: viewport `1440×731`, documento `1440×731`, main `1232×731` após sidebar, zero overflow horizontal. Evidência: `screenshots/live-1440x731.png` e `screenshots/grouped-workbench-1440x731.png`.
- Responsivo 390×844 no modo `case`: documento `390×844`, zero overflow horizontal. Evidência: `screenshots/live-responsive-390x844.png`.
- Revisão independente após três ciclos de correção: zero P0/P1.
- `git diff --check`: PASS.

## Observações e gates restantes

- A tentativa de abrir diretamente o `file://` do protótipo no browser foi bloqueada pela política de segurança do browser; não foi contornada. A comparação contratual usa os hashes congelados, inspeção integral do HTML, matriz elemento→teste e screenshots Live nas dimensões exatas. Esta limitação de captura da referência está documentada, sem divergência funcional conhecida.
- Regressão `pytest` integral: o primeiro erro reproduzido é preexistente e alheio a esta tranche (`test_admin_evolution_email_batch.py`, expectativa de texto com mojibake). A lista exata de CI e a regressão focada passam.
- Restam repetir a lista exata de CI após a correção PostgreSQL, atualizar/commitar esta evidência, confirmar ausência de drift da base e abrir o PR. O CI remoto só começa depois do PR.

## Segurança e fora de âmbito

- Feature flag permanece OFF.
- Sem Green, deploy, merge, Email, RBAC nominal ou dados reais.
- A migration é apenas aditiva e foi exercitada somente numa base PostgreSQL sintética local descartável.
