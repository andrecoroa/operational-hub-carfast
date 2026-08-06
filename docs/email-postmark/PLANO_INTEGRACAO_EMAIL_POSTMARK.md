# Plano de integração de email — CarFast Operational Hub + Postmark

**Estado:** especificação pronta para execução, sem implementação  
**Data de validação das fontes:** 5 de agosto de 2026  
**Âmbito:** experiência Clean, Centro de Tarefas, Oficina, Documentação, Stock e Frota  
**Fora de âmbito deste documento:** criar contas, alterar DNS ou Microsoft 365, escrever código, fazer push, deploy ou qualquer alteração em produção

> Todos os nomes de domínio neste documento são exemplos até André confirmar o domínio real. Onde aparece `<DOMINIO_CONFIRMADO>`, poderá vir a ser `carfast.pt`, mas isso não é assumido.

## 1. Resumo executivo

A solução recomendada mantém o Microsoft 365 como caixa de correio humana e usa a Postmark como canal transacional da aplicação:

1. cada endereço público permanece numa caixa partilhada Microsoft 365;
2. o Microsoft 365 conserva a mensagem e encaminha uma cópia para um endereço técnico Postmark;
3. a Postmark converte o email em JSON e entrega-o por webhook HTTPS à CarFast;
4. a aplicação deduplica, audita, guarda mensagem e anexos, associa registos e cria ou atualiza uma tarefa conforme as regras deste plano;
5. as respostas são enviadas pela aplicação através da API da Postmark;
6. cada email enviado tem um `Reply-To` único com token opaco; a resposta do destinatário regressa diretamente à conversa/tarefa correta;
7. o Microsoft 365 continua disponível como cópia operacional e contingência, mas a CarFast passa a ser a fonte única do workflow — sem Microsoft Lists nem Power Automate paralelos.

### Decisão arquitetural obrigatória

Não se pode usar o mesmo subdomínio simultaneamente como domínio de caixas Microsoft 365 e como domínio inbound da Postmark, porque o respetivo MX só pode encaminhar a receção para um dos serviços.

Recomendação:

| Função | Exemplo, ainda por confirmar | MX |
|---|---|---|
| Domínio principal empresarial | `<DOMINIO_CONFIRMADO>` | permanece exatamente como está |
| Caixas públicas da aplicação e domínio de envio | `app.<DOMINIO_CONFIRMADO>` | Microsoft 365, apenas se os endereços públicos forem `@app...` |
| Domínio técnico inbound/replies | `inbound.app.<DOMINIO_CONFIRMADO>` | Postmark: `inbound.postmarkapp.com`, prioridade 10 |
| Return-Path de envio | `pm-bounces.app.<DOMINIO_CONFIRMADO>` | CNAME para o valor indicado pela Postmark |

Isto não altera o MX principal de `<DOMINIO_CONFIRMADO>`.

Se as caixas públicas já existirem no domínio principal — por exemplo, `oficina@<DOMINIO_CONFIRMADO>` — não é obrigatório criar caixas em `app.<DOMINIO_CONFIRMADO>`. O domínio `app...` pode servir apenas para o `From` da aplicação e o inbound técnico continua em `inbound.app...`.

## 2. Arquitetura recomendada

### 2.1 Componentes

- **Microsoft 365 / Exchange Online:** caixas partilhadas, cópia humana, permissões e encaminhamento externo controlado.
- **DNS autoritativo:** DKIM e Return-Path de envio; MX apenas do subdomínio técnico inbound; eventualmente registos Microsoft para `app...` se este alojar caixas 365.
- **Postmark:** um Server por ambiente, um Transactional Message Stream para correio operacional, Inbound Stream associado e webhooks de inbound, delivery, bounce e spam complaint.
- **CarFast Web Service em Render:** endpoints HTTPS, validação, receção durável, API/UI de triagem e resposta.
- **Base de dados:** metadados, conversas, mensagens, associações, estados, idempotência, outbox e auditoria.
- **Armazenamento persistente de objetos:** conteúdo de anexos, fora do filesystem efémero do serviço web.
- **Worker/fila numa fase posterior:** sanitização pesada, malware scan, extração/classificação documental, envio de anexos e retries.

### 2.2 Ambientes Postmark

Criar servidores separados:

- `CarFast Email - Staging` — primeiro e único usado durante desenvolvimento e smoke tests;
- `CarFast Email - Production` — criado/configurado apenas quando os critérios de staging estiverem concluídos e houver aprovação explícita para ativação.

Cada Server tem token, atividade e inbound próprios. Esta separação impede testes com credenciais ou mensagens de produção.

### 2.3 Message Streams

Em cada Server:

- **Transactional Message Stream:** `carfast-operational` (ou manter o ID `outbound` se a interface não permitir alterar o ID). Todas estas mensagens são transacionais, nunca Broadcast.
- **Inbound Message Stream:** o stream inbound do Server, com um webhook e o domínio técnico `inbound.app.<DOMINIO_CONFIRMADO>`.

Não criar um stream por endereço na primeira versão. O encaminhamento é feito pelo destinatário/local-part (`intake+tarefas`, `intake+oficina`, etc.), `MailboxHash`, regra de routing e metadados. Menos streams significam menos endpoints e configuração, mantendo isolamento suficiente através de tags e metadados.

### 2.4 Fluxo de entrada

