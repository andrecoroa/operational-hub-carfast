# CarFast — Registo de release da Frente A

**Estado:** checkpoint cloud; implementação local em curso  
**Data:** 2026-08-27  
**Branch base confirmada:** `integration/modular-architecture`  
**Base SHA:** `1083b4001d144cc9ab53507ac28215495a2dcce7`  
**Viewport obrigatório:** desktop `1440x731`

Este ficheiro é o registo de coordenação da release da Frente A. Torna-se
canónico apenas depois de merge aprovado na branch de integração. Não substitui
o artefacto funcional `docs/FRONT_A_FUR_DESKTOP_GATE.md`, que ainda deve ser
transferido da worktree de auditoria, comparado com a matriz abaixo e
versionado no GitHub.

## Fonte e precedência

A matriz final abaixo substitui integralmente a lista preliminar de cinco itens.
A sua fonte nesta versão é o mandato explícito do André de 2026-08-27. Enquanto
o ficheiro FUR não estiver no GitHub, nenhuma implementação pode alegar
conformidade por conteúdo local não revisto.

## Matriz binária 9/9

| ID | Gate obrigatório no mesmo artefacto Green | Estado | Evidência |
|---|---|---|---|
| FA-01 | Sidebar, scroll, eixos e labels | UNVERIFIED | Pendente |
| FA-02 | Separação Oficina vs Stock/configuração | UNVERIFIED | Pendente |
| FA-03 | Ações compactas e labels sem quebra | UNVERIFIED | Pendente |
| FA-04 | Primeira dobra da Oficina expõe conteúdo operacional | UNVERIFIED | Pendente |
| FA-05 | Duplicação administrativa apenas no percurso FUR | UNVERIFIED | Pendente |
| FA-06 | Email e Documentação na mesma página, com fila e seleção preservadas | UNVERIFIED | Pendente |
| FA-07 | RBAC server-side nas opções e na submissão | UNVERIFIED | Pendente |
| FA-08 | Guardar, Validar, Avançar, Concluir e Arquivar com transições fail-closed | UNVERIFIED | Pendente |
| FA-09 | Efeitos externos OFF e auditoria preservada | UNVERIFIED | Pendente |

Estados permitidos: `UNVERIFIED`, `PASS` ou `FAIL`. Um gate só pode passar a
`PASS` com evidência reproduzível ligada ao SHA exato da release candidate.
Ausência de overflow, presença de assets/shell ou testes parciais não constitui
PASS funcional, visual ou RBAC.

## Condição de fecho

A Frente A fecha apenas com:

1. os nove gates em `PASS` no mesmo SHA e artefacto Green;
2. CI remoto verde para esse SHA;
3. evidência desktop integral em `1440x731`;
4. testes funcionais e RBAC server-side relevantes;
5. auditoria e efeitos externos OFF comprovados;
6. revisão humana explícita da evidência.

## Fora deste gate

- acessos rápidos;
- redesign integral da Administração;
- ContextNav geral;
- mestre-detalhe integral da Administração;
- polimento visual;
- paridade total;
- responsive fora do viewport obrigatório.

Estes itens pertencem à Frente B ou a regressão posterior e não podem bloquear
nem ser misturados no fecho 9/9.

## Contrato de evidência

A evidência futura deve ser guardada em
`docs/evidence/front-a/<release-sha>/` e incluir, sem dados pessoais nem URLs
privadas:

- `EVIDENCE.md` com comando, ambiente, perfil, rota sanitizada e resultado;
- captura integral `1440x731` por superfície necessária;
- matriz FA-01..FA-09 com ligação entre comportamento e teste;
- resultado do CI e SHA;
- limitações e qualquer FAIL ainda aberto.

O Green atual é alvo de validação, não golden visual.

## Registo da release candidate

| Campo | Valor |
|---|---|
| SHA de integração | Pendente |
| SHA/artefacto Green | Pendente |
| Alembic head | `fff37f8a9b0d` — baseline fornecido; reconfirmar na RC |
| CI | Pendente |
| Gates Front A | 0/9 verificados neste checkpoint |
| Efeitos externos | Devem permanecer OFF |
| Blue | Preservado; sem mutação autorizada |
| Instalação vazia | Preservada; sem mutação autorizada |
| Deploy/DNS/cutover | Não autorizado |

## Trabalho paralelo sem colisão

Até o branch/PR da execução local estar publicado:

- coordenação cloud limita-se a este registo e inspeção read-only;
- não modifica templates, CSS, JavaScript, testes funcionais ou o ficheiro FUR;
- não abre uma implementação concorrente dos mesmos componentes;
- depois da publicação, compara base SHA, ficheiros e CI antes de propor qualquer
  integração.

## Caminho pós-Frente A

Após 9/9 e gate humano:

1. regressão funcional, visual e RBAC separadas;
2. congelamento de release candidate imutável;
3. reconciliação do tooling de delta/cutover/rollback sobre o HEAD atual;
4. revalidação da instalação vazia e idempotência;
5. programa de redesenho da Frente B por famílias e aprovação visual.

Nenhum deploy, mutação Blue/Green, cutover, DNS, domínio ou integração externa
está autorizado por este registo.
