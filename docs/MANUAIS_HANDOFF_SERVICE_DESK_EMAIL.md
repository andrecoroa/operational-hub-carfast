# Resumo para atualização dos manuais

Usar este texto no chat responsável pelos manuais depois de a implementação ser integrada.

## Manual Service Desk

- O antigo Centro de Tarefas passa a Service Desk sem perder tarefas, comentários, anexos, recorrências, integrações ou histórico.
- Explicar os tipos configuráveis: Tarefa, Pedido, Comunicação, Ajuda interna, Incidente e Aprovação.
- Manter a navegação Fila → Departamento → Categoria → Subcategoria. Só opções ativas aparecem em novos tickets; nomes podem mudar e códigos/histórico mantêm-se.
- “Outro” exige descrição e fica marcado para revisão. Tarefas antigas podem continuar “Por classificar”; nunca são convertidas automaticamente em “Outro”.
- Distinguir Supervisor de Executor. Descrever atribuição automática a utilizador/equipa, equipa “Por assumir” e “A aguardar atribuição”.
- Explicar elegibilidade, botão Assumir, reatribuição e auditoria.
- Explicar SLA de primeira resposta e resolução, estados Dentro do prazo/A terminar/Ultrapassado/Concluído/Pausado e datas em Europe/Lisbon.
- Explicar que “Minhas” é apenas um filtro. A segurança usa âmbito total, relação direta ou consulta, com permissões distintas para consultar, criar, assumir, atribuir, alterar, responder, concluir, gerir SLA e classificações.
- Atualizar a Administração com tipos, hierarquia, supervisores, executores, modo de atribuição, SLA, permissões e visibilidade.

## Manual Email

- Email continua independente: uma conversa só cria ticket por ação ou regra configurada.
- Documentar as caixas `hub@carfast.pt`, `multas@carfast.pt`, `oficina@carfast.pt`, `sinistros@carfast.pt` e `vvp@carfast.pt`.
- Por caixa/classificação explicar supervisor, executores elegíveis, atribuição, primeira resposta, resolução, pausa, permissões e auto-ticket.
- Mostrar no dashboard/conversa o executor/equipa, “Por assumir”, os dois SLA e atrasos.
- O envio usa sempre o endereço público da caixa como `From` e `Reply-To`, mantendo aprovação e Postmark.
- A receção usa `MailboxHash`; incluir a tabela de destinos exatos de `docs/email/STAGING_TEST.md`.
- Reforçar que o inbound base sem `+hash` é compatibilidade histórica exclusiva do hub e não deve ser usado nas novas regras.
- Preservar as instruções de anexos, HTML seguro, histórico, aprovação, deduplicação e regras de caixa.

## Nota de ativação

Não instruir o leitor a alterar DNS, Microsoft 365 ou Postmark automaticamente. A integração entrega código e runbook; cada mudança externa exige execução e aprovação administrativa próprias.
