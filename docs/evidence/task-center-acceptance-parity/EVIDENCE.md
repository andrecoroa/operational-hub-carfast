# Centro de Tarefas — paridade com contrato de aceitação

## Referência congelada

- Base canónica: `integration/modular-architecture` em `8479123015ce2797ce8b93c0acadfd73833992e6`.
- Branch local isolada: `codex/task-center-acceptance-parity`.
- Contrato revisto `task-center-acceptance.html`: SHA256 `29E5A1FB9B2BE95E33DC1CC9E865D19CA25D1FF655D408017E9C362C8E21ECA4`.
- Contrato revisto `task-center-acceptance-standalone.html`: SHA256 `C5EF18FF73112283925389D4A297D566F32FD9BDD8E1D50DA63845540DC931A4`.
- O segundo congelamento substitui a versão anterior porque o contrato passou a incluir explicitamente **Recorrentes**.

## Matriz contrato → implementação → prova

| Contrato | Implementação | Prova prevista |
|---|---|---|
| Uma fila, Tarefas e Suporte por defeito | Resolver server-side de filas; Administração só quando autorizada | Matriz web/API positiva e negativa |
| Minhas / Por assumir / Da equipa sem fallback | Relações server-side e vista de equipa vazia fail-closed | Testes focados + browser |
| Estados completos | Filtros exatos Nova, Em curso, Em espera, Suporte solicitado, Resolvida e Cancelada; agregados ativos/fechados/todos | Teste parametrizado de isolamento |
| Fechadas + Em risco incompatíveis | Pedido rejeitado com HTTP 400, sem normalização silenciosa | Teste negativo |
| Prazo, pesquisa e ordenação | Query server-side e contexto na URL | Percursos browser e testes existentes |
| Categoria / Caso / Lista | Categoria agrupa; Caso contém apenas `TaskCase` persistidos; Lista mostra tarefas | Testes de agrupamento/contagens |
| Preview inline | Montagem sob linha/grupo; alternar, trocar e Escape; um único preview | Browser desktop/mobile, teclado/foco |
| Gestão, comentário, suporte e ReturnContext | Workbench e diálogos usam autorização canónica e preservam URL/hash | Testes web/browser positivos e negativos |
| Criação e caso | Componentes progressivos existentes e três fluxos de caso autorizados | Testes de percursos |
| Recorrentes | Ação secundária condicionada a `tasks.recurring.manage`; rota própria com modelo, estado e próxima execução | Testes de contrato, permissão e browser |
| Scroll vertical e zero overflow | Documento com scroll vertical; fila/preview inline responsivos | Geometria 1440×731 e 390×844 |

## Divergências residuais

- A captura real desktop está em `browser/live-desktop-1440x731.png`.
- Browser desktop 1440×731: quatro KPIs, estados completos, scroll vertical,
  zero overflow horizontal e preview inline abrir/fechar/trocar/Escape PASS.
- Restauro por hash/session em Categoria e Caso volta a montar o preview sob o
  elemento visível PASS; Caso contém apenas as duas tarefas do `TaskCase`
  persistido da fixture.
- O override de viewport do browser integrado não alterou a viewport para
  390×844. A captura incorretamente dimensionada foi removida e o gate mobile
  permanece aberto; não é reportado como PASS.
- A política do browser bloqueou a abertura direta do `file://` contratual.
  A comparação estrutural foi feita contra o HTML congelado, mas a captura
  pixel/geometria lado a lado do clicável continua aberta.

## Execuções locais

- Regressão focada final: `68 passed` (Centro aprovado/v3, recorrências,
  casos e autorização).
- Suite integral antes da correção diferencial: `45 failed, 842 passed`.
  Uma falha era causada pelo candidato (o teste canónico exige normalização
  explícita de Fechadas + Em risco, não HTTP 400); foi corrigida sem alterar
  comportamento fora do âmbito. Resultado diferencial esperado: as 44 falhas
  preexistentes da base e zero regressões desta tranche. A renovação integral
  final ainda deve confirmar a contagem.
- Alembic: head único `fff6ab1c2d3e`.
- Ruff global: FAIL preexistente (2282 ocorrências em todo o repositório); o CI
  canónico limita Ruff ao conjunto versionado em `.github/workflows/ci.yml`.
- Compilação de `app` e `scripts`: PASS.

Nenhuma divergência P0/P1 pode permanecer para fechar o gate local.

## Limites

Sem publicação de branch/PR, merge, deploy, alteração de Green, Email, RBAC nominal, dados reais ou schema nesta tranche.
