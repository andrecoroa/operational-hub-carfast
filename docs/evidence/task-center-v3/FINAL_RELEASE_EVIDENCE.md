# Centro de Tarefas v3 — evidência de integração e Green

## Contrato e candidato

- Contrato congelado SHA-256: `D0AE9B2B33F6BF7C44202392A47AF1733D661E72F7428CA5C71C5AFF14678FB1`.
- PR: `#97`.
- Branch: `codex/task-center-v3-contract`.
- Head aprovado: `552dda1c28f4ea1cef910a97e0a28f076666c9e3`.
- Base observada antes do gate: `2f10c9874eee542c1bf82e326e338b2f78cb19c0`.
- Merge base: `2f10c9874eee542c1bf82e326e338b2f78cb19c0` — sem drift.

## Gates pré-merge

| Gate | Resultado | Evidência |
|---|---|---|
| CI integral do PR | PASS | GitHub Actions `fast-checks`, runs `33231491165` (1m58s) e `33231838393` (2m03s), ambos verdes |
| Testes locais focados | PASS | 71/71 |
| Lista exata do CI local | PASS | 156/156 |
| Browser local 1440×731 | PASS | `scrollWidth=1440`, zero overflow; vistas, conflito, teclado e suporte verificados |
| Revisão independente | PASS | zero P0/P1 após dois ciclos de correção |
| Head/base sem drift | PASS | head/base/merge-base acima |
| Mergeability | PASS | GitHub: `Ready to merge`, sem conflitos |

## Integração

- Estado: PASS — PR `#97` merged em 2026-08-29 04:39 Europe/Lisbon.
- Merge SHA: `7aadc5a49e8be0bc21ef03e1334cb9bb49f1b9b4`.
- Read-back remoto: `origin/integration/modular-architecture` avançou para a merge SHA acima.

## Deploy Green

- Serviço: `srv-da5dk9bm8hqs73camds0` (`carfast-green`).
- Estado Green anterior/rollback nominal: deploy `dep-da92uuajnfac73cgu360`, SHA `2f10c9874eee542c1bf82e326e338b2f78cb19c0`.
- Deploy ID: `dep-da959b942hec73ep1kf0` — `live`.
- Deploy SHA: `7aadc5a49e8be0bc21ef03e1334cb9bb49f1b9b4` — seleção explícita por commit no Render.
- Migration/Alembic: PASS — `Running upgrade fff48a9b0c1e -> fff59a0b1c2d`; pre-deploy completo.
- Health HTTP 200: PASS — `{"status":"ok","app":"CarFast Green","environment":"production"}`.

## Smoke autenticado do contrato

- Fila única, vistas, filtros e ordenação: PASS — sessão Green autenticada; fila `tasks_support`; `Da equipa` persistiu após reload; ordenação nominal visível.
- Incompatibilidade: PASS — com `Fechadas`, a opção `Em risco` ficou explicitamente `disabled`.
- Workbench, ReturnContext e acessibilidade: PASS — seleção no mesmo UI, tabs Trabalho/Atividade/Detalhes operacionais e parâmetros `task_scope_view=team&queue=tasks_support&status=open&sort=priority` preservados.
- Geometria: PASS — viewport `1440x731`, `scrollWidth=1440`, zero overflow horizontal.
- Suporte e comentário: PASS por prova transacional automatizada positiva/negativa; não executados contra dados reais no smoke, conforme restrição contratual.
- Loading/vazio/erro/sem permissão/espera/atraso/risco/concluído: PASS por testes server-side/browser sintético; vazio e estados operacionais observados no Green.
- Cleanup: PASS — viewport reposto, separadores temporários fechados, sem servidor local ou mutação de dados Green.

## Email e efeitos externos

- `EMAIL_INBOUND_ENABLED`: `true` antes e depois.
- `EMAIL_OUTBOUND_ENABLED`: `false` antes e depois.
- `WEBHOOKS_ENABLED`: `false` antes e depois.
- Email preservado: PASS — nenhuma flag foi alterada.

## Rollback

Não acionado: todos os gates pós-deploy passaram. O rollback nominal permanece
`dep-da92uuajnfac73cgu360` / `2f10c9874eee542c1bf82e326e338b2f78cb19c0`.
