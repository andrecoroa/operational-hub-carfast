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
| Três fluxos manuais | Serviço transacional e três endpoints web | teste acima + `test_grouped_web_flow_preserves_filters_and_exposes_preview` |
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

- Testes novos: 10 PASS.
- Regressão focada Centro de Tarefas: 70 PASS.
- Lista exata do CI após todas as correções: 167 PASS em 52,88 s.
- Compilação/import: PASS.
- Baseline arquitetural: PASS.
- Alembic graph: uma head, `fff6ab1c2d3e`.
- Revisão independente após três ciclos de correção: zero P0/P1.
- `git diff --check`: PASS.

## Gates bloqueados neste host

- PostgreSQL local: BLOCKED. O host não possui Docker, PostgreSQL nem `psql`; a ligação configurada não disponibiliza uma instância isolada. Upgrade/downgrade/upgrade real não foi declarado PASS.
- Browser sintético 1440×731/responsivo: BLOCKED pelo mesmo pré-requisito PostgreSQL. Nenhum dado real foi usado e não existem screenshots válidos desta tranche.
- Regressão `pytest` integral: o primeiro erro reproduzido é preexistente e alheio a esta tranche (`test_admin_evolution_email_batch.py`, expectativa de texto com mojibake). A lista exata de CI e a regressão focada passam.
- PR/CI remoto: não aberto. O contrato exige todos os gates locais antes do PR; PostgreSQL/browser continuam bloqueantes.

## Segurança e fora de âmbito

- Feature flag permanece OFF.
- Sem Green, deploy, merge, Email, RBAC nominal ou dados reais.
- A migration é apenas aditiva e ainda não foi aplicada fora de testes de metadata SQLite.
