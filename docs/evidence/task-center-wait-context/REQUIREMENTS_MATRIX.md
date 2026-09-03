# Centro de Tarefas — matriz de suporte e alteração mínima

| Requisito | Suporte atual confirmado | Alteração mínima desta tranche |
|---|---|---|
| Espera com motivo, justificação e retoma | `waiting_reason`, `waiting_reason_detail`, `TaskHistory` e auditoria já existem; faltava prazo próprio | Adicionar apenas `Task.waiting_until`; validar os três campos no endpoint dedicado de transição |
| Separar prazo, espera e SLA | `due_on`, `resolution_due_at` e `sla_pause_on_waiting` já são distintos | Expor rótulos distintos e registar a política SLA no evento da entrada em espera; não mudar a política |
| Contexto estruturado | Relações/colunas já cobrem origem, Email, categoria/subcategoria, departamento/fila, equipa/pessoa, matrícula, reserva, contrato, fatura, caso, processo e documentos | Reutilizar os campos existentes; mostrar apenas os aplicáveis e não criar metadata paralela |
| Transição independente da edição | `/v2-clean/tasks/{id}/transition` já é endpoint próprio e a edição preserva o estado | Acrescentar os dados condicionais apenas ao diálogo/formulário de transição |
| Preview/edição leves | Preview inline e detalhe com progressive disclosure já existem | Acrescentar uma faixa compacta de espera; manter restantes campos/contexto em `Mais opções` |
| Compatibilidade | Há tarefas antigas em espera sem prazo próprio | Coluna nullable; leitura identifica legado sem prazo; qualquer nova mutação/retorno para `waiting` passa a exigir contexto completo e futuro |
| Segurança | Resolver de workspace/scope, capabilities, sessão e auditoria já protegem a transição | Manter os mesmos gates server-side; validar payload depois da autorização e antes da mutação |
| Paridade de superfícies | Clean transition, REST create/PATCH, gestão legacy e retorno de suporte podiam divergir | Um validador em `task_workflow` normaliza ou rejeita motivo, detalhe e prazo; saídas limpam os três campos e deixam histórico |
| Mudança de hora | `datetime-local` não transporta offset | Horas Lisboa inexistentes ou ambíguas são rejeitadas; instantes válidos são persistidos em UTC |

Decisão de schema: a data/hora de retoma é estado atual consultável e filtrável, não apenas evidência histórica. Guardá-la em `TaskSlaEvent.details_json` tornaria o read-back dependente de reconstrução de eventos. A coluna nullable e indexada é a única migração aditiva desta tranche.

## Evidência local

- Base canónica congelada: `02354c7da50fd5a991efdd7d8054b282122ddeb5`.
- Testes focados finais após o forward fix: 137 PASS (contrato, API, suporte e cinco testes de head Alembic).
- Suite CI exata: 254 PASS.
- Suite integral: 959 PASS / 39 FAIL. A revisão anterior sobre a mesma base tinha 952 PASS / 44 FAIL; as cinco falhas removidas eram expectativas do head `fff7bc2d3e4f`, e os dois novos testes explicam o aumento de PASS. Não surgiu falha nova do candidato; as 39 restantes são dívida ampla fora desta tranche e não pertencem ao conjunto CI canónico.
- Baseline arquitetural: PASS; atualização explícita do fingerprint de post-actions pela ampliação do formulário de transição dedicado.
- Alembic graph: uma única head `fff8cd3e4f5a`.
- Compile/import: PASS.
- Browser sintético, Email inbound/outbound OFF:
  - desktop 1440×731: transição dedicada para Em espera, campos condicionais obrigatórios, retoma `05/09/2026 10:30` lida sem desvio, preview inline e overflow horizontal 0;
  - detalhe: prazo da tarefa, prazo da espera e SLA separados; contexto aplicável dentro de `Mais opções`;
  - mobile 390×844: diálogo x=17..358 dentro do viewport, campos visíveis/obrigatórios, foco inicial no estado e overflow horizontal 0.
  - renovação pós-P1: preview montado imediatamente sob a linha selecionada; desktop 1440×731 e mobile 390×844 sem overflow horizontal; Escape fecha, limpa seleção e devolve foco à linha; scroll vertical disponível em ambos.
- PostgreSQL local: porta 5432 acessível, mas as contas de teste documentadas foram rejeitadas pelo servidor instalado. Não foi usada qualquer base externa ou Green. O workflow CI contém PostgreSQL 17 isolado e executa upgrade → downgrade → upgrade → `current --check-heads`; esse check remoto é gate bloqueante do PR Draft.

## Risco residual e rollback

- Registos antigos em `waiting` continuam legíveis com `waiting_until=NULL`; a nova obrigatoriedade só se aplica a novas transições.
- A política `sla_pause_on_waiting` não muda: é registada no evento `waiting_context_set` e apresentada ao utilizador.
- Downgrade local da nova revisão remove apenas índice/coluna aditivos; não será executado em Green nesta tranche.
- Sem merge/deploy. Se o PostgreSQL isolado do CI falhar, o PR permanece Draft e a migração/código são corrigidos antes de qualquer novo gate.
