# Checklist imprimível — ativação CarFast Email + Postmark

**Data:** ____ / ____ / ______  
**Responsável da ativação:** ______________________________  
**Ambiente:** ☐ Staging ☐ Produção  
**Canal:** ☐ Tarefas ☐ Oficina ☐ Faturas ☐ Stock ☐ Auditoria

> Não colocar passwords, tokens, códigos MFA ou outros segredos neste impresso.

## A. Decisões e donos

- [ ] Domínio real confirmado: ______________________________________
- [ ] Fornecedor DNS confirmado: ___________________________________
- [ ] Owner DNS: _________________________________________________
- [ ] Administrador Microsoft 365/Exchange: ___________________________
- [ ] Responsável técnico CarFast: __________________________________
- [ ] Endereços públicos finais aprovados.
- [ ] `app.<domínio>` e `inbound.app.<domínio>` têm funções distintas.
- [ ] MX principal do domínio não será alterado.
- [ ] Canal e janela do piloto aprovados.
- [ ] Matriz de filas, módulos e permissões aprovada.
- [ ] Retenção de mensagens/anexos/auditoria aprovada.
- [ ] Storage privado de anexos escolhido e restore testado.
- [ ] Volume mensal estimado, contando inbound e todos os destinatários.
- [ ] Preço atual confirmado em https://postmarkapp.com/pricing/.

**Assinatura negócio:** ____________________  **Data:** __________  
**Assinatura técnica:** ____________________  **Data:** __________

## B. Postmark — staging

- [ ] Conta é propriedade da empresa, com password única e MFA.
- [ ] Acessos individuais por convite; nenhum login partilhado.
- [ ] Server `CarFast Email - Staging` criado.
- [ ] Transactional Message Stream ID registado: ______________________
- [ ] Inbound Stream identificado.
- [ ] Nenhum Broadcast Stream usado.
- [ ] Domínio de envio confirmado: __________________________________
- [ ] DKIM mostra `Verified`.
- [ ] Custom Return-Path mostra `Verified`.
- [ ] Inbound Domain é `inbound.app.<domínio-confirmado>`.
- [ ] Inbound webhook HTTPS staging configurado.
- [ ] Basic Auth dedicado configurado por canal seguro.
- [ ] Raw email está desligado, salvo justificação aprovada.
- [ ] Webhook de Delivery ativo.
- [ ] Webhook de Bounce ativo, conteúdo desligado.
- [ ] Webhook de Spam Complaint ativo, conteúdo desligado.
- [ ] Webhook de Subscription Change ativo.
- [ ] Open/Click tracking desligado.
- [ ] Todos os `Send test`/`Check` devolvem 2xx.

## C. DNS

- [ ] Foi feita captura/inventário dos registos antes da mudança.
- [ ] TXT DKIM copiado exatamente da Postmark.
- [ ] CNAME Return-Path copiado exatamente da Postmark.
- [ ] CNAME está `DNS only`, se aplicável.
- [ ] Não foi criado SPF Postmark adicional.
- [ ] MX de `inbound.app` aponta apenas para `inbound.postmarkapp.com`.
- [ ] Prioridade do MX inbound é 10.
- [ ] MX principal não foi alterado.
- [ ] Se `@app...` aloja caixas, o MX de `app` aponta para o valor Microsoft, não Postmark.
- [ ] Não há conflito de MX entre Microsoft 365 e Postmark.
- [ ] Resolução DNS verificada após propagação.

**Registos validados por:** ____________________  **Data/hora:** __________

## D. Aplicação staging

- [ ] Base de dados/migrações staging concluídas.
- [ ] Endpoints inbound/events acessíveis por HTTPS.
- [ ] Requests sem auth são rejeitados.
- [ ] Allowlist Postmark e proxy confiável validados.
- [ ] Schema, content-type e limites validados.
- [ ] Idempotência inbound e eventos testada.
- [ ] Storage de anexos é persistente e privado.
- [ ] HTML é sanitizado; original nunca é renderizado.
- [ ] Imagens remotas bloqueadas por defeito.
- [ ] Malware scan/quarentena testados.
- [ ] Logs não contêm tokens, Basic Auth, corpos ou Base64.
- [ ] RBAC por fila/módulo testado.
- [ ] Auditoria restrita a utilizadores autorizados.
- [ ] Outbox/idempotência outbound testada.
- [ ] Timeout ambíguo produz `unknown`, sem retry cego.
- [ ] Feature flags iniciais: inbound ______ outbound ______ auto-task ______ auto-document ______
- [ ] Health check Render verde.
- [ ] Alertas e dead-letter/revisão testados.

## E. Microsoft 365 — piloto

- [ ] Caixa piloto existe e tem owner/membros mínimos.
- [ ] Sign-in direto de shared mailbox bloqueado.
- [ ] Full Access/Send As revistos.
- [ ] Auditoria tem grupo restrito.
- [ ] Política custom outbound forwarding aplica-se só aos objetos necessários.
- [ ] `Automatic forwarding rules = On` apenas nessa política.
- [ ] Remote domain/mail flow rules não bloqueiam o domínio técnico.
- [ ] Encaminhamento aponta para o endereço técnico correto.
- [ ] `Deliver message to both forwarding address and mailbox` está ativo.
- [ ] Não existe regra Outlook paralela.
- [ ] Não existe mail flow rule paralela para a mesma caixa.
- [ ] Possível propagação de 30+ minutos foi considerada.

