# Manual — Email

## Funcionamento em poucas palavras

O módulo Email recebe mensagens via Postmark, separa-as por caixa autorizada, agrupa-as em conversas, preserva anexos e entregas técnicas e permite triar, assumir, responder, aprovar, associar ou converter em tarefa. Email continua independente do Service Desk: uma conversa só cria uma tarefa por ação do utilizador ou regra configurada.

## Disponível agora

- Caixas base `hub@carfast.pt`, `multas@carfast.pt`, `oficina@carfast.pt`, `sinistros@carfast.pt` e `vvp@carfast.pt`.
- Caixas configuráveis Seguradoras, Brokers, Dep. Financeiro, Reports, Administrativo, Suporte e Outros; os endereços/hashes reais continuam por parametrizar.
- Routing inbound por `MailboxHash`, regras de caixa e compatibilidade histórica controlada do hub.
- Pesquisa e filtro por estado/caixa.
- Conversas, mensagens, HTML sanitizado, anexos privados e preview de PDF.
- Triagem pela classificação comum e atribuição/assunção com elegibilidade.
- SLA de primeira resposta e resolução.
- Rascunho, aprovação, envio e threading de respostas Postmark.
- Responder e Responder a todos; o servidor exclui endereços/aliases internos.
- Deduplicação por RFC `Message-ID` ou fallback conservador dentro da mesma caixa; caixas diferentes mantêm isolamento de autorização.
- Preservação de entregas, `Para`, `Cc` e origem técnica para auditoria.
- Conversão explícita em tarefa e ligações existentes.
- Políticas por caixa, proprietário/executor, permissões avançadas de destinatários e modelos hierárquicos.
- Propostas provisórias de classificação com revisão administrativa.

## Operador simples

### O que vê, consulta e pesquisa

O operador com `email.read` vê apenas caixas autorizadas ao seu perfil/utilizador. Pode filtrar por **Por triar**, **Em tratamento**, **A aguardar resposta**, **Nova resposta**, **A aguardar aprovação**, **Devolvido**, **Associado**, **Convertido em tarefa**, **Resolvido** e **Arquivado**, ou pesquisar assunto/remetente nos limites da caixa.

Ao abrir uma conversa, consulta remetente, assunto, mensagens, anexos, `Para`, `Cc`, origem recebida, classificação, atribuição, SLA e tarefa ligada. A mesma correlação técnica noutra caixa não concede acesso ao conteúdo dessa caixa.

### Criar/enviar e limites

Com `email.reply`, pode preparar nova mensagem ou resposta conforme as caixas permitidas. O envio real pode exigir `email.approve`; guardar rascunho não equivale a enviar. Não altere destinatários para contornar uma política de caixa. O botão genérico de anexar no outbound ainda não tem pipeline concluído e não deve ser anunciado como funcional.

## Executor

### Assumir e receber trabalho

Uma conversa pode estar por triar, atribuída ou disponível a executores elegíveis. **Assumir** exige `email.assume` e elegibilidade na classificação/caixa. A atribuição por supervisor exige `email.assign` ou permissão administrativa correspondente.

### Tratamento, SLA e comentários

1. Confirme que a mensagem caiu na caixa correta e reveja `Para`, `Cc` e origem.
2. Classifique Fila → Departamento → Categoria → Subcategoria.
3. Assuma ou aceite atribuição e faça a primeira resposta dentro do SLA.
4. Use o estado **A aguardar resposta** apenas quando depende do interlocutor; retome ao chegar nova resposta.
5. Registe decisões no histórico/auditoria e, quando necessário, crie tarefa ligada.

### Responder, aprovar e concluir

- **Responder** usa um destinatário principal editável quando a política permite.
- **Responder a todos** é recalculado no servidor e remove aliases/endereço de envio CarFast.
- O `From`/`Reply-To` é o endereço público da caixa configurada.
- Alterações relevantes após aprovação exigem nova revisão; não envie conteúdo diferente do aprovado.
- Marque **Resolvido** quando o tratamento terminou; use **Arquivado** conforme política, sem eliminar histórico.

### Anexos e ligações

Anexos recebidos podem ser pré-visualizados/descarregados apenas com autorização da conversa e classificados quando permitido. Converta em tarefa quando existe execução concreta; não crie automaticamente um ticket para toda a mensagem.

## Supervisor

### Triagem, atribuição e prioridades

O supervisor revê caixa, classificação, responsável, prioridade e SLA. Deve distinguir proprietário funcional, executor e aprovador. Atribua apenas utilizadores elegíveis e investigue mensagens em “Outros” ou regras sem correspondência.

### SLA, escalamento e validação

Monitorize primeira resposta, resolução e atrasos por caixa/classificação. Escale para tarefa ou processo quando a conversa exige execução complexa. Aprove respostas apenas depois de validar destinatários, caixa remetente, conteúdo e contexto; a aprovação deve ficar auditada.

### Reabertura e auditoria

Uma nova resposta pode reabrir trabalho resolvido conforme regras. Use eventos Postmark, entregas estruturadas e auditoria do Email para investigar duplicação, bounce, complaint ou entrega na caixa errada. Nunca mova mensagens entre perímetros por atualização direta de base.

## Implementador/parametrizador

### Caixas, regras e modelos

- Parametrize canais, acessos por perfil/utilizador, elegibilidade, regras de inbox, tipos/classificações e modelos.
- As cinco caixas base e respetivos hashes estão documentados no runbook Postmark.
- As caixas adicionais deixam endereços/hashes vazios até serem fornecidos e validados dados reais.

### Segurança e permissões

Use `email.read`, `email.triage`, `email.reply`, `email.approve`, `email.manage`, `email.assume`, `email.assign` e `email.sla.manage`. Aplique também acesso à caixa e elegibilidade. Valide MIME/conteúdo, nomes seguros e storage privado; não exponha URLs públicas.

### Postmark, automações e testes

- Inbound: `/api/webhooks/postmark/inbound`, protegido conforme configuração.
- Eventos: `/api/webhooks/postmark/events` para delivery, bounce e complaint.
- Teste `MailboxHash`, `ToFull`, retries, idempotência, duas entregas na mesma caixa e cópias em caixas distintas.
- Teste Reply All, remoção de aliases internos, aprovação, mudança de destinatário/remetente e acesso negado.
- Nunca coloque tokens no repositório ou relatórios.

### Publicação e reversão

1. Integrar código e migrações numa branch própria.
2. Confirmar head Alembic único, Ruff, `py_compile`, testes e `git diff --check`.
3. Aplicar em staging e testar uma caixa com outbound/auto-ticket desligados.
4. Configurar Microsoft 365/Postmark manualmente, uma caixa de cada vez, mantendo cópia na mailbox quando aprovado.
5. Em falha, desativar forwarding/regra externa e manter dados recebidos. Não apagar eventos, mensagens ou entregas para “reverter”.

## Planeado/em implementação — não disponível agora

- Pipeline de anexos outbound: **bloqueado** por falta de contrato de armazenamento/envio.
- Programa **Gestão Diária e Performance Operacional**: **planeado**; relatórios de volume/tempos e eventos comuns ainda não existem como módulo transversal.
- Recomendações/IA de gestão: fase futura, explicável e sem decisões automáticas de pessoal.

## Referências

- `docs/email-postmark/README.md`
- `docs/email-postmark/GUIA_CONFIGURACAO_ANDRE.md`
- `docs/email/STAGING_TEST.md`
- `docs/RELATORIO_INTEGRACAO_SERVICE_DESK_EMAIL.md`
- `docs/INVENTARIO_EVOLUCAO_RECENTE_2026-08-21.md`
