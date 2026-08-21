# Inventário factual de alterações e evolução recente

Data de corte: 2026-08-21

Base auditada: `origin/v2/production` em `d77ae7c0e6ddfbedfc3f83bf661bb131a0d50c03`

Catálogo importável: `data/evolution_catalog_2026-08-21.json`

## Como ler os estados

- **Em produção**: o código está no ramo remoto `origin/v2/production`. Não significa que o deploy, dados externos ou parametrização tenham sido verificados independentemente.
- **Implementado em branch por integrar**: existe código e validação numa branch isolada, sem merge/push para production.
- **Em execução**: a tarefa Codex ainda não entregou resultado final; commits intermédios não são tratados como conclusão.
- **Proposta aprovada**: decisão aceite para trabalho futuro; ainda não está disponível na aplicação.
- **Apenas mockup/estudo**: artefacto visual ou análise, sem implementação funcional.
- **Bloqueado**: falta uma dependência concreta e a funcionalidade não deve ser anunciada como disponível.

Contagem no catálogo: **30 registos** — 15 em produção; 1 implementado em branch por integrar; 1 em execução; 10 propostas aprovadas; 2 apenas mockup/estudo; 1 bloqueado.

## Verificação das fontes

- O histórico Git de `origin/v2/production`, código, migrações, testes e documentação foram auditados numa worktree limpa.
- Os commits originais `104ff3fb` e `67d24ab0`, citados pela tarefa de Administração, não são ancestrais diretos do ramo remoto porque foram reaplicados. Os seus `patch-id` coincidem, respetivamente, com `29c430c2` e `0480e260`, que estão em production.
- As caixas funcionais foram reaplicadas em production como `bbaa0650`, `60d87fec`, `dd036723` e `8220be9a`.
- As classificações provisórias foram reaplicadas como `597148f0`, `09dab709` e `20d5d624`; `86bf697e` encadeou as duas migrações e `d77ae7c0` limpou imports integrados.
- A ação “Tirar fotografia” permanecia ativa e sem entrega final verificável no corte.
- As tarefas do Construtor de Fluxos e de modelos/tarefas entregaram apenas imagens/protótipos fora do repositório.

## Administração/permissões

| Título | Descrição breve | Estado | Origem | Dependências | Próximo passo |
|---|---|---|---|---|---|
| Administração modular, pesquisa e permissões operacionais | Sete domínios administrativos, pesquisa, Operações e Service Desk e gestão granular, preservando legacy. | **Em produção** | `29c430c2`, `0480e260`, `2405031a`; task `01a0219b…` | RBAC, âmbitos e gates server-side | Validar a matriz com perfis reais; manter aliases legacy enquanto houver uso. |

## Centro de Tarefas/Service Desk

| Título | Descrição breve | Estado | Origem | Dependências | Próximo passo |
|---|---|---|---|---|---|
| Service Desk com âmbito, atribuição e SLA | Tipos, hierarquia, supervisor/executor, assumir, atribuir, primeira resposta, resolução, pausa e auditoria. | **Em produção** | `fd1f61c0`, `9461cdf3`, `fe62f9b2` | Motor de tarefas, classificação, permissões | Testes negativos com perfis/âmbitos reais. |
| Recorrência segura e fluxos guiados leves | Modelos idempotentes de recorrência e checklists estáticos sem substituir processos. | **Em produção** | `f39a61ed`, `69be6cca`; migração `ff6e7f8a9b0c` | Scheduler, modelos e ocorrências | Parametrizar e monitorizar ocorrências ignoradas/duplicadas. |
| Modelos, editor e sequências do Centro de Tarefas | Proposta visual de modelos versionados, checklists e sequências simples. | **Apenas mockup/estudo** | task `01a021d8…`; 7 imagens e HTML | Contrato canónico, versões e Processos | Aprovar o modelo funcional antes de implementar. |

## Centro de Processos

| Título | Descrição breve | Estado | Origem | Dependências | Próximo passo |
|---|---|---|---|---|---|
| Centro de Processos e gestão de ocorrências | Processos tipificados, associações, regras, ações, evidências, histórico e sinistros/AR. | **Em produção** | `4f1eefbf`; `management_center.py` | Histórico e importações de origem | Manter processos complexos aqui e tarefas como execução ligada. |

## Email/Postmark

