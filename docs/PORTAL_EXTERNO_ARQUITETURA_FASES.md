# Portal Externo CarFast

## Decisao tecnica inicial

O portal externo deve nascer como uma camada controlada de entrada, sem acesso direto ao nucleo operacional da CarFast.

Para o MVP, a melhor opcao e manter o backend em FastAPI, dentro da arquitetura atual, mas com fronteiras claras:

- modelos proprios para utilizadores externos, entidades externas e pedidos externos;
- rotas publicas separadas das rotas internas;
- schemas proprios para entrada externa;
- servico de triagem/conversao que cria tarefas internas apenas apos validacao;
- auditoria de todos os eventos relevantes;
- sem anexos na primeira fase.

Nao se recomenda criar ja um backend separado em Node/NestJS. Isso duplicaria autenticacao, deploy, seguranca, logs, base de dados e manutencao antes de termos validado o fluxo operacional. A opcao mais segura e evolutiva e criar primeiro o dominio externo no backend atual e, mais tarde, ligar um frontend dedicado em React/Next.js ou PWA.

## Principio base

O portal externo nunca deve escrever diretamente nas tabelas operacionais.

Fluxo correto:

```text
Utilizador externo
  -> Portal externo
  -> API publica limitada
  -> Pedido externo
  -> Triagem interna
  -> Tarefa interna
  -> Operacao CarFast
  -> Estado resumido de volta ao portal
```

## Separacao de dominios

### Interno

Dominio previsto: `app.carfast.pt`

Utilizadores:

- operadores;
- supervisores;
- coordenadores;
- direcao;
- oficina interna.

Pode aceder a:

- tarefas internas;
- oficina;
- frota;
- importacoes;
- administracao;
- auditoria;
- relatorios.

### Externo

Dominio previsto: `portal.carfast.pt`

Utilizadores:

- clientes;
- parceiros;
- brokers;
- oficinas externas;
- franchisados;
- fornecedores.

Pode aceder apenas a:

- os seus pedidos;
- pedidos da sua entidade, quando autorizado;
- mensagens visiveis externamente;
- estados externos simplificados.

Nao pode aceder a:

- tarefas internas completas;
- comentarios internos;
- decisoes internas;
- historico operacional interno;
- anexos internos;
- administracao;
- importacoes;
- dados Rentway diretos.

## Modelo de dados proposto

### external_entities

Representa a entidade externa a que um utilizador pertence.

Campos iniciais:

- `id`
- `name`
- `entity_type`: customer, partner, broker, workshop, franchisee, supplier
- `tax_number`
- `email`
- `phone`
- `active`
- `created_at`
- `updated_at`

### external_users

Utilizadores do portal externo, separados de `users`.

Campos iniciais:

- `id`
- `external_entity_id`
- `name`
- `email`
- `password_hash`
- `profile`: customer, partner, broker, workshop, franchisee, supplier
- `active`
- `last_login_at`
- `created_at`
- `updated_at`

### external_requests

Tabela intermedia principal.

Campos iniciais:

- `id`
- `public_reference`
- `external_entity_id`
- `external_user_id`
- `source`
- `user_type`
- `category`
- `subcategory`
- `plate`
- `contract_number`
- `reservation_number`
- `station`
- `priority`
- `subject`
- `description`
- `contact_name`
- `contact_email`
- `contact_phone`
- `external_status`
- `internal_status`
- `triage_status`
- `internal_task_id`
- `assigned_internal_user_id`
- `created_at`
- `updated_at`
- `submitted_at`
- `converted_at`
- `closed_at`

Estados externos iniciais:

- `received`: Recebido
- `in_review`: Em analise
- `in_progress`: Em execucao
- `waiting_information`: A aguardar informacao
- `resolved`: Resolvido
- `closed`: Fechado

Estados de triagem:

- `pending`: Pendente
- `accepted`: Aceite
- `converted`: Convertido
- `rejected`: Rejeitado
- `duplicate`: Duplicado
- `no_action_needed`: Sem acao necessaria

### external_request_messages

Comunicacao controlada visivel no portal.

Campos iniciais:

- `id`
- `external_request_id`
- `author_type`: external, internal, system
- `external_user_id`
- `internal_user_id`
- `message`
- `visible_to_external`
- `created_at`

### external_request_events

Historico/auditoria do pedido externo.

Campos iniciais:

- `id`
- `external_request_id`
- `event_type`
- `old_value`
- `new_value`
- `metadata_json`
- `created_by_external_user_id`
- `created_by_internal_user_id`
- `created_at`

## Conversao para tarefa interna

