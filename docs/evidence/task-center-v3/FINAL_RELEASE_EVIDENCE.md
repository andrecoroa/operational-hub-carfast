# Centro de Tarefas v3 — evidência de integração e Green

## Contrato e candidato

- Contrato congelado SHA-256: `D0AE9B2B33F6BF7C44202392A47AF1733D661E72F7428CA5C71C5AFF14678FB1`.
- PR: `#97`.
- Branch: `codex/task-center-v3-contract`.
- Head aprovado: `239a5be22a38af48d413cb77d799132b50ab605d`.
- Base observada antes do gate: `2f10c9874eee542c1bf82e326e338b2f78cb19c0`.
- Merge base: `2f10c9874eee542c1bf82e326e338b2f78cb19c0` — sem drift.

## Gates pré-merge

| Gate | Resultado | Evidência |
|---|---|---|
| CI integral do PR | PASS | GitHub Actions `fast-checks`, run `33231491165`, 1m58s |
| Testes locais focados | PASS | 71/71 |
| Lista exata do CI local | PASS | 156/156 |
| Browser local 1440×731 | PASS | `scrollWidth=1440`, zero overflow; vistas, conflito, teclado e suporte verificados |
| Revisão independente | PASS | zero P0/P1 após dois ciclos de correção |
| Head/base sem drift | PASS | head/base/merge-base acima |
| Mergeability | PASS | GitHub: `Ready to merge`, sem conflitos |

## Integração

- Estado: PENDENTE.
- Merge SHA: PENDENTE.

## Deploy Green

- Serviço esperado: `srv-da5dk9bm8hqs73camds0` (`carfast-green`).
- Estado Green anterior: PENDENTE.
- Deploy ID: PENDENTE.
- Deploy SHA: PENDENTE.
- Migration/Alembic: PENDENTE.
- Health HTTP 200: PENDENTE.

## Smoke autenticado do contrato

- Fila única, vistas, filtros e ordenação: PENDENTE.
- Workbench, ReturnContext e acessibilidade: PENDENTE.
- Suporte e comentário: PENDENTE.
- Loading/vazio/erro/sem permissão/espera/atraso/risco/concluído: PENDENTE.
- Cleanup: PENDENTE.

## Email e efeitos externos

- `EMAIL_INBOUND_ENABLED`: PENDENTE.
- `EMAIL_OUTBOUND_ENABLED`: PENDENTE.
- webhooks gerais: PENDENTE.
- Email preservado: PENDENTE.

## Rollback

Se qualquer gate pós-deploy falhar, repor imediatamente o deploy Green anterior,
confirmar health e smoke nominal e registar o read-back nesta secção.
