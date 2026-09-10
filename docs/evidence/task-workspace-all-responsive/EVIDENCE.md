# Centro de Tarefas — vista Todas e filtros responsivos

## Candidato

- Base canónica: `be622c7aa568307dce9d4fe02cbceee0d60a00d9`.
- Branch: `codex/task-workspace-all-responsive`.
- Ambiente browser: HTTP local `127.0.0.1:18767`, SQLite descartável,
  Email inbound/outbound OFF e fixtures exclusivamente sintéticas.
- Sem schema, migration, RBAC nominal, Email, Green ou dados reais.

## Matriz contrato → prova

| Contrato | Implementação | Prova |
| --- | --- | --- |
| Vista `Todas` canónica | `TaskScopeView("all", "all", "all", "")`; seletor envia `task_scope_view=all`, `workspace=all`, `mine_kind=all`, sem `assignment` | `test_all_scope_uses_canonical_state_and_preserves_filters`; browser confirmou URL canónico |
| Sem ampliação de visibilidade | A query continua a aplicar `task_visibility_filter`; não agrega filas | `test_all_scope_keeps_restricted_operator_visibility_fail_closed`; operador só recebeu tarefa relacionada |
| Forgery fail-closed | Combinações não canónicas/conflictantes devolvem 400 | quatro casos em `test_all_scope_rejects_noncanonical_or_conflicting_parameters` |
| Estado preservado | Mudança para `Todas` mantém fila, estado, prazo, pesquisa, ordenação e agrupamento; paginação usa o URL integral | browser confirmou `tasks_support`, `status=all`, `due=overdue`, `q=sintética`, `sort=created_desc`, `grouping=category` |
| Desktop sem colisões | Grelha explícita de oito colunas; botão Limpar dentro da grelha | geometria 1440×731: oito controlos na mesma linha, largura útil 1151 px, `scrollWidth == clientWidth`, chips terminam antes do agrupamento |
| Breakpoint intermédio | Quatro colunas por linha entre 901–1390 px, considerando sidebar e padding | geometria browser real a 1280×800, regra CSS versionada e teste de contrato UI |
| Mobile empilhado | Uma coluna, botão a 100%, chips e agrupamento em blocos separados | geometria 390×844: controlos com 325 px, `scrollWidth == clientWidth == 375`, agrupamento começa abaixo dos chips |

## Capturas

- `desktop-all-1440x731.png`: vista `Todas`, desktop.
- `desktop-1440x731.png`: grelha completa com relação visível, desktop.
- `intermediate-all-1280x800.png`: grelha em duas linhas no intervalo intermédio.
- `mobile-all-390x844.png`: vista `Todas`, mobile empilhado.

## Gates locais

- Focados de vista/contrato/casos: `72 passed`.
- Contrato UI: `8 passed`.
- Suite pytest exata do CI: `237 passed`.
- `compileall`: PASS.
- import da aplicação: PASS.
- Ruff exato do CI: PASS.
- baseline de arquitetura: PASS.
- Alembic: uma head `fff6ab1c2d3e`.
- Browser desktop/mobile: PASS; zero overflow horizontal e zero overlaps.
- Revisão independente renovada após correção do breakpoint: APPROVE, zero P0/P1/P2.

## Resíduos e rollback

Não houve mutação externa. A base local sintética é descartável. O diff não altera
persistência, configurações ou permissões; rollback é a remoção integral do commit
desta branch.
