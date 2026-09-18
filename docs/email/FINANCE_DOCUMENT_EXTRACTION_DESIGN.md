# Entrada documental financeira — desenho da etapa de extração

Estado: **proposta para revisão; não implementada nem ativada**. Esta especificação não autoriza processar emails históricos, ligar regras no Green, publicar documentos no SharePoint/OneDrive ou fazer lançamentos contabilísticos.

## Fronteira atual

- A regra de email pode ser limitada ao alias destinatário original. Um email só é resolvido automaticamente quando a mensagem atual tem pelo menos um anexo e todos ficaram guardados. A resolução do email **não** é tratamento fiscal.
- `EmailAttachment` conserva metadados de receção, estado `ingest_state`, caminho e SHA-256. Os bytes são guardados sob `EMAIL_STORAGE_ROOT` (ou `var/email` se não configurado).
- `Document` e `DocumentWorkflowState` representam o arquivo e estados independentes de ingestão, associação, extração, validação e destino. O arquivo usa `DOCUMENT_ARCHIVE_ROOT` na operação atual.
- A persistência efetiva dos volumes do Green e a política de backup/restauro devem ser comprovadas antes de ativar qualquer consumidor de anexos. Nunca considerar uma cópia SharePoint como a única fonte para visualização na app.

## Contrato proposto: um anexo, um documento, várias tentativas de extração

1. Um consumidor, inicialmente **desligado**, recebe somente `EmailAttachment.id` após a transação de receção confirmar `ingest_state=stored`. Nunca infere o anexo a partir do assunto, do remetente encaminhador ou de anexos antigos da conversa.
2. Uma ligação persistida `EmailAttachment → Document`, com `UNIQUE(email_attachment_id)` e `UNIQUE(document_id)`, torna a criação idempotente. O documento guarda a origem `email`, o ID da mensagem/anexo, nome, tamanho e SHA-256. A proveniência conserva separadamente o remetente efetivo, o encaminhador e o alias destinatário; nenhum deles é automaticamente o emitente fiscal.
3. Antes de criar um documento utilizável, confirmar que o ficheiro existe dentro da raiz permitida, é legível e o seu SHA-256 coincide com o registo. Copiar para armazenamento **persistente da app** sob uma chave imutável; escrever em ficheiro temporário, verificar tamanho/hash e promover atomicamente. Só então confirmar a ligação e o estado de ingestão do documento. Nunca sobrescrever bytes com o mesmo nome de ficheiro.
4. Se houver falha entre ficheiro e transação, o estado fica `queued`/`failed` e o reconciliador retoma pelo ID do anexo; ficheiros temporários ou órfãos são inventariados, não apagados automaticamente. Repetir a mesma mensagem/anexo não cria outro `Document`. Dois anexos iguais em mensagens diferentes mantêm proveniências distintas; eventual deduplicação física não elimina os seus registos.
5. Uma linha de outbox na mesma transação que confirma o documento agenda a extração. Chave única `(document_id, extractor_version)`; a execução reclama a linha com lease/timeout e trata retries sem efeitos duplicados. Registar versão do extrator, hash de entrada, início/fim, falha e resultado imutável. Reprocessar cria **nova versão de execução**, nunca apaga texto ou decisões anteriores.

O email pode estar resolvido enquanto cada documento segue pendente. Um anexo bloqueado ou ausente não entra nesta fila: o email continua pendente pelas regras de receção já existentes.

## Extração e classificação até ao ponto de decisão

O extrator devolve evidência estruturada e confiança, sem alterar tarefas, contabilidade ou arquivo externo:

| Campo | Significado / regra |
|---|---|
| `tipo_identidade` | Emitente/entidade: fornecedor, banco, financiadora, seguradora, colaborador, autoridade ou desconhecido. |
| `identidade` | Nome e NIF/identificador **lidos do documento**, com fonte e confiança; nunca apenas do email encaminhador. |
| `tipo_documento` | Fatura, nota de crédito, extrato, comprovativo, contrato, documento de leasing, outro ou desconhecido. |
| `tipo_acao` | Despesa, receita, financiamento, pagamento/conciliação, estorno, apenas arquivo, por determinar. |
| `associacao` | Viatura, contrato, fornecedor, período ou referência, sempre com evidência e possibilidade de não associação. |
| `efeito_contabilistico` | Proposta separada do tipo documental; extrato/comprovativo não gera uma segunda despesa. Vencimento não é prova de pagamento. |

