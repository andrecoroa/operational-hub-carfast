# Matriz factual das superfícies v2-clean

Base: `integration/modular-architecture@4161572a899289d27ca7636e64bf623c25c419b8`

Inventário: `scripts/check_visual_surface_inventory.py` — 54/54 rotas estáticas canónicas, incluindo o assistente `/v2-clean/admin/setup` e a biblioteca `/v2-clean/admin/task-process-models`.
Shell: **PASS transversal em todas as 54 rotas** (asset, sidebar, topbar e composição de navegação). A coluna `Conteúdo` não herda esse PASS: descreve apenas a reconstrução da superfície funcional.

| # | Rota | Shell | Conteúdo | Evidência / próxima tranche |
|---:|---|---|---|---|
| 1 | `/v2-clean` | PASS | reconstruído/aprovado | Dashboard aprovado |
| 2 | `/v2-clean/admin` | PASS | reconstruído pendente de captura | Parceiros/Admin runtime PASS |
| 2A | `/v2-clean/admin/setup` | PASS | reconstruído/aprovado | Green 46166d87; 9/9, RBAC e responsive PASS |
| 3 | `/v2-clean/admin/audit` | PASS | reconstruído/aprovado | Administração residual |
| 4 | `/v2-clean/admin/evolution` | PASS | reconstruído/aprovado | Administração residual |
| 5 | `/v2-clean/admin/integrations` | PASS | reconstruído/aprovado | Administração residual; efeitos externos OFF |
| 6 | `/v2-clean/admin/operations` | PASS | reconstruído/aprovado | Administração residual |
| 7 | `/v2-clean/admin/organization` | PASS | reconstruído/aprovado | Administração residual |
| 8 | `/v2-clean/admin/overview` | PASS | reconstruído pendente de captura | Parceiros/Admin runtime PASS |
| 9 | `/v2-clean/admin/roles` | PASS | reconstruído pendente de captura | Perfis/RBAC runtime PASS |
| 10 | `/v2-clean/admin/security` | PASS | reconstruído/aprovado | Administração residual |
| 11 | `/v2-clean/admin/settings` | PASS | reconstruído/aprovado | Administração residual |
| 12 | `/v2-clean/admin/suppliers` | PASS | reconstruído pendente de captura | Tipos/subtipos/modelos runtime PASS |
| 12A | `/v2-clean/admin/task-process-models` | PASS | reconstruído/aprovado | Tarefas-tipo e Processos-modelo versionados; Green 1db3b916 |
| 13 | `/v2-clean/admin/users` | PASS | reconstruído pendente de captura | Utilizadores runtime PASS |
| 14 | `/v2-clean/admin/work-classification` | PASS | reconstruído pendente de captura | Categorias/parametrização/Email runtime PASS |
| 15 | `/v2-clean/admin/workshop-models` | PASS | reconstruído/aprovado | Oficina/Configuração residual |
| 16 | `/v2-clean/diagnostics` | PASS | reconstruído/aprovado | Documentação residual Green 84204d61 |
| 17 | `/v2-clean/documentation` | PASS | reconstruído/aprovado | Workbench documental aprovado |
| 18 | `/v2-clean/documentation/archive` | PASS | reconstruído/aprovado | Documentação residual Green 84204d61 |
| 19 | `/v2-clean/documentation/by-vehicle` | PASS | reconstruído/aprovado | Runtime Green 8226c6e1 PASS |
| 20 | `/v2-clean/documentation/extraction-models` | PASS | reconstruído/aprovado | Documentação residual Green 84204d61 |
| 21 | `/v2-clean/documentation/financial-plans` | PASS | reconstruído/aprovado | Documentação residual Green 84204d61 |
| 22 | `/v2-clean/documentation/imports` | PASS | reconstruído/aprovado | Documentação residual Green 84204d61 |
| 23 | `/v2-clean/documentation/invoices` | PASS | reconstruído/aprovado | Documentação residual Green 84204d61 |
| 24 | `/v2-clean/documentation/treatment` | PASS | reconstruído/aprovado | Workbench documental aprovado |
| 25 | `/v2-clean/documentation/triage` | PASS | reconstruído/aprovado | Workbench documental aprovado |
| 26 | `/v2-clean/documents` | PASS | reconstruído/aprovado | Documentação residual Green 84204d61 |
| 27 | `/v2-clean/documents/new` | PASS | reconstruído/aprovado | Documentação residual Green 84204d61 |
| 28 | `/v2-clean/documents/ocr-validation` | PASS | reconstruído/aprovado | Documentação residual Green 84204d61 |
| 29 | `/v2-clean/email` | PASS | reconstruído/aprovado | Email aprovado |
| 30 | `/v2-clean/fleet` | PASS | reconstruído/aprovado | Frota aprovada |
| 31 | `/v2-clean/fleet/financial-audit` | PASS | reconstruído/aprovado | Green 4161572a; runtime, ReturnContext e responsive PASS |
| 32 | `/v2-clean/fleet/sales` | PASS | reconstruído/aprovado | Pipeline aprovado |
| 33 | `/v2-clean/fleet/sales-access` | PASS | reconstruído/aprovado | Green 4161572a; runtime, RBAC e responsive PASS |
| 34 | `/v2-clean/fleet/sales/opportunities` | PASS | reconstruído pendente de captura | Runtime funcional PASS |
| 35 | `/v2-clean/fleet/sales/proposals` | PASS | reconstruído pendente de captura | Runtime funcional PASS |
| 36 | `/v2-clean/fleet/sales/publications` | PASS | reconstruído pendente de captura | Runtime funcional PASS |
| 37 | `/v2-clean/processes` | PASS | reconstruído/aprovado | Centro de Processos runtime PASS |
| 38 | `/v2-clean/stock` | PASS | reconstruído pendente de captura | Stock/Compras runtime PASS |
| 39 | `/v2-clean/stock/articles` | PASS | reconstruído pendente de captura | Stock/Compras runtime PASS |
| 40 | `/v2-clean/stock/current` | PASS | reconstruído pendente de captura | Stock/Compras runtime PASS |
| 41 | `/v2-clean/stock/inventory` | PASS | reconstruído pendente de captura | Stock/Compras runtime PASS |
| 42 | `/v2-clean/stock/invoices` | PASS | reconstruído pendente de captura | Stock/Compras runtime PASS |
| 43 | `/v2-clean/stock/movements` | PASS | reconstruído pendente de captura | Stock/Compras runtime PASS |
| 44 | `/v2-clean/stock/orders` | PASS | reconstruído pendente de captura | Stock/Compras runtime PASS |
| 45 | `/v2-clean/stock/receipts` | PASS | reconstruído pendente de captura | Stock/Compras runtime PASS |
| 46 | `/v2-clean/stock/suppliers` | PASS | reconstruído pendente de captura | Stock/Compras runtime PASS |
| 47 | `/v2-clean/stock/workshop-requests` | PASS | reconstruído pendente de captura | Stock/Compras runtime PASS |
| 48 | `/v2-clean/suppliers` | PASS | reconstruído pendente de captura | Parceiros runtime PASS |
| 49 | `/v2-clean/tasks` | PASS | reconstruído/aprovado | Service Desk aprovado |
| 50 | `/v2-clean/tasks/recurring` | PASS | reconstruído/aprovado | Green 4161572a; modal, teclado e responsive PASS |
| 51 | `/v2-clean/workshop` | PASS | reconstruído/aprovado | Oficina aprovada |
| 52 | `/v2-clean/workshop-entry` | PASS | reconstruído/aprovado | Oficina aprovada |

## Superfícies ainda parcial ou legado

Não existem superfícies classificadas como `parcial` ou `legado` após o fecho runtime da tranche final no Green `4161572a`.

As superfícies reconstruídas pendentes apenas de captura não constam desta lista, porque o bloqueio é de evidência da plataforma e não de conteúdo.

## Regra de fecho

Uma rota só muda para `reconstruído/aprovado` após testes funcionais/RBAC/estados, regressão transversal 53/53, revisão independente, CI, deploy Green, smoke autenticado e evidência responsive. A presença da shell nunca altera por si só a classificação do conteúdo.
