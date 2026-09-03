# Centro de Tarefas — sinais operacionais e prazo com hora

## Referência congelada

- Base remota: `integration/modular-architecture` em `260795eafa100ed80d8f27508b1c40fc580a5103`.
- Branch isolada: `codex/task-center-signals`.
- Âmbito: alerta Nova, semântica Atrasada/Em risco, hora opcional do prazo e total de comentários.
- Fora do âmbito: Email, Oficina, Processos, RBAC nominal, Green e dados reais.

## Matriz contrato → implementação → prova

| Contrato | Implementação | Prova |
|---|---|---|
| Nova não se confunde com Por assumir | Métrica `Novas`, contador `status == new` e atalho `status=new`; Por assumir mantém a regra de atribuição | `test_approved_task_center_has_five_contractual_keyboard_counters`; browser desktop/mobile confirmou contadores independentes e URL `status=new` |
| Atrasada versus Em risco | Texto explícito no UI; `task_due_condition` centraliza as duas condições | `test_timed_deadline_crosses_risk_to_overdue_at_local_time`; browser confirmou a explicação com janela de 3 dias |
| Hora opcional sem alterar datas existentes | `Task.due_time` nullable `Time`; `due_on` permanece `Date`; sem backfill | migration `fff9de4f5a6b`; `test_api_contract_accepts_optional_time_without_changing_date_only_payloads`; `test_due_time_migration_is_additive_and_has_explicit_rollback` |
| Hora tem semântica local explícita | Comparação com `ZoneInfo("Europe/Lisbon")`; UI identifica Lisboa | teste de fronteira às 10:00 e browser com `03/09/2026 23:30` |
| Guardar não altera silenciosamente a hora | Clientes que omitem o novo campo preservam a hora; o formulário real envia `due_time_present=1`, permitindo limpeza explícita | `test_clean_task_deadline_time_create_preserve_clear_and_validate` |
| Sem hora mantém comportamento de data | `due_time=NULL` não fica atrasado durante o próprio dia e continua em risco pela regra histórica | `test_timed_deadline_crosses_risk_to_overdue_at_local_time` |
| Comentários sem inventar unread | A linha/cartão mostra apenas `Comentários: N` quando N > 0; não existe alegação de novos/não lidos | `test_deadline_and_comment_signals_are_explicit_and_non_invented`; render HTTP com 2 comentários |
| Preview agrupado restaura no elemento visível | Mantido o bootstrap canónico que exige `groupButton` quando existe agrupamento e monta inline sob esse botão | regressão focada de casos/categorias incluída em 152 PASS |

## Resultados locais

- Compile: PASS.
- Ruff nos ficheiros alterados: PASS.
- Head Alembic único: PASS, `fff9de4f5a6b`.
- Contratos de migrations e compilação PostgreSQL offline: 28 PASS.
- Regressão focada Tarefas/Casos: 152 PASS.
- Browser HTTP sintético:
  - 1440×731: cinco métricas com 230 px cada; `scrollWidth == 1440`; overflow horizontal falso.
  - 390×844: cinco métricas visíveis; `scrollWidth == 375`; overflow horizontal falso.
  - atalho Nova: `status=new`, uma linha Nova; comentário total visível; data com hora e data-only renderizadas sem alteração.
- Suite integral da base: 39 FAIL / 961 PASS.
- Primeira execução do candidato, antes de atualizar cinco expectativas legítimas do novo head: 45 FAIL / 961 PASS.
- Causalidade: os 39 FAIL são idênticos à base e fora desta tranche; os cinco FAIL adicionais eram testes que fixavam o head anterior; foram atualizados e os contratos de migration passaram.

## PostgreSQL e instalação limpa

- O servidor PostgreSQL local respondeu, mas rejeitou as credenciais configuradas. Não foram procurados ou contornados segredos.
- A tentativa SQLite para migrations completas para numa migration histórica anterior (`e4f5a6b7c8d9`) porque SQLite não suporta o `ALTER CONSTRAINT` usado. Esta falha ocorre antes de `fff9de4f5a6b`.
- Alternativa segura: modelos SQLite via metadata para os testes comportamentais, SQL PostgreSQL offline para migrations, head único e CI canónico do PR para PostgreSQL real.

## Rollback

O downgrade de `fff9de4f5a6b` remove apenas `tasks.due_time`. Não existe backfill nem alteração de `due_on`. Antes de qualquer eventual downgrade futuro deve ser exportada a hora introduzida depois do upgrade, pois a remoção da coluna é destrutiva para esses valores novos.
