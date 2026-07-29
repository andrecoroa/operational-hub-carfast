# Auditoria e transicao para a experiencia Clean

Data da auditoria: 2026-07-29

## Objetivo

Transformar a experiencia `v2-clean` na unica interface utilizada pelos
utilizadores, sem duplicar os dados operacionais e sem interromper os fluxos
existentes.

Este documento e o ponto de controlo para:

- identificar dependencias entre a experiencia atual e a Clean;
- avaliar novas alteracoes antes da implementacao;
- planear a substituicao das funcionalidades que ainda so existem na atual;
- retirar progressivamente a interface atual com risco controlado.

## Conclusao executiva

A experiencia atual e a Clean nao sao duas aplicacoes independentes. Existe:

- uma aplicacao FastAPI;
- uma base de dados;
- uma autenticacao e um conjunto de permissoes;
- um arquivo fisico de documentos;
- duas familias de rotas, templates e fluxos de navegacao.

A separacao e principalmente visual. Frota, tarefas, documentos, importacoes e
parte da Oficina usam dados comuns. Alguns filtros por `source` ou `origin`
separam filas na Clean, mas essa separacao nem sempre existe nas rotas atuais.

Eliminar apenas templates antigos nao resolveria os principais problemas. A
transicao deve primeiro substituir as funcionalidades e ligacoes antigas,
definir a propriedade de cada fluxo e tornar os filtros simetricos.

## Mapa atual

| Area | Persistencia | Interface | Estado |
| --- | --- | --- | --- |
| Autenticacao e permissoes | Partilhada | Atual e Clean | Nucleo comum |
| Frota | Tabelas comuns | Duas fichas | Dados totalmente partilhados |
| Tarefas | Tabela `tasks` | Dois centros | Separacao assimetrica |
| Oficina antiga | `workshop_processes` | Atual | Motor legado |
| Oficina faseada | `workshop_phased_processes` | Atual e Clean | Motor comum com fluxos diferentes |
| Documentos | `documents` e arquivo comum | Atual e Clean | Totalmente partilhado |
| Registos estruturados | `vehicle_document_records` | Sobretudo Clean | Partilhados com historico/importacoes |
| Diagnosticos | Tabelas proprias ligadas a `documents` | Clean e ligacoes antigas | Parcialmente cruzado |
| Importacoes | Tabelas de lotes comuns | Formularios distribuidos | Parte ainda so existe na atual |
| Administracao | Utilizadores e regras comuns | Gestao real na atual | Clean ainda e placeholder |

## Navegacao e experiencia

A experiencia e escolhida na sessao, mas o menu tambem infere a experiencia
atraves do prefixo da rota.

Rotas Clean principais:

- `/v2-clean`
- `/v2-clean/tasks`
- `/v2-clean/processes`
- `/v2-clean/workshop`
- `/v2-clean/workshop-entry`
- `/v2-clean/fleet`
- `/v2-clean/documents`
- `/v2-clean/admin`

Rotas atuais principais:

- `/`
- `/task-board`
- `/workshop`
- `/workshop/processes-ui`
- `/workshop/new-process`
- `/fleet`
- `/management-center`
- `/imports`
- `/documents`
- `/admin`

### Ligacoes Clean que ainda abrem a interface atual

Foram encontradas tres dependencias diretas:

1. Validacao de diagnosticos abre `/documents/{id}`.
2. Dados e validacao de diagnostico na ficha da viatura abrem
   `/documents/{id}`.
3. O formulario de novo documento ainda apresenta acesso a
   `/documents/manage`.

Estas ligacoes devem ser substituidas antes de tornar a Clean obrigatoria.

## Oficina

Existem dois motores distintos.

### Motor antigo

- tabela `workshop_processes`;
- notas, evidencias, servicos e leituras proprias;
- paginas atuais `/workshop/{id}`.

### Motor faseado

- tabela `workshop_phased_processes`;
- fases, alertas, servicos, relatorios tecnicos, verificacoes e incidentes;
- utilizado tanto pela interface faseada atual como pela Clean.

