# CarFast — ponto de situação operacional

Atualizado em 07/09/2026. Este documento é o ponto de retoma para coordenar trabalho local e Codex Cloud sem perder decisões.

## Regras de coordenação

- Esta branch é apenas de coordenação e documentação; não recebe desenvolvimento funcional.
- Cada alteração de produto usa uma branch própria e termina num PR Draft com testes e resumo do impacto.
- Não fazer merge nem deploy sem revisão e autorização explícita.
- GitHub é a fonte técnica para código e PRs; este documento regista decisões, estado e próximos passos.
- Não reutilizar o checkout principal antigo enquanto as respetivas alterações locais não forem auditadas.

## Situação confirmada

### Tarefas

- PR #136 integrado em `integration/modular-architecture`.
- Merge commit: `b6a7cc18f47a7eb15f1c5343c8f37da45d3f6f5e`.
- Implementação validada no Green.
- Pequenos ajustes posteriores devem ser entregues numa branch isolada, com comparação visual antes/depois.

### Email

- PR #137 integrado em `integration/modular-architecture`.
- Merge commit: `5bd7b9c787167294c347a9e459e482556459c0bb`.
- O resultado integrado ficou aquém da proposta visual aprovada.
- Correção visual concluída e publicada na branch `codex/email-mockup-fidelity-20260907`: base funcional `fa501cbf` e ajuste final dos contadores `f1bb8ec`.
- PR #138 integrado em `integration/modular-architecture`: https://github.com/andrecoroa/operational-hub-carfast/pull/138.
- Merge commit: `5004b02f09b723bb5ff96aab4e99456c05fb2fea`.
- Validação: 33 testes focados de Email aprovados; QA local a 1440×731 e 390×844; sintaxe Python e `git diff --check` sem erro.
- O CI remoto do PR #138 concluiu com sucesso (workflow run #404); o GitHub indica que o PR é integrável.
- A execução local da suite global apresentou falhas fora dos testes focados de Email; manter esta ressalva na revisão da baseline.
- Deploy Green confirmado: `/health` e CSS público responderam HTTP 200; as assinaturas da nova superfície de Email e da correção dos contadores estão publicadas.
- Estado: implementação publicada; falta apenas validação funcional autenticada pelo utilizador.

### Oficina

- Proposta compacta pronta, validada a 1024 px e 360 px.
- Objetivo: melhorar a lista de processos e permitir `Em espera` e `Pedir decisão`, sem duplicar o Centro de Tarefas.
- Artefacto: `C:/Users/andre/.codex/visualizations/2026/06/02/019e8ab1-286f-7713-926d-8de2f21373e0/oficina-processos-compactos.html`.
- Estado: aguarda aprovação funcional; implementação não iniciada.

### Auditoria documental e matrículas

- Operador em `C:/Users/andre/Documents/Codex/2026-09-05/operador-ia-auditoria-viaturas`.
- Inventário integral confirmado: 1.434 documentos e 7.724 linhas extraídas; 225 documentos sem linhas, dos quais 152 são importações diretas de stock fora do universo técnico.
- Permanecem problemas de qualidade e âmbito: duplicados, conflitos matrícula/VIN, regressões de quilometragem, linhas contaminadas e campos incorretos; a comparação visual integral dos PDFs ainda não foi realizada.
- Taxonomia v1.1 com 65 classes e amostra de 62 linhas reais: aprovada como baseline de auditoria, ainda não como versão de produção.
- Ajustes obrigatórios antes da implementação: bloquear `GLASS.REPLACE` para lava-vidros; formalizar eixo/lado como dimensões sem pseudocódigos; criar mapa explícito de códigos legados; guardar `taxonomy_version`, origem, confiança e bloqueio de validação humana.
- Ordem segura: (1) corrigir falsos positivos sem migrar dados; (2) fechar universo das verdadeiras faturas técnicas; (3) executar simulação sem escrita apenas sobre falhas reais; (4) apresentar impacto e riscos; (5) só depois autorizar migração/reprocessamento controlado.
- Princípios: preservar texto e documento originais, classificação anterior e rastreabilidade; contar serviços por `service_event_id`, nunca por linha.
- Estado: preparar especificação e testes das correções de falsos positivos; nenhuma alteração em massa autorizada.

### Estratégia de gestão

- Operador em `C:/Users/andre/Documents/Codex/2026-09-05/operador-ia-estrategia-gestao`.
- Existe material de análise, mas ainda não há relatório final em `outputs`.
- Estado: manter ativo e solicitar checkpoint próprio.

## Riscos do ambiente local

- O checkout principal antigo está em `codex/workshop-fleet-linked-creation`, com commits e alterações locais por auditar.
- Existem worktrees históricas, algumas marcadas como `prunable`; não remover antes de verificar trabalho exclusivo.
- Não apagar branches, worktrees, commits, projetos ou ficheiros até concluir essa auditoria.

## GitHub

- Único PR antigo aberto identificado: PR #25, Draft, desatualizado e com conflitos.
- Classificação: candidato a fechar depois de confirmar que não contém trabalho exclusivo necessário.

## Estrutura operacional recomendada

1. Este chat principal coordena decisões, prioridades, revisão, merge e deploy.
2. Codex Cloud executa desenvolvimento remoto em branches isoladas e entrega PRs Draft.
3. Auditoria de viaturas, Estratégia e Tratamento documental permanecem projetos separados.
4. Cada operador deixa no PR ou checkpoint: objetivo, alterações, testes, riscos e pendências.
5. O operador principal revê novos PRs e atualiza este documento antes de integrar.

## Checkpoint do Operador Cloud

- Auditoria inicial concluída na cópia Cloud limpa, branch interna `work`, commit `f17f2a7`.
- Os merges dos PRs #136 e #137 estão presentes no histórico dessa cópia.
- Nenhum código foi alterado pelo Operador Cloud.
- O checkout disponibilizado à tarefa não contém `remote` Git configurado nem autenticação GitHub; por isso o operador ainda não consegue confirmar PRs em tempo real, publicar branches ou criar PRs Draft pelo terminal.
- A correção de Email (`fa501cbf` + `f1bb8ec`) está publicada no PR Draft #138 e não deve ser recriada em paralelo.
- Antes de lhe atribuir desenvolvimento, validar num teste controlado o mecanismo de publicação de branch/PR disponibilizado pela plataforma.
- Mantêm-se proibidos merge, deploy, encerramento de PRs e eliminação de branches ou worktrees sem autorização explícita.

## Ordem de retoma

1. Validar funcionalmente o Centro de Email autenticado no Green.
2. Preparar especificação/testes dos falsos positivos do classificador, sem escrita em dados existentes.
3. Decidir a proposta de Oficina antes de iniciar implementação.
4. Auditar o checkout principal, worktrees antigas e PR #25.
5. Arquivar apenas conversas e projetos comprovadamente concluídos ou obsoletos.

## Instrução para novos trabalhos no Codex Cloud

Começar sempre a partir da base indicada pelo coordenador. Criar uma branch exclusiva `codex/<tema>`, limitar o âmbito ao pedido, executar testes proporcionais ao risco e abrir PR Draft. Não fazer merge nem deploy. No final, registar no PR o objetivo, ficheiros alterados, testes, riscos, decisões pendentes e relação com outros PRs.
