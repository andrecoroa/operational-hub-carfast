# Matriz factual das superfícies v2-clean

Base: `integration/modular-architecture@46166d8713bcff8222c7f954fa36ae1b0f6f18cc`

Inventário: `scripts/check_visual_surface_inventory.py` — 53/53 rotas estáticas canónicas, incluindo o novo assistente `/v2-clean/admin/setup`.
Shell: **PASS transversal em todas as 53 rotas** (asset, sidebar, topbar e composição de navegação). A coluna `Conteúdo` não herda esse PASS: descreve apenas a reconstrução da superfície funcional.

| # | Rota | Shell | Conteúdo | Evidência / próxima tranche |
|---:|---|---|---|---|
| 1 | `/v2-clean` | PASS | reconstruído/aprovado | Dashboard aprovado |
| 2 | `/v2-clean/admin` | PASS | reconstruído pendente de captura | Parceiros/Admin runtime PASS |
| 2A | `/v2-clean/admin/setup` | PASS | reconstruído/aprovado | Green 46166d87; 9/9, RBAC e responsive PASS |
| 3 | `/v2-clean/admin/audit` | PASS | parcial | Administração residual |
| 4 | `/v2-clean/admin/evolution` | PASS | parcial | Administração residual |
| 5 | `/v2-clean/admin/integrations` | PASS | parcial | Administração residual; efeitos externos OFF |
| 6 | `/v2-clean/admin/operations` | PASS | parcial | Administração residual |
| 7 | `/v2-clean/admin/organization` | PASS | parcial | Administração residual |
| 8 | `/v2-clean/admin/overview` | PASS | reconstruído pendente de captura | Parceiros/Admin runtime PASS |
| 9 | `/v2-clean/admin/roles` | PASS | reconstruído pendente de captura | Perfis/RBAC runtime PASS |
| 10 | `/v2-clean/admin/security` | PASS | parcial | Administração residual |
| 11 | `/v2-clean/admin/settings` | PASS | parcial | Administração residual |
| 12 | `/v2-clean/admin/suppliers` | PASS | reconstruído pendente de captura | Tipos/subtipos/modelos runtime PASS |
| 13 | `/v2-clean/admin/users` | PASS | reconstruído pendente de captura | Utilizadores runtime PASS |
| 14 | `/v2-clean/admin/work-classification` | PASS | reconstruído pendente de captura | Categorias/parametrização/Email runtime PASS |
| 15 | `/v2-clean/admin/workshop-models` | PASS | parcial | Oficina/Configuração residual |
| 16 | `/v2-clean/diagnostics` | PASS | parcial | Documentação por viatura/diagnósticos |
| 17 | `/v2-clean/documentation` | PASS | reconstruído/aprovado | Workbench documental aprovado |
| 18 | `/v2-clean/documentation/archive` | PASS | parcial | Documentação residual |
| 19 | `/v2-clean/documentation/by-vehicle` | PASS | reconstruído/aprovado | Runtime Green 8226c6e1 PASS |
| 20 | `/v2-clean/documentation/extraction-models` | PASS | parcial | Documentação residual |
| 21 | `/v2-clean/documentation/financial-plans` | PASS | legado | Documentação residual |
| 22 | `/v2-clean/documentation/imports` | PASS | parcial | Documentação residual |
| 23 | `/v2-clean/documentation/invoices` | PASS | parcial | Documentação residual |
| 24 | `/v2-clean/documentation/treatment` | PASS | reconstruído/aprovado | Workbench documental aprovado |
| 25 | `/v2-clean/documentation/triage` | PASS | reconstruído/aprovado | Workbench documental aprovado |
| 26 | `/v2-clean/documents` | PASS | parcial | Documentação residual |
| 27 | `/v2-clean/documents/new` | PASS | legado | Documentação residual |
| 28 | `/v2-clean/documents/ocr-validation` | PASS | parcial | OCR/matching aprovado no workbench; rota residual |
| 29 | `/v2-clean/email` | PASS | reconstruído/aprovado | Email aprovado |
| 30 | `/v2-clean/fleet` | PASS | reconstruído/aprovado | Frota aprovada |
| 31 | `/v2-clean/fleet/financial-audit` | PASS | parcial | Frota residual |
| 32 | `/v2-clean/fleet/sales` | PASS | reconstruído/aprovado | Pipeline aprovado |
| 33 | `/v2-clean/fleet/sales-access` | PASS | parcial | Vendas residual |
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
| 50 | `/v2-clean/tasks/recurring` | PASS | parcial | Service Desk residual |
| 51 | `/v2-clean/workshop` | PASS | reconstruído/aprovado | Oficina aprovada |
| 52 | `/v2-clean/workshop-entry` | PASS | reconstruído/aprovado | Oficina aprovada |

## Superfícies ainda parcial ou legado (lista nominal fechada em 46166d87)

1. **Documentação residual (tranche final A, ativa):** `/v2-clean/diagnostics` (auditoria técnica ainda isolada), `/v2-clean/documentation/archive` (lista sem contexto transversal), `/v2-clean/documentation/extraction-models` (área técnica isolada), `/v2-clean/documentation/financial-plans` (fluxo de importação antigo), `/v2-clean/documentation/imports` (hub sem percurso unificado), `/v2-clean/documentation/invoices` (monitor compatível, mas residual), `/v2-clean/documents` (centro histórico), `/v2-clean/documents/new` (formulário com estilos locais antigos) e `/v2-clean/documents/ocr-validation` (calibração fora da navegação canónica).
2. **Administração residual (tranche final B):** `/v2-clean/admin/audit`, `/evolution`, `/integrations`, `/operations`, `/organization`, `/security`, `/settings` e `/workshop-models`; funcional, mas ainda sem composição final homogénea do assistente aprovado.
3. **Resíduos operacionais (tranche final C):** `/v2-clean/fleet/financial-audit`, `/v2-clean/fleet/sales-access` e `/v2-clean/tasks/recurring`; superfícies especializadas ainda não fechadas pelo respetivo workbench.

As superfícies reconstruídas pendentes apenas de captura não constam desta lista, porque o bloqueio é de evidência da plataforma e não de conteúdo.

## Regra de fecho

Uma rota só muda para `reconstruído/aprovado` após testes funcionais/RBAC/estados, regressão transversal 53/53, revisão independente, CI, deploy Green, smoke autenticado e evidência responsive. A presença da shell nunca altera por si só a classificação do conteúdo.
