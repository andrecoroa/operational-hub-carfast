# Matriz de permissões da Administração CarFast

Auditoria realizada sobre `origin/v2/production` em 2026-08-20, incluindo `aaac1280`.
A matriz descreve o catálogo interno. As permissões do portal externo (`PortalInvitation` e
`PortalPublicationAccess.permissions_json`) pertencem a outro sujeito e fronteira de autorização;
não são lacunas nem aliases deste catálogo.

Estados usados:

- **ativa** — verificada em middleware, dependência/rota, ação ou menu;
- **alias legado** — preservada e expandida de forma aditiva em
  `app/services/authorization.py`; a concessão persistida não é reescrita;
- **parcial** — válida, mas combinada com um segundo nível (âmbito, caixa ou elegibilidade);
- **sem uso** — existe no catálogo, mas não foi encontrada aplicação específica;
- **em falta (resolvida)** — lacuna encontrada e preenchida nesta evolução.

| Código | Nome funcional | Módulo | Ações / rotas efetivas | Menu | Perfis iniciais | Estado | Substituição / evolução proposta |
|---|---|---|---|---|---|---|---|
| `dashboard.read` | Ver dashboard | Geral | `/`, `/v2-clean` | Início | todos | ativa | manter |
| `admin.manage` | Gerir Administração | Sistema | API `/admin/*`, toda a Administração Clean, bypass operacional controlado | Administração | Admin | alias legado | manter como compatibilidade; conceder granulares em novos perfis |
| `users.manage` | Gerir utilizadores | Geral | utilizadores, perfis, organização e revisão de acessos | Administração | legado/migrações | alias legado | `admin.users.*`, `admin.roles.*`, `admin.organization.*`, `admin.security.read` |
| `settings.manage` | Gerir parametrização | Sistema | configurações, modelos, integrações e auditoria de leitura | Administração | legado/migrações | alias legado | `admin.settings.*`, `admin.workshop_models.*`, `admin.integrations.*`, `admin.audit.read` |
| `admin.dashboard.read` | Visão geral administrativa | Geral | GET `/v2-clean/admin/overview` | Visão geral | User Admin, Funcional, Auditor | ativa | manter |
| `admin.users.read` | Consultar utilizadores | Geral | GET `/v2-clean/admin/users` | Utilizadores | User Admin, Auditor | ativa | manter |
| `admin.users.manage` | Gerir utilizadores/acessos | Geral | POST utilizadores e acessos | Utilizadores | User Admin | ativa | manter |
| `admin.users.credentials` | Credenciais temporárias | Sistema | POST password local | Utilizadores | User Admin | ativa | manter separada de gestão de acessos |
| `admin.roles.read` | Consultar perfis | Geral | GET `/v2-clean/admin/roles` | Perfis e permissões | User Admin, Auditor | ativa | manter |
| `admin.roles.manage` | Gerir perfis | Geral | POST perfis/permissões/estado | Perfis e permissões | User Admin | ativa | manter; Admin de sistema continua protegido |
| `admin.organization.read` | Consultar organização | Geral | GET unidades/equipas | Organização | User Admin, Auditor | ativa | manter |
| `admin.organization.manage` | Gerir organização | Geral | POST unidades/equipas | Organização | por concessão | ativa | manter |
| `admin.settings.read` | Consultar configurações | Sistema | GET catálogos e classificação | Configurações | Funcional, Auditor | ativa | manter |
| `admin.settings.manage` | Gerir configurações | Sistema | POST catálogos, valores, classificação, Email | Configurações | Funcional | ativa | separar futuramente por módulo sem quebrar este código |
| `admin.workshop_models.read` | Consultar modelos Oficina | Oficina | GET modelos/versionamento | Modelos da Oficina | Funcional, Auditor | ativa | manter |
| `admin.workshop_models.manage` | Gerir modelos Oficina | Oficina | criar/editar versões | Modelos da Oficina | Funcional | ativa | manter |
| `admin.workshop_models.publish` | Publicar modelos Oficina | Oficina | publicar versão | Modelos da Oficina | Funcional | ativa | manter |
| `admin.audit.read` | Consultar auditoria | Sistema | GET `/v2-clean/admin/audit` | Auditoria | Funcional, Auditor | ativa | manter |
| `admin.audit.export` | Exportar auditoria | Sistema | GET `/v2-clean/admin/audit/export` | Auditoria | Auditor | ativa | manter |
| `admin.integrations.read` | Consultar integrações | Sistema/Email | monitorização de intake | Integrações | Funcional, Auditor | ativa | manter |
| `admin.integrations.manage` | Gerir integrações | Sistema/Email | autorização de gestão; configuração atual não expõe segredos | Integrações | Funcional | parcial | manter até existir configuração mutável dedicada |
| `admin.integrations.credentials` | Credenciais de integrações | Sistema | nenhuma rota/ação específica encontrada | — | Admin via catálogo total | sem uso | aplicar apenas quando existir cofre/rotação; não reutilizar como `manage` |
| `admin.security.read` | Revisão de acessos | Sistema | GET `/v2-clean/admin/security` | Segurança e acessos | User Admin, Auditor | ativa | manter |
| `admin.security.manage` | Controlos de segurança | Sistema | reservado no middleware; sem formulário específico | Segurança e acessos | Admin | parcial | ligar apenas a ações concretas futuras |
| `admin.evolution.read` | Consultar Registo de Evolução | Geral | lista/detalhe, filtros, histórico, anexos/comentários | Registo de Evolução | Funcional, Auditor | em falta (resolvida) | nova permissão própria |
| `admin.evolution.manage` | Gerir Registo de Evolução | Geral | criar/editar/comentar/ligar documento/converter tarefa | Registo de Evolução | Funcional | em falta (resolvida) | nova permissão própria |
| `experience.legacy.access` | Abrir experiência anterior | Sistema | gate de rotas legacy | ligação lateral | Funcional e perfis operacionais | ativa | manter até retirada explícita da experiência anterior |
| `vehicles.read` | Consultar viaturas | Frota e Venda | GET Frota/API | Frota | Auditor, Gestor, Operador, Consulta | ativa | manter |
| `vehicles.write` | Editar viaturas | Frota e Venda | POST/PATCH Frota/API | Frota | Gestor, Operador | ativa | manter |
| `fleet.commerce.manage` | Gestão comercial da frota | Frota e Venda | venda/publicação/propostas | Venda de viaturas | Gestor | ativa | manter |
| `workshop.read` | Consultar Oficina | Oficina | GET Oficina | Oficina | Auditor, Gestor, Operador, Consulta | ativa | manter |
| `workshop.write` | Gerir Oficina | Oficina | POST Oficina | Oficina | Gestor, Operador | ativa | manter |
| `imports.run` | Executar importações | Sistema/Documentação | endpoints de importação | Importações | Gestor | ativa | manter |
| `imports.approve` | Aprovar importações | Sistema/Documentação | aprovação de importação | Importações | Admin/por concessão | ativa | manter |
| `tasks.read` | Consultar tarefas (API/legado) | Centro de Tarefas | REST `/tasks`, compatibilidade e origens | Centro de Tarefas | Auditor, Gestor, Operador, Consulta | ativa | manter; não expandir automaticamente para todos os workspaces |
| `tasks.write` | Editar tarefas (API/legado) | Centro de Tarefas | REST `/tasks`, origens e Email | Centro de Tarefas | Gestor, Operador | ativa | manter; ações Clean usam granulares + âmbito |
| `tasks.operational.read` | Consultar workspace Operacional | Centro de Tarefas | GET Clean operacional | Centro de Tarefas | Gestor, Operador, Consulta | ativa | manter |
| `tasks.operational.write` | Gerir workspace Operacional | Centro de Tarefas | POST Clean operacional | Centro de Tarefas | Gestor, Operador | ativa | manter |
| `tasks.workshop.read` | Consultar workspace Oficina | Centro de Tarefas/Oficina | GET Clean Oficina | Centro de Tarefas | Gestor, Operador | ativa | manter |
| `tasks.workshop.write` | Gerir workspace Oficina | Centro de Tarefas/Oficina | POST Clean Oficina | Centro de Tarefas | Gestor, Operador | ativa | manter |
| `tasks.audit.read` | Consultar antiga fila Auditoria | Centro de Tarefas | sem workspace atual próprio | — | Auditor, Gestor, Operador, Consulta | alias legado | `tasks.administration.read` |
| `tasks.audit.write` | Gerir antiga fila Auditoria | Centro de Tarefas | sem workspace atual próprio | — | Auditor, Gestor, Operador | alias legado | `tasks.administration.write` |
| `tasks.assign.peer` | Atribuir ao mesmo nível | Centro de Tarefas | validação hierárquica de responsável | Centro de Tarefas | Gestor | ativa | manter |
| `tasks.administration.read` | Consultar workspace Administração | Centro de Tarefas/Geral | GET Clean Administração | Centro de Tarefas | Gestor, Operador | ativa | substitui `tasks.audit.read` |
| `tasks.administration.write` | Gerir workspace Administração | Centro de Tarefas/Geral | POST Clean Administração | Centro de Tarefas | Gestor, Operador | ativa | substitui `tasks.audit.write` |
| `tasks.management.read` | Consultar workspace Gestão | Centro de Tarefas | GET Clean Gestão | Centro de Tarefas | Gestor | ativa | manter |
| `tasks.management.create` | Criar em Gestão | Centro de Tarefas | criação Clean Gestão | Centro de Tarefas | Gestor | ativa | manter |
| `tasks.management.update` | Alterar em Gestão | Centro de Tarefas | edição Clean Gestão | Centro de Tarefas | Gestor | ativa | manter |
| `tasks.management.close` | Fechar/reabrir em Gestão | Centro de Tarefas | decisão de fecho | Centro de Tarefas | Gestor | ativa | manter |
| `tasks.recurring.manage` | Gerir recorrências | Centro de Tarefas | `/v2-clean/tasks/recurring` | Centro de Tarefas | Gestor | ativa | manter |
| `service_desk.read` | Consultar tickets | Service Desk | gate Clean + alias para leitura operacional; âmbito `can_read` | Centro de Tarefas | Funcional, Gestor, Operador, Consulta | parcial | manter como capacidade geral; âmbito decide objetos |
| `service_desk.create` | Criar tickets | Service Desk | gate Clean + alias escrita operacional; âmbito `can_create` | Centro de Tarefas | Funcional, Gestor, Operador | parcial | manter |
| `service_desk.assume` | Assumir tickets | Service Desk | gate Clean; âmbito `can_assume` | Centro de Tarefas | Funcional, Gestor, Operador | parcial | manter |
| `service_desk.assign` | Atribuir tickets | Service Desk | supervisão/atribuição; âmbito `can_assign` | Centro de Tarefas | Funcional, Gestor | parcial | manter |
| `service_desk.update` | Alterar tickets | Service Desk | gate Clean; âmbito `can_update` | Centro de Tarefas | Funcional, Gestor, Operador | parcial | manter |
| `service_desk.respond` | Responder em tickets | Service Desk | gate Clean; âmbito `can_respond` | Centro de Tarefas | Funcional, Gestor, Operador | parcial | manter |
| `service_desk.complete` | Concluir tickets | Service Desk | supervisão/fecho; âmbito `can_complete` | Centro de Tarefas | Funcional, Gestor, Operador | parcial | manter |
| `service_desk.sla.manage` | Gerir SLA tickets | Service Desk | gate Clean; âmbito `can_manage_sla` | Centro de Tarefas | Funcional, Gestor | parcial | manter |
| `service_desk.classifications.manage` | Administrar classificação | Service Desk | Administração Clean com restrição `can_administer_classifications` | Filas e classificação | Funcional | ativa | middleware corrigido para coincidir com botões/rota |
| `documents.read` | Consultar documentos | Documentação | GET Documentação/API | Documentação | Auditor, Gestor, Operador, Consulta | ativa | manter |
| `documents.write` | Gerir documentos | Documentação | POST Documentação/API | Documentação | Gestor, Operador | ativa | manter |
| `email.read` | Capacidade geral de consulta | Email | entrada no módulo; exige também acesso a caixa | Email | Funcional e perfis configurados | parcial | manter separada de `EmailChannelRole.can_read` |
| `email.triage` | Triagem geral | Email | ações de classificação; exige caixa | Email | Funcional | parcial | manter |
| `email.reply` | Preparar resposta | Email | composer; exige `can_reply` na caixa | Email | Funcional | parcial | manter |
| `email.approve` | Aprovar/enviar | Email | aprovação; exige `can_approve` na caixa | Email | Funcional | parcial | manter |
| `email.manage` | Gerir Email | Email | gestão operacional; `can_manage` na caixa | Email | Funcional | parcial | manter |
| `email.assume` | Assumir conversa | Email | ação de claim; `can_assume` + elegibilidade | Email | Funcional | parcial | manter |
| `email.assign` | Atribuir conversa | Email | atribuição; `can_assign` + elegibilidade | Email | Funcional | parcial | manter |
| `email.sla.manage` | Gerir SLA Email | Email | prazos; `can_manage_sla` na caixa | Email | Funcional | parcial | manter |
| `stock.read` | Consultar Stock | Stock | GET Stock | Stock | Funcional, Auditor e operacionais | ativa | manter |
| `stock.operate` | Operar Stock | Stock | artigos/receções/movimentos | Stock | Operador por perfil | ativa | manter |
| `stock.manage` | Administrar Stock | Stock | fornecedores/mínimos/acertos/configuração | Stock | Funcional, Gestor | ativa | manter |
| `stock.orders.manage` | Gerir encomendas | Stock | encomendas | Stock | perfis operacionais | ativa | manter |
| `stock.inventory.count` | Contagem de inventário | Stock | sessões de contagem | Stock | perfis operacionais | ativa | manter |
| `stock.inventory.confirm` | Confirmar inventário | Stock | diferenças/acertos | Stock | gestores | ativa | manter |
| `stock.compatibility.manage` | Compatibilidade artigo-viatura | Stock/Frota | compatibilidades | Stock | Funcional | ativa | manter |
| `stock.conference` | Conferir documentos | Stock/Documentação | conferência | Stock | perfis operacionais | ativa | manter |
| `management_center.read` | Consultar Centro de Gestão | Geral | GET processos | Centro de Processos | Gestor | ativa | manter |
| `management_center.write` | Gerir Centro de Gestão | Geral | POST processos | Centro de Processos | Gestor | ativa | manter |

