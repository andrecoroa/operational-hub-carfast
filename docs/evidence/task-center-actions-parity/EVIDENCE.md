# Centro de Tarefas — experiência operacional unificada

- Base canónica verificada: `integration/modular-architecture@5c9df0c3bdc36c5a26156cf3a05161b663d79c32`
- Ambiente: runtime local isolado, SQLite e dados exclusivamente sintéticos
- Viewport: `1440×731`
- Email inbound/outbound: `OFF`
- Green e Blue: não consultados nem alterados durante a implementação

## Resultado

| Gate | Resultado | Evidência |
| --- | --- | --- |
| Abrir e trabalhar | PASS | Abre o workbench completo na própria rota `/v2-clean/tasks`, sem mudar de shell ou perder a fila; `02-unified-workbench-1440x731.png` |
| Vista inicial | PASS | Apresenta todo o trabalho autorizado e ativo, sem impor Documentação como foco oculto |
| Filtros | PASS | Minhas, Por assumir e Da equipa são vistas operacionais; a fila vem da hierarquia persistida e é read-only quando só existe uma opção |
| Alterar estado | PASS | Dialog acessível e opções calculadas no servidor; POST forjado e transição inválida falham fechados; `03-state-editor-1440x731.png` |
| Registar nota | PASS | Dialog acessível, sem `window.prompt`, POST autorizado e retorno à seleção; `04-note-editor-1440x731.png` |
| Nova tarefa | PASS | Só aparece com filas criáveis; Pedido simples, Informação/Comunicação e Tarefa completa partilham classificação canónica; `03-three-models-1440x731.png` |
| Paridade lista/detalhe | PASS | A abertura canónica e o detalhe histórico usam `user_can_view_task`; ações revalidam visibilidade e capacidade específica |
| ReturnContext | PASS | Workspace, estado, prazo, categoria, pesquisa e seleção permanecem na URL; scroll permanece em `sessionStorage` |
| Classificação | PASS | Lista, preview e workbench apresentam fila e categoria persistidas; os buckets hard-coded deixam de ser o filtro principal |
| Atribuição | PASS | Executor individual e equipa responsável são alternativas exclusivas; o servidor continua a revalidar o POST |
| Estado | PASS | A edição geral preserva o estado; as transições permanecem numa ação própria e autorizada |
| Geometria | PASS | `geometry.json`: body `1440`, zero descendentes fora do viewport |

## Inventário do fixture

Filas canónicas: `Tarefas e Suporte` e `Administração`. A interface só apresenta filas permitidas pelo resolver existente e nunca transforma os workspaces legacy em filas visíveis. Equipas e classificações continuam a ser filtradas pelas capacidades e hierarquia persistida.

Este inventário prova apenas o fixture/runtime isolado. O estado `active` e os scopes efetivos do Green exigem leitura administrativa no próprio Green e não são inferidos a partir do seed.

## Testes

- `84 passed`: contratos do Centro, criação/edição, notificações, ReturnContext, service desk, UI foundation e regressão visual.
- `57 passed`: repetição focada do Centro de Tarefas após o fecho das incoerências de edição.
- Baseline arquitetural, `compileall` e `git diff --check`: PASS.
- Browser Chrome 1440×731: fila, preview, workbench unificado e três modelos de criação PASS; nenhum POST em dados reais.
- A suite REST/RBAC mantém cinco falhas já reproduzidas na base canónica e não é alterada por este diff; o endurecimento de acessos permanece numa tranche separada conforme decisão do André.

O script `scripts/task_center_actions_browser_evidence.mjs` recaptura os percursos e falha se o body ou qualquer descendente ultrapassar horizontalmente o viewport.
