# Inventário prévio — reorganização da Administração

Data: 2026-08-21

Base auditada: `origin/v2/production` em `986189a101f53546b72a4b61869f688df354cd56`

Âmbito: experiência Clean, Administração, Operações/Service Desk, Email e Registo de Evolução.

Este inventário foi concluído antes das alterações funcionais. A análise foi feita sobre uma
worktree limpa; a árvore de trabalho original, que contém alterações alheias, não foi usada nem
modificada.

## Superfícies e rotas preservadas

| Superfície | Rotas atuais | Dados/regras reutilizados | Estado/decisão |
|---|---|---|---|
| Administração Clean | `/v2-clean/admin/*` | `clean_admin.py`, `clean_admin.html`, autorização granular | principal; reorganizar apresentação |
| Administração legacy | `/admin`, `/admin/roles`, `/admin/permissions` | API e templates anteriores | legado ainda referenciado; manter |
| Centro de Tarefas | `/v2-clean/tasks`, `/task-board`, REST `/tasks` | `Task` e tabelas de histórico/âmbito/SLA | manter; não duplicar |
| Centro de Processos | `/v2-clean/processes`, `/management-center` | `ManagementProcess*`, tarefas e associações | manter; expor por ligação |
| Email | `/v2-clean/email/*` | canais, regras, mensagens, anexos, elegibilidade e auditoria | manter; expor configuração existente |
| Service Desk | Centro de Tarefas + Administração `work-classification` | `Task`, `RoleWorkScope`, políticas, supervisores e executores | manter; centralizar acessos |
| Evolução | `/v2-clean/admin/evolution*` | `EvolutionRecord` + comentários, histórico e documentos | manter e estender de modo aditivo |

## Páginas administrativas e campos

| Página | Campos/ações inventariados | Permissões server-side atuais |
|---|---|---|
| Visão geral | métricas, atividade recente | `admin.dashboard.read`, aliases administrativos |
| Utilizadores | nome, email, password temporária, estado, perfis, áreas, equipas | `admin.users.read/manage/credentials` |
| Perfis e permissões | código, nome, descrição, estado, catálogo completo de permissões | `admin.roles.read/manage` |
| Organização | unidade: código, nome, tipo, superior, ordem, estado; equipa: código, nome, unidade, estado | `admin.organization.read/manage` |
| Configurações | catálogo: código, nome, descrição, estado; valor: código, etiqueta, descrição, cor, ordem, estado | `admin.settings.read/manage` |
| Filas e classificação | filas, departamentos, categorias, subcategorias, âmbitos, tipos de ticket, políticas, SLA, supervisores, executores, canais, regras de caixa, acesso por perfil/utilizador, modelos e defaults | leitura/gestão de settings + `service_desk.classifications.manage`; âmbito verificado nas operações |
| Modelos da Oficina | modelos, versões, publicação e ativação | `admin.workshop_models.read/manage/publish` |
| Integrações | estado de configuração, intakes, anexos, encaminhamento e erros | `admin.integrations.read/manage` |
| Segurança e acessos | modo de autenticação, admins ativos, contas sem perfil/âmbito | `admin.security.read/manage` |
| Auditoria | pesquisa, ação, entidade, utilizador, intervalo de datas, exportação | `admin.audit.read/export` |
| Evolução | tipo, módulo, título, descrição, origem, prioridade, estado, decisão, notas, responsável, equipa, tarefa/chat/branch/commit, comentários e documentos | `admin.evolution.read/manage` |

## Tabelas e histórico relevante

Não é criada uma segunda fonte de verdade para tarefas, processos, Email, permissões ou
auditoria. As estruturas seguintes são as referências canónicas encontradas:

- identidade e RBAC: `users`, `roles`, `permissions`, `user_roles`, `role_permissions`;
- organização: `organizational_units`, `user_organizational_units`, `teams`, `team_members`;
- parametrização/auditoria: `settings_catalogs`, `settings_values`, `audit_logs`;
- trabalho: `tasks`, `task_comments`, `task_documents`, `task_history`,
  `task_assignment_events`, `task_sla_events`, `task_participants`, `quick_records`;
- classificação/Service Desk: `work_queues`, `work_departments`, `work_categories`,
  `work_subcategories`, `role_work_scopes`, `service_desk_ticket_types`,
  `service_desk_category_policies`, `service_desk_category_supervisors`,
  `service_desk_category_executors`, `work_source_defaults`;
- Email: `email_channels`, `email_channel_roles`, `email_channel_users`,
  `email_executor_eligibilities`, `email_inbox_rules`, `email_templates`, `email_threads`,
  `email_messages`, `email_message_deliveries` (aditiva nesta alteração), `email_attachments`,
  `email_webhook_events`, `email_audit_events`;
- processos: `management_process_types`, `management_processes`,
  `management_process_associations`, `management_rules`, `management_actions`,
  `management_evidences`, `management_history`;
