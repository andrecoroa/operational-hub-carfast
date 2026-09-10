# Centro de Tarefas — preview inline compacto

## Candidato local

- Base canónica: `b8bbd2ddd9dcae2a4a00bd1df271874af916b4f4`.
- Branch isolada: `codex/task-preview-compact`.
- Ambiente browser: HTTP local `127.0.0.1:18767`, SQLite descartável,
  utilizador sintético e Email inbound/outbound OFF.
- Sem alterações de schema, migrations, RBAC nominal, Email, Green ou dados reais.

## Alteração e prova

| Requisito | Implementação | Prova |
| --- | --- | --- |
| Evitar identidade duplicada | A linha/grupo selecionado conserva referência, título, estado e prioridade; o preview contém apenas o botão de fecho | contrato Python e seis percursos browser |
| Descrição legível | Área própria com scroll local, 4–5 linhas visíveis | geometria real: 52,8 px em todos os percursos |
| Contexto sem ruído | Contexto vazio fica oculto; contexto existente permanece numa linha com scroll local | contrato Python/CSS e browser |
| Metadados compactos | Responsabilidade, classificação e prazo/SLA aparecem numa faixa compacta | capturas desktop/mobile |
| Atualização junto do estado | `Atualizada …` passou para a linha e para o item agrupado | browser confirmou elemento visível nos seis percursos |
| Ações sem largura artificial | Botões têm largura do conteúdo e alinham à esquerda | desktop: 98–164 px de ações em footer de 1180–1182 px |
| Mecânica preservada | Abrir, repetir clique, fechar, trocar, Escape, foco, hash/session restore e ReturnContext | `result.json`, Lista/Caso/Categoria, desktop/mobile |
| Sem overflow | `body.scrollWidth == innerWidth` | 1440×731 e 390×844 em todos os agrupamentos |

## Capturas e comparação

- Antes: `docs/evidence/task-preview-toggle/browser/flat-1440x731.png`.
- Depois: `browser/flat-1440x731.png`.
- Depois mobile: `browser/flat-390x844.png`.
- Também existem capturas equivalentes para `case` e `category`.
- Medições e read-back: `browser/result.json`.

## Gates locais

- Focados de Centro de Tarefas/casos/UI: `107 passed`.
- Browser autenticado sintético: PASS nos 6 percursos.
- `compileall`: PASS.
- Ruff exato do CI: PASS.
- baseline de arquitetura: PASS.
- Alembic: uma head `fffaef5a6b7c`.
- Suite integral pós-ajuste: `985 passed`, `41 failed`. As 41 falhas reproduzem
  famílias exteriores ao diff (admin, documentos, inventários, migrations com
  constantes antigas, service desk e oficina). A execução anterior tinha
  `984 passed`, `42 failed`; a única falha adicional era a expectativa antiga de
  metadados duplicados no preview, entretanto alinhada. Diferencial: zero
  regressões e um contrato do preview corrigido.

## Estado de publicação

Trabalho exclusivamente local. Não houve push, PR, merge ou deploy.
