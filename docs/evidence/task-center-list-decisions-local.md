# Centro de Tarefas — lista refinada e fundação de decisões (local)

## Âmbito e isolamento

- Base canónica: `2f7bb7c51004a51c7fb852af6d24d25315e4535c`.
- Branch: `codex/task-center-list-decisions`.
- Apenas execução local com fixtures sintéticas; Email inbound/outbound desligado.
- Sem push, PR, merge, deploy, Green ou dados reais.

## Matriz pedido → implementação → prova → risco

| Pedido | Implementação | Prova | Risco residual |
|---|---|---|---|
| Linhas legíveis e prioridades sem símbolos | Separação de 48 px, bordas e prioridade textual neutra/alta/urgente/baixa | Browser 1440×731 e teste de contrato | Cores são auxiliares; texto permanece sempre presente |
| Preview curto | Descrição com 4–5 linhas e scroll; factos compactos; sem painel vazio | Browser desktop/mobile, Escape e foco | Em mobile os factos empilham verticalmente |
| Cinco ações diretas | Abrir, estado, comentar, suporte e Criar caso sem disclosure | Teste de markup e regressão de casos | Ações continuam ocultas server-side/client-side por capacidade |
| Contexto recuperado | `Task.plate`, contrato, reserva, cliente, `case_id`, `process_instance_id` e `TaskEmailOrigin` | Teste de payload persistido | Sem link inferido por matrícula; contrato/reserva/cliente ficam texto porque não há FK inequívoca |
| Aguarda decisão | `TaskDecision` aditivo, estado dedicado bloqueado a transição genérica e feature flag OFF | 6 testes positivos/negativos | Requer migration e ativação explícita futura |
| Permissões separadas | `tasks.request_decision` e `tasks.resolve_decision`, excluídas de concessão automática | Negativos sem grant e decisor sem permissão | Parametrização nominal fica para gate posterior |
| Resolver decisão | Aprovar/recusar regressa a Em curso; pedir informação mantém espera; responsável preservado | Testes de estado, histórico e notificação | Não altera regras globais de SLA |
| Decisões para mim | Filtro server-side apenas para decisor com permissão | Teste de listagem e 403 implícito no resolver | Feature flag desligada por defeito |

## Auditoria das relações

Os dados não foram removidos por migration: matrícula, reserva, contrato e cliente estão em `Task`; caso e processo usam FKs; a origem de Email usa `TaskEmailOrigin`. Só há link para viatura quando `entity_type=vehicle` e `entity_id` é explícito, para processo por FK e para URL de origem já persistido com esquema HTTP(S) ou caminho interno. Não existe reconstrução heurística.

## Resultados

- Regressão inicial: 116 PASS.
- Suite focada final: 54 PASS.
- Regressão alargada: 125 PASS e 1 expectativa textual desatualizada; após alinhar o rótulo aprovado curto, o teste afetado passou.
- Compile `app` + `migrations`: PASS.
- Alembic: uma cabeça, `fffaef5a6b7c`.
- Browser sintético: desktop 1440×731 e mobile 390×844; `scrollWidth == clientWidth` no mobile; preview inline; Escape fecha e foco regressa à linha.
- Restauro do preview: a automação `task_preview_toggle_browser_evidence.mjs` cobre Lista, Por categoria e Por caso; em cada modo valida reload/hash, um único preview e montagem imediatamente sob a linha/acionador visível (nunca sob a linha de tabela oculta do agrupamento).
- Renovação pré-PR: 82 testes focados PASS; compile/import PASS; Ruff canónico PASS; baseline arquitetural regenerado apenas para a tabela aditiva e novos formulários/redirects e novamente verificado pelo check oficial.

## Migration e rollback

`fffaef5a6b7c` cria apenas `task_decisions` e índices. O downgrade remove exclusivamente essa tabela. A feature `TASK_DECISIONS_ENABLED` permanece OFF por defeito; não houve execução em Green.