1. Uma pessoa envia email para a caixa pública Microsoft 365.
2. Exchange Online entrega a mensagem na caixa e encaminha cópia para `intake+<canal>@inbound.app.<DOMINIO_CONFIRMADO>`.
3. A Postmark recebe, executa a análise de spam e envia o payload JSON ao webhook inbound.
4. O endpoint verifica HTTPS, Basic Auth, origem permitida, tamanho, método e schema.
5. Numa transação curta, regista o evento/idempotency key e grava a mensagem e anexos em armazenamento durável.
6. Só depois da receção durável responde HTTP 200. Em falha transitória antes disso, responde 5xx para a Postmark repetir.
7. Regras determinísticas associam reply, canal, tarefa e entidades conhecidas.
8. Classificação/extração automática só produz sugestões. Associações de baixa confiança ficam em “Por triar”; nunca são apagadas.
9. A ação fica integralmente auditada.

### 2.5 Fluxo de saída e reply

1. Um utilizador autorizado escreve a resposta dentro da tarefa/conversa.
2. A aplicação valida destinatários, permissão, anexos e estado da tarefa.
3. Cria uma mensagem `pending` e uma operação de outbox com chave idempotente.
4. Envia pela API Postmark no stream transacional.
5. Define:
   - `From`: endereço público apropriado, por exemplo `Oficina CarFast <oficina@app.<DOMINIO_CONFIRMADO>>`;
   - `Reply-To`: `reply+<TOKEN_OPACO>@inbound.app.<DOMINIO_CONFIRMADO>`;
   - `Message-ID`: identificador RFC controlado pela aplicação, por exemplo `<email-message-UUID@app.<DOMINIO_CONFIRMADO>>`;
   - `In-Reply-To` e `References`: IDs RFC da conversa quando aplicável;
   - `Tag`: canal ou tipo (`oficina`, `faturas`, etc.);
   - `Metadata`: apenas identificadores não sensíveis, como UUID de thread e ambiente.
6. Guarda o `MessageID` devolvido pela Postmark, distinto do header RFC `Message-ID`.
7. Delivery/bounce/spam complaint atualizam o estado da mensagem e geram alerta/tarefa quando necessário.
8. Ao responder, o destinatário envia para o token no `Reply-To`; o webhook localiza a thread e acrescenta a mensagem.

### 2.6 Threading robusto

Usar três mecanismos, por ordem:

1. **reply token opaco** no endereço — mecanismo principal e inequívoco;
2. **`In-Reply-To`/`References`** — mecanismo compatível com clientes de correio;
3. **heurística controlada** por assunto normalizado, participantes e janela temporal — apenas para sugestão, nunca associação silenciosa de baixa confiança.

O token deve ter pelo menos 128 bits de entropia, não conter ID sequencial, não revelar matrícula/tarefa, ser revogável e estar ligado a uma única thread. Um token conhecido não é autenticação do remetente: se o remetente não for participante esperado, a mensagem entra na thread como “remetente não reconhecido — revisão necessária” ou fica em triagem, conforme política.

## 3. Fluxos funcionais por endereço e módulo

### 3.1 Regras comuns de decisão

| Situação | Ação por defeito |
|---|---|
| Reply token válido | acrescentar à conversa/tarefa indicada; não criar tarefa nova |
| Identificador inequívoco de registo e mensagem acionável | associar ao registo; criar tarefa se não existir uma ativa adequada |
| Documento reconhecido e registo inequívoco | guardar como documento; criar tarefa apenas se houver ação, exceção, prazo ou validação |
| Informação sem ação, ligada a processo existente | anexar à conversa/registo e arquivar como “informativo” |
| Duplicado exato | registar como duplicado e arquivar sem nova tarefa/anexo físico |
| Canal reconhecido mas associação incerta | deixar na caixa “Por triar” do canal; nunca escolher matrícula/registo por aproximação fraca |
| Spam/malware/ficheiro bloqueado | quarentena; sem criação automática de tarefa operacional, exceto alerta de segurança |
| Endereço não previsto no domínio inbound | rejeitar logicamente para “destinatário desconhecido” ou quarentena, sem criar tarefa |

### 3.2 `tarefas@...`

- **Fila:** Operacional.
- **Módulos associados:** Centro de Tarefas; ligação transversal a Frota, Stock, Oficina e Documentação.
- **Criar tarefa:** pedido explícito, prazo, pendência, reclamação, follow-up ou ação atribuível.
- **Deixar em inbox:** assunto vago, remetente novo, falta de entidade, CC informativo potencialmente relevante.
- **Associar:** matrícula, número de reserva, contrato, fatura ou documento com correspondência única.
- **Classificar como documento:** apenas se existir anexo documental e tipo/registo forem confirmados.
- **Arquivar:** notificações informativas, confirmação sem ação, duplicado ou mensagem já incorporada numa tarefa.

### 3.3 `oficina@...`

- **Fila:** Oficina.
- **Módulo:** Oficina, com ligação à viatura/Frota e Documentação.
- **Criar tarefa:** pedido de diagnóstico, orçamento, marcação, aprovação, peça pendente, relatório técnico ou incidência.
- **Deixar em inbox:** matrícula ausente/ambígua, oficina externa não reconhecida ou conteúdo apenas comercial.
- **Associar:** matrícula/VIN exatos, processo de oficina aberto, ordem de trabalho ou tarefa referenciada.
- **Classificar como documento:** orçamento, relatório, checklist, fatura de oficina, fotografias técnicas; exige tipo e viatura confirmados.
- **Arquivar:** confirmação de receção ou conclusão já refletida no processo, sem nova ação.

### 3.4 `faturas@...`

