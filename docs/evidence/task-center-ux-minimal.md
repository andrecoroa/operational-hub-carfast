# Centro de Tarefas — evidência local

Data: 2026-09-02

Branch: `codex/task-center-ux-minimal-v2`

Base canónica remota: `7a3317bb20f7832dac9b27dac4cb8f5ed13b0cc6`

## Âmbito

- A lista inicial deixou de materializar um workbench completo por tarefa.
- Preview inline único, compacto e reutilizável; gestão completa carregada on demand.
- ReturnContext, abrir/fechar/trocar, Escape e restituição de foco preservados.
- Destinatários de suporte carregados on demand por endpoint autenticado e fail-closed.
- Fila única apresentada como contexto fixo; múltiplas filas usam o resolver canónico.
- Filtro de estado identificado como recorte agregado; Estado atual e transições legais são superfícies distintas.
- Criação só expõe hierarquias de filas com capability de escrita e scope de criação; Administração exige grant explícito.

## Antes / depois

Medição browser HTTP local sintético, sem dados reais.

| Medida | Base (4 linhas) | Candidato (6 linhas) |
| --- | ---: | ---: |
| Nós DOM | 831 | 550 |
| Forms | 19 | 15 |
| Campos | 56 | 52 |
| Botões | 52 | 48 |
| Dialogs | 11 | 7 |
| Overflow horizontal | não | não |

Com dez tarefas adicionais, a base congelada executava 197 queries; o candidato executa 136 (-31%). O teste regressivo fixa o máximo em 140. Os tempos locais variaram demasiado entre execuções para sustentar uma conclusão de latência.

## Provas funcionais

- 141 testes focados do Centro de Tarefas: PASS.
- 26 testes de casos e Service Desk: PASS.
- 9 testes da matriz canónica de filas, incluindo criação Administração positiva, read-only negativa e `admin.manage` forjado: PASS.
- Browser final: ajuda de fila/estado presente; um único preview; troca imediata; Escape fecha e restitui foco; zero overflow horizontal.
- Browser mobile 390×844 e desktop 1440×731: PASS na iteração anterior; as alterações posteriores foram apenas texto curto e enforcement server-side.
- `compileall`: PASS.
- Alembic: cabeça única `fff6ab1c2d3e`.
- Baseline arquitetural regenerada para a alteração intencional de formulários/rotas.
- Revisão independente do forward fix de autorização: zero P0/P1; o P1 de `admin.manage` forjado foi fechado e renovado com 9 testes PASS.
- Atualização de base: os commits `a491f52c..7a3317bb` alteravam Email; a única sobreposição foi `ui-contract-v1.css`, reaplicada automaticamente preservando os dois âmbitos.
- Diferencial formal na mesma base limpa: base `192 PASS`; candidato `197 PASS` (cinco provas adicionais, zero regressões).
- Teste afetado pela sobreposição, `test_email_triage_preview.py`, incluído no gate candidato: PASS.
- Revisão independente final contra `7a3317bb`: zero P0/P1; CSS Task Center estritamente isolado dos seletores Email e gates server-side preservados.

## Suite integral e causalidade

A suite integral anterior ao último forward fix fail-closed terminou com `45 failed, 928 passed`. Após o forward fix, 177 gates focados/baseline passaram; a integral não foi novamente executada por continuar bloqueada pela mesma dívida canónica.

- Cinco falhas em `test_service_desk_api_security.py` foram reproduzidas sem alterações na base canónica local: dívida preexistente.
- As restantes falhas estão em Administração, migrações com expectativas antigas, documentos/diagnóstico, email, inventários visuais, frota, oficina e fluxos legacy; nenhuma dessas superfícies é alterada por esta tranche.
- Uma falha diferencial legítima da baseline arquitetural foi causada pela redução de formulários e foi corrigida regenerando a baseline versionada.

Como o CI canónico integral continua vermelho, o veredito técnico permanece **NO-GO para Ready/merge/deploy**, mesmo sem regressão focada identificada.

## Segurança

- Sem schema ou migration nova.
- Sem alterações de RBAC nominal.
- Sem dados reais.
- Email e integrações permaneceram desativados no servidor sintético.
- Sem push, PR, merge ou deploy.