- evolução: `evolution_records`, `evolution_record_comments`,
  `evolution_record_history`, `evolution_record_documents`.

O Registo de Evolução já preserva autor, responsável, ligações a tarefa/documento, comentários e
histórico por campo. A extensão deve reutilizar estas tabelas, sem migrar ou reescrever registos.

## Permissões e regras de autorização

A matriz detalhada existente está em `docs/ADMIN_PERMISSION_MATRIX.md`. Foram confirmadas as
seguintes camadas cumulativas:

1. middleware por rota em `app/main.py`;
2. autorização explícita nas rotas de `app/web/clean_admin.py`;
3. permissões RBAC e aliases aditivos em `app/services/authorization.py`;
4. âmbito por fila/departamento/categoria/subcategoria em `RoleWorkScope`;
5. capacidade por caixa em `EmailChannelRole`/`EmailChannelUser`;
6. elegibilidade de execução em `EmailExecutorEligibility` e
   `ServiceDeskCategoryExecutor`;
7. auditoria das mutações por `record_audit` e históricos específicos.

A UI não é considerada barreira de segurança. Toda nova ação deve repetir a validação no
servidor.

## Duplicações, legado e itens parciais

| Elemento | Evidência | Classificação/decisão |
|---|---|---|
| Administração legacy e Clean | ambas têm rotas e referências de navegação | duplicação de experiência, não de dados; manter legacy |
| páginas legacy/Clean de tarefas e processos | rotas e templates continuam ativos | compatibilidade; manter |
| `quick_records` vs `evolution_records` | o primeiro é ocorrência operacional; o segundo é backlog de evolução com decisão/histórico | conceitos distintos; não consolidar fisicamente |
| `tasks.audit.*` | alias runtime para `tasks.administration.*`; sem workspace próprio | alias legado; manter e não mostrar como destino novo |
| `admin.manage`, `users.manage`, `settings.manage` | aliases ainda concedidos e verificados | compatibilidade; manter |
| `admin.integrations.credentials` | catálogo sem ação específica | sem uso comprovado; manter inativo, não remover |
| `admin.security.manage` | gate existente sem formulário mutável específico | parcial; manter reservado |
| tipos de evolução | tipos atuais não cobrem literalmente erro, decisão e implementação futura | estender constraint/labels de modo aditivo |
| anexos no registo rápido | documentos podem ser ligados na gestão completa; upload genérico seguro não existe nesta superfície | não improvisar upload; manter ligação documental administrativa |

## Saneamento decidido antes da implementação

- **Preservar:** todas as tabelas, rotas, dados, históricos, aliases e páginas legacy.
- **Consolidar:** apenas a navegação, agrupando links para as superfícies canónicas existentes.
- **Inativar:** nada nesta alteração; os códigos sem ação continuam documentados/reservados.
- **Remover:** nada. Não há inspeção de dados de produção nem evidência suficiente para apagar
  estruturas com segurança.
- **Proteção:** novos códigos e tipos serão aditivos; não será feita reescrita de concessões nem
  de registos históricos.

## Baseline de validação

- Alembic: head único `ffcf2a3b4c5d`.
- Testes focados de Administração/Evolução: passaram no baseline.
- Suite alargada focada: 28 passaram e 5 falharam antes das alterações. As 5 falhas são de
  colisão preexistente em `/tasks`: pedidos REST recebem a página HTML Clean. Esta reorganização
  não deve ocultar nem ampliar esse problema fora do seu âmbito.

## Adenda urgente — entrega lógica de Email e Reply All

Inventário efetuado antes de alterar a ingestão Postmark:

- `EmailWebhookEvent.event_key` é único, mas `_event_key()` usa o `MessageID` atribuído pelo
  Postmark. Duas entregas técnicas da mesma mensagem original podem, portanto, passar como
  eventos distintos.
- `EmailMessage` já conserva `ToFull`, `CcFull` e os cabeçalhos da entrega escolhida em
  `recipients_json`, `cc_json` e `headers_json`; a mensagem apresentada não mostra `Para`/`Cc`.
- O payload bruto de cada webhook fica em `EmailWebhookEvent.payload_json`, mas não existe uma
  relação entre o evento de entrega e a mensagem lógica criada. Assim, não é possível auditar
  de forma estruturada todas as caixas originais, aliases de entrada, `MailboxHash` e IDs
  técnicos Postmark que originaram a mesma mensagem.
- `_channel_for_payload()` dá precedência ao `MailboxHash`. Isto é adequado para definir o
  perímetro de autorização da entrega, mas não constitui uma chave de identidade da mensagem.
- A resposta atual aceita um destinatário editável e envia apenas `To`; não existe semântica de
  `Responder a todos`, nem exclusão central de endereços/aliases internos.

### Decisão de segurança e modelo

- Introduzir uma tabela aditiva de entregas, ligada a `EmailMessage`, `EmailChannel` e
  `EmailWebhookEvent`. Cada entrega mantém o ID técnico, chave lógica, `To`, `Cc`, destinatário
  original, alias técnico e cabeçalhos no evento bruto já preservado.
