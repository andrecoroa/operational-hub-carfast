# Centro de Tarefas — correção local de agrupamento e preview

Data: 2026-08-30  
Branch: `codex/fix-task-grouping-preview`  
Base canónica congelada: `origin/integration/modular-architecture@5e2b7a64ecfd37aa2e1b3f57a9e4ddc3cd0c4170`  
Referência cloud indisponível no remoto: `273d42d398ef3141c2ca2ccc8b88207b3fb4501e`

## Contrato congelado

- Proposta agrupada standalone SHA256: `76C518085A6A7BC4A266D81D2F3D38942B65B01226E67633A9E4AB6CB2E46D94`.
- Proposta v3 SHA256: `D0AE9B2B33F6BF7C44202392A47AF1733D661E72F7428CA5C71C5AFF14678FB1`.

## Matriz contrato → implementação → prova

| Contrato | Implementação | Prova |
|---|---|---|
| `grouping=category` sem HTTP 500 | `work_category_labels` obtido da hierarquia canónica antes da construção dos grupos | `tests/test_task_cases.py`; browser local autenticado, resposta 200 |
| Preview exclusivamente abaixo da linha/grupo | workbench único é montado após `tr` ou botão de grupo; workspace de uma coluna | testes estruturais; desktop e mobile sem overflow |
| Por casos só contém `TaskCase` persistidos | filtro `Task.case_id IS NOT NULL` aplicado antes de count/paginação; grupos sem fallback sintético | testes web/API de casos e browser com duas tarefas de caso; tarefa simples ausente |
| Tarefa simples fora de Por casos | vista vazia explica exclusão; ação criar/converter separada em disclosure secundário | testes de contagem/caso e captura desktop |
| ReturnContext e paginação preservados | query/contexto reaplicados nas ações e navegação; paginação usa total já filtrado | regressão focada e testes estruturais |
| Quatro ações primárias | abrir, alterar estado, comentar e solicitar suporte; criar caso é secundária | inspeção do DOM e teste contratual |
| Suporte autorizado, sem equipas inativas | alvos derivados do resolver server-side; tarefas sem `update` recebem lista vazia antes de qualquer cálculo | teste negativo de leakage; revisão independente |

## Browser sintético

- Desktop `1440×731`: Lista, Por categoria e Por casos; preview inline com intervalo de 1 px; overflow horizontal zero.
- Mobile `390×844`: largura útil 358 px; grupo 356 px; preview 354 px; quatro ações dentro do viewport; overflow zero.
- Teclado: Enter seleciona grupo/tarefa; setas mudam separador; foco e `aria-selected` verificados.
- Dados: fixtures locais identificáveis; nenhum dado real.

Capturas:

- `after-desktop-category-1440x731.png`
- `after-mobile-case-390x844.png`
- `contract-prototype-1440x731.png`

## Gates locais

- Focados Centro de Tarefas/casos: **41 PASS**.
- Revisão independente renovada: **zero P0/P1**; regressão do revisor **21 PASS**.
- `compileall`: **PASS**.
- Ruff exato do workflow: **PASS**.
- Baseline de arquitetura: **PASS**.
- Alembic: head único `fff6ab1c2d3e`.
- PostgreSQL local: upgrade → downgrade para `ffae1f2a3b4c` → upgrade: **PASS**, terminou em `fff6ab1c2d3e`.
- Bootstrap e instalação limpa: **PASS**, 17 tabelas.
- Suite integral exata: **FAIL — 45 falhas, 832 passes**. As falhas observadas são fora do diff desta tranche e incluem expectativas antigas de Alembic, Admin, Email, Frota, Documentação e Oficina. Não foram alteradas nem ocultadas.

## Gate e contenção

O código não foi publicado como PR pronto porque a autorização exige CI integral verde. Corrigir as 45 falhas transversais ampliaria indevidamente o âmbito. Green, Email, RBAC, schema e dados reais permaneceram intocados; não houve merge nem deploy.

