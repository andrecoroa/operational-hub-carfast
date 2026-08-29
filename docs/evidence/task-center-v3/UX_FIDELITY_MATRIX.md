# Centro de Tarefas v3 — matriz de fidelidade UX

Referência recongelada: `carfast-task-center-v3-proposal.html`, SHA-256
`D0AE9B2B33F6BF7C44202392A47AF1733D661E72F7428CA5C71C5AFF14678FB1`.

Base canónica da tranche: `7aadc5a49e8be0bc21ef03e1334cb9bb49f1b9b4`.

| Contrato | Live antes | Implementação desta tranche | Prova |
|---|---|---|---|
| Filtros combináveis | Estado/prazo/pesquisa; sem responsável | Responsável, prioridade e condição combináveis sem substituir vista | `test_combined_owner_and_cross_context_search` |
| Pesquisa transversal | Referência ou assunto | Referência CF, assunto/descrição, matrícula e processo | teste acima |
| Ordenação completa | Critérios parciais em select | Urgência, prazo, prioridade, estado, responsável, criação, atualização e referência; cabeçalhos reais | `test_complete_sort_contract_and_headers_are_real` |
| Tabela contextual | Assunto numa linha | Contexto secundário com relação/matrícula/origem e SLA | `test_dense_table_has_context_pagination_and_no_fake_bulk_selection` |
| Densidade/paginação | 50 por página sem controlo visível | 25/50, intervalo e navegação preservando filtros | teste acima |
| Seleção múltipla | Não existia ação bulk segura | Sem checkbox falso; seleção singular abre workbench | teste acima |
| Próxima ação | Genérica por permissão | Assumir, acompanhar suporte, resolver atraso, evitar violação, rever espera ou continuar | `test_workbench_separates_state_condition_responsibility_and_contextual_action` |
| Criação | Modal com três modelos, depois formulário | Mantida no mesmo contexto e componentes atuais | testes v3 existentes |
| Edição | Página detalhada extensa | Não unificada nesta tranche: endpoints de update atuais não partilham contrato de criação; não foi improvisado bypass | decisão técnica documentada |
| Estado/condição/responsabilidade | Misturados visualmente | Estado persistido, condição SLA, responsabilidade e próxima ação separados | teste de workbench |
| Suporte solicitado | Ação/modal | Faixa visual de acompanhamento, resumo e ação contextual; pedido duplicado continua ocultando nova solicitação | teste de workbench + testes transacionais existentes |
| Loading/vazio/erro/permissão | Cobertura parcial | Loading explícito; vazio, erro de ação e sem permissão preservados e acessíveis | `test_loading_empty_error_permission_and_responsive_contract_are_explicit` |
| 1440×731 e responsivo | Primeira dobra aprovada | Fila/workbench sem checkbox falso e breakpoints 1180/820 | **Pendente/bloqueante:** o ambiente sintético local não arrancou; ver abaixo |

## Gates executados

- SHA-256 do protótipo reconfirmado: `D0AE9B2B33F6BF7C44202392A47AF1733D661E72F7428CA5C71C5AFF14678FB1`.
- Base remota reconfirmada antes da branch: `origin/integration/modular-architecture` em `7aadc5a49e8be0bc21ef03e1334cb9bb49f1b9b4`.
- Regressão focada: 66 testes passaram.
- Lista exata de testes do CI: 163 testes passaram em 73,66 s.
- Compilação e import da aplicação: PASS.
- Grafo Alembic: uma head, `fff59a0b1c2d`.
- Baseline arquitetural: PASS. A atualização intencional ficou limitada ao inventário de ações de formulário (562→564 ações únicas; 761→764 ocorrências); redirects inalterados.
- Revisão independente: zero P0/P1 após corrigir normalização `Fechadas + Em risco`, ordenação semântica de prioridade/responsável e persistência da densidade.
- Browser real sintético: BLOCKED. A base SQLite descartável não consegue atravessar a migration legada `e4f5a6b7c8d9`, que usa alteração de constraint não suportada por SQLite; o PostgreSQL sintético necessário não está disponível neste ambiente local. Nenhum dado real foi usado. Não há screenshots/geometria desta tranche e este gate não pode ser declarado PASS nem autoriza merge/deploy.

## Divergências deliberadamente não improvisadas

- Edição integral no formulário de criação exige convergência de contratos de update e validação; não exige schema, mas merece tranche própria para não contornar regras atuais.
- Seleção múltipla permanece ausente até existir uma ação bulk segura, auditável e autorizada.
- Nenhuma alteração a Email, RBAC, schema, migrations ou backend transacional de suporte.
- A PR desta tranche é apenas para revisão/CI enquanto o gate browser real 1440×731 e responsivo não for executado num PostgreSQL sintético.