- A primeira entrega é marcada canónica e fica protegida por unicidade parcial
  `(channel_id, logical_key)`. Entregas seguintes com a mesma chave **e a mesma caixa funcional**
  apontam para a mensagem canónica; os destinatários são unidos sem criar nova conversa.
- A mesma chave numa **caixa funcional diferente** cria uma mensagem/conversa independente nesse
  perímetro. As entregas partilham apenas a chave técnica de correlação para auditoria. A UI e as
  pesquisas de utilizador não atravessam caixas, evitando expor conteúdo a perfis sem acesso.
- A chave lógica prefere o RFC `Message-ID` original. Sem esse cabeçalho, só é usada uma chave de
  fallback quando existe data original, combinando remetente, assunto/data normalizados e hashes
  de corpo/anexos. Na ausência de dados suficientes, mantém-se o ID Postmark para não colapsar
  mensagens legítimas por suposição.
- `Responder a todos` será calculado novamente no servidor a partir da última mensagem recebida:
  remetente em `To`, destinatários externos originais em `Cc`, sem duplicados, excluindo todas as
  caixas/aliases configuradas e o endereço selecionado em `De`. A edição manual de um único
  destinatário continua disponível em `Responder` por compatibilidade.

Não será apagado nem reescrito qualquer evento, mensagem, anexo ou conversa histórica. Mensagens
anteriores à migração permanecem válidas mesmo sem linhas de entrega estruturada.

## Resultado final de saneamento e evidência

| Resultado | Elementos | Evidência |
|---|---|---|
| **Preservado** | rotas e páginas legacy/Clean; tabelas e histórico de Administração, tarefas, processos, Email e Evolução; aliases e permissões atuais; mensagens, anexos e payloads webhook | não há `DROP TABLE`, `DELETE` ou reescrita de dados nas funções `upgrade`; os testes de idempotência confirmam uma linha de evento/entrega para o mesmo webhook e duas entregas para dois IDs Postmark |
| **Consolidado** | navegação administrativa por sete domínios; Operações e Service Desk reúne links para centros canónicos; entregas da mesma mensagem lógica na mesma caixa apontam para uma mensagem/conversa | `ADMIN_DOMAIN_DEFINITIONS`; rota `/v2-clean/admin/operations`; `email_message_deliveries` com unicidade canónica por caixa/chave; testes de duas entregas e um único `EmailMessage`/`EmailThread` |
| **Inativado** | nada | não foi encontrada evidência suficiente para inativar campos, permissões, rotas ou tabelas; os códigos parciais continuam reservados/documentados |
| **Removido** | nada | nenhuma estrutura foi considerada comprovadamente sem uso e sem histórico; não existem menus, campos ou permissões apagados |

Alterações aditivas verificáveis:

- `admin.evolution.create` permite criar pelo `+` global; leitura, edição e priorização continuam
  protegidas por `admin.evolution.read/manage` ou `admin.manage` no servidor.
- os novos tipos de Evolução coexistem com `problem` e `feature`, marcados como legado na gestão;
- `email_message_deliveries` liga cada payload bruto à mensagem e caixa, conserva destinatário
  original, destino técnico, alias/hash de entrada, `To`, `Cc` e IDs Postmark;
- a UI apresenta `Para`, `Cc` e `Recebido originalmente em` com expansão compacta;
- Reply All é recalculado no servidor e o Postmark recebe `To` e `Cc` separados;
- cópias entre caixas funcionais ficam isoladas por autorização e recebem auditoria
  `inbound_logical_copy_isolated`; não existe pesquisa transversal dessa correlação na UI;
- o downgrade das migrações recusa remover tipos ou entregas que já contenham histórico.

Validação final executada na worktree isolada:

- Alembic: head único `ffe04c5d6e7f`;
- testes focados de Administração, Evolução, Email e migrações: `47 passed`;
- `py_compile`: passou em todos os ficheiros Python alterados;
- Ruff: passou nos ficheiros novos e nos alterados, ignorando apenas `E501`/`F841` já existentes
  nos módulos históricos volumosos;
- `git diff --check`: passou (apenas avisos de conversão LF/CRLF do ambiente Windows);
- QA visual desktop e 390 × 844: pesquisa/domínios, ação global, modal rápido, mensagem deduplicada,
  `Para`/`Cc`/origens e Reply All; sem overflow horizontal no móvel.

Limitações deliberadas e seguras:

- anexos no registo rápido não foram adicionados porque a superfície atual não oferece upload
  genérico com o mesmo arquivo, autorização e auditoria da gestão completa;
- mensagens históricas não são inferidas retroativamente: continuam intactas, sem inventar
  relações de entrega ausentes;
- as cinco falhas baseline de `tests/test_service_desk_api_security.py`, causadas pela colisão
  preexistente da rota `/tasks`, permanecem documentadas e fora desta alteração.