## Camadas que complementam o catálogo

| Camada | Chave | Regra efetiva | Gestão |
|---|---|---|---|
| Âmbito de trabalho | `RoleWorkScope` | fila → departamento → categoria → subcategoria + ações + visibilidade | Administração / Centro de Tarefas |
| Caixa por perfil | `EmailChannelRole` | consultar, responder, enviar diretamente, aprovar, assumir, atribuir, SLA, gerir + visibilidade | matriz e lote Email |
| Exceção por utilizador | `EmailChannelUser` | acesso implícito e exceções responder/aprovar/assumir/atribuir/SLA | explicitamente marcada como exceção |
| Elegibilidade Email | `EmailExecutorEligibility` | utilizador ou equipa por caixa e categoria | gestão unitária e em lote |
| Elegibilidade Service Desk | `ServiceDeskCategoryExecutor` | utilizador ou equipa por categoria | Filas e classificação |
| Portal externo | `permissions_json` | publicação/organização externa | Administração do portal; catálogo separado |

## Decisões de compatibilidade

1. Não são removidas permissões, perfis, âmbitos nem concessões existentes.
2. `admin.manage`, `users.manage` e `settings.manage` expandem apenas para equivalentes
   administrativos documentados; o Super Admin continua com todo o catálogo persistido.
3. `tasks.audit.*` torna-se alias runtime de `tasks.administration.*`; os códigos permanecem
   consultáveis e atribuíveis durante a migração.
4. `service_desk.*` participa no gate Clean e resolve para o workspace Operacional; as ações
   continuam dependentes de `RoleWorkScope`, não apenas da capacidade geral.
5. `tasks.read/write` permanecem ativos na API e integrações e não são expandidos para todos os
   workspaces, evitando aumento silencioso de privilégio.
6. Botões e endpoints novos usam a mesma autorização server-side. A UI nunca é a barreira de
   segurança.
