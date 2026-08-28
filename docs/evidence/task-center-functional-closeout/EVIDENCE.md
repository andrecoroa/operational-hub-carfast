# Centro de Tarefas — fecho funcional local

Base imutável: `7c47f9fee27168ca9e91fe07acfe3092c0f81fd5`  
Branch: `codex/task-center-functional-closeout`

## Âmbito

- `Abrir tarefa` mantém o resolver existente e abre `/v2-clean/tasks/{id}/detail`
  com ReturnContext assinado, seleção e filtros.
- O detalhe real permite editar conteúdo, prioridade, prazo, hierarquia persistida
  e owner/executor elegíveis.
- A criação distingue `request`, `request_info` e tarefa completa. Pedido e
  Informação expõem relação e anexos; planeamento (owner/executor, prioridade e
  prazo) fica em `Mais opções` apenas para a tarefa completa.
- Fila/departamento/categoria/subcategoria são exclusivamente os registos ativos
  de WorkQueue/WorkDepartment/WorkCategory/WorkSubcategory permitidos pelo resolver
  de criação atual. Nenhuma equipa é apresentada como fila.
- Nenhum helper RBAC, RoleWorkScope, catálogo de permissões, migração ou dado Green
  foi alterado.

## Prova local isolada

Runtime: `127.0.0.1:18768`, SQLite descartável, conta e tarefas sintéticas, Email
inbound/outbound OFF. Viewport imposto a `1440×731`.

- `01-selected-1440x731.png`: fila + preview, body width 1440, zero descendentes
  fora dos limites horizontais.
- `02-detail-1440x731.png`: detalhe real; formulário contém assunto, descrição,
  prioridade, prazo, quatro níveis da hierarquia, equipa owner e executor.
- `03-models-1440x731.png`: três modelos explícitos antes de qualquer submissão.
- `geometry.json`: viewport, body width e verificação de overflow.

Read-back do detalhe: ReturnContext resolveu para
`/v2-clean/tasks?workspace=all&status=open&category=all#task-2`.
Nenhum formulário browser foi submetido.

## Testes

- Regressão focada Centro de Tarefas: `65 passed`.
- Baseline modular: `7 passed`.
- Contrato criação/detalhe: incluído na regressão; três modelos persistidos com
  tipos distintos e hierarquia sintética determinística.
- `compileall app scripts`: PASS.
- Alembic: head único `fff48a9b0c1e`.
- `git diff --check`: PASS.

Revisão do diff contra a base confirmou zero alterações em helpers RBAC,
RoleWorkScope, catálogo de permissões, API REST ou modelos/schema. Zero P0/P1
novo identificado no âmbito funcional. A suite REST de segurança conserva os
cinco FAIL já presentes na base Green e pertence à fase RBAC explicitamente
congelada; este candidato não os mascara nem os altera.

## Gate

Candidato exclusivamente local. Sem push, PR, merge, deploy ou mutação Green.
