# Forward fix — autorização para adicionar tarefa ao caso

- Base canónica: `e8fa154161639d7cd8c0428fbe8d7855d5d211db`
- Branch: `codex/fix-task-case-add-authorization`
- Ambiente de browser: SQLite descartável, dados exclusivamente sintéticos, Email OFF.
- Green/Email/RBAC/schema/dados reais: sem mutações.

## Causa e correção

O `task_visibility_filter()` devolve `None` para utilizadores sem restrição adicional.
O POST anterior adicionava esse valor diretamente ao `WHERE`, gerando `AND NULL` e
recusando um caso que a listagem apresentava corretamente. A superfície também
usava apenas `cases.update`, sem as restantes verificações do POST.

O forward fix introduz `_resolve_case_add_task_access()` como resolver único da
visibilidade da ação e do POST. O resolver exige flag, utilizador ativo,
`cases.update`, fila canónica gravável, criação no workspace real do exemplar,
scope hierárquico quando classificado, caso e tarefa visíveis e caso ativo. O
serviço revalida o estado sob lock imediatamente antes da escrita. Fila
desconhecida, caso vazio/concluído/inexistente ou
scope forjado falham fechados. `None` deixa de ser introduzido no SQL.

## Matriz contrato → prova

| Contrato | Prova |
| --- | --- |
| Utilizador autorizado adiciona tarefa | `test_add_to_case_surface_and_post_share_positive_capability` |
| UI e POST usam o mesmo resolver | condição `group.can_add_task`; teste estrutural conta as utilizações do resolver |
| Fora de scope falha fechado | `test_add_to_case_fails_closed_outside_task_scope` |
| Caso concluído/inexistente e título vazio falham fechados | `test_add_to_case_hides_and_blocks_completed_missing_and_blank_cases` |
| Administração exige grant direto; operação continua autorizada | `test_add_to_administration_case_requires_explicit_queue_write_grant` e matriz de filas |
| ReturnContext preservado | teste positivo e browser validam query, agrupamento e fragmento |
| Contagem e auditoria | teste positivo valida 1→2 e `task_case.task_added`; browser valida 2→3 |
| Desktop/mobile, foco, erros e overflow do documento | `browser/result.json` e capturas 1440×731 / 390×844 |

## Resultados locais

- Focados casos + filas: `26 passed`.
- Suite integral candidato: `44 failed, 839 passed`; base congelada do PR #101:
  `44 failed, 833 passed`. Diferença: seis novos testes PASS, zero novas falhas.
- Compileall: PASS.
- Alembic head: `fff6ab1c2d3e`.
- Ruff exato do CI: PASS; Ruff do ficheiro de testes alterado: PASS.
- Baseline arquitetural regenerada e `--check`: PASS.
- Browser: PASS; 1440×731 `bodyWidth=1440`, 390×844 `bodyWidth=390`, zero
  overflow não contido e zero page errors. A base descartável foi removida após
  a execução.
- PostgreSQL local: serviço em `127.0.0.1:5432` não aceita as credenciais padrão do
  devcontainer; validação PostgreSQL fica no job CI isolado antes de o draft poder
  avançar.

As 44 falhas integrais são a mesma dívida canónica já classificada no PR #101;
nenhuma está nos testes alterados ou nas superfícies deste forward fix.
