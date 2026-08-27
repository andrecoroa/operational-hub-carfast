# Centro de Tarefas — guardrails consolidados

## Implementado e comprovável sem novo contrato

- Lista, pesquisa, contadores, preview e ações reutilizam permissões de workspace, filtro de visibilidade e `RoleWorkScope` server-side. As ações continuam a revalidar o âmbito no POST.
- O conjunto terminal canónico atual é `closed`, `cancelled` e `no_action_needed`; o default exclui os três e a consulta de terminais é explícita.
- Owner/equipa, executor individual, por atribuir, participantes e pedidos de apoio permanecem conceitos distintos. Pedir apoio não reatribui a tarefa nem reinicia o SLA.
- Opções de tarefa-tipo e o POST usam a mesma autoridade `TaskCreationCapabilityResolver`.
- O preview consome o estado global do snapshot SLA existente e mostra condicionalmente origem, processo e tarefa mãe, sem adicionar colunas à linha ou criar um segundo relógio.
- Alterações existentes de atribuição, categoria, prioridade e estado mantêm `TaskHistory`/eventos de atribuição com valores anterior/novo; ReturnContext preserva filtros, categoria, seleção e scroll.

## Findings — proposta futura, sem código nesta tranche

- Não existe hoje uma taxonomia canónica completa e configurável com capacidades separadas `read/create/triage/assign/reassign/execute/validate/complete/reopen/manage` para todos os workspaces. O runtime combina permissões existentes com `RoleWorkScope`; há compatibilidade histórica por códigos de role em partes do filtro e em templates que declarem `allowed_role_codes`. Substituir essa compatibilidade exige decisão de contrato e migração de configuração, fora desta tranche.
- Os tipos futuros “Pedido simples / Informação-Comunicação simples / Tarefa completa / Mais opções” não têm ainda contrato de criação aprovado. O botão `Nova tarefa` fica explicitamente desativado e marcado para a tranche futura; não aponta para um fluxo inexistente nem simula o seletor.
- Estados “Atualizada” e “Apoio solicitado”, automatizações por comentário, duplo SLA e novas regras de supervisão não foram criados.
