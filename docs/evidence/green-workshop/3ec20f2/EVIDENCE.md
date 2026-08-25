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

## Matriz de aceitação

| Critério | Estado | Evidência |
|---|---|---|
| Shell transversal | PASS | Sidebar navy, marca CarFast, topbar e conteúdo útil coerentes |
| Cabeçalho de processo | PASS | Referência, fase, contexto, metadados e ações reais |
| Contexto da viatura | PASS | Identidade, factos, alertas e pendências em composição compacta |
| Stepper de fases | PASS | Fase ativa visível; scroll exclusivamente local em mobile |
| Workbench + resumo | PASS | Conteúdo funcional e resumo lateral 286px em desktop |
| Preferência do resumo | PASS | Persistência server-side por utilizador em `SettingsValue` |
| Stock e Compras | PASS | Submenu de Oficina com rotas reais; fallback independente preservado |
| Funcionalidade | PASS | POST/save/advance, tarefas, ficha, documentos e permissões preservados |
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
- A tranche reconstrói o detalhe operacional de Oficina; outras superfícies de Oficina/Stock seguem a expansão aprovada em tranches posteriores.
