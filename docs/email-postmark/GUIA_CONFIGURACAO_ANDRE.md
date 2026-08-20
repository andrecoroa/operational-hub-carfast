# Guia Postmark e Microsoft 365 para André

Este guia descreve as alterações externas a executar manualmente depois da integração e validação em staging. O código não altera DNS, Microsoft 365 ou Postmark e este documento não contém segredos.

## Routing confirmado

O Inbound Address confirmado no painel Postmark é:

`da0078240da719f585b6f441e02a1951@inbound.postmarkapp.com`

Não encaminhar todas as caixas para esse endereço base. Cada caixa Microsoft 365 deve usar exatamente o destino correspondente:

| Caixa Microsoft 365 | Destino externo exato Postmark | `MailboxHash` esperado |
|---|---|---|
| `hub@carfast.pt` | `da0078240da719f585b6f441e02a1951+hub@inbound.postmarkapp.com` | `hub` |
| `multas@carfast.pt` | `da0078240da719f585b6f441e02a1951+multas@inbound.postmarkapp.com` | `multas` |
| `oficina@carfast.pt` | `da0078240da719f585b6f441e02a1951+oficina@inbound.postmarkapp.com` | `oficina` |
| `sinistros@carfast.pt` | `da0078240da719f585b6f441e02a1951+sinistros@inbound.postmarkapp.com` | `sinistros` |
| `vvp@carfast.pt` | `da0078240da719f585b6f441e02a1951+vvp@inbound.postmarkapp.com` | `vvp` |

O endereço base sem `+hash` permanece aceite pela aplicação apenas para preservar a receção histórica de `hub@carfast.pt`. Não deve ser usado em novas regras.

O contrato Postmark de inbound expõe o texto depois de `+` como `MailboxHash`, no objeto principal e nos contactos `ToFull`. A aplicação dá precedência ao `MailboxHash` principal, reconhece também `ToFull`, o endereço técnico completo, o destinatário público original e os headers habituais de encaminhamento.

## Antes da ativação

1. Integrar os commits numa branch de staging e executar `alembic upgrade head`.
2. Confirmar que existe um único head Alembic.
3. Abrir Administração → Filas e classificação → Caixas de email e confirmar as cinco caixas, os hashes e os destinos acima.
4. Configurar separadamente, por caixa e/ou regra: supervisor, executores elegíveis, modo de atribuição, primeira resposta, resolução, pausa e auto-ticket.
5. Definir storage persistente para anexos e introduzir os segredos apenas no gestor de ambiente.
6. Começar com inbound ativo, outbound desativado e auto-ticket desativado.

Variáveis de runtime relevantes:

- `EMAIL_PUBLIC_BASE_URL`
- `EMAIL_STORAGE_ROOT`
- `EMAIL_INITIAL_ADDRESS=hub@carfast.pt`
- `POSTMARK_SERVER_TOKEN`
- `POSTMARK_MESSAGE_STREAM`
- `POSTMARK_INBOUND_BASIC_USER`
- `POSTMARK_INBOUND_BASIC_PASSWORD`

## Postmark — passos manuais

1. No Server correto, abrir **Message Streams → Inbound → Settings**.
2. Confirmar visualmente que o Inbound Address é `da0078240da719f585b6f441e02a1951@inbound.postmarkapp.com`. Se o painel mostrar outro valor, não inventar nem adaptar: copiar o valor do painel e parar a ativação até o código/runbook serem revistos.
3. Configurar o webhook HTTPS de staging em `POST /api/webhooks/postmark/inbound`.
4. Introduzir o Basic Auth diretamente no painel Postmark, sem o colocar em tickets, screenshots ou documentos.
5. Usar **Check** ou **Send test** e exigir resposta 2xx.
6. No Transactional Stream, configurar o webhook de eventos em `POST /api/webhooks/postmark/events` e testar Delivery/Bounce/Complaint.
7. Confirmar o domínio de envio, DKIM e Return-Path com os valores exatos apresentados no painel. Não copiar valores de exemplos e não alterar MX automaticamente.