| Título | Descrição breve | Estado | Origem | Dependências | Próximo passo |
|---|---|---|---|---|---|
| Centro de Email Postmark, conversas e entregas preservadas | Inbound/outbound, triagem, anexos, aprovação, threading, deduplicação por caixa e Reply All seguro. | **Em produção** | `34fa4b0c`, `4d7007d9`, `29c430c2`; `ffe04c5d6e7f` | Postmark, storage privado, acesso por caixa | Piloto em staging antes de alterações externas. |
| Caixas funcionais configuráveis e compositor por política | Sete caixas adicionais, aliases/hashes reais configuráveis, SLA, filtros, políticas, Cc/Bcc e modelos. | **Em produção** | task `01a021cf…`; `bbaa0650`…`8220be9a` | Dados M365/Postmark e migração `ffd02a3b4c5e` | Alembic/testes em staging; parametrizar endereços reais depois. |
| Pipeline de anexos no envio | Armazenar/enviar anexos e invalidar aprovação quando mudam. | **Bloqueado** | limitação confirmada na task `01a021cf…` | Pipeline outbound inexistente | Definir contrato de storage/envio e implementar testes. |

## Estruturas/tipos/modelos

| Título | Descrição breve | Estado | Origem | Dependências | Próximo passo |
|---|---|---|---|---|---|
| Classificação comum entre Tarefas e Email | Fila, Departamento, Categoria e Subcategoria partilhadas, editáveis e ordenáveis. | **Em produção** | `56ca0a15`, `89052cab`, `172b561b`, `cff55796` | Tabelas `Work*` | Preservar códigos estáveis e impedir catálogos paralelos. |
| Modelos de tarefas propostos | Editor, versões, checklist e sequências descritos nos mockups do Centro de Tarefas. | **Apenas mockup/estudo** | task `01a021d8…` | Decisão de produto e versionamento | Consolidar com o futuro Construtor, sem duplicar Processos. |

## Construtor de Fluxos

| Título | Descrição breve | Estado | Origem | Dependências | Próximo passo |
|---|---|---|---|---|---|
| Construtor de Fluxos visual | Canvas e parametrização do bloco “Calcular valor”; não existe motor genérico no código auditado. | **Apenas mockup/estudo** | task `01a021fc…`; 2 PNG | Contrato versionado, publicação e permissões | Aprovar arquitetura e serialização antes de construir. |

## Classificações provisórias

| Título | Descrição breve | Estado | Origem | Dependências | Próximo passo |
|---|---|---|---|---|---|
| Propostas provisórias de categoria/subcategoria | Propor, reutilizar semelhantes, marcar provisório e rever/aprovar/fundir/reclassificar com auditoria. | **Em produção** | task `01a021f3…`; `597148f0`, `09dab709`, `20d5d624`, `86bf697e` | Classificação comum, Evolução e `ffd05e6f7a8b` | Alembic e validação com dados/perfis representativos em staging. |

## Evolução

| Título | Descrição breve | Estado | Origem | Dependências | Próximo passo |
|---|---|---|---|---|---|
| Registo de Evolução e criação global contextual | Backlog, prioridade, estado, referências, comentários, documentos, histórico e botão global autorizado. | **Em produção** | `986189a1`, `29c430c2`; `evolution.py` | Permissões `admin.evolution.*` | Usar a UI no dia a dia e importação idempotente para catálogos. |
| Inventário, manuais e importador idempotente | Este catálogo, três manuais e importador conservador com dry-run e relatório. | **Implementado em branch por integrar** | task `01a02239…`; branch `codex/manuals-evolution-inventory-20260821` | Revisão e autorização de produção | Integrar commits; executar primeiro dry-run na base alvo. |

## Fotografia/anexos

| Título | Descrição breve | Estado | Origem | Dependências | Próximo passo |
|---|---|---|---|---|---|
| Media e anexos existentes | Media em oportunidades, anexos de tarefas/Email e documentos de processos; não são ainda uma ação transversal. | **Em produção** | `875e27d8`, `cff55796`; modelos `Document`, `EmailAttachment`, `TaskDocument` | Storage e autorização por módulo | Reutilizar ficheiros por referência, sem duplicação física. |
| Ação reutilizável “Tirar fotografia” | Captura configurável, validação e ligação a tarefa/processo/fase/viatura. | **Em execução** | task `01a0222d…` | Documentos, permissões, versões da Oficina | Aguardar entrega/testes; ligação futura ao canvas usa o mesmo esquema. |

## Oficina

| Título | Descrição breve | Estado | Origem | Dependências | Próximo passo |
|---|---|---|---|---|---|
| Modelos versionados, visão operacional e integração Stock | Editor de versões, visão de processos, fluxo simplificado e pedidos/consumos de Stock. | **Em produção** | `7534490f`, `b7704525`, `81858760`, `959baa76`, `a3357a1e` | Modelos versionados, Processos e Stock | Preservar snapshots e reutilizar evidências comuns. |

## Stock

| Título | Descrição breve | Estado | Origem | Dependências | Próximo passo |
|---|---|---|---|---|---|
| Inventário, compras, ciclo de vida e receção de faturas | MVP, UI Clean, catálogo, encomendas, receções e consumos de Oficina. | **Em produção** | `424ff707`, `e67adfb9`, `72fd8589`, `f64ee424`, `f69d0273` | OCR, receções, catálogo e Oficina | Monitorizar reconciliação fatura–receção sem perda documental. |

