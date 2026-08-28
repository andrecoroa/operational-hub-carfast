# Centro de Tarefas — ações e paridade

- Base canónica verificada: `integration/modular-architecture@395669db`
- Ambiente: runtime local isolado, SQLite e dados exclusivamente sintéticos
- Viewport: `1440×731`
- Email inbound/outbound: `OFF`
- Green e Blue: não consultados nem alterados durante a implementação

## Resultado

| Gate | Resultado | Evidência |
| --- | --- | --- |
| Abrir tarefa | PASS | Reabre a seleção na rota `/v2-clean/tasks`, sem passar por `/task-board/{id}` nem pelo início; `02-open-return-context-1440x731.png` |
| Continuar | PASS | Mantém a fila e move o foco para o contexto de trabalho; claim continua reservado ao resolver server-side |
| Alterar estado | PASS | Dialog acessível e opções calculadas no servidor; POST forjado e transição inválida falham fechados; `03-state-editor-1440x731.png` |
| Registar nota | PASS | Dialog acessível, sem `window.prompt`, POST autorizado e retorno à seleção; `04-note-editor-1440x731.png` |
| Nova tarefa | PASS | Só aparece com workspaces criáveis e abre o formulário clean; categorias dependem do workspace permitido; `05-create-editor-1440x731.png` |
| Paridade lista/detalhe | PASS | A abertura canónica e o detalhe histórico usam `user_can_view_task`; ações revalidam visibilidade e capacidade específica |
| ReturnContext | PASS | Workspace, estado, prazo, categoria, pesquisa e seleção permanecem na URL; scroll permanece em `sessionStorage` |
| Categoria | PASS | Preview separa “Categoria canónica” de “Agrupamento de foco”; `other` deixa de ser apresentado como Documentação |
| Geometria | PASS | `geometry.json`: body `1440`, zero descendentes fora do viewport |

## Inventário do fixture

Filas canónicas: `Tarefas e Suporte` e `Administração`. Workspaces autorizáveis: Operacional, Oficina, Auditoria, Gestão e Administração. Equipas seed: Suporte, Operações, Oficina, Financeira e Gestão. As categorias de criação são as categorias canónicas existentes por workspace; os quatro focos Documentação, Oficina, Sinistros e Todas são agrupamentos de consulta, não uma taxonomia alternativa.

Este inventário prova apenas o fixture/runtime isolado. O estado `active` e os scopes efetivos do Green exigem leitura administrativa no próprio Green e não são inferidos a partir do seed.

## Testes

- `48 passed`: contratos, filtros/contadores, criação, notificações, ReturnContext, visibilidade e ações.
- `25 passed`: repetição focada após corrigir capacidades `close`, SLA e resolução terminal.
- `23 passed`: gate final das últimas correções; baseline arquitetural e compilação também PASS.
- Browser: cinco percursos reais em Chrome, com nota sintética submetida apenas à SQLite local.
- Comparação: `00-before-selected-1440x731.png` e `01-selected-1440x731.png`.

O script `scripts/task_center_actions_browser_evidence.mjs` recaptura os percursos e falha se o body ou qualquer descendente ultrapassar horizontalmente o viewport.
