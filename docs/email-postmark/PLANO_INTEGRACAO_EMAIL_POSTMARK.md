# Plano de integração — CarFast Email + Postmark

## Decisão técnica confirmada

O Email permanece um módulo independente do Service Desk. Uma conversa só cria
ticket por ação humana ou regra explicitamente configurada. O Microsoft 365
mantém cada caixa pública e uma cópia das mensagens; a CarFast recebe a cópia
encaminhada, aplica permissões por caixa e conserva histórico, anexos, aprovação,
envio, auditoria e deduplicação.

O inbound base confirmado no painel Postmark é:

`da0078240da719f585b6f441e02a1951@inbound.postmarkapp.com`

O routing usa a sintaxe plus/hash do Postmark. Estes são os únicos destinos a
configurar para as cinco caixas:

| Código | Caixa pública / `From` / `Reply-To` | Destino técnico Microsoft 365 |
|---|---|---|
| `hub` | `hub@carfast.pt` | `da0078240da719f585b6f441e02a1951+hub@inbound.postmarkapp.com` |
| `multas` | `multas@carfast.pt` | `da0078240da719f585b6f441e02a1951+multas@inbound.postmarkapp.com` |
| `oficina` | `oficina@carfast.pt` | `da0078240da719f585b6f441e02a1951+oficina@inbound.postmarkapp.com` |
| `sinistros` | `sinistros@carfast.pt` | `da0078240da719f585b6f441e02a1951+sinistros@inbound.postmarkapp.com` |
| `vvp` | `vvp@carfast.pt` | `da0078240da719f585b6f441e02a1951+vvp@inbound.postmarkapp.com` |

Não usar o endereço base nas regras das caixas: sem hash não distingue o destino.
A receção sem hash fica suportada apenas como fallback histórico do hub.

## Fluxo de entrada

1. A caixa Microsoft 365 recebe a mensagem e mantém uma cópia.
2. A regra manual encaminha para o destino técnico exato da tabela.
3. O Postmark envia o payload ao webhook inbound.
4. A aplicação resolve primeiro o `MailboxHash` principal, depois os contactos
   `ToFull` e só depois os endereços; a comparação é case-insensitive.
5. A mensagem é deduplicada, auditada e guardada com anexos na conversa da caixa.
6. Regras da caixa/classificação podem atribuir, colocar numa equipa para assumir,
   manter à espera de atribuição e, opcionalmente, criar um ticket.

## Fluxo de saída

- `From` e `Reply-To` usam sempre o endereço público da caixa selecionada.
- O token do Server, Basic Auth e outros segredos existem apenas no ambiente.
- Aprovação, histórico de rascunhos, anexos, delivery, bounce e complaint mantêm-se.
- Antes de outbound, o domínio/remetentes e os valores DKIM/Return-Path têm de
  aparecer como autorizados no painel Postmark.

## Operação por caixa

Cada caixa e/ou regra configura de forma independente:

- supervisor e executores elegíveis utilizador/equipa;
- atribuição automática, equipa “Por assumir” ou espera de atribuição;
- prazo de primeira resposta e de resolução, normalizados para minutos;
- aviso e pausa de SLA em espera;
- permissões para consultar, responder, gerir e criar ticket;
- hierarquia de destino e criação automática de ticket, desligada por defeito.

Caixas inativas deixam de aceitar novas operações, mas o histórico permanece
consultável por perfis autorizados.

## Fases de integração

1. Rever commits e aplicar a migração apenas em staging.
2. Confirmar bootstrap idempotente e um único head Alembic.
3. Configurar webhooks/segredos manualmente e testar payloads sintéticos para os
   cinco `MailboxHash`, incluindo conflitos e retries.
4. Configurar uma caixa piloto Microsoft 365, mantendo a cópia local.
5. Validar permissões negativas, anexos, SLA, atribuição e `From`/`Reply-To`.
6. Ativar as restantes caixas uma a uma após aprovação do piloto.

## Limites de autorização

Esta implementação não altera DNS, Microsoft 365, Postmark externo, Render ou
produção. Não cria nem copia segredos. Se o inbound base apresentado no painel
for diferente do confirmado acima, a ativação deve parar para revisão; não se
deve inventar ou adaptar o endereço.

## Referências oficiais

- [Postmark — inbound webhook](https://postmarkapp.com/developer/webhooks/inbound-webhook)
- [Postmark — parsing e MailboxHash](https://postmarkapp.com/developer/user-guide/inbound/parse-an-email)
- [Microsoft — encaminhamento e cópia da mailbox](https://learn.microsoft.com/en-us/exchange/recipients-in-exchange-online/manage-user-mailboxes/configure-email-forwarding)
