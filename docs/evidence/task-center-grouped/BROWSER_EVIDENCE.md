# Evidência browser local — casos/agrupamento

## Ambiente

- Aplicação local: `http://127.0.0.1:8765`, PostgreSQL 17 sintético `carfast_task_cases_test`.
- Flags apenas locais: `TASK_CASES_ENABLED=true`, `VISUAL_FOUNDATION_ENABLED=true`.
- Utilizador, permissões, scope, casos e tarefas exclusivamente sintéticos; nenhuma ligação a Green ou dados reais.
- Email inbound/outbound desativado.

## Fluxos executados

1. `Novo caso` → título `Caso browser sintético` + `Primeira tarefa browser`: PASS; o caso apareceu com uma tarefa e não aumentou a contagem de tarefas.
2. `+ Nova tarefa neste caso` → `Segunda tarefa browser`: PASS; o mesmo caso passou a duas tarefas.
3. Tarefa original sem caso → `+ Criar tarefa relacionada` → `Caso relacionado browser` + `Tarefa relacionada browser`: PASS; original e nova tarefa apareceram no mesmo caso.

O primeiro ensaio do fluxo 2 falhou fechado porque o utilizador sintético inicial tinha permissões mas não um `RoleWorkScope` de trabalho coerente. Foi criado um scope apenas nessa instalação local; não houve alteração de código nem grant nominal no produto. O fluxo repetido passou.

## Geometria e acessibilidade

- 1440×731: documento 1440×731; `main` 1232×731 depois da sidebar de 208 px; `scrollWidth=1440`; zero overflow horizontal.
- 390×844 em agrupamento `case`: documento 390×844; `scrollWidth=390`; zero overflow horizontal; navegação colapsada.
- Foco inicial do modal no título do caso; `Tab` avançou para o assunto.
- Linha de tarefa selecionável com `Enter`; `aria-selected=true` e foco mantido na tarefa selecionada.
- Agrupamento por caso, preview na linha e workbench foram verificados na mesma superfície.
- A revisão independente detetou inicialmente texto herdado claro sobre os filhos brancos do agrupamento (P1). A regra passou a definir `rgb(29, 41, 57)` e foco visível; as capturas desktop e responsiva foram repetidas no modo `case` após a correção.

## Capturas

- `screenshots/live-1440x731.png`
- `screenshots/grouped-workbench-1440x731.png`
- `screenshots/live-responsive-390x844.png`

O browser recusou a navegação direta para o `file://` da referência standalone por política de segurança. A restrição não foi contornada. A referência continua congelada pelos dois SHA-256 registados na matriz e foi comparada por inspeção integral do HTML e mapeamento contrato→implementação→teste.
