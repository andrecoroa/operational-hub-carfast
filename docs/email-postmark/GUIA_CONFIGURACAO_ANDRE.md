# Guia de configuração para André

**CarFast Operational Hub + Postmark**  
**Português de Portugal — versão de 5 de agosto de 2026**

Este guia descreve o que fazer, mas não executa nenhuma alteração. Não criar a configuração de produção enquanto o responsável técnico não confirmar por escrito que staging cumpre os critérios do plano.

## Regra de ouro

Substituir sempre `<DOMINIO_CONFIRMADO>` pelo domínio real depois de o confirmar. `carfast.pt` é apenas o domínio indicado no contexto e continua marcado como decisão.

Arquitetura recomendada:

- caixas públicas: `tarefas@app.<DOMINIO_CONFIRMADO>`, etc., em Microsoft 365, **se essa convenção for aprovada**;
- receção técnica Postmark: `inbound.app.<DOMINIO_CONFIRMADO>`;
- replies: `reply+<token>@inbound.app.<DOMINIO_CONFIRMADO>`;
- MX principal de `<DOMINIO_CONFIRMADO>`: não alterar.

Não aponte o MX de `app.<DOMINIO_CONFIRMADO>` para a Postmark se pretender ter caixas Microsoft 365 nesse mesmo subdomínio. O MX da Postmark pertence a `inbound.app.<DOMINIO_CONFIRMADO>`.

## Antes de começar: reunir sem alterar

Preencher esta ficha:

| Pergunta | Resposta |
|---|---|
| Domínio real confirmado | |
| Fornecedor que gere o DNS autoritativo | |
| Pessoa com acesso DNS | |
| Administrador Exchange/Microsoft 365 | |
| Responsável técnico CarFast | |
| URL HTTPS de staging | |
| URL HTTPS de produção | ainda não usar |
| Caixas públicas finais | |
| As caixas são shared mailboxes, user mailboxes ou aliases? | |
| Canal do piloto | recomendação: tarefas |
| Storage privado de anexos | |
| Retenção aprovada | |
| Volume mensal estimado | |

Para localizar o fornecedor DNS, consulte a entidade onde estão os nameservers/NS do domínio ou peça essa informação ao responsável atual. No painel do fornecedor, o menu costuma chamar-se **DNS**, **DNS Management**, **Manage Zone**, **Zone Editor** ou **Registos DNS**. Não altere nameservers.

## Sequência exata e ordenada

### 1. Aprovar endereços e separação de subdomínios

Escolher uma destas opções:

**Opção A — endereços públicos no subdomínio `app`**

- público/From: `tarefas@app.<DOMINIO_CONFIRMADO>`, etc.;
- `app.<DOMINIO_CONFIRMADO>` é adicionado ao Microsoft 365 e recebe o MX indicado pela Microsoft;
- técnico inbound: `inbound.app.<DOMINIO_CONFIRMADO>` aponta por MX para Postmark.

**Opção B — caixas públicas existentes no domínio principal**

- público: por exemplo `tarefas@<DOMINIO_CONFIRMADO>`;
- `From` da aplicação pode ser o mesmo endereço, se o domínio for verificado na Postmark, ou um endereço `@app...` aprovado;
- técnico inbound continua em `inbound.app.<DOMINIO_CONFIRMADO>`.

Recomendação: A se a empresa quer distinguir claramente o correio da aplicação; B se as caixas já existem e não é desejável mudar endereços públicos.

**Ponto de paragem:** não avançar sem confirmar o domínio real e a opção.

### 2. Pedir ao responsável técnico que prepare staging

Antes de contratar inbound, o técnico deve disponibilizar:

- endpoint HTTPS staging `POST /api/webhooks/postmark/inbound`;
- endpoint HTTPS staging `POST /api/webhooks/postmark/events`;
- Basic Auth dedicado a staging;
- armazenamento persistente de anexos;
- base de dados/migrações staging;
- logs redigidos e alertas;
- feature flags com outbound e auto-criação desligados;
- utilizadores internos de teste autorizados.

Não envie credenciais neste pedido. O técnico fornece apenas URLs não secretas e confirma o método seguro para introduzir os segredos.

**Ponto de paragem:** não configurar encaminhamento Microsoft 365 sem endpoint staging testado diretamente.

### 3. Criar a conta Postmark