Um pedido externo so passa para tarefa interna atraves de acao controlada.

Ao converter:

- cria `tasks.source = external_portal`;
- copia assunto, descricao, categoria, prioridade, matricula, contrato, reserva, estacao e contacto;
- define `tasks.external_source_id = external_requests.public_reference`;
- define `tasks.entity_type = external_request`;
- define `tasks.entity_id = external_requests.id`;
- regista evento em `external_request_events`;
- atualiza `external_requests.internal_task_id`;
- atualiza `external_requests.triage_status = converted`;
- sincroniza estado externo para `in_review` ou `in_progress`.

## Regras de seguranca do MVP

- Sem anexos.
- Limites de tamanho nos campos.
- Sanitizacao de HTML e scripts.
- Validacao rigorosa por schema.
- Rate limiting por IP e por utilizador externo.
- Login separado dos utilizadores internos.
- Passwords com hash igual ao sistema interno.
- Sessao/JWT separado do login interno.
- Logs de autenticacao, criacao, alteracao de estado e mensagens.
- O portal nunca devolve comentarios internos.
- O portal nunca devolve IDs internos sensiveis, exceto referencia publica.

## API publica inicial

Prefixo recomendado:

```text
/public
```

Rotas MVP:

- `POST /public/auth/login`
- `POST /public/auth/logout`
- `GET /public/me`
- `GET /public/requests`
- `POST /public/requests`
- `GET /public/requests/{public_reference}`
- `POST /public/requests/{public_reference}/messages`

Rotas internas de triagem:

- `GET /external-requests`
- `GET /external-requests/{id}`
- `POST /external-requests/{id}/convert-to-task`
- `POST /external-requests/{id}/reject`
- `POST /external-requests/{id}/mark-duplicate`
- `POST /external-requests/{id}/messages`

## Fases de implementacao

### Fase 0 - Arquitetura e contrato

Objetivo: fechar fronteiras antes de expor qualquer rota publica.

Entregaveis:

- modelo de dados;
- estados;
- regras de conversao;
- regras de seguranca;
- contrato inicial da API.

Estado recomendado: fazer antes de codigo operacional.

### Fase 1 - MVP interno controlado

Objetivo: permitir testar o fluxo sem expor dominio publico.

Entregaveis:

- modelos `external_entities`, `external_users`, `external_requests`, `external_request_messages`, `external_request_events`;
- migracao Alembic;
- pagina interna "Pedidos externos";
- criacao manual/simulada de pedido externo;
- conversao controlada em tarefa interna;
- auditoria;
- testes automatizados.

Este e o melhor proximo passo.

### Fase 2 - Portal externo simples

Objetivo: permitir login externo e criacao de pedidos reais.

Entregaveis:

- login externo;
- listagem dos pedidos do utilizador/entidade;
- formulario de novo pedido;
- detalhe com estado e mensagens externas;
- rate limiting basico;
- logs de seguranca.

### Fase 3 - Dominio e isolamento publico

Objetivo: preparar `portal.carfast.pt`.

Entregaveis:

- configurar dominio/subdominio;
- separar cookies/sessoes;
- rever CORS e headers de seguranca;
- Cloudflare/WAF;
- monitorizacao de erros;
- backups confirmados.

### Fase 4 - Comunicacao e notificacoes

Objetivo: reduzir e-mail solto e manter rastreabilidade.

Entregaveis:

- notificacoes por e-mail;
- templates;
- mensagens internas/externas separadas;
- sincronizacao de estado entre tarefa interna e pedido externo.

### Fase 5 - Anexos seguros

Objetivo: permitir documentos e evidencias sem aumentar risco.

Entregaveis:

- upload isolado;
- storage externo separado;
- validacao de extensao e tamanho;
- antivirus;
- quarentena;
- associacao posterior ao pedido.

## Decisoes adiadas

Estas decisoes devem ficar para depois do MVP:

- frontend Next.js dedicado;
- app/PWA;
- WhatsApp;
- Microsoft 365;
- uploads;
- IA;
- integracao direta com brokers;
- notificacoes push.

## Riscos principais

- abrir acesso externo cedo demais;
- misturar utilizadores externos com `users` internos;
- permitir anexos antes de haver validacao;
- expor comentarios internos;
- criar tarefas internas automaticamente sem triagem;
- duplicar tecnologia antes de validar processo.

## Recomendacao

Avancar primeiro com a Fase 1: base de dados, pagina interna de triagem e conversao para tarefa.

Isto permite testar o conceito com seguranca, sem expor ainda o portal ao exterior, e cria a fundacao correta para depois ligar `portal.carfast.pt`.