- **Fila:** Administração/Gestão quando há exceção; caso normal pode não criar tarefa.
- **Módulo:** Documentação, com ligação a contrato, reserva, viatura e fornecedor.
- **Criar tarefa:** fatura sem correspondência, divergência de valor, duplicado suspeito, vencimento, nota de crédito ou validação necessária.
- **Deixar em inbox:** documento ilegível, remetente/fornecedor desconhecido, mais de um contrato possível.
- **Associar:** número de fatura + fornecedor e, quando aplicável, contrato/reserva/matrícula com correspondência única.
- **Classificar como documento:** PDF/XML/imagem de fatura, nota de crédito ou recibo; guardar hash e metadados.
- **Arquivar:** documento válido e associado sem ação pendente; o arquivo não elimina a mensagem nem o audit trail.

### 3.5 `stock@...`

- **Fila:** Operacional (subfila/etiqueta Stock). Não se introduz uma fila “Stock” sem decisão funcional, porque não consta das filas atuais.
- **Módulo:** Stock, com ligação a Frota e Documentação.
- **Criar tarefa:** entrada/saída, disponibilidade, preço, documentação em falta, dano, preparação, fotografia ou publicação.
- **Deixar em inbox:** viatura não identificada ou comunicação comercial genérica.
- **Associar:** stock ID, matrícula, VIN ou reserva inequívocos.
- **Classificar como documento:** ficha de viatura, declaração, inspeção, fotografia ou documento de aquisição, após confirmação do tipo.
- **Arquivar:** atualização já aplicada e sem ação.

### 3.6 `auditoria@...`

- **Fila:** Auditoria.
- **Módulos:** Auditoria e Documentação, com associação transversal.
- **Criar tarefa:** pedido de evidência, não conformidade, prazo, amostra, validação ou achado.
- **Deixar em inbox:** âmbito/confidencialidade incertos ou associação não confirmada.
- **Associar:** processo auditado, contrato, fatura, reserva, viatura ou documento inequívoco.
- **Classificar como documento:** evidência, relatório ou checklist com nível de confidencialidade e retenção definidos.
- **Arquivar:** comunicação de fecho/receção sem ação, preservando trilho.
- **Permissão:** acesso restrito a Auditoria e Administração/Gestão; o simples acesso a outra entidade ligada não concede acesso ao conteúdo do email.

## 4. Matriz resumida de endereços

A matriz operacional completa encontra-se em `MATRIZ_ENDERECOS.csv`.

| Público Microsoft 365 (proposta) | Técnico inbound | Fila/módulo | `From` da aplicação | Por defeito |
|---|---|---|---|---|
| `tarefas@app.<DOMINIO_CONFIRMADO>` | `intake+tarefas@inbound.app.<DOMINIO_CONFIRMADO>` | Operacional / Tarefas | igual ao público | criar tarefa se acionável; senão triagem |
| `oficina@app.<DOMINIO_CONFIRMADO>` | `intake+oficina@inbound.app.<DOMINIO_CONFIRMADO>` | Oficina / Oficina | igual ao público | associar à viatura/processo; criar tarefa se acionável |
| `faturas@app.<DOMINIO_CONFIRMADO>` | `intake+faturas@inbound.app.<DOMINIO_CONFIRMADO>` | Administração/Gestão / Documentação | igual ao público | documento associado; tarefa só para exceção |
| `stock@app.<DOMINIO_CONFIRMADO>` | `intake+stock@inbound.app.<DOMINIO_CONFIRMADO>` | Operacional / Stock | igual ao público | criar tarefa operacional se acionável |
| `auditoria@app.<DOMINIO_CONFIRMADO>` | `intake+auditoria@inbound.app.<DOMINIO_CONFIRMADO>` | Auditoria / Auditoria+Documentação | igual ao público | triagem restrita/criar tarefa |
| n/a | `reply+<TOKEN>@inbound.app.<DOMINIO_CONFIRMADO>` | thread já identificada | `From` do canal da thread | acrescentar reply; não criar tarefa |

## 5. Plano técnico da aplicação

### 5.1 Modelos/tabelas

Adaptar nomes ao ORM existente; reutilizar as tabelas de utilizadores, tarefas e entidades atuais.

| Tabela | Campos essenciais | Regras |
|---|---|---|
| `email_channels` | `id`, `code`, `public_address`, `inbound_route`, `from_address`, `queue`, `module`, `default_policy`, `active` | uma linha por canal; configuração auditável |
| `email_threads` | `id` UUID, `channel_id`, `task_id` opcional, `subject_normalized`, `status`, `confidentiality`, `last_message_at`, `created_by` | uma conversa pode existir em triagem antes de ter tarefa |
| `email_messages` | `id` UUID, `thread_id`, `direction`, `provider`, `provider_message_id`, `rfc_message_id`, `in_reply_to`, `references`, `from`, `reply_to`, `subject`, `text_body`, `html_original_ref`, `html_sanitized`, `received_at`, `sent_at`, `state`, `spam_score`, `content_hash`, `raw_headers_json` | constraints únicas de idempotência; HTML apresentado é sempre sanitizado |
| `email_participants` | `message_id`, `kind` (`from/to/cc/bcc`), `address_normalized`, `display_name` | endereços normalizados sem perder o original |
| `email_attachments` | `id`, `message_id`, `original_name`, `safe_name`, `mime_claimed`, `mime_detected`, `size`, `sha256`, `storage_key`, `scan_state`, `document_type`, `document_id`, `quarantined` | bytes nunca no filesystem efémero; download autorizado |
| `email_entity_links` | `thread_id`/`message_id`, `entity_type`, `entity_id`, `confidence`, `source`, `confirmed_by`, `confirmed_at` | tipos permitidos: matrícula/vehicle, reserva, contrato, fatura, documento, processo oficina |
| `email_reply_tokens` | `token_hash`, `thread_id`, `state`, `created_at`, `expires_at`, `revoked_at` | só hash em base de dados; rotação/revogação |
| `email_webhook_events` | `id`, `provider`, `event_type`, `provider_message_id`, `fingerprint`, `received_at`, `processed_at`, `status`, `attempts`, `error_code`, `payload_ref` | append-only; constraint única em `fingerprint` |
| `email_delivery_events` | `message_id`, `type`, `occurred_at`, `details_redacted`, `provider_event_id` | delivery, bounce, spam complaint, suppression |
| `email_outbox` | `idempotency_key`, `message_id`, `state`, `attempts`, `next_attempt_at`, `locked_at`, `last_error_code` | impede duplo envio e suporta worker futuro |
| `email_audit_events` | `actor_type`, `actor_id`, `action`, `object_type`, `object_id`, `before_json`, `after_json`, `ip`, `created_at` | append-only; nunca guardar tokens/credenciais |