A Clean cria processos com `origin="v2_clean"` e filtra o seu dashboard por
essa origem. A API faseada atual lista os processos sem excluir essa origem.
Assim, a interface atual pode encontrar processos criados na Clean.

Um processo pode abrir em tres familias de pagina:

- processo Clean: `/v2-clean/workshop-entry` ou fase Clean;
- processo antigo: `/workshop/{id}`;
- processo faseado atual: `/workshop/processes-ui/{id}/manage`.

Os IDs podem coincidir entre as tabelas antiga e faseada. A familia da rota e
necessaria para identificar corretamente o processo.

### Decisao estrutural recomendada

Adotar o motor faseado como motor definitivo, impedir novas criacoes no motor
antigo e consolidar fases, estados e regras numa unica camada de servico.

## Tarefas e problemas

As duas experiencias usam a tabela `tasks` e as mesmas tabelas de comentarios,
documentos, historico, subtarefas e fluxos guiados.

A Clean:

- cria tarefas com `source="v2_clean"`;
- lista apenas essa origem;
- recusa alterar tarefas com outra origem.

O centro atual nao exclui `v2_clean` nas consultas principais. Logo, a
visibilidade e assimetrica: a Clean nao edita tarefas antigas, mas a atual pode
mostrar e alterar tarefas Clean.

Os documentos anexos a tarefas usam a tabela geral `documents`; nao existe um
arquivo de anexos separado.

### Decisao estrutural recomendada

Usar uma fila unica. `source` deve ser metadado de origem, nao uma fronteira de
visibilidade. O acesso deve depender da area, equipa e permissoes. A criacao de
problemas permanece exclusiva da Oficina.

## Documentos

Os documentos nao estao duplicados por experiencia.

- `documents`: ficheiros reais e metadados;
- `document_links`: associacoes;
- `document_events`: eventos;
- `vehicle_document_records`: folhas de obra, contratos, impros e outros
  registos estruturados;
- um unico `DOCUMENT_ARCHIVE_ROOT`.

O mesmo PDF pode ser consultado e alterado pelas duas interfaces. Relatorios
tecnicos da Oficina, diagnosticos e anexos de tarefas referenciam o mesmo
arquivo documental.

### Decisao estrutural recomendada

Manter um unico nucleo documental e completar na Clean todas as operacoes:
importar, associar, extrair, reprocessar, validar, pre-visualizar, remover
duplicados e consultar auditoria.

## Diagnosticos

Os diagnosticos possuem estrutura propria:

- `diagnostic_documents`;
- `diagnostic_extractions`;
- ligacao ao `Document` original.

Podem ter origem no arquivo documental, num processo de Oficina ou numa
importacao historica. Todas as origens devem alimentar o mesmo historico por
viatura, ordenado pela data e hora reais de recolha.

Ainda existem ligacoes para a validacao documental atual. A pagina Clean de
diagnosticos deve tornar-se a pagina canonica de consulta, extracao,
reprocessamento e validacao.

## Importadores

### Disponiveis na Clean

- folhas de obra;
- detalhes das folhas de obra;
- contratos;
- impros;
- arquivo ZIP;
- pastas e lotes de faturas;
- listas de faturas pendentes;
- manifestos de OCR;
- relatorios historicos e diagnosticos;
- caixa de entrada documental e triagem.

### Ainda dependentes da experiencia atual

- atualizacao da frota Rentway;
- importacao tecnica antiga;
- tarefas em massa;
- divida para comercio;
- partes do Centro de Gestao, AR e sinistros.

As duas experiencias reutilizam `ImportBatch`, `ImportFile`, `ImportRawRow` e
`ImportError`. Os dados e historicos dos lotes sao comuns, apesar de os
formularios estarem em menus diferentes.

## Administracao

`/v2-clean/admin` e atualmente uma pagina de preparacao sem gestao funcional.
A gestao efetiva de utilizadores, perfis, permissoes, configuracoes e alguns
fluxos administrativos continua na experiencia atual.

Antes de retirar a interface atual, a Clean precisa de:

