# Matriz factual das superfícies v2-clean

Base: `integration/modular-architecture@5a5ff8ac7a0b946962cb7bd8334a368d5b730078`  
Inventário: `scripts/check_visual_surface_inventory.py` — 52/52 rotas estáticas canónicas.  
Shell: **PASS transversal em todas as 52 rotas** (asset, sidebar, topbar e composição de navegação). A coluna `Conteúdo` não herda esse PASS: descreve apenas a reconstrução da superfície funcional.

| # | Rota | Shell | Conteúdo | Evidência / próxima tranche |
|---:|---|---|---|---|
| 1 | `/v2-clean` | PASS | reconstruído/aprovado | Dashboard aprovado |
| 2 | `/v2-clean/admin` | PASS | reconstruído pendente de captura | Parceiros/Admin runtime PASS |
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
| 19 | `/v2-clean/documentation/by-vehicle` | PASS | parcial | Prioridade Documentação por viatura |
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
| 37 | `/v2-clean/processes` | PASS | legado | **Tranche ativa: Centro de Processos** |
| 38 | `/v2-clean/stock` | PASS | parcial | Stock/Compras tranche seguinte |
| 39 | `/v2-clean/stock/articles` | PASS | parcial | Stock/Compras tranche seguinte |
| 40 | `/v2-clean/stock/current` | PASS | legado | Stock/Compras tranche seguinte |
| 41 | `/v2-clean/stock/inventory` | PASS | parcial | Stock/Compras tranche seguinte |
| 42 | `/v2-clean/stock/invoices` | PASS | parcial | Stock/Compras tranche seguinte |
| 43 | `/v2-clean/stock/movements` | PASS | parcial | Stock/Compras tranche seguinte |
| 44 | `/v2-clean/stock/orders` | PASS | parcial | Stock/Compras tranche seguinte |
| 45 | `/v2-clean/stock/receipts` | PASS | parcial | Stock/Compras tranche seguinte |
| 46 | `/v2-clean/stock/suppliers` | PASS | parcial | Stock/Compras tranche seguinte |
| 47 | `/v2-clean/stock/workshop-requests` | PASS | parcial | Stock/Compras tranche seguinte |
| 48 | `/v2-clean/suppliers` | PASS | reconstruído pendente de captura | Parceiros runtime PASS |
| 49 | `/v2-clean/tasks` | PASS | reconstruído/aprovado | Service Desk aprovado |
| 50 | `/v2-clean/tasks/recurring` | PASS | parcial | Service Desk residual |
| 51 | `/v2-clean/workshop` | PASS | reconstruído/aprovado | Oficina aprovada |
| 52 | `/v2-clean/workshop-entry` | PASS | reconstruído/aprovado | Oficina aprovada |

## Tranches residuais fechadas

1. **Centro de Processos (ativa):** `/v2-clean/processes`; substituir o catálogo preparatório por comando operacional, filtros, filas, estados, prioridades, responsáveis, detalhe/retorno e estados vazios/sem permissão.
2. **Stock e Compras:** resumo, artigos/existências, movimentos, pedidos Oficina, encomendas, receções, inventário, conferência e fornecedores; preservar ativação independente sob Oficina.
3. **Documentação por viatura e residual:** por viatura, diagnósticos, arquivo, importações/faturas, modelos de extração, planos financeiros, criação e validação OCR.
4. **Administração residual:** operações, organização, definições, segurança, auditoria, evolução, integrações e modelos Oficina.
5. **Resíduos Vendas/Frota/Service Desk:** acesso a vendas, auditoria financeira, recorrências; fechar captura visual pendente sem repetir loops da plataforma.

## Regra de fecho

Uma rota só muda para `reconstruído/aprovado` após testes funcionais/RBAC/estados, regressão transversal 52/52, revisão independente, CI, deploy Green, smoke autenticado e evidência responsive. A presença da shell nunca altera por si só a classificação do conteúdo.