### 5.2 Endpoints

| Método e caminho proposto | Uso | Autorização |
|---|---|---|
| `POST /api/webhooks/postmark/inbound` | receção inbound | Basic Auth dedicado + IP allowlist + schema |
| `POST /api/webhooks/postmark/events` | delivery, bounce, spam complaint e subscription change | Basic Auth/custom header dedicado + IP allowlist |
| `GET /api/email/inbox` | lista por canal/estado | sessão CarFast + permissão de fila |
| `GET /api/email/threads/{id}` | conversa e associações | sessão + RBAC + confidencialidade |
| `POST /api/email/threads/{id}/triage` | associar, criar/ligar tarefa, documentar, arquivar | permissão de triagem; auditado |
| `POST /api/tasks/{task_id}/email/replies` | resposta pela tarefa | permissão na tarefa e no canal |
| `POST /api/email/messages/{id}/retry` | retry administrativo controlado | Administração técnica; motivo obrigatório |
| `GET /api/email/attachments/{id}` | download/preview | autorização por thread e scan concluído |
| `POST /api/email/attachments/{id}/classify` | confirmar tipo/documento | permissão no módulo de destino |

Os endpoints públicos de webhook não usam CSRF, mas aceitam apenas `POST`, `Content-Type: application/json`, HTTPS e autenticação própria. Os endpoints de UI mantêm CSRF e autenticação normal da aplicação.

### 5.3 Variáveis de ambiente

Lista e placeholders em `VARIAVEIS_AMBIENTE_EXEMPLO.txt`. Separar staging e produção. Valores secretos são introduzidos diretamente em **Render Dashboard > serviço > Environment**, nunca em Git, `.env` versionado, ticket ou chat.

Grupos:

- Postmark: token do Server, stream ID, `From` por canal;
- webhooks: utilizador e password Basic Auth dedicados/aleatórios;
- domínios: sending domain e inbound domain confirmados;
- limites: corpo, anexos, tipos, timeouts e spam thresholds;
- storage: bucket/endpoint/região/credenciais, quando escolhido;
- jobs: backend/fila e número de tentativas;
- feature flags: inbound, outbound, auto-task e auto-document separados.

### 5.4 Autenticação e validação do webhook

A Postmark não fornece atualmente assinatura HMAC para webhooks. Implementar:

1. HTTPS obrigatório;
2. HTTP Basic Authentication com credencial exclusiva por ambiente e endpoint;
3. comparação em tempo constante;
4. allowlist das gamas IP oficiais da Postmark, revista no momento da implementação;
5. validação do IP apenas a partir da cadeia de proxy confiável da Render, nunca de um `X-Forwarded-For` arbitrário;
6. `POST` e JSON apenas;
7. limite de `Content-Length` antes de ler o corpo e limite durante streaming;
8. schema estrito com campos adicionais tolerados/logados para compatibilidade futura;
9. destinatário/local-part numa allowlist;
10. nenhum segredo incluído em URL, logs, payload persistido ou alertas. Se a UI inbound da Postmark exigir Basic Auth na URL, o valor é introduzido apenas na consola Postmark e mascarado na aplicação/operacionalização.

Resposta:

- `200` para evento já recebido ou guardado com sucesso;
- `5xx` para falha transitória antes de persistência durável, permitindo retries;
- `403` apenas para autenticação definitivamente inválida, sabendo que a Postmark deixa de repetir após `403`;
- nunca devolver detalhes internos no corpo.

### 5.5 Trabalho síncrono e jobs

**Obrigatório dentro do webhook, antes do 200:** autenticar, limitar tamanho, validar schema mínimo, obter idempotency key, registar receção, guardar bytes dos anexos/payload necessários de forma durável e confirmar transação.

**Pode ser síncrono, desde que limitado:** normalização de endereços, routing por local-part, lookup exato do reply token e associação exata por ID.

**Job assíncrono recomendado:** malware scan, HTML avançado, OCR, extração de fatura, classificação, thumbnails, notificação, envio com anexos, retries e reconciliação. A Render documenta Background Workers para retirar tarefas longas do request path e Key Value para filas.

Na primeira fase, se ainda não existir worker, usar uma outbox em base de dados e processamento limitado/recuperável. Não depender de threads em memória do processo web: podem desaparecer num restart/deploy.

### 5.6 Armazenamento de anexos

Recomendação de produção:

- metadados e hashes em base de dados;
- bytes num armazenamento de objetos persistente, privado e com cifragem em repouso;
- chaves não previsíveis, sem nome/matrícula no path;
- downloads por endpoint autorizado ou URL assinada de curta duração;
- retenção e eliminação segundo política aprovada;
- cópia de segurança e teste de restore.