Usar as regras contabilísticas já **aprovadas** como limite de automatismo. A leitura de leasing deve separar capital, juros e IVA quando existir evidência; não presumir uma categoria a partir do nome do ficheiro. `DocumentWorkflowState.extraction_status` passa por `queued → processing → extracted/failed`; validação, classificação operacional e arquivo continuam independentes. A extração técnica não confirma uma fatura nem lança movimentos.

Se o tipo/identidade for desconhecido, o ficheiro for ilegível ou a evidência ficar abaixo do limiar aprovado: manter o documento `por tratar`, guardar a razão e criar **uma** tarefa de alerta por `(document_id, reason_code)` com ligação ao documento. O destino proposto é Fila `Administração` → Departamento `Dep. Financeiro` → Categoria `Tarefas Financeiras`, resolvido por configuração da instalação, não por IDs fixos. Reexecuções atualizam evidência/estado da mesma ocorrência; não multiplicam tarefas. A resolução do email não é revertida por esta dúvida documental.

## Segurança e observabilidade

- Validar formato pelo conteúdo, limites de tamanho/páginas e autorização de leitura; não aceitar caminhos fornecidos pelo email como caminhos de armazenamento. Isolar falhas de OCR e não enviar ficheiros para serviços externos sem configuração e aprovação específicas.
- Conservar original e histórico de extrações, hashes, auditoria de transições e versões de regras. Restringir pré-visualização e logs para evitar expor dados fiscais desnecessários.
- Medir: anexos elegíveis, documentos criados, replays sem duplicação, hashes inválidos, extrações em fila/falhadas, desconhecidos e tarefas abertas. Alertar para fila parada e para divergência entre DB e ficheiros.
- Backfill de emails existentes é **operação separada**, com seleção explícita, pré-visualização de impacto, cópia de segurança e autorização; nunca executar por migração, bootstrap ou deploy.

## Ordem mínima de implementação (cada passo com revisão própria)

1. Provar armazenamento persistente/backup e implementar ligação idempotente anexo→documento + outbox, atrás de flag desligada. Testar crash/retry, hash inválido, ficheiro ausente e duplicados em PostgreSQL isolado.
2. Ligar um extrator técnico a essa outbox, guardar texto/JSON e versões imutáveis; testar só com PDFs sintéticos. Não classificar nem criar tarefas nesta fase.
3. Aplicar taxonomia e regras aprovadas, com tarefa deduplicada para desconhecidos e pré-visualização *read-only* do impacto. Rever amostras sem escrever nos emails/documentos reais.
4. Só após decisão expressa do André: piloto pequeno do alias `faturas@carfast.pt`, com métricas, reversão e validação de cada tipo documental. SharePoint/OneDrive é uma entrega posterior e nunca substitui a cópia persistente da app.

## Critérios de aceitação antes de qualquer ativação

- Reentrega do mesmo webhook, corrida entre trabalhadores e retry após crash produzem um único documento por anexo, uma tarefa por razão e histórico de extração preservado.
- Uma mensagem com fatura e extrato cria dois documentos independentes; o extrato não duplica despesa. Email DAF, destinatário ambíguo ou original desconhecido não entra na regra fiscal.
- Anexo de mensagem anterior da mesma conversa nunca satisfaz a elegibilidade de uma mensagem nova. PDF ausente, hash divergente ou anexo bloqueado não é marcado como extraído.
- A app continua a abrir o PDF quando a cópia SharePoint é removida; a restauração da base de dados e do volume documental é ensaiada em ambiente isolado.
- Documento desconhecido fica `por tratar` com uma única tarefa financeira; o estado do email pode permanecer resolvido.

## Decisões pendentes para André e equipa financeira

- Confirmar que formatos além de PDF entram no piloto e os limites de tamanho/páginas.
- Aprovar quais tipos documentais podem seguir automaticamente após extração, e o limiar de confiança por tipo. Os restantes ficam pendentes sem lançamento.
- Confirmar o responsável/tempo de resposta da tarefa de documento desconhecido e a política de reabertura quando uma nova extração altera a proposta.
- Validar o volume persistente da app, backups, retenção e restauro antes de qualquer fluxo com dados reais; decidir separadamente se/quando publicar cópia no SharePoint.
