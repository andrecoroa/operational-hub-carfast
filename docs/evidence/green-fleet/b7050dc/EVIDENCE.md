# Frota — evidência Green

- Runtime/deploy: `b7050dc308e4c4b1c2a8be31e223bb7816710fb2`
- PR funcional: `#59`
- Asset carregado: `visual-v2.css?v=20260825-convergence1`
- Captura: sessão autenticada, zoom 100%, viewport completo, sem recorte de componentes
- Registo usado no detalhe: viatura existente `528` (`CG-57-DE`), consulta read-only
- Blue: intocado

## URLs auditadas

- Lista: `https://carfast-green.onrender.com/v2-clean/fleet`
- Detalhe: `https://carfast-green.onrender.com/v2-clean/fleet/528?return_to=%2Fv2-clean%2Ffleet%23vehicle-528`
- Pipeline: `https://carfast-green.onrender.com/v2-clean/fleet/sales`

## Capturas autenticadas

### Lista Frota

- `fleet-list-desktop-1440x900.png` — 1440 × 900
- `fleet-list-tablet-1024x900.png` — 1024 × 900
- `fleet-list-mobile-390x844.png` — 390 × 844

### Detalhe real da viatura 528

- `fleet-detail-528-desktop-1440x900.png` — 1440 × 900
- `fleet-detail-528-tablet-1024x900.png` — 1024 × 900
- `fleet-detail-528-mobile-390x844.png` — 390 × 844

### Pipeline de Vendas

- `fleet-sales-pipeline-desktop-1440x900.png` — 1440 × 900
- `fleet-sales-pipeline-tablet-1024x900.png` — 1024 × 900
- `fleet-sales-pipeline-mobile-390x844.png` — 390 × 844

## Medições responsive

| Viewport | `clientWidth` | `scrollWidth` | Overflow global |
|---|---:|---:|---|
| 1440 × 900 | 1425 | 1425 | PASS — não |
| 1024 × 900 | 1009 | 1009 | PASS — não |
| 390 × 844 | 375 | 375 | PASS — não |

Na lista tablet, a tabela usa scroll exclusivamente local (`895 → 1120`),
sem expandir o documento. Os controlos principais em mobile medem 48 px ou
mais. A navegação móvel fecha com `Escape` e devolve o foco ao acionador.

## Matriz de aceitação

| Critério | Estado | Evidência |
|---|---|---|
| Shell e navegação Frota | PASS | Sidebar única; Vendas aninhada sob Frota |
| Lista operacional | PASS | KPIs, filtros, tabela real e paginação |
| Detalhe real | PASS | Contexto da viatura, alertas, ações e workbench |
| Documentos e Diagnósticos | PASS | Separadores e rotas reais; `return_to` preservado |
| Pipeline de Vendas | PASS | KPIs, filtros e tabela real sob o contexto Frota |
| ReturnContext | PASS | Lista → detalhe → separadores → regresso preserva o fragmento da viatura |
| RBAC e ativação independente | PASS | Testes focados; rotas e permissões existentes preservadas |
| Feature flag OFF | PASS | Fallback legado coberto pelos testes da tranche |
| Filtro seguro | PASS | GET por `CG-57-DE`, uma linha correspondente, sem mutação |
| Teclado e Escape | PASS | Menu mobile abre/fecha por teclado e restaura o estado |
| Responsive | PASS | Nove capturas; sem overflow global nos três viewports |
| Blue | PASS | Nenhum merge, deploy ou mutação em `v2/production` |

## Validação técnica

- CI do PR `#59`: `1/1` PASS.
- Testes focados e regressivos: `79 passed`.
- Inventário transversal: `51` rotas `v2-clean` cobertas pela shell canónica.
- `compileall`: PASS.
- Alembic head: `fff37f8a9b0d`.
- Baseline arquitetural: PASS.
- Revisão independente: PASS após correções de ReturnContext, rotas de Vendas
  e fallback da feature flag.

## Limitações honestas

- A tabela da lista mantém scroll local em tablet/mobile porque o inventário é
  denso; o documento não tem overflow global.
- Os separadores do Pipeline usam scroll local em mobile para preservar todas
  as entradas e a ativação independente.
- `Processos de venda`, `Clientes/comerciantes` e `Publicações` ainda conservam
  conteúdo anterior; serão auditados/reconstruídos numa tranche posterior e
  não são apresentados como concluídos por esta evidência.