Não usar o filesystem normal da Render: é efémero. Um Persistent Disk pode servir num piloto controlado, mas só é acessível a uma instância, impede escalar para múltiplas instâncias e desativa zero-downtime deploys; por isso não é a opção preferida de produção.

A Postmark envia o conteúdo completo dos anexos no webhook e não deve ser tratada como arquivo. A aplicação tem de o guardar no momento da receção.

### 5.7 Limites, HTML, malware e spam

Limites oficiais Postmark relevantes:

- outbound: mensagem total até 10 MB após Base64; `TextBody` e `HtmlBody` até 5 MB cada;
- inbound: anexos acumulados até 35 MB;
- máximo de 50 destinatários por email; cada destinatário conta para utilização.

Limites internos propostos, mais conservadores:

- webhook inbound: máximo 50 MB de HTTP body;
- anexos inbound: 30 MB descodificados no total e 20 MB por ficheiro;
- outbound: 7 MB de anexos binários no total, para reservar overhead Base64/corpo;
- máximo 20 anexos por mensagem;
- nomes até 255 caracteres após normalização;
- MIME real detetado por conteúdo e comparado com o declarado.

Política de segurança:

- guardar HTML original apenas como objeto restrito para auditoria; nunca renderizá-lo diretamente;
- sanitizar HTML com allowlist, remover scripts, forms, iframes, objects, eventos `on*`, CSS perigoso e URLs ativas não seguras;
- bloquear imagens remotas por defeito para evitar tracking;
- links abrem com proteção `noopener noreferrer` e domínio visível;
- gerar texto seguro para pesquisa; usar `StrippedTextReply` apenas como conveniência, preservando o corpo original;
- malware scan antes de download, preview, classificação ou envio;
- executáveis, scripts, atalhos, ficheiros macro suspeitos e arquivos protegidos por password ficam em quarentena;
- nunca autoeliminar por spam: usar SpamAssassin headers da Postmark e política de quarentena;
- limiares iniciais sugeridos: score `<5` normal, `5–7,99` revisão, `>=8` quarentena; confirmar depois com amostras reais;
- rate limiting distinto para webhooks autenticados e ações de utilizador. Não bloquear retries legítimos por limite global; limitar abuso por remetente, canal e volume, com quarentena.

### 5.8 Idempotência, deduplicação e retries

**Inbound:** constraint única em `(provider, server, stream, MessageID)`. Como proteção adicional, calcular `sha256` de remetente normalizado + destinatário técnico + RFC Message-ID + conteúdo/anexos. Uma repetição devolve 200 e não repete efeitos.

**Forwarding duplicado:** se a mesma caixa/regra encaminhar duas vezes, o hash secundário marca duplicado. O original permanece auditado, mas não cria nova tarefa nem duplica anexos.

**Eventos:** fingerprint por tipo + Postmark `MessageID` + identificador/timestamp relevante. Guardar todos os estados válidos sem regredir `Delivered` para `Pending` por evento fora de ordem.

**Outbound:** idempotency key gerada na ação do utilizador e `Message-ID` RFC determinístico. Nunca fazer retry automático cego após timeout ambíguo da API, porque a Postmark pode ter aceite a mensagem. Marcar `unknown`, reconciliar pela atividade/API/Message-ID e só reenviar depois de confirmar ausência ou por decisão administrativa auditada.

Retries de falhas inequivocamente transitórias: backoff exponencial com jitter, limite de tentativas e dead-letter/revisão. Erros permanentes de destinatário, supressão ou validação não são repetidos.

A Postmark repete inbound e bounce até 10 vezes em intervalos crescentes quando não recebe 200; um `403` termina as tentativas. Delivery/click/open/subscription têm um calendário mais curto. A aplicação deve ser idempotente em todos os casos.

### 5.9 Delivery, bounce e complaint

- `Delivered`: atualizar a mensagem para “entregue ao servidor do destinatário”; não equivale a leitura.
- soft bounce: estado temporário, possível retry segundo tipo e política;
- hard bounce: não repetir automaticamente; assinalar destinatário e notificar responsável;
- spam complaint: bloquear novos envios para o endereço, criar alerta administrativo e conservar evidência mínima;
- suppression change: sincronizar estado local;
- payloads e conteúdo completos de bounce/complaint só quando necessários; preferir `IncludeContent=false` para minimização de dados.
- opens/clicks ficam desligados por defeito por privacidade e porque não são necessários para o workflow operacional. Ativar apenas com decisão explícita.

### 5.10 UI Clean

**Menu independente “Email”:** filtros por caixa/canal, categoria, estado, data, remetente, matrícula/entidade sugerida, spam/quarentena e “sem associação”. As conversas podem ser tratadas e respondidas sem criar tarefa. Estados funcionais: Por triar, Em tratamento, A aguardar resposta, Nova resposta, A aguardar aprovação, Devolvido para correção, Associado, Convertido em tarefa, Resolvido e Arquivado. Contadores técnicos: Com erro, Quarentena e Bounces.

**Painel de mensagem:** remetente/destinatários, assunto, corpo sanitizado, anexos/scan, cabeçalhos técnicos recolhidos numa secção de diagnóstico, sugestões de associação e histórico de auditoria.

**Ações de triagem:** responder sem criar tarefa, criar tarefa, ligar a tarefa, associar matrícula/reserva/contrato/fatura/documento, classificar anexo, mudar fila, marcar informativo, resolver, arquivar e quarentena/libertar (permissão especial). Uma reply nunca cria uma nova tarefa: se a conversa já tiver tarefa, entra nessa timeline; caso contrário permanece no menu Email.

