# Centro de Tarefas — correção local de agrupamento e preview

Data: 2026-08-30

Branch: `codex/fix-task-grouping-preview`

Base canónica congelada: `origin/integration/modular-architecture@5e2b7a64ecfd37aa2e1b3f57a9e4ddc3cd0c4170`

Referência cloud indisponível no remoto: `273d42d398ef3141c2ca2ccc8b88207b3fb4501e`

## Contrato congelado

- Proposta agrupada standalone SHA256: `76C518085A6A7BC4A266D81D2F3D38942B65B01226E67633A9E4AB6CB2E46D94`.
- Proposta v3 SHA256: `D0AE9B2B33F6BF7C44202392A47AF1733D661E72F7428CA5C71C5AFF14678FB1`.

## Matriz contrato → implementação → prova

| Contrato | Implementação | Prova |
|---|---|---|
| `grouping=category` sem HTTP 500 | `work_category_labels` obtido da hierarquia canónica antes da construção dos grupos | `tests/test_task_cases.py`; browser local autenticado, resposta 200 |
| Preview exclusivamente abaixo da linha/grupo | workbench único é montado após `tr` ou botão de grupo; workspace de uma coluna | testes estruturais; desktop e mobile sem overflow |
| Por casos só contém `TaskCase` persistidos | filtro `Task.case_id IS NOT NULL` aplicado antes de count/paginação; grupos sem fallback sintético | testes web/API de casos e browser com duas tarefas de caso; tarefa simples ausente |
| Tarefa simples fora de Por casos | vista vazia explica exclusão; ação criar/converter separada em disclosure secundário | testes de contagem/caso e captura desktop |
| ReturnContext e paginação preservados | query/contexto reaplicados nas ações e navegação; paginação usa total já filtrado | regressão focada e testes estruturais |
| Quatro ações primárias | abrir, alterar estado, comentar e solicitar suporte; criar caso é secundária | inspeção do DOM e teste contratual |
| Suporte autorizado, sem equipas inativas | alvos derivados do resolver server-side; tarefas sem `update` recebem lista vazia antes de qualquer cálculo | teste negativo de leakage; revisão independente |

## Browser sintético

- Desktop `1440×731`: Lista, Por categoria e Por casos; preview inline com intervalo de 1 px; overflow horizontal zero.
- Mobile `390×844`: largura útil 358 px; grupo 356 px; preview 354 px; quatro ações dentro do viewport; overflow zero.
- Teclado: Enter seleciona grupo/tarefa; setas mudam separador; foco e `aria-selected` verificados.
- Dados: fixtures locais identificáveis; nenhum dado real.

Capturas:

- `after-desktop-category-1440x731.png`
- `after-mobile-case-390x844.png`
- `contract-prototype-1440x731.png`

## Gates locais

- Focados Centro de Tarefas/casos: **41 PASS**.
- Revisão independente renovada: **zero P0/P1**; regressão do revisor **21 PASS**.
- `compileall`: **PASS**.
- Ruff exato do workflow: **PASS**.
- Baseline de arquitetura: **PASS**.
- Alembic: head único `fff6ab1c2d3e`.
- PostgreSQL local: upgrade → downgrade para `ffae1f2a3b4c` → upgrade: **PASS**, terminou em `fff6ab1c2d3e`.
- Bootstrap e instalação limpa: **PASS**, 17 tabelas.
- Suite integral exata: **FAIL — 45 falhas, 832 passes**. As falhas observadas são fora do diff desta tranche e incluem expectativas antigas de Alembic, Admin, Email, Frota, Documentação e Oficina. Não foram alteradas nem ocultadas.

## Gate e contenção

O código não foi publicado como PR pronto porque a autorização exige CI integral verde. Corrigir as 45 falhas transversais ampliaria indevidamente o âmbito. Green, Email, RBAC, schema e dados reais permaneceram intocados; não houve merge nem deploy.

## Matriz causal das 45 falhas observadas no candidato inicial

A mesma suite foi executada no worktree destacado da base congelada. Resultado da
base: **44 FAIL / 828 PASS**. Resultado inicial do candidato: **45 FAIL / 832
PASS**. Logo, 44 falhas são anteriores ao diff e uma era uma expectativa de teste
desatualizada pelo cache-busting do próprio candidato. Nenhuma regressão funcional
do Centro de Tarefas foi encontrada.

