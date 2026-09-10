# Fecho dos conteúdos finais no Green

## Release e âmbito

- PR: `#75`
- Branch HEAD aprovado: `1b6dde02359704600d3c894c74ba4be9bb8f4158`
- Merge/deploy Green: `4161572a899289d27ca7636e64bf623c25c419b8`
- Serviço: `srv-da5dk9bm8hqs73camds0`
- Superfícies: `/v2-clean/fleet/financial-audit`, `/v2-clean/fleet/sales-access` e `/v2-clean/tasks/recurring`
- Blue: intocado

## Gates

| Gate | Resultado | Evidência |
|---|---|---|
| CI remoto | PASS | `fast-checks` concluído com sucesso no PR #75 |
| Testes focados | PASS | 40 testes e, após correções da revisão, 27 testes |
| Revisão independente | PASS após correção | ReturnContext filtrado e contenção/nome acessível do modal corrigidos |
| Smoke autenticado | PASS | três rotas carregadas com shell, métricas e dados reais Green |
| ReturnContext | PASS | filtros `entity` e `missing` preservados no link de regresso da viatura |
| Modal/teclado | PASS | foco inicial, `aria-labelledby`, Escape, reposição de foco e ciclo Tab/Shift+Tab |
| Responsive | PASS | 9 capturas reais; body/html sem overflow global nos três breakpoints |
| RBAC e dados | PASS | sem alteração de permissões, dados, `/api/tasks`, REST legado, migrações ou integrações |

## Métricas de runtime

Capturas sem recorte, zoom `1`, `font-size` efetivo `14px`, asset carregado
`visual-v2.css?v=20260825-convergence1`.

| Viewport | `body clientWidth/scrollWidth` | Resultado |
|---|---:|---|
| 1440×900 | 1425/1425 | PASS |
| 1024×900 | 1009/1009 | PASS |
| 390×844 | 375/375 | PASS |

As métricas completas por rota estão em `metrics.json`.

## Capturas

- `financial-audit-{desktop-1440x900,tablet-1024x900,mobile-390x844}.png`
- `sales-access-{desktop-1440x900,tablet-1024x900,mobile-390x844}.png`
- `tasks-recurring-{desktop-1440x900,tablet-1024x900,mobile-390x844}.png`

## Resultado

PASS para esta tranche no Green. A matriz canónica fica com 53/53 superfícies sem conteúdo classificado como `parcial` ou `legado`. As cinco falhas históricas do REST legado `/tasks` permanecem dívida nominal separada; `/api/tasks` não foi alterado nem enfraquecido.
