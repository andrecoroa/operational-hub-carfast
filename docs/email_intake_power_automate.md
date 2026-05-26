# Entrada de e-mails para a app

## Objetivo

Permitir que um e-mail recebido no Microsoft 365 entre na CarFast sem intervenção manual na lista intermédia.

Fluxo fase 1:

1. Outlook recebe e-mail numa caixa funcional.
2. Power Automate cria/atualiza item numa Microsoft List apenas como auditoria técnica.
3. Power Automate chama a app em `POST /api/integrations/email-intake`.
4. A app cria:
   - registo rápido, quando for assunto operacional/oficina;
   - documento por classificar, quando for assunto documental/financeiro com link.
5. A List fica apenas como entrada bruta, controlo de erros e reprocessamento.

## Segurança

O endpoint exige o header:

```text
X-CarFast-Integration-Key: <chave definida no Render>
```

No Render deve existir a variável:

```text
INTEGRATION_API_KEY=<chave forte>
```

Sem esta variável, a integração fica bloqueada.

## Endpoint

```text
POST https://operational-hub-carfast.onrender.com/api/integrations/email-intake
```

Também existe o alias interno `/integrations/email-intake`.

Payload mínimo:

```json
{
  "source_mailbox": "financeiro@carfast.pt",
  "sender": "fornecedor@example.com",
  "subject": "Fatura fornecedor",
  "body_preview": "Resumo ou primeiras linhas do e-mail",
  "received_at": "2026-05-26T10:30:00Z",
  "email_url": "https://outlook.office.com/...",
  "attachments_url": "https://carfast.sharepoint.com/...",
  "list_item_id": "123",
  "list_item_url": "https://carfast.sharepoint.com/lists/..."
}
```

Campos opcionais úteis para evitar duplicados:

```json
{
  "external_message_id": "outlook-message-id",
  "conversation_id": "outlook-conversation-id"
}
```

Campos opcionais para forçar destino:

```json
{
  "target_kind": "document",
  "target_area": "finance"
}
```

Valores aceites:

- `target_kind`: `document`, `quick_record`
- `target_area`: `finance`, `workshop`

## Regras iniciais

- `oficina@...` cria registo rápido em Oficina.
- `financeiro@...`, caixas de faturação ou contabilidade criam documento Financeiro por classificar.
- caixas com `document` ou `arquivo` criam documento por classificar.
- outros e-mails criam registo rápido Operacional.

Se a regra pedir documento mas não existir link de e-mail, anexo ou item da lista, a app devolve erro para ficar visível no Power Automate/List.

## Resposta esperada

```json
{
  "status": "created_in_app",
  "intake_id": 1,
  "target_type": "document",
  "target_id": "1",
  "target_url": "/documents/1",
  "routing_note": "E-mail recebido na caixa financeira."
}
```

Se for duplicado:

```json
{
  "status": "duplicate",
  "intake_id": 1,
  "target_type": "document",
  "target_id": "1",
  "target_url": "/documents/1"
}
```
