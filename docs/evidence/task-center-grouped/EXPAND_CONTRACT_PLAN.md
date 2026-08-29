# Centro de Tarefas agrupado/casos — plano expand/contract

## Referência congelada

- Standalone: `task-center-grouped-proposal-standalone.html`
  - SHA-256: `76C518085A6A7BC4A266D81D2F3D38942B65B01226E67633A9E4AB6CB2E46D94`
- Fragmento editável: `task-center-grouped-proposal.html`
  - SHA-256: `BD9BC6A3975947DAAA427EB763A627FEAE8E488F9354A095B5AA3FBC01B3A4D6`
- Base canonical: `origin/integration/modular-architecture` em
  `7aadc5a49e8be0bc21ef03e1334cb9bb49f1b9b4`.

## Diagnóstico do modelo atual

- `Task` já é a unidade contabilizada e auditada; `parent_task_id` tem semântica própria e não será reutilizado.
- Não existe contentor de caso nem FK de caso.
- O mecanismo RBAC suporta permissões catalogadas sem atribuição automática a roles.
- A visibilidade por fila/scope já é centralizada no Centro de Tarefas e deve ser aplicada antes do agrupamento.
- O backend usa uma sessão por request, permitindo executar cada fluxo manual numa única transação.

## Expand

1. Criar tabela aditiva `task_cases`, sem hierarquia e sem contagem operacional própria.
2. Adicionar `tasks.case_id` anulável com `ON DELETE SET NULL` e índices para listagem/agrupamento.
3. Catalogar `cases.read`, `cases.create` e `cases.update`, sem inserir `role_permissions`.
4. Adicionar feature flag `task_cases_enabled`, OFF por defeito.
5. Implementar serviço transacional com três comandos explícitos:
   - novo caso + primeira tarefa;
   - nova tarefa num caso existente;
   - tarefa relacionada: criar caso com tarefa original + nova tarefa.
6. Auditar criação/associação nas histórias das tarefas e no registo de auditoria do caso.
7. Expor agrupamentos `category`, `case` e `flat`, sempre depois de autorização, fila e filtros.
8. Renderizar preview na linha e manter filtros, ordenação e ReturnContext.

## Contract

- Não remover nem reinterpretar colunas existentes nesta tranche.
- O downgrade remove apenas FK/índices/coluna/tabela/permissões criadas pela migration; não apaga tarefas.
- Em instalações onde já existam associações, o downgrade falha fechado antes de remover `case_id`, preservando os dados para decisão explícita.
- A flag OFF mantém a experiência anterior e impede endpoints de casos.
- Administração continua dependente das permissões existentes da fila; `cases.*` não amplia esse acesso.

## Gates

- Migration upgrade/downgrade/upgrade em PostgreSQL isolado e uma única head.
- Testes positivos/negativos dos três fluxos, atomicidade, scopes, Administração, auditoria e contagens.
- Testes web de agrupamento, filtros, ordenação, preview e ReturnContext.
- Browser sintético a 1440×731 e responsivo, sem dados reais.
- Matriz contrato→prova, regressão integral, CI e revisão independente zero P0/P1.
- Sem merge, deploy, Green, Email, grants RBAC nominais ou dados reais.
