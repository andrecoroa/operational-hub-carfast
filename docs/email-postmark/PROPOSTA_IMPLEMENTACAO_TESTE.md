# Proposta de teste interno — Email operacional

## Âmbito implementado

O piloto cobre cinco caixas Microsoft 365 mantidas como módulos de email
independentes: `hub@carfast.pt`, `multas@carfast.pt`, `oficina@carfast.pt`,
`sinistros@carfast.pt` e `vvp@carfast.pt`.

Cada caixa tem permissões, supervisor, executores elegíveis, atribuição, regras e
SLA próprios. A conversa não cria ticket salvo ação humana ou regra ativa.

## Routing confirmado

Encaminhar manualmente cada caixa para:

- hub: `da0078240da719f585b6f441e02a1951+hub@inbound.postmarkapp.com`
- multas: `da0078240da719f585b6f441e02a1951+multas@inbound.postmarkapp.com`
- oficina: `da0078240da719f585b6f441e02a1951+oficina@inbound.postmarkapp.com`
- sinistros: `da0078240da719f585b6f441e02a1951+sinistros@inbound.postmarkapp.com`
- vvp: `da0078240da719f585b6f441e02a1951+vvp@inbound.postmarkapp.com`

O inbound base sem `+hash` é aceite apenas para compatibilidade histórica do
hub. Um hash desconhecido não deve cair silenciosamente noutra caixa.

## Sequência do piloto

1. Integrar os commits em staging e aplicar a migração.
2. Executar o bootstrap duas vezes e confirmar as cinco caixas sem duplicados.
3. Introduzir segredos no gestor de ambiente, nunca no repositório.
4. Testar payloads sintéticos com `MailboxHash` principal, `ToFull`, endereço plus,
   conflitos, retries e inbound base histórico.
5. Configurar manualmente o webhook Postmark de staging.
6. Configurar uma única caixa Microsoft 365, mantendo uma cópia na mailbox.
7. Validar permissões negativas, anexos, atribuição, SLA e auto-ticket desligado.
8. Ativar outbound apenas depois de confirmar remetentes e testar aprovação,
   `From` e `Reply-To` da caixa pública.
9. Repetir para as restantes caixas uma de cada vez.

## Critérios de aceitação

- Cada mensagem aparece uma vez e na caixa correta.
- Histórico e anexos persistem e continuam protegidos por caixa.
- Só executores ativos, elegíveis e de perfil permitido podem ser selecionados.
- “Por assumir na equipa” exige claim de um membro elegível.
- Primeira resposta, resolução, aviso, atraso e pausa/retoma ficam auditados.
- Respostas mantêm aprovação e saem pelo endereço público da respetiva caixa.
- A receção de uma conversa não cria ticket por defeito.
- Nenhum passo altera automaticamente DNS, Microsoft 365, Postmark ou produção.