**Endereço público:** _____________________________________________  
**Endereço técnico:** _____________________________________________

## F. Smoke test

- [ ] Email texto simples recebido uma vez.
- [ ] Email HTML recebido e sanitizado.
- [ ] PDF e imagem persistem após restart/deploy.
- [ ] Anexo bloqueado fica em quarentena.
- [ ] Mensagem acima do limite tem comportamento controlado.
- [ ] Retry/duplicado não cria segunda tarefa/anexo.
- [ ] Matrícula/registo inequívoco é associado corretamente.
- [ ] Associação ambígua fica “Por triar”.
- [ ] Fatura normal é documento sem tarefa desnecessária.
- [ ] Fatura divergente cria/propõe tarefa Administração/Gestão.
- [ ] Resposta sai com From correto.
- [ ] Reply-To contém token opaco sem IDs de negócio.
- [ ] Reply regressa à mesma thread/tarefa.
- [ ] Reply numa conversa sem tarefa permanece Email e não cria tarefa.
- [ ] Utilizador responde no menu Email e estado passa a “A aguardar resposta”.
- [ ] Nova reply muda para “Nova resposta” e sobe na inbox.
- [ ] Concluir tarefa propõe “Resolver conversa”; opção pode ser desmarcada.
- [ ] Nova reply após conclusão não cria tarefa automaticamente.
- [ ] Utilizador com acesso à tarefa mas sem acesso ao email não vê remetente, corpo ou anexos protegidos.
- [ ] Partilha seletiva de descrição/entidades/anexos com a tarefa respeita permissões.
- [ ] Modelo renderiza variáveis permitidas e apresenta preview antes do envio.
- [ ] Página externa permite resposta/anexo sem acesso ao Hub e rejeita token expirado/revogado.
- [ ] Submissão para aprovação não envia o rascunho.
- [ ] Alteração após aprovação invalida a decisão e exige nova aprovação.
- [ ] Aprovador pode aprovar e enviar, aprovar para envio ou devolver com comentário.
- [ ] Remetente inesperado com token é sinalizado.
- [ ] Delivery aparece na UI.
- [ ] Soft/hard bounce têm estado correto.
- [ ] Complaint/suppression bloqueia novo envio.
- [ ] Utilizador sem permissão recebe acesso negado.
- [ ] Email piloto permanece também na caixa Microsoft 365.
- [ ] Zero loops.
- [ ] Reconciliação Postmark Activity ↔ CarFast sem diferenças.

**Amostra testada:** ______ mensagens  
**Diferenças encontradas:** ________________________________________

## G. Segurança de segredos

- [ ] Server Token foi introduzido diretamente na Render/gestor de segredos.
- [ ] Account Token não foi dado ao runtime.
- [ ] Password Postmark nunca foi partilhada.
- [ ] Passwords/MFA/cookies Microsoft 365 e DNS nunca foram partilhados.
- [ ] `.env` real não está em Git, chat, email ou ticket.
- [ ] Screenshots não expõem tokens, Environment ou faturação.
- [ ] Staging e produção usam segredos diferentes.
- [ ] Procedimento de rotação foi documentado/testado.

## H. Aprovação de produção

- [ ] Todas as fases de staging aprovadas.
- [ ] Server `CarFast Email - Production` separado.
- [ ] URLs, tokens e Basic Auth de produção novos.
- [ ] Backup e restore testados.
- [ ] Migrações retrocompatíveis e rollback ensaiado.
- [ ] Runbook e contactos de incidente disponíveis.
- [ ] Equipa formada na inbox, estados e quarentena.
- [ ] Monitorização reforçada nas primeiras 48 horas.
- [ ] Ativação é canal a canal.
- [ ] Auto-task/auto-document permanecem desligados no início.

**GO / NO-GO:** ☐ GO ☐ NO-GO  
**Negócio:** ____________________  **Data/hora:** __________  
**Técnico:** ____________________  **Data/hora:** __________  
**Microsoft/DNS:** ______________  **Data/hora:** __________

## I. Rollback rápido

- [ ] Desligar `EMAIL_OUTBOUND_ENABLED`.
- [ ] Desligar `EMAIL_AUTO_TASK_ENABLED` e `EMAIL_AUTO_DOCUMENT_ENABLED`.
- [ ] Desativar o encaminhamento da caixa afetada.
- [ ] Confirmar receção normal no Microsoft 365.
- [ ] Manter webhooks de eventos para mensagens já enviadas.
- [ ] Não apagar dados; marcar integração suspensa.
- [ ] Reconciliar mensagens durante o incidente.
- [ ] Se necessário, executar rollback Render para deploy anterior.
- [ ] Registar causa, período, impacto e decisão de retoma.

**Rollback executado por:** ____________________  
**Data/hora:** ____________________  
**Resultado:** ____________________________________________________