1. Abra [Postmark](https://postmarkapp.com/) e selecione **Start free trial** / **Get started**.
2. Use um email empresarial controlado pela CarFast, não um email pessoal do programador.
3. Defina uma password única e longa no gestor de passwords da empresa.
4. Ative MFA/2FA se a opção estiver disponível em **Account**, **Profile** ou **Security**.
5. Registe pelo menos dois responsáveis da empresa com funções adequadas; dê acesso mínimo ao técnico por convite, em vez de partilhar login.
6. Preencha o processo de aprovação/identificação da Postmark com informação empresarial verdadeira.
7. Comece no plano Developer apenas para validar a integração de envio com `POSTMARK_API_TEST`. O Developer inclui 100 mensagens/mês, mas a página de preços não inclui inbound.
8. Quando staging inbound estiver pronto, abra **Account > Plans & Add-ons**, **Plan** ou **Billing** e confirme o plano **Pro — 10,000 emails**.
9. Antes de comprar, volte a confirmar [o preço oficial](https://postmarkapp.com/pricing/). Em 5 de agosto de 2026: US$ 16,50/mês; excedente US$ 1,30/1.000; inbound incluído. Considerar impostos e conversão cambial no total faturado.

Não contratar um IP dedicado para este volume inicial. Não criar Broadcast Streams.

### 4. Criar o Server de staging

1. No dashboard Postmark, abra **Servers**.
2. Selecione **Create Server** / **Add Server**.
3. Nome: `CarFast Email - Staging`.
4. Cor: escolher uma cor claramente diferente de produção.
5. Manter o Server em modo de teste/sandbox enquanto possível.
6. Abrir o Server e anotar, sem segredo:
   - nome;
   - Server ID;
   - ambiente `staging`.
7. Não criar ainda `CarFast Email - Production` se staging não estiver aprovado.

Se a conta apresentar “Servers” como cartões na página inicial, use o botão **Create server** dessa página.

### 5. Configurar os Message Streams de staging

1. Dentro do Server, abrir **Message Streams**.
2. Localizar o **Default Transactional Stream**, normalmente com ID `outbound`.
3. Pode renomear a designação visível para `CarFast Operational`, mas anote o **Stream ID real**. Se criar um novo:
   - **Create Message Stream**;
   - nome `CarFast Operational`;
   - tipo **Transactional**;
   - ID sugerido `carfast-operational`.
4. Confirmar a existência do **Inbound Stream** associado ao Server.
5. Não criar streams `Broadcast`/marketing.
6. Em **Transactional Stream > Settings**, confirmar que SMTP está enabled se a interface/requisito de inbound forwarding o pedir, embora a aplicação vá enviar pela API.

Um único stream transacional e um inbound chegam para os cinco endereços; o routing é feito pela aplicação.

### 6. Adicionar e validar o domínio de envio

Só depois de confirmar o domínio real:

1. No menu de conta Postmark, abrir **Sender Signatures** ou **Domains**.
2. Selecionar **Add Domain** / **Add Domain or Signature**.
3. Introduzir o domínio de envio:
   - `app.<DOMINIO_CONFIRMADO>` se os `From` forem `@app...`;
   - `<DOMINIO_CONFIRMADO>` se o `From` for uma caixa do domínio principal.
4. Abrir **DNS Settings** desse domínio.
5. Na secção **DKIM**, copiar exatamente **Hostname** e **Value**.
6. Na secção **Return-Path**, escolher o alias sugerido `pm-bounces` e copiar exatamente o CNAME apresentado.
7. Não copiar valores de exemplos da Internet. Os valores DKIM são próprios da conta.

### 7. Adicionar os registos de envio no fornecedor DNS

No painel DNS autoritativo, selecionar a zone de `<DOMINIO_CONFIRMADO>` e adicionar:

| Ordem | Tipo | Nome/Host | Prioridade | Destino/Valor | TTL |
|---|---|---|---|---|---|
| 1 | TXT | `<HOST_DKIM_EXATO_MOSTRADO_PELA_POSTMARK>` | — | `<VALOR_DKIM_EXATO_MOSTRADO_PELA_POSTMARK>` | 3600 ou default |
| 2 | CNAME | `<HOST_RETURN_PATH_EXATO_MOSTRADO_PELA_POSTMARK>` | — | `<DESTINO_CNAME_EXATO_MOSTRADO_PELA_POSTMARK>` | 3600 ou default |

Normalmente o Return-Path será semelhante a:

- FQDN: `pm-bounces.app.<DOMINIO_CONFIRMADO>`;
- target oficial atual: `pm.mtasv.net`.

Mas o valor mostrado na conta Postmark prevalece sempre.

Cuidados:

- alguns fornecedores pedem apenas a parte relativa do Host; por exemplo, `pm-bounces.app`, e acrescentam o domínio automaticamente;
- outros pedem o FQDN completo;
- não duplicar o sufixo do domínio;
- num fornecedor com proxy DNS/CDN, o CNAME de Return-Path deve ficar **DNS only**, não proxied;
- não criar um segundo SPF TXT. A Postmark indica que já não é necessário adicionar Postmark ao SPF do domínio; o custom Return-Path serve o alinhamento SPF/DMARC;
- não editar ou substituir o DKIM Microsoft 365 existente; o DKIM Postmark usa outro selector/hostname;
- não alterar MX nesta etapa.

Depois:

1. voltar a **Postmark > Sender Signatures/Domains > DNS Settings**;
2. selecionar **Verify** no DKIM e Return-Path;
3. aguardar propagação; DKIM pode demorar até 48 horas segundo a Postmark;
4. só marcar concluído quando ambos mostrarem **Verified**.

### 8. Configurar o domínio inbound técnico na Postmark

1. Abrir `CarFast Email - Staging`.
2. Abrir **Message Streams > Inbound**.
3. Abrir **Settings**.
4. Em **Inbound Domain** / **Inbound Forwarding Domain**, introduzir:
   - `inbound.app.<DOMINIO_CONFIRMADO>`.
5. Em **Inbound Webhook**, introduzir a URL staging fornecida pelo técnico.
6. Configurar HTTP Basic Auth pela área própria, se existir. Se a UI pedir credenciais na URL, o formato suportado é `https://user:password@host/...`; faça isto apenas no painel Postmark, nunca num documento/chat.
7. Deixar **Include raw email content** desligado por defeito. Ativar apenas se o técnico justificar a necessidade e o impacto de dados/tamanho.
8. Usar **Check**, **Send test** ou equivalente. Tem de obter sucesso HTTP 200.

A Postmark não assina webhooks com HMAC. A proteção prevista é HTTPS + Basic Auth + allowlist de IP + validação do payload.

### 9. Adicionar o MX do inbound técnico

No DNS autoritativo, adicionar exatamente:

| Tipo | Nome/Host na zone `<DOMINIO_CONFIRMADO>` | Prioridade | Destino | TTL |
|---|---|---:|---|---|
| MX | `inbound.app` | 10 | `inbound.postmarkapp.com` | 3600 ou default |

Se o fornecedor exigir FQDN, usar `inbound.app.<DOMINIO_CONFIRMADO>` como nome. Alguns fornecedores exigem ponto final no destino; siga a interface, sem alterar o hostname.

Antes de guardar, confirmar:

- é `inbound.app`, não `@`, não `app`;
- não remove nem altera nenhum MX do domínio principal;
- não existe outro MX concorrente em `inbound.app.<DOMINIO_CONFIRMADO>`;
- a Postmark mostra o mesmo inbound domain no Inbound Stream.

Depois, testar diretamente enviando para:

- `intake+tarefas@inbound.app.<DOMINIO_CONFIRMADO>`.

A mensagem deve aparecer uma vez na inbox staging da CarFast. Ainda não configurar Microsoft 365.

### 10. Se os endereços públicos forem `@app...`, adicionar o subdomínio ao Microsoft 365

Esta etapa não é necessária se forem usadas caixas/aliases já existentes no domínio principal.

1. Abrir [Microsoft 365 admin center](https://admin.microsoft.com/).
2. Ir a **Settings > Domains**. Se não estiver visível: **Show all > Settings > Domains**.
3. Selecionar **Add domain**.
4. Introduzir `app.<DOMINIO_CONFIRMADO>`.
5. A Microsoft apresentará um TXT de verificação. Copiar exatamente o Host/Value para o DNS.
6. Depois de verificado, escolher **Add your own DNS records** e a configuração de email/Exchange.
7. Para o futuro MX de `app.<DOMINIO_CONFIRMADO>`, anotar **exatamente** o destino e prioridade apresentados pela Microsoft, semelhante mas não necessariamente igual a `<tenant>.mail.protection.outlook.com`.
8. **Ainda não publicar o MX Microsoft.** Primeiro criar/confirmar todas as caixas na etapa 11, para que não haja destinatários inexistentes quando o MX começar a receber.
9. Não selecionar `inbound.postmarkapp.com` para este subdomínio. Esse valor pertence apenas a `inbound.app...`.
10. Não alterar o MX do domínio principal.

Registos desta etapa, sempre copiados do Microsoft 365; o TXT é publicado já e o MX fica anotado até à etapa 11:

| Tipo | Nome | Valor |
|---|---|---|
| TXT | conforme Microsoft | conforme Microsoft, para verificação |
| MX | `app` ou FQDN, conforme fornecedor | valor exato Microsoft; prioridade exata Microsoft |
| CNAME/TXT adicionais | apenas se a Microsoft os solicitar e forem aprovados | valores exatos Microsoft |

### 11. Criar ou confirmar as caixas públicas Microsoft 365

Para shared mailboxes:

1. Em [Microsoft 365 admin center](https://admin.microsoft.com/), abrir **Teams & groups > Shared mailboxes**.
2. Se não estiver visível: **Show all > Teams & groups > Shared mailboxes**.
3. Para cada endereço, confirmar ou selecionar **+ Add a shared mailbox**:
   - `tarefas@app.<DOMINIO_CONFIRMADO>`;
   - `oficina@app.<DOMINIO_CONFIRMADO>`;
   - `faturas@app.<DOMINIO_CONFIRMADO>`;
   - `stock@app.<DOMINIO_CONFIRMADO>`;
   - `auditoria@app.<DOMINIO_CONFIRMADO>`.
4. Adicionar membros mínimos necessários.
5. Em **Manage mailbox permissions**, atribuir:
   - **Read and manage / Full Access** a quem triage manualmente;
   - **Send as** apenas a quem precisa responder fora da aplicação durante contingência.
6. Para Auditoria, usar grupo reduzido e validar que não há membros por herança indevida.
7. Manter sign-in direto da shared mailbox bloqueado; os membros acedem com as suas contas.

Se forem aliases ou user mailboxes existentes, documentar o objeto real e não criar duplicados.

Depois de todas as caixas/aliases `@app...` existirem:

1. voltar a **Microsoft 365 admin center > Settings > Domains > app.<DOMINIO_CONFIRMADO> > DNS records**;
2. publicar no fornecedor DNS o MX de `app.<DOMINIO_CONFIRMADO>` com o destino e prioridade exatos mostrados pela Microsoft;
3. publicar apenas os CNAME/TXT adicionais Microsoft aprovados para esse subdomínio;
4. concluir **Verify/Continue/Done** no assistente;
5. testar receção em cada caixa antes de configurar qualquer forwarding.

Referência oficial: [adicionar um domínio personalizado ao Microsoft 365](https://learn.microsoft.com/en-us/microsoft-365/admin/setup/add-domain?view=o365-worldwide).

### 12. Permitir encaminhamento externo de forma limitada

Por segurança, o Microsoft 365 costuma bloquear encaminhamento externo automático por defeito. Não abra a política global.

1. Abrir [Microsoft Defender portal](https://security.microsoft.com/).
2. Ir a **Email & collaboration > Policies & rules > Threat policies > Anti-spam**. Alternativa direta: `https://security.microsoft.com/antispam`.
3. Em **Outbound spam filter policy**, criar uma política customizada, por exemplo `Allow Postmark inbound forwarding - CarFast`.
4. Aplicar apenas às cinco caixas/objetos do piloto/produção, começando por uma caixa de teste.
5. Em **Forwarding rules**, definir **Automatic forwarding rules = On - Forwarding is enabled**.
6. Confirmar se existem **Remote domains** ou mail flow rules que continuam a bloquear. Um bloqueio prevalece sobre uma permissão.
7. Se a organização usar remote domains, permitir auto-forward apenas para `inbound.app.<DOMINIO_CONFIRMADO>`.
8. Guardar e aguardar propagação. Mudanças em mail flow podem demorar 30 minutos ou mais.

Peça ao administrador Exchange que documente o âmbito e reveja periodicamente a política. Não usar uma regra de Outlook criada por um utilizador como solução oficial.

### 13. Configurar encaminhamento e manter a cópia

Fazer primeiro apenas na caixa de piloto.

Método preferido no Exchange admin center:

1. Abrir [Exchange admin center](https://admin.exchange.microsoft.com/).
2. Ir a **Recipients > Mailboxes**.
3. Selecionar a caixa de piloto.
4. Em **Mailbox > Email forwarding**, selecionar **Manage email forwarding**.
5. Ativar **Forward all emails sent to this mailbox**.
6. Selecionar **Forward to an external email address**.
7. Introduzir o endereço técnico exato:
   - tarefas → `intake+tarefas@inbound.app.<DOMINIO_CONFIRMADO>`;
   - oficina → `intake+oficina@inbound.app.<DOMINIO_CONFIRMADO>`;
   - faturas → `intake+faturas@inbound.app.<DOMINIO_CONFIRMADO>`;
   - stock → `intake+stock@inbound.app.<DOMINIO_CONFIRMADO>`;
   - auditoria → `intake+auditoria@inbound.app.<DOMINIO_CONFIRMADO>`.
8. Ativar **Deliver message to both forwarding address and mailbox** / **Entregar à caixa e ao endereço de reencaminhamento**.
9. Guardar.

Se essa opção não aparecer para uma shared mailbox no Microsoft 365 admin center, usar o Exchange admin center acima ou pedir ao administrador Exchange para configurar `DeliverToMailboxAndForward=true`. Não usar simultaneamente mailbox forwarding e uma mail flow rule para a mesma caixa, pois causaria duplicados.

Método alternativo — só se o anterior não for aceite pela política interna:

- regra de mail flow em **Exchange admin center > Mail flow > Rules**, adicionando o endereço técnico como destinatário/Bcc para a caixa específica;
- criar primeiro o mail contact externo se a interface o exigir;
- incluir exceções contra loops;
- testar exaustivamente;
- nunca manter os dois métodos ativos.

### 14. Configurar webhooks de eventos outbound

Na Postmark staging:

1. Abrir **Server > Message Streams > CarFast Operational > Webhooks**.
2. Selecionar **Add webhook**.
3. URL: endpoint staging `/api/webhooks/postmark/events`.
4. Configurar Basic Auth na área **HTTP Auth** e, se acordado, um custom header secreto adicional.
5. Ativar:
   - Delivery;
   - Bounce, com **Include message content = off**;
   - Spam Complaint, com conteúdo off;
   - Subscription Change.
6. Manter Open e Click desligados.
7. Selecionar **Send test** para cada tipo e exigir 2xx.
8. Guardar.

### 15. Entregar configuração ao responsável técnico com segurança

#### Dados não secretos que pode enviar por email/ticket/chat empresarial

- domínio confirmado;
- endereços públicos e técnicos;
- Server ID;
- Transactional Message Stream ID;
- nomes dos Servers;
- URLs dos endpoints;
- DKIM/Return-Path/MX **depois de publicados** (são DNS públicos);
- owners/membros por função, sem dados pessoais desnecessários;
- políticas de routing, retenção, limites e piloto;
- screenshots redigidos sem tokens, passwords, cookies ou detalhes de faturação.

#### Segredos que o técnico pode precisar, mas que devem ser introduzidos por canal seguro

- **Postmark Server API Token de staging**;
- **Postmark Server API Token de produção**, mais tarde;
- utilizador/password de Basic Auth dos webhooks;
- custom webhook header secret, se usado;
- credenciais do armazenamento de objetos;
- credenciais da fila/Key Value, se não forem ligadas automaticamente pela Render.

Forma preferida: André ou o owner introduz diretamente os valores em **Render Dashboard > serviço > Environment > + Add Environment Variable**, com o técnico em chamada, sem os ler em voz alta; alternativa: gestor de segredos empresarial com acesso temporário/auditado.

#### Nunca enviar por chat, email, ticket ou documento

- password da conta Postmark;
- Postmark Account API Token (não é necessário para o runtime);
- passwords Microsoft 365 ou DNS;
- códigos MFA, códigos de recuperação ou cookies de sessão;
- API key da Render ou credenciais da base de dados;
- dados de cartão/faturação;
- `.env` real;
- dumps de produção;
- URL de webhook contendo `user:password@`;
- screenshots da página **API Tokens**, **Environment** ou password manager sem redação total.

Se um segredo for enviado por engano, considerá-lo comprometido, revogá-lo e gerar outro.

### 16. Testar, por esta ordem

#### A. DNS e envio sem entrega real

1. Postmark mostra DKIM e Return-Path **Verified**.
2. Técnico usa `POSTMARK_API_TEST` para validar payload; não usa o token real em logs.
3. Confirmar que o `From` é autorizado e o Message Stream ID existe.

#### B. Webhooks sintéticos

1. **Inbound Stream > Settings > Check/Send test** → 200.
2. **Transactional Stream > Webhooks > Send test** para Delivery/Bounce/Complaint → 2xx.
3. Confirmar um único evento na CarFast e ausência de segredos nos logs.

#### C. Inbound técnico direto

Enviar de uma conta interna de teste para `intake+tarefas@inbound.app.<DOMINIO_CONFIRMADO>`:

1. texto simples;
2. HTML;
3. PDF pequeno;
4. dois anexos;
5. repetição da mesma mensagem/retry.

Esperado: uma mensagem, anexos persistentes, duplicado sem nova tarefa.

#### D. Outbound real de staging

Enviar apenas para uma allowlist interna aprovada. Verificar:

- From correto;
- Reply-To com token;
- DKIM/DMARC nos detalhes da mensagem;
- estado sent/delivered;
- conteúdo e anexos;
- ausência de dados internos no Metadata/headers.

#### E. Reply/threading

Responder no Outlook ao email de D. Esperado: resposta aparece na mesma thread/tarefa, não numa nova. Testar sender esperado e sender diferente.

#### F. Piloto Microsoft 365

1. Ativar encaminhamento apenas da caixa piloto.
2. Enviar email externo para a caixa pública.
3. Confirmar a mesma mensagem na caixa Microsoft 365 e uma única vez na CarFast.
4. Responder pela CarFast e responder novamente pelo Outlook do destinatário.
5. Confirmar thread, anexos, delivery e auditoria.
6. Repetir durante vários dias antes do próximo canal.

### 17. Preparar produção, sem reutilizar staging

Só depois da aprovação formal:

1. criar `CarFast Email - Production`;
2. usar tokens e Basic Auth novos;
3. configurar URLs de produção;
4. confirmar feature flags desligadas inicialmente;
5. repetir testes de webhook e smoke test;
6. ativar um canal de cada vez;
7. manter auto-task e auto-document desligados durante o piloto;
8. registar hora, responsável e rollback de cada mudança.

Não copiar tokens de staging para produção. Não usar a mailbox inbound técnica de staging em regras de produção.

## Diagnóstico rápido

| Sintoma | Verificar primeiro |
|---|---|
| Postmark não verifica DKIM | host duplicado, TXT truncado, sufixo do domínio repetido, propagação |
| Return-Path não verifica | CNAME proxied, host/target incorreto, CNAME em nome com outros registos |
| Inbound direto não chega | MX apenas de `inbound.app`, domínio no Inbound Stream, webhook 200/auth |
| Caixa recebe mas CarFast não | forwarding ativo, política outbound, NDR 5.7.520, regra remota |
| CarFast recebe duas vezes | mailbox forwarding + mail flow rule simultâneos, regra duplicada, dedupe |
| Postmark mostra Inbound Error | endpoint/auth/storage, retries, opção manual de retry na Inbound Activity |
| Reply cria thread nova | Reply-To alterado, token não localizado, headers não guardados |
| Email enviado duas vezes | duplo clique/retry cego; verificar idempotency key e estado `unknown` |
| Anexo desaparece após deploy | uso indevido do filesystem efémero; confirmar object storage/persistent storage |
| Auditoria visível indevidamente | RBAC por thread/anexo e política mais restritiva |

## Referências oficiais

- [Preços Postmark](https://postmarkapp.com/pricing/)
- [Configurar inbound domain forwarding](https://postmarkapp.com/developer/user-guide/inbound/inbound-domain-forwarding)
- [Configurar DKIM](https://postmarkapp.com/support/article/1091-how-do-i-set-up-dkim-for-postmark)
- [Configurar custom Return-Path](https://postmarkapp.com/support/article/910-how-do-i-add-a-custom-return-path)
- [Segurança e retries de webhooks](https://postmarkapp.com/developer/webhooks/webhooks-overview)
- [Encaminhamento Microsoft 365 com cópia](https://learn.microsoft.com/en-us/exchange/recipients-in-exchange-online/manage-user-mailboxes/configure-email-forwarding)
- [Shared mailbox settings](https://learn.microsoft.com/en-us/microsoft-365/admin/email/configure-a-shared-mailbox?view=o365-worldwide)
- [Adicionar um domínio personalizado ao Microsoft 365](https://learn.microsoft.com/en-us/microsoft-365/admin/setup/add-domain?view=o365-worldwide)
- [Políticas de external forwarding](https://learn.microsoft.com/en-us/defender-office-365/outbound-spam-policies-external-email-forwarding)
- [Environment variables e secrets na Render](https://render.com/docs/configure-environment-variables)