- utilizadores e perfis;
- permissoes por modulo e acao;
- configuracoes operacionais;
- auditoria de acoes sensiveis;
- gestao dos importadores que permanecem na atual.

## Impacto no desempenho

A existencia de templates e rotas antigas, por si so, tem impacto reduzido. Os
custos principais resultam de:

- consultas antigas que tambem carregam registos Clean;
- contadores globais repetidos;
- tabelas documentais com grande volume;
- falta de paginacao ou indices adequados;
- OCR e importacoes executados no pedido web;
- preparacao duplicada dos mesmos dados para interfaces diferentes;
- um unico worker ocupado por tarefas pesadas.

A consolidacao ajuda o desempenho, mas deve ser acompanhada por paginacao no
servidor, indices, carregamento sob pedido e processamento assincrono.

## Estrategia de transicao

### Fase 1 - Fronteiras e inventario

- manter este inventario atualizado;
- identificar todas as ligacoes para rotas atuais;
- definir uma pagina canonica Clean por entidade;
- adicionar testes de fronteira entre origens;
- medir rotas e consultas lentas.

### Fase 2 - Cobertura funcional

- completar a Administracao Clean;
- migrar importadores ainda necessarios;
- completar tarefas, anexos e historico;
- concluir validacao documental e diagnosticos;
- garantir consulta e gestao integral da Oficina.

### Fase 3 - Unificacao

- tornar o motor faseado a unica Oficina;
- unificar a fila de tarefas;
- concentrar regras de dominio em servicos comuns;
- deixar `source` e `origin` apenas como metadados auditaveis;
- impedir criacoes nos motores antigos.

### Fase 4 - Entrada exclusivamente Clean

- redirecionar `/` e o login para `/v2-clean`;
- retirar o seletor da experiencia atual;
- remover links antigos dos menus;
- manter acesso atual apenas para administradores durante a transicao;
- registar acessos a rotas antigas.

### Fase 5 - Desativacao

- colocar paginas antigas em modo de consulta;
- redirecionar rotas com equivalente Clean;
- confirmar que o registo de acessos antigos permanece a zero;
- arquivar templates e rotas;
- remover codigo apenas depois de um ciclo estavel em producao.

## Criterios para tornar a Clean obrigatoria

- o utilizador comum nao encontra rotas atuais;
- todos os fluxos diarios funcionam sem trocar de experiencia;
- nenhum botao Clean abre uma pagina atual;
- todos os importadores necessarios estao acessiveis;
- processos, tarefas e documentos abrem na pagina canonica;
- a mesma acao nao cria dados duplicados;
- permissoes e auditoria estao completas;
- testes cobrem as fronteiras entre modulos.

## Registo de novas propostas

Antes de implementar uma nova alteracao, registar:

| Campo | Conteudo |
| --- | --- |
| Proposta | O que se pretende alterar |
| Objetivo operacional | Problema que resolve |
| Modulos afetados | Frota, Oficina, Tarefas, Documentos, etc. |
| Dados afetados | Tabelas, ficheiros ou integracoes |
| Dependencia atual | Funcao ou pagina que ainda so existe na atual |
| Destino canonico | Pagina/servico Clean responsavel |
| Impacto na transicao | Ajuda, neutro ou cria nova dependencia |
| Risco | Baixo, medio ou alto |
| Compatibilidade | Migracao, adaptador temporario ou substituicao direta |
| Testes necessarios | Casos funcionais, dados e permissoes |
| Decisao | Aprovada, adiada, rejeitada ou em analise |

## Regra de trabalho

Novas melhorias visuais ou funcionais devem ser avaliadas em conjunto com esta
transicao. Uma alteracao nao deve:

- criar uma nova dependencia da interface atual;
- duplicar dados para separar artificialmente as experiencias;
- introduzir um terceiro fluxo para a mesma entidade;
- alterar silenciosamente dados partilhados;
- impedir a futura pagina canonica Clean.

Quando uma proposta depender de funcionalidade atual, deve ser implementada
primeiro numa camada comum ou diretamente na pagina Clean definitiva.
