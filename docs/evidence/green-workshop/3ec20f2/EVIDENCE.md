# Oficina — evidência Green

- Runtime/deploy: `3ec20f2d67e27fa0239c7bd9e4684a313d308c1c`
- URL auditada: `https://carfast-green.onrender.com/v2-clean/workshop/reparacao?process_id=216`
- Asset: `visual-v2.css?v=20260825-workshop2`
- Referência canónica: `carfast-processo-oficina.png` + contratos de sistema visual
- Blue: intocado

## Capturas autenticadas, viewport completo

- `workshop-desktop-1440x900.png` — 1440 × 900, zoom 100%
- `workshop-tablet-1024x900.png` — 1024 × 900, zoom 100%
- `workshop-mobile-390x844.png` — 390 × 844, zoom 100%

As três capturas acima usam o processo histórico `216` e provam a shell, o
contexto e a composição superior. Não são usadas isoladamente como prova do
workbench operacional.

## Evidência operacional complementar — processo 207

- URL auditada: `https://carfast-green.onrender.com/v2-clean/workshop/reparacao?process_id=207`
- Processo existente, não histórico: `OF-2026-0046 | Reparação`, viatura `BT-04-GA`
- Consulta exclusivamente read-only; nenhum campo foi alterado e nenhuma ação de guardar/avançar foi executada.
- `operational-207/operational-workbench-desktop-1440x900.png` — trabalho autorizado, execução, evidências, desvios/custos, resumo lateral e ações finais reais.
- `operational-207/operational-documents-desktop-1440x900.png` — secção real de documentos e fotografias.
- `operational-207/operational-materials-desktop-1440x900.png` — área de peças/custos e pedidos ao Stock.
- `operational-207/operational-history-desktop-1440x900.png` — histórico em modal acessível.
- `operational-207/operational-actions-desktop-1440x900.png` — fim do workbench e barra Guardar/Avançar, sem ocultação do conteúdo acionável.
- `operational-207/operational-workbench-tablet-1024x900.png` — workbench operacional em tablet.
- `operational-207/operational-workbench-mobile-390x844.png` — workbench operacional em mobile, fluxo de coluna única.

As ações `Guardar reparação` e `Enviar para Validação e Fecho` permanecem
visíveis numa barra de ação própria, sem remover nem substituir o conteúdo do
workbench; os controlos continuam a usar as rotas reais e não foram acionados
durante a auditoria.

## Matriz de aceitação

| Critério | Estado | Evidência |
|---|---|---|
| Shell transversal | PASS | Sidebar navy, marca CarFast, topbar e conteúdo útil coerentes |
| Cabeçalho de processo | PASS | Referência, fase, contexto, metadados e ações reais |
| Contexto da viatura | PASS | Identidade, factos, alertas e pendências em composição compacta |
| Stepper de fases | PASS | Fase ativa visível; scroll exclusivamente local em mobile |
| Workbench + resumo | PASS | Processo operacional 207: trabalho, execução, evidências, custos e resumo lateral em uso real |
| Preferência do resumo | PASS | Persistência server-side por utilizador em `SettingsValue` |
| Stock e Compras | PASS | Submenu de Oficina com rotas reais; fallback independente preservado |
| Funcionalidade | PASS | POST/save/advance, tarefas, ficha, documentos e permissões preservados; auditoria operacional sem mutações |
| Histórico por teclado | PASS | Foco em Fechar, trap, Escape e retorno ao acionador comprovados no runtime |
| Responsive | PASS | Body 1425/1425, 1009/1009 e 375/375; sem overflow global |
| Mobile ações rápidas | PASS | Botões 135px sem interseção; grelha 2+1 e altura mínima 44px |
| Blue | PASS | Nenhum merge/deploy/mutação em `v2/production` |

## Validação

- CI `fast-checks`: PASS nos PRs #53, #54, #55 e #56.
- Testes focados: 16 PASS; contrato visual final: 7 PASS.
- Baseline arquitetural: `Architecture baseline matches`.
- Revisão independente: PASS após correção de rotas, targets, flag OFF, preferência e ciclo de foco.

## Limitações não bloqueantes

- O stepper e as tabs usam scroll local em ecrãs estreitos; não existe overflow global.
- A cobertura visual agora inclui o detalhe operacional de reparação; listagens adicionais de Oficina e as superfícies completas de Stock continuam na expansão aprovada.