Não é necessário criar um domínio inbound alternativo ou um MX `inbound.app...` para este routing confirmado. As caixas Microsoft 365 encaminham diretamente para os endereços Postmark da tabela.

## Microsoft 365 — passos manuais

Executar primeiro numa única caixa piloto.

1. Abrir **Exchange admin center → Recipients → Mailboxes**.
2. Selecionar a caixa e abrir **Mailbox → Email forwarding → Manage email forwarding**.
3. Ativar o encaminhamento para endereço externo.
4. Copiar da tabela deste guia o destino exato da caixa; confirmar visualmente o sufixo `+hub`, `+multas`, `+oficina`, `+sinistros` ou `+vvp`.
5. Ativar **Deliver message to both forwarding address and mailbox**.
6. Guardar e testar antes de configurar a caixa seguinte.

Se o tenant bloquear encaminhamento externo, o administrador Exchange deve criar uma exceção de âmbito mínimo apenas para estas caixas e estes destinos. Não abrir a política global. Não manter simultaneamente mailbox forwarding e uma regra de mail flow para a mesma caixa, porque isso gera duplicados.

## Envio e resposta por caixa

O runtime usa o endereço público da caixa selecionada como `From` e `Reply-To`:

- `hub@carfast.pt`
- `multas@carfast.pt`
- `oficina@carfast.pt`
- `sinistros@carfast.pt`
- `vvp@carfast.pt`

Antes de ativar outbound, confirmar no Postmark que o domínio/remetentes estão autorizados. Não incluir tokens no repositório e não reutilizar credenciais de staging em produção.

## Smoke test por caixa

Para cada caixa, por esta ordem: `hub`, `multas`, `oficina`, `sinistros`, `vvp`:

1. Enviar uma mensagem com identificador único para a caixa pública.
2. Confirmar que permanece uma cópia no Microsoft 365.
3. Confirmar no webhook o `MailboxHash` esperado.
4. Confirmar que a conversa aparece uma única vez e apenas na caixa correta.
5. Verificar histórico, HTML seguro, anexos e deduplicação.
6. Confirmar que um utilizador sem acesso à caixa recebe 403/404 e não vê a conversa.
7. Confirmar que os seletores mostram apenas executores ativos e elegíveis.
8. Testar atribuição manual, automática e “Por assumir na equipa”.
9. Testar primeira resposta, resolução, aviso, atraso e pausa/retoma do SLA.
10. Responder em modo de aprovação e confirmar `From` e `Reply-To` iguais à caixa pública.
11. Responder pelo destinatário e confirmar continuidade da mesma conversa.
12. Confirmar que não nasce ticket, salvo ação manual ou regra explicitamente configurada.

Teste adicional de compatibilidade: entregar um payload sintético ao inbound base, sem `+hash`, e confirmar que é encaminhado para o histórico de `hub@carfast.pt`.

## Segredos e produção

Nunca colocar em Git, chat, email ou screenshots não redigidos:

- Postmark Server API Token;
- credenciais Basic Auth dos webhooks;
- passwords Microsoft 365/DNS;
- códigos MFA ou cookies;
- credenciais de base de dados/storage;
- `.env` real.

Produção só deve ser configurada depois da aprovação formal do smoke test, uma caixa de cada vez, com credenciais próprias e plano de rollback. Este guia não autoriza alterações automáticas nem uma ativação direta em produção.

## Referências oficiais

- [Postmark — inbound webhook](https://postmarkapp.com/developer/webhooks/inbound-webhook)
- [Postmark — inbound email processing](https://postmarkapp.com/developer/user-guide/inbound/parse-an-email)
- [Microsoft — configurar encaminhamento](https://learn.microsoft.com/en-us/exchange/recipients-in-exchange-online/manage-user-mailboxes/configure-email-forwarding)
