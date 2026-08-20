# Checklist de ativação — CarFast Email + Postmark

Este checklist é manual. Não autoriza alterações automáticas em Postmark,
Microsoft 365, DNS, Render ou produção e nunca deve conter tokens, passwords,
códigos MFA ou outros segredos.

## Destinos confirmados

O inbound base confirmado no painel Postmark é:

`da0078240da719f585b6f441e02a1951@inbound.postmarkapp.com`

Não encaminhar as caixas para esse endereço base. Configurar exatamente:

| Caixa Microsoft 365 | Encaminhar para |
|---|---|
| `hub@carfast.pt` | `da0078240da719f585b6f441e02a1951+hub@inbound.postmarkapp.com` |
| `multas@carfast.pt` | `da0078240da719f585b6f441e02a1951+multas@inbound.postmarkapp.com` |
| `oficina@carfast.pt` | `da0078240da719f585b6f441e02a1951+oficina@inbound.postmarkapp.com` |
| `sinistros@carfast.pt` | `da0078240da719f585b6f441e02a1951+sinistros@inbound.postmarkapp.com` |
| `vvp@carfast.pt` | `da0078240da719f585b6f441e02a1951+vvp@inbound.postmarkapp.com` |

O texto depois de `+` é o `MailboxHash` recebido no payload Postmark. O
endereço base sem hash existe apenas como fallback histórico para o hub.

## Antes de integrar

- [ ] Branch e commits revistos; nenhum push/merge direto em produção.
- [ ] Migração aplicada em staging e `alembic heads` devolve um único head.
- [ ] Backup/restore de staging validado.
- [ ] Bootstrap executado duas vezes sem duplicar caixas, permissões ou relações.
- [ ] Storage privado e persistente de anexos configurado.
- [ ] Segredos introduzidos apenas no gestor de ambiente.
- [ ] Inbound ativo; outbound e auto-ticket inicialmente desligados.

## Postmark, execução manual

- [ ] Confirmar no Server correto o inbound base mostrado acima.
- [ ] Configurar o webhook HTTPS `/api/webhooks/postmark/inbound` com Basic Auth.
- [ ] Testar o webhook e exigir uma resposta 2xx.
- [ ] Configurar `/api/webhooks/postmark/events` para delivery, bounce e complaint.
- [ ] Confirmar DKIM e Return-Path copiando somente os valores do painel.
- [ ] Confirmar que o Server Token nunca foi guardado no repositório.

Esta solução não precisa de criar um domínio inbound alternativo nem de alterar
o MX principal. Qualquer configuração DNS necessária ao envio deve ser copiada
do painel Postmark e aprovada separadamente.

## Microsoft 365, execução manual por caixa

- [ ] Ativar encaminhamento apenas para o destino exato da respetiva linha.
- [ ] Manter “Deliver message to both forwarding address and mailbox”.
- [ ] Não manter uma regra Outlook/mail-flow paralela que duplique mensagens.
- [ ] Se o tenant bloquear forwarding externo, criar uma exceção de âmbito mínimo.
- [ ] Fazer piloto numa caixa antes de configurar a seguinte.

## Smoke test por caixa

- [ ] A mensagem permanece na caixa Microsoft 365.
- [ ] O payload contém o `MailboxHash` esperado e cai na caixa CarFast correta.
- [ ] Um retry não cria nova conversa, mensagem ou anexo.
- [ ] HTML é sanitizado e anexos continuam acessíveis após restart/deploy.
- [ ] Perfis sem permissão à caixa não veem conversa nem anexos.
- [ ] Só aparecem executores ativos, elegíveis e de perfil permitido.
- [ ] Atribuição manual, automática e “Por assumir na equipa” ficam auditadas.
- [ ] SLA de primeira resposta e resolução, pausa/retoma e atraso funcionam.
- [ ] Resposta aprovada sai com `From` e `Reply-To` iguais à caixa pública.
- [ ] Uma conversa sem regra de auto-ticket continua independente.

Teste adicional do hub: entregar um payload sintético no inbound base sem hash e
confirmar que é associado ao histórico de `hub@carfast.pt`.

## Produção e rollback

- [ ] Ativação aprovada caixa a caixa, com segredos próprios de produção.
- [ ] Em incidente, desligar outbound/auto-ticket e o forwarding da caixa afetada.
- [ ] Não apagar histórico; reconciliar Postmark Activity, Microsoft 365 e CarFast.
- [ ] Registar causa, impacto, responsável e decisão de retoma.
