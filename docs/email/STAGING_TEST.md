# Email Postmark: ativação e teste de staging

Este procedimento prepara a aplicação; não altera automaticamente DNS, Microsoft 365, Postmark ou produção.

## Destinos de encaminhamento confirmados

Configurar no Microsoft 365 **Deliver message to both forwarding address and mailbox** e usar exatamente um destino por caixa:

| Caixa pública | Encaminhar exatamente para |
|---|---|
| `hub@carfast.pt` | `da0078240da719f585b6f441e02a1951+hub@inbound.postmarkapp.com` |
| `multas@carfast.pt` | `da0078240da719f585b6f441e02a1951+multas@inbound.postmarkapp.com` |
| `oficina@carfast.pt` | `da0078240da719f585b6f441e02a1951+oficina@inbound.postmarkapp.com` |
| `sinistros@carfast.pt` | `da0078240da719f585b6f441e02a1951+sinistros@inbound.postmarkapp.com` |
| `vvp@carfast.pt` | `da0078240da719f585b6f441e02a1951+vvp@inbound.postmarkapp.com` |

O inbound base confirmado é `da0078240da719f585b6f441e02a1951@inbound.postmarkapp.com`. Não o usar nas cinco regras: sem `+hash`, o webhook não distingue a caixa. A aplicação aceita-o apenas como fallback histórico de `hub@carfast.pt`.

O contrato oficial Postmark define que o texto após `+` é disponibilizado como `MailboxHash`, tanto no objeto principal como em `ToFull`. A aplicação valida os dois locais, o endereço técnico completo, o destinatário público original e headers de encaminhamento.

## Ativação da aplicação

1. Integrar a branch e aplicar `alembic upgrade head`; confirmar um único head.
2. Confirmar as cinco caixas na Administração > Trabalho > Email.
3. Configurar, de forma independente por caixa/classificação:
   - supervisor;
   - executores utilizador/equipa elegíveis;
   - modo automático, equipa para assumir ou espera de atribuição;
   - primeira resposta e resolução em minutos ou dias;
   - aviso e pausa em espera;
   - criação automática de ticket, se explicitamente aprovada.
4. Criar storage persistente e definir `EMAIL_STORAGE_ROOT`.
5. Introduzir segredos Postmark diretamente no ambiente; nunca no Git, documentos ou chat.
6. Começar com `EMAIL_INBOUND_ENABLED=true` e `EMAIL_OUTBOUND_ENABLED=false`.
7. Configurar o webhook inbound HTTPS em `/api/webhooks/postmark/inbound` com Basic Auth.
8. Não ligar auto-ticket até routing, anexos, deduplicação, permissões e auditoria passarem.

## Variáveis de runtime

- `EMAIL_PUBLIC_BASE_URL`
- `EMAIL_STORAGE_ROOT`
- `EMAIL_INITIAL_ADDRESS=hub@carfast.pt`
- `POSTMARK_SERVER_TOKEN`
- `POSTMARK_MESSAGE_STREAM`
- `POSTMARK_INBOUND_BASIC_USER`
- `POSTMARK_INBOUND_BASIC_PASSWORD`

Nenhum valor secreto é incluído neste repositório.

## Matriz de smoke test

Para cada uma das cinco caixas:

1. Enviar uma mensagem com identificador único para a caixa pública.
2. Confirmar que permanece uma cópia no Microsoft 365.
3. Confirmar no webhook `MailboxHash` igual ao código esperado.
4. Confirmar que a conversa aparece apenas na caixa correta e uma única vez.
5. Confirmar histórico, HTML sanitizado e anexos persistentes.
6. Confirmar que um utilizador sem permissão dessa caixa recebe acesso negado.
7. Confirmar que os seletores mostram apenas executores ativos e elegíveis.
8. Confirmar atribuição manual, automática e “Por assumir na equipa X”.
9. Confirmar primeira resposta, resolução, aviso, atraso e pausa/retoma do SLA.
10. Responder primeiro em modo de aprovação; verificar que `From` e `Reply-To` são exatamente a caixa pública original.
11. Responder ao email enviado e confirmar que regressa à mesma conversa.
12. Confirmar que a conversa não cria ticket, salvo ação manual ou regra configurada.

Teste adicional de compatibilidade do hub: entregar uma mensagem sintética ao inbound base sem `+hash` e confirmar routing para `hub@carfast.pt`. Não criar novas regras Microsoft 365 com esse destino base.

## Ordem de abertura

Ativar uma caixa de cada vez: `hub`, `multas`, `oficina`, `sinistros`, `vvp`. Só avançar quando a reconciliação Microsoft 365 ↔ Postmark Activity ↔ CarFast não tiver diferenças. Outbound só deve ser ligado depois de aprovação formal do smoke test.
