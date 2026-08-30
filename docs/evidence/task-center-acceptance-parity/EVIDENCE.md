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
| Fechadas + Em risco incompatíveis | Em risco é desativado e removido explicitamente, com aviso; sem fallback da vista | Teste negativo |
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
- Recorrentes: utilizador sintético com `tasks.recurring.manage` vê a ação
  secundária, abre `/v2-clean/tasks/recurring` e encontra modelos, estado e
  próxima execução; sem a permissão, a ação continua ausente.
- Browser mobile real 390×844: viewport confirmada por `innerWidth/innerHeight`,
  documento e body sem overflow horizontal, filtros numa coluna, KPIs numa
  coluna, tabela reduzida aos quatro campos úteis, preview abrir/trocar/Escape,
  Categoria/Caso e restauro por hash PASS. Capturas em
  `browser/live-mobile-390x844.png`, `browser/mobile-case-preview-390x844.png`
  e `browser/mobile-management-390x844.png`.
- Criação: seletor progressivo mostra Pedido simples, Informação/Comunicação,
  Tarefa completa e Caso; Caso fecha o primeiro diálogo, abre o fluxo canónico
  e coloca foco no título. Gestão: Editar, Comentar, Alterar estado e Solicitar
  suporte partilham a mesma linguagem visual e os alvos de suporte são
  resolvidos server-side/fail-closed.
- A política do browser bloqueou a abertura direta do `file://` contratual.
  A comparação estrutural foi feita contra o HTML congelado, mas a captura
  pixel/geometria lado a lado do clicável continua aberta.

## Execuções locais

- Regressão focada final: `90 passed` (Centro aprovado/v3, recorrências,
  casos e autorização).
- Suite integral antes da correção diferencial: `45 failed, 842 passed`.
  Uma falha era causada pelo candidato (o teste canónico exige normalização
  explícita de Fechadas + Em risco, não HTTP 400); foi corrigida sem alterar
  comportamento fora do âmbito. Renovação integral final: `44 failed,
  843 passed`; as 44 falhas são as preexistentes da base e não há regressões
  adicionais desta tranche. Após a continuação de paridade, nova execução
  integral: `44 failed, 846 passed`; mantém exatamente as mesmas 44 falhas
  preexistentes e acrescenta três testes PASS, sem regressões novas.
- Alembic: head único `fff6ab1c2d3e`.
- Ruff global: FAIL preexistente (2282 ocorrências em todo o repositório); o CI
  canónico limita Ruff ao conjunto versionado em `.github/workflows/ci.yml`.
- Compilação de `app` e `scripts`: PASS.
- Workflow CI canónico local renovado: Ruff restrito PASS, arquitetura
  congelada PASS, Alembic graph PASS e seleção exata de testes `186 passed`.
  O novo formulário de suporte acrescentou uma ocorrência POST ao baseline;
  o delta mecânico foi regenerado e verificado antes desta execução.
- Revisão independente renovada no HEAD `9de7a93d`: zero P0/P1 de código;
  suite independente `100 passed`. O revisor manteve como P1 de aceitação
  documental — não de produto — a comparação visual lado a lado que a política
  do browser impediu executar sobre `file://`.

Nenhuma divergência P0/P1 pode permanecer para fechar o gate local.

## Limites

Sem publicação de branch/PR, merge, deploy, alteração de Green, Email, RBAC nominal, dados reais ou schema nesta tranche.