**Dentro da tarefa:** cartão/preview da origem, timeline única com emails enviados/recebidos, estados de entrega e anexos; editor de resposta com `From` bloqueado ao canal permitido; To/Cc editáveis conforme permissão; aviso de destinatário externo; preview; confirmação em casos sensíveis. A conclusão da tarefa propõe marcar a conversa como Resolvida, selecionado por defeito mas anulável quando ainda se aguarda resposta. Uma nova reply numa tarefa concluída passa a `Nova resposta — tarefa concluída`, permitindo reabrir, criar nova tarefa, responder sem reabrir ou arquivar.

**Separação tarefa/email:** acesso à tarefa não concede acesso à conversa original. Ao criar a tarefa, o utilizador escolhe título, descrição, entidades e anexos a partilhar. Corpo, remetente e anexos começam não partilhados nas categorias Financeiro, Auditoria e Confidencial. Sem permissão, a tarefa mostra apenas `Origem protegida`, sem assunto, remetente, conteúdo ou botão para abrir o original.

**Modelos de email:** modelos administráveis, versionados e auditados por módulo/categoria, com assunto, corpo, remetente permitido, variáveis validadas, anexos opcionais e botões. Preview obrigatório antes do envio. Casos iniciais: receção de pedido, orçamento, aprovação/rejeição, marcação, pedido de documentos/fotografias, peça/stock, inspeção/manutenção/seguro/contrato, validação de fatura e conclusão de processo.

**Páginas externas:** os botões abrem uma página isolada, sem menu nem acesso ao Hub, através de token aleatório, temporário, revogável e limitado à conversa/ação. Pode permitir responder, anexar, confirmar data ou decisão simples. Ações definitivas usam página de confirmação para evitar cliques por scanners. Dados sensíveis podem exigir OTP/autenticação adicional.

**Aprovação de respostas:** configurável por caixa, categoria, modelo, processo, regra de risco ou tarefa. Estados: Rascunho, A aguardar aprovação, Devolvido, Aprovado, Enviado. O aprovador pode `aprovar e enviar`, `aprovar para envio` ou `devolver`. Alterar destinatário, assunto, corpo, valor ou anexos invalida a aprovação.

**Falhas visíveis:** pending, sent, delivered, soft bounce, hard bounce, suppressed, unknown e failed; nunca mostrar “enviado” antes da aceitação Postmark.

### 5.11 Permissões e auditoria

- RBAC por fila e módulo, com política mais restritiva a prevalecer.
- Cada caixa tem classificação (Geral, Operacional, Oficina, Financeiro, Stock, Auditoria ou Confidencial) e permissões independentes para listar, ler, responder, criar/associar tarefa, partilhar anexo, descarregar, reatribuir, arquivar e administrar.
- Operacional vê tarefas/stock autorizados; Oficina vê Oficina; Auditoria vê apenas quem tiver função Auditoria/Admin; Administração/Gestão vê faturas conforme função.
- Permissões distintas: preparar resposta, submeter para aprovação, aprovar, editar após submissão e enviar. Responder pela tarefa exige também acesso ao canal/conversa, exceto quando o utilizador apenas prepara um rascunho com o contexto explicitamente partilhado.
- Alterar associação/document type e libertar quarentena são permissões separadas.
- Anexos herdam confidencialidade da thread/documento.
- Todas as visualizações/downloads de anexos sensíveis, respostas, alterações de destinatário, associações, arquivos, retries e mudanças de permissão são auditados.
- Nenhuma password, token, corpo integral desnecessário ou Base64 em logs. Redigir endereços/conteúdo em monitorização quando possível.

## 6. Plano de implementação faseado

### Fase 0 — decisões e inventário

Sem mudanças externas.

- confirmar domínio, endereços públicos e proprietário do DNS;
- confirmar se as caixas são shared mailboxes, user mailboxes ou aliases;
- escolher armazenamento de objetos e retenção;
- nomear responsáveis Microsoft 365, DNS, Postmark, técnico e negócio;
- estimar volume incluindo inbound e cada destinatário To/Cc/Bcc;
- aprovar matriz de routing e permissões.

**Aceitação:** todas as decisões P0 da secção 9 têm dono e resposta; diagrama DNS não contém conflito de MX.

### Fase 1 — fundação em staging

- criar conta/plano de teste Postmark e Server `CarFast Email - Staging`;
- configurar stream transacional e inbound **apenas staging**;
- implementar modelos, webhooks autenticados, idempotência, armazenamento, auditoria e feature flags desligadas;
- usar endereço técnico Postmark/staging sem encaminhamento das caixas reais;
- testar payloads simulados e `POSTMARK_API_TEST` para validação de outbound.

**Aceitação:** duplicados não repetem efeitos; anexos sobrevivem a restart/deploy; webhook sem auth é rejeitado; nenhuma mensagem chega a cliente real.

### Fase 2 — inbox/triagem staging

- UI Clean de inbox e thread;
- routing dos cinco canais;
- associações manuais e exatas;
- criação de tarefa controlada;
- sanitização/quarentena/limites;
- auditoria e RBAC.

**Aceitação:** cenários da matriz produzem resultado esperado; Auditoria não é visível a utilizador sem função; documento incerto não é associado automaticamente.

### Fase 3 — envio e replies staging

- resposta pela tarefa;
- tokens opacos e headers de threading;
- webhooks delivery/bounce/complaint;
- idempotência outbound e reconciliação de timeout ambíguo;
- testes reais apenas com uma lista de endereços internos aprovada.