| # | Teste / grupo | Classificação | Prova factual / decisão |
|---:|---|---|---|
| 1 | `test_ui_contract_v1::test_contract_asset_is_global_for_foundation_surfaces` | contrato de teste desatualizado pelo candidato | O HTML canónico referencia `20260830-task-center-inline-v3`; expectativa antiga `20260829-task-center-v5` corrigida. |
| 2 | `admin_evolution_email_batch::test_evolution_and_module_navigation_are_compact_and_compatible` | contrato visual preexistente desatualizado | Reproduz na base; composição Admin atual já não contém o marcador legado. Não alterado nesta tranche. |
| 3 | `admin_evolution_email_batch::test_admin_is_grouped_by_domains_with_central_operations_area` | contrato visual preexistente desatualizado | Reproduz na base; procura marcador da composição Admin anterior. |
| 4 | `admin_evolution_email_batch::test_evolution_creation_permission_does_not_grant_management` | contrato de segurança preexistente desatualizado | Runtime canónico falha fechado com 403; teste espera redirect 303. Não enfraquecido. |
| 5 | `admin_evolution_migration::test_admin_evolution_migration_is_the_single_head` | contrato de migration preexistente desatualizado | Teste fixa `fff26e7f8a9c`; head canónico verificado é `fff6ab1c2d3e`. |
| 6–12 | 7 parametrizações `admin_residual_closeout::test_admin_residual_routes_share_canonical_composition` | contrato visual preexistente desatualizado | Todas reproduzem na base e exigem a navegação Admin residual removida/substituída. |
| 13 | `admin_residual_closeout::test_admin_residual_navigation_has_one_current_page` | contrato visual preexistente desatualizado | Mesmo contrato residual; reproduz na base. |
| 14 | `clean_vehicle_documents::test_clean_vehicle_documents_service_choices_match_operational_vocabulary` | contrato de teste preexistente desatualizado | Vocabulário canónico contém quatro categorias adicionais; teste exige igualdade ao mapa antigo de duas. |
| 15 | `clean_vehicle_documents::test_clean_vehicle_documents_treats_cruz_allen_fs_reference_as_invoice` | dívida funcional preexistente | Classificação de invoice passa, mas o conteúdo visual esperado não é renderizado; requer decisão fora do Centro de Tarefas. |
| 16–21 | 6 testes `diagnostic_documents` | dívida funcional preexistente | Reproduzem na base em fluxos de ingestão, associação, idempotência e histórico diagnóstico; não são expectativas estáticas seguras para atualizar. |
| 22 | `document_workflow_states::test_alembic_task_recurrence_revision_is_the_only_head` | contrato de migration preexistente desatualizado | Head fixo anterior ao head canónico. |
| 23 | `email_delivery_migration::test_email_delivery_migration_is_the_single_additive_head` | contrato de migration preexistente desatualizado | Head fixo anterior ao head canónico. |
| 24 | `functional_email_mailboxes::test_approval_is_invalidated_when_message_changes` | dívida funcional preexistente | Falha comportamental de aprovação Email; Email está explicitamente fora do âmbito. |
| 25 | `green_partners_admin_visual::test_admin_context_selects_roles_categories_and_email` | contrato visual preexistente desatualizado | Reproduz na base após convergência da superfície Admin. |
| 26 | `html_surface_inventory::test_all_html_surfaces_are_classified_and_inventory_is_current` | contrato/inventário preexistente desatualizado | Inventário congelado não acompanha superfícies canónicas atuais. |
| 27 | `photo_capture_action::test_photo_migration_is_the_single_alembic_head` | contrato de migration preexistente desatualizado | Head fixo anterior ao head canónico. |
| 28–32 | 5 testes `service_desk_api_security` | dívida RBAC/API preexistente conhecida | Reproduzem integralmente na base; autorização proibiu misturar esta dívida. |
| 33 | `service_desk_migration::test_service_desk_migration_remains_on_the_single_head_chain` | contrato de migration preexistente desatualizado | Head fixo anterior ao head canónico. |
| 34 | `ui_contract_core_workspaces::test_email_uses_same_page_list_preview_contract` | contrato visual Email preexistente desatualizado | Reproduz na base; Email fora do âmbito. |
| 35 | `visual_document_workbench::test_document_workbench_rebuilds_canonical_three_pane_composition` | contrato visual preexistente desatualizado | Marcadores da composição documental anterior; reproduz na base. |
| 36–37 | 2 testes `visual_email` | contrato visual/funcional Email preexistente desatualizado | Marcadores da UI Email anterior; não alterados porque Email está fora do âmbito. |
| 38 | `visual_fleet::test_sales_is_composed_under_fleet_but_remains_independent` | contrato visual preexistente desatualizado | Procura condição Jinja removida da sidebar atual. |
| 39 | `visual_fleet::test_fleet_uses_shared_convergence_asset_version` | contrato de asset preexistente desatualizado | Espera `20260825-convergence1`; runtime canónico usa `20260826-elevation-v3`. |
| 40 | `visual_fleet::test_fleet_list_detail_documents_and_diagnostics_render_composed_surfaces` | contrato de asset preexistente desatualizado | Mesma versão de asset antiga; reproduz na base. |
| 41 | `visual_process_center::test_route_content_matrix_covers_every_canonical_surface_once` | contrato/inventário preexistente desatualizado | Falta `/v2-clean/admin/task-process-models` na matriz congelada. |
| 42 | `visual_surface_inventory::test_sidebar_has_the_canonical_global_group_order` | contrato visual preexistente desatualizado | Procura “Alertas personalizados” removido da sidebar atual. |
| 43 | `web_process_flow::test_web_task_process_creates_task_and_audit_history` | contrato de navegação preexistente desatualizado | Runtime canónico redireciona para `/v2-clean`; teste espera board legado. |
| 44 | `workshop_clean_restructure::test_material_need_records_contract_without_simulating_stock` | contrato funcional preexistente ambíguo | Runtime guarda `requested`; teste espera `unavailable`. Sem fonte contratual desta tranche, não foi reescrito. |
| 45 | `workshop_training_flow::test_complete_workshop_training_flow` | dívida funcional preexistente | Processo legado não é criado; reproduz na base e exige correção de Oficina fora do âmbito. |

Resumo causal: **0 regressões funcionais deste diff; 1 expectativa causada pelo
cache-busting do candidato e corrigida; 28 expectativas/contratos preexistentes
desatualizados; 15 falhas de dívida funcional preexistente; 1 contrato funcional
preexistente ambíguo**. As expectativas preexistentes não foram mecanicamente
reescritas porque isso criaria uma tranche transversal sem as respetivas fontes de
aceitação. A dívida real não foi ocultada com `xfail`, exclusões ou mudanças de
produto.