## Frota/vendas

| Título | Descrição breve | Estado | Origem | Dependências | Próximo passo |
|---|---|---|---|---|---|
| Pesquisa, finanças e propostas versionadas | Paginação/filtros, normalização Rentway, planos/auditoria financeira e negociação comercial versionada. | **Em produção** | `65f0d000`, `50f40c9d`, `b84fdec6`, `edbd3db6`, `46b50fff`, `95ece8cd` | Rentway, planos e documentos | Validar imports e preservar snapshots/cálculos. |

## Documentação/faturas

| Título | Descrição breve | Estado | Origem | Dependências | Próximo passo |
|---|---|---|---|---|---|
| Documentação Clean, faturas e diagnósticos | Fluxos centralizados, preview, OCR/importação, tratamento por viatura e diagnósticos técnicos. | **Em produção** | `52748a70`, `28f95bab`, `692e1850`, `9c6e9937`, `0ef635ad` | Documentos, OCR, Frota, Stock e storage | Testar documentos reais por amostragem e auditar reclassificações. |

## Integrações

| Título | Descrição breve | Estado | Origem | Dependências | Próximo passo |
|---|---|---|---|---|---|
| Postmark e Rentway | Routing por MailboxHash/regras e imports para Frota, finanças e processos. | **Em produção** | `a0e6c464`, `c2840d9f`, `50f40c9d`, `11a036b1` | Segredos, M365, Postmark e exports | Distinguir código de ativação externa e versionar snapshots Rentway. |

## Programa planeado — Gestão Diária e Performance Operacional

Os itens 1–9 são **propostas aprovadas** e o item de IA é uma **fase futura planeada/adiada**. Nenhum está disponível agora. A associação ao programa principal é preservada no catálogo por `program_key: daily-management.program`.

| Chave / título | Descrição breve | Prioridade | Dependências | Próximo passo |
|---|---|---|---|---|
| `daily-management.program` — Centro de Gestão Diária | Módulo transversal Planear, Executar e Analisar. | Alta | Service Desk, Email, Processos, Rentway, escalas | Arquitetura e piloto por equipa/local. |
| `daily-management.capacity-planning` — Planeamento de capacidade | Carga por intervalos, recursos, competências e recomendações explicáveis. | Alta | Rentway, escalas, tempos médios, competências | Definir intervalos, unidades e fontes. |
| `daily-management.daily-plan` — Plano Operacional Diário | Momentos, checklists, responsáveis, previsto/real, evidências e passagem de turno. | Alta | Processos, tarefas, fotografia/anexos | Modelar piloto sem duplicar fontes. |
| `daily-management.productivity` — Produtividade e autoria real | Planeado/adicional, executor/supervisor, tempos, espera, bloqueio e retrabalho. | Alta | Eventos e tempos comuns | Semântica, privacidade e interpretação justa. |
| `daily-management.activity-reporting` — Relatório operacional | Volume, pendentes, primeira resposta, resolução, média, mediana, p90 e SLA. | Alta | Eventos, histórico e autoria | Aprovar definições métricas. |
| `daily-management.capacity-alerts` — Ocupação e alertas | Previsto/real, capacidade livre, horas extra, backlog, risco e recomendações humanas. | Alta | Planeamento, eventos e SLA | Limiar, explicação e confirmação humana. |
| `daily-management.rentway-analytics` — Analytics Rentway | Reservas, cancelamentos, utilização, tendências e previsão versus realizado. | Alta | Imports versionados e snapshots | Inventariar exports e chaves imutáveis. |
| `daily-management.shift-handover` — Fecho e passagem de turno | Resumo, desvios, transferência e capacidade do dia seguinte. | Normal | Plano Diário e relatórios | Regras de fecho/reabertura/assinatura. |
| `daily-management.event-layer` — Eventos operacionais comuns | Envelope analítico de criado a cancelado, sem duplicar fontes. | Alta | Históricos, identidade, timestamps, idempotência | Definir envelope e projeções. |
| `daily-management.ai-recommendations` — Recomendações e IA | Resumos/previsões explicáveis, nunca decisões automáticas de pessoal; fase futura adiada. | Baixa | Dados estáveis, governação e explicabilidade | Adiar até métricas e snapshots estarem validados. |

## Limitações e itens não verificáveis

- Não foi feita escrita nem leitura de dados de produção; “em produção” deriva da presença no ramo remoto indicado.
- Não foram verificados DNS, encaminhamento Microsoft 365, tokens, webhooks ou atividade real do Postmark.
- Não foram inventados endereços para as novas caixas funcionais.
- A tarefa de fotografia pode avançar depois da data de corte; o catálogo deve ser atualizado idempotentemente quando houver entrega final verificável.