**Aceitação:** reply regressa à thread certa; reply de remetente inesperado é sinalizado; duplo clique não envia duas mensagens; bounce aparece na UI.

### Fase 4 — piloto Microsoft 365

- um único canal não crítico, preferencialmente `tarefas`, para uma caixa de teste/staging;
- encaminhamento com cópia mantida;
- política de outbound forwarding limitada aos objetos necessários;
- monitorização diária e reconciliação entre M365 e CarFast.

**Aceitação:** 100% das mensagens da amostra aparecem na caixa 365 e na CarFast; zero loops; zero tarefa duplicada; falhas recuperáveis.

### Fase 5 — preparação de produção

- Server/tokens/domínios separados de produção;
- backup/restore testado;
- dashboards e alertas;
- runbook, formação, suporte e rollback aprovados;
- smoke test em staging repetido e assinado.

**Aceitação:** checklist de ativação integralmente aprovado; nenhuma variável staging em produção; rollback ensaiado.

### Fase 6 — ativação gradual

Ativar um canal de cada vez, começando por menor risco. Manter criação automática de tarefa/documento desligada inicialmente; triagem manual. Só automatizar após métricas de precisão aprovadas.

## 7. Testes e smoke test de staging

### 7.1 Casos mínimos

1. texto simples;
2. HTML com script/iframe/imagem remota;
3. acentos portugueses e assunto longo;
4. PDF, imagem e múltiplos anexos;
5. ficheiro bloqueado/malware de teste autorizado;
6. anexos acima dos limites internos e Postmark;
7. spam scores baixo, intermédio e alto;
8. duplicado por retry Postmark;
9. duplicado por duas regras M365;
10. reply token válido, revogado, desconhecido e com remetente inesperado;
11. `In-Reply-To`/`References` corretos e em falta;
12. matrícula/reserva/contrato inequívocos e ambíguos;
13. fatura associável e fatura sem match;
14. delivery, soft bounce, hard bounce, complaint e suppression;
15. timeout antes/depois da aceitação Postmark;
16. acesso proibido a Auditoria/anexo;
17. restart/deploy após receção;
18. falha de storage/database;
19. loop de encaminhamento;
20. reply a partir de Outlook desktop, Outlook web e cliente externo.

### 7.2 Smoke test antes de qualquer produção

- health check verde na Render;
- feature flags de produção desligadas;
- webhook test da Postmark devolve 200 autenticado;
- email para cada endereço técnico staging aparece uma vez;
- anexos abrem após restart;
- resposta para mailbox interna de teste chega com DKIM/DMARC esperado;
- reply liga à thread certa;
- delivery/bounce visíveis;
- utilizador sem permissão recebe 403 na UI/API;
- logs não mostram token, Basic Auth, corpos ou Base64;
- alertas de erro e dead-letter testados;
- reconciliação total Postmark Activity ↔ `email_messages` na amostra.

## 8. Rollback e tratamento de falhas

### 8.1 Rollback funcional imediato

1. desligar `EMAIL_OUTBOUND_ENABLED` e `EMAIL_AUTO_TASK_ENABLED`;
2. desativar os encaminhamentos das caixas Microsoft 365, uma de cada vez;
3. confirmar que as caixas continuam a receber normalmente;
4. manter webhooks ativos temporariamente para eventos de mensagens já enviadas;
5. não apagar dados; marcar integração como suspensa;
6. reconciliar mensagens durante a janela de incidente.

### 8.2 Rollback de deploy

Usar rollback da Render para o deploy anterior e confirmar health check. Notar que rollback de código/configuração não reverte dados nem conteúdo de discos. Alterações de schema devem ser retrocompatíveis durante a janela de ativação e ter migração de reversão testada.

### 8.3 Falhas específicas

- **CarFast indisponível:** Postmark repete; Microsoft 365 mantém a cópia dos intakes públicos.
- **Storage indisponível:** webhook devolve 5xx antes do 200; alerta crítico.
- **Postmark indisponível no envio:** manter `pending`; backoff apenas em falha inequivocamente não aceite.
- **Timeout ambíguo:** `unknown`, reconciliar; não reenviar automaticamente.
- **DNS inbound incorreto:** remover/desativar o encaminhamento M365; não tocar no MX principal.
- **Loop:** desativar regra afetada; regra deve excluir mensagens originadas pelo endereço técnico/aplicação e nunca encaminhar o técnico para o público.
- **Credencial exposta:** revogar/rodar imediatamente no Postmark/Render; auditar acessos; não partilhar a nova credencial por chat.

## 9. Decisões ainda necessárias

### P0 — antes de configurar

1. Qual é o domínio real e quem gere o DNS autoritativo?
2. Os endereços públicos finais são `@app.<domínio>`, `@<domínio>` existentes, ou aliases de caixas atuais?
3. Se forem `@app...`, esse subdomínio será adicionado ao Microsoft 365 e o seu MX apontará para Microsoft?
4. Quem são os membros e owners de cada caixa/fila?
5. Qual é o ambiente/URL de staging público HTTPS?
6. Que armazenamento persistente privado será usado para anexos?
7. Qual a retenção de mensagens, anexos, audit log e atividade Postmark?
8. Qual o volume mensal estimado, contando inbound e cada destinatário?
9. Que canal será o piloto e qual a janela de ativação/rollback?

### P1 — antes do piloto

