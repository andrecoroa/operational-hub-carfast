# Email Postmark: ativação de staging

1. Aplicar `alembic upgrade head` e confirmar a existência do menu **Email**.
2. Criar um disco persistente e definir `EMAIL_STORAGE_ROOT` para esse caminho.
3. Definir os segredos Postmark diretamente no Render; nunca os colocar no Git ou enviar por chat.
4. Começar com `EMAIL_INBOUND_ENABLED=true` e `EMAIL_OUTBOUND_ENABLED=false`.
5. Configurar o inbound webhook para `/api/webhooks/postmark/inbound` com Basic Auth.
6. Encaminhar uma mensagem de teste para `hub@carfast.pt` e confirmar criação única da conversa.
7. Testar triagem, criação de tarefa, rascunho e pedido de aprovação.
8. Só depois definir `EMAIL_OUTBOUND_ENABLED=true` e aprovar uma resposta para um endereço de teste.

## Variáveis obrigatórias

- `EMAIL_PUBLIC_BASE_URL`
- `EMAIL_STORAGE_ROOT`
- `EMAIL_INITIAL_ADDRESS=hub@carfast.pt`
- `POSTMARK_SERVER_TOKEN`
- `POSTMARK_MESSAGE_STREAM`
- `POSTMARK_INBOUND_BASIC_USER`
- `POSTMARK_INBOUND_BASIC_PASSWORD`

O primeiro ensaio usa apenas `hub@carfast.pt`. As restantes caixas só devem ser criadas depois
de a receção, deduplicação e persistência de anexos estarem confirmadas.
