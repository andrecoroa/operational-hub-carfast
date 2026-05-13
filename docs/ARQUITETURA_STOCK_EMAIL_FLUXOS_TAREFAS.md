# CarFast v2 - Stock, e-mail e fluxos por tarefa

Documento de trabalho para validacao antes de implementar.

Objetivo: definir uma base simples, escalavel e sem excesso de complexidade para tres areas que vao tocar no nucleo operacional da app:

- gestao de stocks;
- envio e rececao de e-mails;
- fluxos configuraveis por tarefa, montados por blocos de acao.

## Principio geral

A app deve evitar criar um ERP paralelo ao Rentway. O objetivo e controlar trabalho, evidencias, responsabilidades, comunicacao, tarefas, decisoes e seguimento.

Para esta fase, a decisao recomendada e:

- stock: controlar pedidos, movimentos e disponibilidade operacional, sem tentar substituir contabilidade ou compras completas;
- e-mail: comecar por envio manual registado e fila de saida, antes de automatizar leitura de caixas;
- fluxos: criar um motor de blocos configuraveis, mas executar primeiro de forma assistida pelo utilizador.

## 1. Gestao de stock

### Objetivo operacional

Permitir saber o que existe, onde esta, o que foi pedido, o que foi consumido e que processos/tarefas justificaram o movimento.

### Fase 1 - minimo util

Entidades propostas:

| Entidade | Objetivo | Observacoes |
|---|---|---|
| stock_items | Artigos ou referencias | Pode comecar simples: nome, referencia interna, categoria, unidade, ativo |
| stock_locations | Locais de stock | Ex.: oficina, aeroporto, armazem, viatura apoio |
| stock_balances | Quantidade atual por artigo/local | Pode ser calculado por movimentos, mas guardar snapshot facilita leitura |
| stock_movements | Entradas, saidas, ajustes, transferencias | Sempre com motivo e origem |
| stock_requests | Pedidos de material | Ligado a tarefa, processo de oficina ou viatura |
| suppliers | Fornecedores | Ja previsto na arquitetura; usar de forma leve |

Campos minimos:

### stock_items

- id
- code
- name
- category
- unit
- minimum_quantity
- active
- notes

### stock_locations

- id
- name
- location_type
- active

### stock_movements

- id
- item_id
- from_location_id
- to_location_id
- movement_type: entrada, saida, transferencia, ajuste, consumo
- quantity
- reason
- task_id
- workshop_process_id
- vehicle_id
- supplier_id
- document_id
- created_by_id
- created_at

### stock_requests

- id
- item_id
- requested_quantity
- approved_quantity
- status: rascunho, pedido, aprovado, parcial, recebido, cancelado, sem necessidade
- priority
- task_id
- workshop_process_id
- vehicle_id
- requested_by_id
- assigned_to_id
- due_on
- notes
- created_at

### Fluxo simples de stock

1. Operador identifica necessidade.
2. Cria pedido de stock a partir de tarefa, oficina ou manual.
3. Responsavel valida.
4. Pode gerar:
   - movimento de reserva;
   - movimento de consumo;
   - tarefa para encomendar material;
   - e-mail para fornecedor.
5. Quando material chega, regista entrada ou rececao parcial.
6. Consumo fica associado ao processo/tarefa/viatura.

### O que nao fazer ja

- Nao criar compras completas.
- Nao criar faturacao de fornecedores.
- Nao tentar reconciliar automaticamente com contabilidade.
- Nao criar estrutura de armazem demasiado detalhada antes de uso real.

## 2. Envio e rececao de e-mails

### Objetivo operacional

Centralizar e-mails relevantes dentro das tarefas, mantendo historico, responsavel e contexto.

### Abordagem recomendada

Comecar pelo envio controlado pela app e so depois evoluir para leitura automatica de caixas.

Motivo: enviar um e-mail a partir de uma tarefa e guardar o historico e mais simples e seguro do que tentar interpretar todas as caixas logo no inicio.

### Fase 1 - envio manual registado

Entidades propostas:

| Entidade | Objetivo |
|---|---|
| email_templates | Modelos de resposta |
| email_outbox | E-mails preparados/enviados pela app |
| email_events | Historico de envio, erro, resposta futura |

### email_templates

- id
- name
- area: tarefas, oficina, stock, financeiro, geral
- subject_template
- body_template
- active
- created_by_id
- updated_at

### email_outbox