10. Limiar de spam e lista de tipos/tamanhos permitidos.
11. Regras de auto-criação de tarefa e nível de confiança mínimo.
12. Quem pode libertar quarentena, reclassificar documento e reenviar.
13. Se Auditória exige retenção/confidencialidade próprias.
14. Se To/Cc podem ser editados livremente ou só escolher contactos ligados.
15. Política para sender inesperado com reply token válido.
16. Ativação ou não de opens/clicks — recomendação: desligados.
17. Se é necessária cópia de mensagens enviadas numa mailbox 365; recomendação: a thread CarFast é o registo oficial, evitando BCC/loops.
18. Classificação e matriz de ações de cada caixa; quem pode ver tarefa sem ver o email original.
19. Categorias/modelos iniciais, respetivos owners e variáveis permitidas.
20. Categorias, valores, anexos ou destinatários que exigem aprovação; grupos aprovadores e quem efetua o envio.
21. Prazo, revogação, OTP e limites das páginas externas de resposta/anexos.
22. Política para concluir tarefa: resolver conversa por defeito e tratamento de nova resposta após conclusão.

## 10. Custos

Valores confirmados em 5 de agosto de 2026; André deve voltar a consultar a página oficial no momento da contratação:

- **Postmark Pro, 10.000 emails/mês:** US$ 16,50/mês; inclui inbound e até 10 custom sending domains.
- **Excedente Pro:** US$ 1,30 por 1.000 mensagens.
- Valores em USD antes de eventuais impostos e conversão cambial; confirmar o total apresentado na faturação.
- Uma mensagem outbound conta por destinatário, incluindo Cc/Bcc; uma mensagem inbound processada também conta.
- Plano Developer gratuito: 100 mensagens/mês para testar; sem excedentes.
- Retenção Pro: por defeito 45 dias, configurável até 365 dias; confirmar se há add-on aplicável ao período escolhido.
- Microsoft 365: confirmar licenciamento das caixas atuais; shared mailboxes têm regras próprias de licenciamento/capacidade. Não é proposto substituir o plano atual.
- Render: custo incremental depende de staging, worker, Key Value, base de dados, persistent storage e bandwidth. Cotar na página oficial depois de escolher a arquitetura. Não anexar um Persistent Disk ao web service apenas para poupar storage sem aceitar as limitações de escala/downtime.
- Armazenamento de objetos/malware scanning: fornecedor e preço ainda por decidir.

## 11. Fontes oficiais

### Postmark

- [Preços Postmark](https://postmarkapp.com/pricing/)
- [Como funciona a faturação mensal](https://postmarkapp.com/support/article/1107-how-does-monthly-pricing-work)
- [Inbound domain forwarding](https://postmarkapp.com/developer/user-guide/inbound/inbound-domain-forwarding)
- [Inbound webhook e calendário de retries](https://postmarkapp.com/developer/webhooks/inbound-webhook)
- [Parsing inbound e anexos](https://postmarkapp.com/developer/user-guide/inbound/parse-an-email)
- [Limites de email e anexos](https://postmarkapp.com/support/article/1056-what-are-the-attachment-and-email-size-limits)
- [Webhooks: segurança, idempotência e retries](https://postmarkapp.com/developer/webhooks/webhooks-overview)
- [API de webhooks](https://postmarkapp.com/developer/api/webhooks-api)
- [Envio pela API e custom Message-ID](https://postmarkapp.com/developer/user-guide/send-email-with-api)
- [Email API](https://postmarkapp.com/developer/api/email-api)
- [DKIM](https://postmarkapp.com/support/article/1091-how-do-i-set-up-dkim-for-postmark)
- [Custom Return-Path](https://postmarkapp.com/support/article/910-how-do-i-add-a-custom-return-path)
- [SPF com Postmark](https://postmarkapp.com/support/article/how-do-i-set-up-spf-for-postmark)

### Microsoft

- [Configurar encaminhamento no Exchange Online e manter cópia](https://learn.microsoft.com/en-us/exchange/recipients-in-exchange-online/manage-user-mailboxes/configure-email-forwarding)
- [Configurar uma shared mailbox](https://learn.microsoft.com/en-us/microsoft-365/admin/email/configure-a-shared-mailbox?view=o365-worldwide)
- [Controlar encaminhamento externo automático](https://learn.microsoft.com/en-us/defender-office-365/outbound-spam-policies-external-email-forwarding)
- [Configurar políticas outbound anti-spam](https://learn.microsoft.com/en-us/defender-office-365/outbound-spam-policies-configure)
- [Gerir mail flow rules no Exchange Online](https://learn.microsoft.com/en-us/exchange/security-and-compliance/mail-flow-rules/manage-mail-flow-rules)
- [Shared mailboxes: funcionamento e limitações](https://learn.microsoft.com/en-us/microsoft-365/admin/email/about-shared-mailboxes?view=o365-worldwide)
- [Adicionar domínio e obter registos DNS Microsoft 365](https://learn.microsoft.com/en-us/microsoft-365/admin/setup/add-domain?view=o365-worldwide)

### Render

- [Environment variables e secrets](https://render.com/docs/configure-environment-variables)
- [Filesystem e Persistent Disks](https://render.com/docs/disks)
- [Background Workers](https://render.com/docs/background-workers)
- [Render Key Value para filas](https://render.com/docs/key-value)
- [Health checks](https://render.com/docs/health-checks)
- [Rollbacks](https://render.com/docs/rollbacks)
- [Preços Render](https://render.com/pricing)

## 12. Resultado esperado

Depois de implementada e ativada faseadamente, qualquer email operacional relevante terá uma única conversa auditável na CarFast, ligada à tarefa e entidades certas; as caixas Microsoft 365 continuarão disponíveis; respostas manterão o threading; anexos serão persistentes e seguros; falhas serão visíveis e recuperáveis; e não existirá uma segunda fonte de workflow em Lists/Power Automate.
