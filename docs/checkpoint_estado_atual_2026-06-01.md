# Checkpoint CarFast v2 - 2026-06-01

Este documento regista o ponto de situação atual para reduzir o risco de alterações erradas ou regressões em funcionalidades já discutidas.

## Referência técnica

- Repositório local: `C:\carfast_v2`
- Branch de trabalho: `codex/operational-hub-carfast-foundation`
- Último commit funcional antes deste checkpoint: `0a414b2 Rebuild workshop detail column layout`
- Deploy: Render a partir da branch indicada.
- Estado Git observado: existem ficheiros não versionados antigos em `.github/`, `docs/`, `exports/` e `tests/`. Não devem ser incluídos automaticamente sem validação.

## Estado geral da aplicação

### Módulos existentes

- Dashboard operacional.
- Centro de Tarefas.
- Oficina.
- Frota.
- Documentos.
- Importações.
- Administração.
- Manual / apoio à utilização da app.

### Integrações / entradas externas

- Entrada de e-mails via Microsoft Lists / Power Automate para criação de registos na app.
- Os anexos ficam referenciados por links SharePoint/Lists.
- A app deve guardar metadados e links, não ficheiros binários.
- Integração Microsoft Graph, OCR e automações de arquivo ficam para fase futura.

## Oficina

### Implementado / em curso

- Processo de oficina com fluxo guiado.
- Resumo da viatura no topo do processo.
- Estrutura de página reorganizada:
  - resumo no topo;
  - coluna principal com receção, linha do processo, BSI e histórico completo;
  - coluna lateral com ações complementares, alertas, zona documental e histórico técnico.
- Menus principais em `details`, por defeito fechados.
- Fases atuais do fluxo:
  - Receção administrativa;
  - Verificar histórico;
  - Revisão Stellantis / Service Box;
  - Registo de leitura técnica / BSI inicial;
  - Registo de informação técnica;
  - Verificações sistemáticas;
  - Serviços a executar / orçamento;
  - Registar decisão;
  - Registo de leitura técnica / BSI final;
  - Fecho técnico;
  - Fecho administrativo;
  - Fecho sem intervenção.
- Consulta por fase: cada fase pode mostrar registos associados.
- Histórico completo permanece como consulta geral.
- Alertas automáticos iniciais para etapas em falta.
- BSI tem leitura inicial e final, com tipos de relatório diferenciados.
- Histórico técnico importado por viatura existe e pode ser consultado em matriz por relatório.

### Pontos sensíveis na Oficina

- Evitar voltar ao layout com blocos alinhados lado a lado por linhas, porque cria espaços vazios e confusão.
- A coluna esquerda e direita devem ser independentes.
- Ações complementares não devem substituir os passos do fluxo.
- BSI deve fazer parte do fluxo, mas a área de preenchimento pode estar recolhida.
- Documentos e incidentes ainda podem precisar de associação explícita à fase para aparecerem sempre no local correto.
- Antes de mexer em `workshop_detail.html`, validar sempre:
  - resumo fora das colunas;
  - `workshop-columns` com duas colunas;
  - esquerda = fluxo;
  - direita = ações / apoio.

## Tarefas

### Implementado / em curso

- Centro de tarefas por espaços:
  - Operacional;
  - Oficina;
  - Gestão;
  - Administração.
- Estrutura com tarefas e registos rápidos.
- Tarefas mãe e subtarefas previstas/implementadas em base funcional.
- Tarefas periódicas previstas/implementadas em base funcional.
- Permissões por centro de tarefas começaram a ser preparadas.
- Tarefas da oficina devem poder existir como módulo próprio e, quando necessário, aparecer no centro global.

### Regras acordadas

- Tarefa mãe deve ser a única a aparecer no backlog principal.
- Subtarefas aparecem dentro da tarefa mãe.
- Responsabilidade de execução pode ser pessoa ou equipa.
- Utilizadores não devem conseguir atribuir tarefas a perfis superiores; devem poder pedir decisão/ajuda com contexto.
- Pedido de decisão deve obrigar:
  - contextualização;
  - sugestão de resolução.

## Documentos

### Implementado / em curso

- Gestão documental inicial focada em Oficina e Financeiro.
- A app guarda:
  - metadados;
  - classificação;
  - estado;
  - link original;
  - link arquivado;
  - caminho sugerido.
- Não guarda ficheiros binários.
- Entrada por e-mail passa por Microsoft Lists / Power Automate.

### Regras acordadas

- Nesta fase, usar links OneDrive/SharePoint manuais.
- Arquivo real/mover ficheiros no 365 fica para fase futura.
- Oficina deve arquivar preferencialmente por matrícula/processo, evitando estrutura excessiva.
- Financeiro fica mais simples por ano/mês e entidade quando aplicável.

## Frota

### Implementado / em curso

- Importação de frota Rentway.
- Ficha da viatura com dados principais.
- Filtro por ativos/vendidos/todos foi identificado como necessário.
- Ficha da viatura deve mostrar dados de manutenção relevantes quando existirem:
  - marca;
  - modelo;
  - versão;
  - chassi;
  - data matrícula;
  - data compra;
  - último serviço;
  - próximo serviço.

## Administração e permissões

### Implementado / em curso

- Base de roles/permissões existe.
- Permissões por centro de tarefas começaram a ser preparadas.
- Página de administração tem quadro de implementações previstas.

### Ainda a consolidar

- Limitação efetiva de acessos por centro.
- Perfis hierárquicos para criação/atribuição de tarefas.
- Permissões específicas para:
  - tarefas recorrentes;
  - tarefas de gestão;
  - tarefas de administração;
  - centros de tarefas isolados.

## Riscos de regressão

1. Alterações grandes em templates podem desfazer layouts aprovados.
2. CSS em cache no Render/browser pode mostrar versão antiga; atualizar sempre query string de `app.css`.
3. `workshop_detail.html` está grande; alterações devem ser pequenas e validadas por blocos.
4. Não incluir ficheiros não versionados antigos sem confirmação.
5. Antes de cada deploy, validar:
   - import da app;
   - compilação de templates principais;
   - `git diff --check`;
   - estado Git limpo ou com alterações conhecidas.

## Próximo passo recomendado

Antes de novas funcionalidades, validar em produção a página de processo de oficina após o commit `0a414b2` e este checkpoint:

1. Abrir um processo real.
2. Confirmar que o resumo está no topo.
3. Confirmar que esquerda e direita são colunas independentes.
4. Confirmar que os menus aparecem fechados por defeito.
5. Confirmar que não há duplicação visual de menus.
6. Só depois avançar para associação de documentos/incidentes por fase e refinamento BSI.