- id
- task_id
- workshop_process_id
- stock_request_id
- to_email
- cc_email
- bcc_email
- subject
- body
- status: draft, ready, sent, failed, cancelled
- provider: manual, smtp, microsoft_graph
- external_message_id
- sent_by_id
- sent_at
- error_message
- created_at

### email_events

- id
- email_outbox_id
- event_type: created, edited, sent, failed, reply_received
- detail
- created_at
- created_by_id

### Fase 2 - rececao por caixa/lista

Criar caixas de entrada ou listas por area:

- tarefas@carfast.pt
- oficina@carfast.pt
- stock@carfast.pt
- financeiro@carfast.pt
- documentos@carfast.pt

O e-mail entra como registo bruto, nao como tarefa definitiva.

Entidade futura:

### inbound_messages

- id
- channel: email, whatsapp, webex, form, rentway
- mailbox
- from_name
- from_email
- subject
- body_preview
- received_at
- external_message_id
- conversation_id
- status: novo, triado, convertido, arquivado, ignorado
- suggested_area
- linked_task_id
- linked_document_id
- linked_vehicle_id
- processed_by_id

Regra importante:

Um e-mail recebido pode:

- criar tarefa;
- ser associado a tarefa existente;
- criar documento para arquivo;
- ficar arquivado sem acao;
- gerar pedido de stock;
- gerar pedido de validacao.

## 3. Fluxos por tarefa montados por blocos

### Objetivo

Permitir criar fluxos configuraveis sem programar cada caso. O utilizador escolhe blocos de acao e monta uma sequencia adaptada ao tipo de tarefa.

Exemplo:

Tarefa de dano em viatura:

1. Classificar como incidente.
2. Pedir evidencias.
3. Atribuir a responsavel.
4. Enviar e-mail ao cliente.
5. Aguardar resposta.
6. Criar documento.
7. Fechar ou escalar.

### Conceito "lego"

O sistema deve ter uma biblioteca de blocos reutilizaveis.

Cada fluxo e uma sequencia de blocos.

Cada bloco tem:

- nome;
- tipo de acao;
- parametros;
- se e manual ou automatico;
- condicao para avancar;
- resultado esperado;
- logs/auditoria.

### Blocos iniciais recomendados

| Bloco | O que faz | Fase |
|---|---|---|
| Alterar estado | Muda o estado da tarefa | Fase 1 |
| Atribuir responsavel | Define pessoa ou equipa | Fase 1 |
| Criar subtarefa | Abre tarefa filha | Fase 1 |
| Adicionar checklist | Mostra lista de validacao | Fase 1 |
| Pedir comentario interno | Solicita nota/decisao | Fase 1 |
| Registar documento | Associa documento | Fase 1 |
| Enviar e-mail | Cria e-mail a partir de template | Fase 2 |
| Criar pedido stock | Abre pedido de material | Fase 2 |
| Abrir processo oficina | Cria processo ligado | Fase 2 |
| Aguardar resposta | Mantem tarefa em espera | Fase 2 |
| Escalar | Muda prioridade/responsavel | Fase 2 |
| Criar alerta SLA | Cria alerta operacional | Fase 2 |
| Chamar automacao externa | Microsoft Graph, Lists, API | Fase 3 |

### Modelo de dados proposto

### workflow_templates

- id
- name
- description
- area: tarefas, oficina, stock, documentos
- trigger_type: manual, task_type, category, status_change, inbound_message
- active
- created_by_id
- created_at
- updated_at

### workflow_steps

- id
- workflow_template_id
- position
- name
- action_type
- action_config_json
- is_required
- is_automatic
- next_on_success_step_id
- next_on_failure_step_id

### workflow_runs

- id
- workflow_template_id
- task_id
- workshop_process_id
- stock_request_id
- status: ativo, concluido, pausado, cancelado, erro
- current_step_id
- started_by_id
- started_at
- completed_at

### workflow_step_runs

- id
- workflow_run_id
- workflow_step_id
- status: pendente, em_execucao, concluido, ignorado, erro
- assigned_to_id
- result_json
- error_message
- started_at
- completed_at

### workflow_action_catalog

Opcional, mas recomendado para tornar a configuracao mais clara.

- id
- action_type
- name
- description
- config_schema_json
- active

## 4. Ligacao entre tarefas, stock e e-mail

Fluxos devem conseguir criar ou ligar entidades sem duplicar informacao.

Exemplos:

### Tarefa -> Stock

Uma tarefa pode gerar um pedido de stock.

