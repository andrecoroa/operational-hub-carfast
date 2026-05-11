# CarFast Operational Hub - Blueprint

## Objetivo

Construir uma aplicacao complementar ao Rentway para funcionar como hub operacional, sistema de auditoria, gestor de processos, manual operacional vivo e plataforma de suporte a decisao da CarFast.

A aplicacao nao substitui o Rentway. O Rentway continua a ser o sistema principal para contratos, operacao diaria da frota e gestao financeira base. Este sistema existe para transformar relatorios do Rentway em controlo, auditoria, alertas, dashboards, workflows e inteligencia operacional.

## Principio Fundamental

Nao duplicar trabalho.

Toda a informacao operacional de base deve entrar por importacao de relatorios padrao do Rentway ou de fontes equivalentes. A atualizacao nao deve ser manual viatura a viatura.

Cada fluxo de importacao deve definir:

- relatorio de origem
- frequencia de atualizacao
- responsavel pela atualizacao
- mapeamento de colunas
- regras de validacao
- regras de historico e auditoria
- impacto nos indicadores e alertas

## Papel Da Aplicacao

A aplicacao deve permitir perceber em poucos minutos:

- o que esta a acontecer na empresa
- quais sao os problemas operacionais
- quais sao as prioridades
- quais processos estao atrasados
- quais viaturas sao criticas
- quais tarefas ficaram esquecidas
- quais custos sao anormais
- quais padroes de erro se repetem
- quais riscos operacionais existem
- quais desvios de execucao estao a surgir

## Estrutura Ja Identificada

Segundo o briefing, a aplicacao ja inclui ou deve preservar:

- gestao de processos de oficina
- diagnosticos
- rececao tecnica
- folhas de obra
- tarefas de folha de obra
- validacoes
- historico de diagnosticos
- comparacao de diagnosticos
- anexos
- ficha tecnica de viaturas
- workflow de estados
- Flask e SQLite
- upload de documentos
- importacao inicial da frota
- separacao entre gestao de stock e gestao de manutencao
- menu principal, menu manutencao e menu stock
- filtros de frota
- lifecycle da viatura

## Entidade Viatura

A viatura deve ser uma entidade permanente.

Uma viatura nunca deve ser apagada quando e vendida, abatida ou deixa de estar operacional. Deve manter:

- historico
- diagnosticos
- folhas de obra
- custos
- auditoria
- contratos
- impros
- incidentes
- anexos
- eventos de lifecycle

## Estados Da Frota

Devem existir dois conceitos separados.

### Estado Lifecycle

Representa a existencia da viatura na empresa.

Exemplos:

- Ativa
- Em venda
- Vendida
- Baixada
- Abatida
- Imobilizada

### Estado Operacional Atual

Representa a situacao operacional no momento.

Exemplos:

- Em contrato
- Livre
- Em impro
- Em preparacao
- Bloqueada
- Em manutencao
- Reservada
- Em transferencia

## Filtros De Frota

A listagem de frota deve suportar:

- lifecycle: ativas, vendidas, todas
- estado operacional
- marca
- modelo
- grupo
- categoria
- estacao
- km
- data de compra
- data de venda
- risco tecnico
- campanhas pendentes

## Importacao De Frota

O ficheiro de frota do Rentway deve ser importado integralmente, sem manipulacao previa.

Fluxo esperado:

1. Extrair relatorio do Rentway.
2. Importar diretamente na aplicacao.
3. Listar todas as colunas encontradas.
4. Permitir escolher quais entram no modelo normalizado nesta fase.
5. Guardar o mapeamento usado.
6. Guardar tambem dados brutos para auditoria e expansao futura.
7. Permitir adicionar novas colunas e novos mapeamentos no futuro.

Campos prioritarios:

- ID unico da viatura
- matricula
- VIN
- marca
- modelo
- versao
- ano
- km
- estado atual
- estado lifecycle
- estacao
- grupo
- categoria
- datas relevantes
- dados de venda
- dados de compra

## Importacoes Prioritarias

1. Frota total
2. Historico de folhas de obra
3. Historico de impros
4. Historico de contratos
5. Historico de utilizacao
6. Historico de faturacao
7. Faturas de fornecedores

## Modelo De Dados Recomendado

### Tabelas Nucleares

- vehicles
- vehicle_lifecycle_events
- vehicle_operational_status_events
- imports
- import_files
- import_mappings
- import_rows_raw
- audit_events
- attachments

### Manutencao E Oficina

- workshop_processes
- diagnostics
- diagnostic_comparisons
- work_orders
- work_order_tasks
- technical_receptions
- validations
- maintenance_costs
- supplier_invoices

### Operacao

- rental_contracts
- utilization_events
- impro_events
- damage_events
- transfer_events
- reservations_snapshot

### Gestao E Controlo

- tasks
- task_followups
- process_checklists
- process_rules
- alerts
- risk_scores
- dashboard_metrics

### Venda

- sale_candidates
- sale_preparation_steps
- sale_documents
- sale_audit_checks
- sale_status_events

## Auditorias Pretendidas

O sistema deve produzir auditorias como:

- viaturas com custos anormais
- reincidencia de avarias
- padroes por motorizacao
- padroes por versao
- diagnosticos criticos
- manutencoes atrasadas
- oficinas com problemas
- diferencas entre diagnostico e reparacao
- custos excessivos
- excesso de impros
- excesso de danos
- clientes com sinistralidade elevada

## Modulo De Viaturas Para Venda

Deve existir um modulo proprio para:

- selecao de viaturas para venda
- preparacao para venda
- acompanhamento do processo
- controlo documental
- auditoria pre-venda
- historico de decisoes e estados

A estrutura atual usada no Microsoft Lists deve ser usada como referencia quando for fornecida.

## Proxima Implementacao Recomendada

Como primeiro incremento tecnico, implementar uma fundacao robusta de importacao e frota:

1. Criar ou rever o modelo persistente de viatura permanente.
2. Separar estado lifecycle de estado operacional.
3. Criar importador de frota integral com armazenamento bruto.
4. Criar ecra de mapeamento de colunas.
5. Guardar mapeamentos por tipo de relatorio.
6. Atualizar apenas campos normalizados escolhidos.
7. Preservar historico de alteracoes de estados, km, estacao e dados criticos.
8. Melhorar filtros de frota com lifecycle e estado operacional separados.

## Regra De Produto

Sempre que surgir uma nova funcionalidade, validar primeiro:

- isto pertence ao Rentway ou ao hub CarFast?
- evita trabalho manual ou cria duplicacao?
- melhora auditoria, controlo, execucao ou decisao?
- fica rastreavel?
- preserva historico?
- pode ser alimentado por importacao?