- task_id fica em stock_requests;
- stock_request_id pode ficar no workflow_run;
- o historico da tarefa mostra "Pedido de stock criado".

### Tarefa -> E-mail

Uma tarefa pode preparar ou enviar e-mail.

- email_outbox.task_id guarda a ligacao;
- task_history regista e-mail criado/enviado;
- se houver resposta futura, inbound_message liga a task_id.

### Oficina -> Stock

Um processo de oficina pode gerar pedido de material.

- workshop_process_id fica no stock_request;
- se a oficina estiver associada a tarefa, tambem pode ligar a task_id.

## 5. Interface recomendada

### Gestao de stock

Menus fase 1:

- Stock
  - Dashboard
  - Artigos
  - Pedidos
  - Movimentos
  - Locais

Ecras prioritarios:

1. Lista de pedidos de stock.
2. Criar pedido rapido.
3. Detalhe de pedido.
4. Registar movimento.
5. Lista de artigos simples.

### E-mail na tarefa

No detalhe da tarefa:

- separador "Comunicacao";
- botao "Preparar e-mail";
- escolher template;
- editar assunto/corpo;
- guardar como rascunho ou marcar como enviado.

Fase 1 pode ter "marcar como enviado manualmente" se ainda nao houver integracao Microsoft.

### Fluxos na tarefa

No detalhe da tarefa:

- painel "Fluxo";
- botao "Iniciar fluxo";
- selecionar modelo;
- ver passos em lista;
- cada passo tem botao de executar, ignorar ou concluir;
- passo automatico fica bloqueado ate a integracao existir.

Visual pretendido:

- blocos pequenos;
- sequencia vertical;
- estados por cor;
- sem diagrama complexo na fase 1.

## 6. Fases de implementacao

### Fase 1 - base manual segura

Criar:

- modelo de stock minimo;
- pedidos de stock ligados a tarefa/oficina/viatura;
- movimentos simples;
- templates de e-mail;
- e-mails preparados/registados manualmente;
- modelos de fluxo;
- passos de fluxo executados manualmente.

Nao criar ainda:

- envio real por Microsoft Graph;
- leitura automatica de caixas;
- automacoes sem confirmacao;
- OCR;
- regras complexas de stock.

### Fase 2 - operacao assistida

Criar:

- envio real por e-mail;
- rascunhos e historico de envio;
- criacao de pedido de stock a partir de bloco de fluxo;
- criacao de subtarefas por fluxo;
- atribuicao automatica simples por equipa/fila;
- alertas SLA.

### Fase 3 - integracoes

Criar:

- rececao de e-mails via Microsoft Graph;
- ligacao a SharePoint/Lists;
- WhatsApp/Webex quando houver decisao tecnica;
- regras de triagem;
- automatizacoes condicionais.

### Fase 4 - melhoria inteligente

Criar:

- sugestao de fluxo por tipo de tarefa;
- sugestao de template de resposta;
- classificacao assistida;
- analise de historico;
- relatorios de produtividade, tempos e bloqueios.

## 7. Decisoes a validar

Antes de implementar, validar:

1. Stock deve nascer como modulo autonomo ou primeiro dentro de Oficina?
2. Artigos devem ter referencia interna obrigatoria ou podem ser livres no inicio?
3. Queremos stock por local ja na fase 1?
4. E-mail deve comecar como "registo manual de e-mail enviado" ou ja com integracao real?
5. Que caixas de e-mail vao existir por area?
6. Os fluxos devem ser globais ou por tipo/natureza de tarefa?
7. O utilizador pode ignorar passos obrigatorios com justificacao?
8. Quem pode criar/editar modelos de fluxo?
9. Um fluxo deve poder correr em oficina e stock, ou apenas em tarefas na fase 1?
10. Quando um bloco cria uma subtarefa, a tarefa principal fica a aguardar automaticamente?

## 8. Recomendacao pratica

Implementar nesta ordem:

1. Stock minimo: artigos, locais, pedidos, movimentos.
2. Ligacao de pedido de stock a tarefa e processo de oficina.
3. Templates de e-mail e registo de e-mail enviado/manual.
4. Fluxos manuais por tarefa com blocos simples.
5. Primeiro bloco real: "criar pedido de stock".
6. Segundo bloco real: "preparar e-mail".
7. Depois validar com casos reais antes de automatizar.

Esta ordem evita construir automacoes em cima de conceitos que ainda podem mudar.
