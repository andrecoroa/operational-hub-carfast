# Operational Hub Carfast - Arquitetura Base

## Objetivo

A CarFast v2 deve ser a plataforma operacional central da CarFast para controlo,
auditoria, follow-up, decisao e historico.

Nao deve substituir o Rentway. O Rentway continua a ser o sistema operacional
principal para contratos, movimentos operacionais base e informacao financeira de
origem. A CarFast v2 deve organizar, cruzar, auditar e acompanhar essa
informacao.

## Principio De Construcao

A v2 deve nascer pequena, modular e preparada para evoluir.

Isto significa:

- criar primeiro o nucleo permanente;
- deixar configuravel tudo o que pode mudar;
- separar dados importados de dados internos;
- separar processos temporarios de entidades permanentes;
- garantir auditoria desde o inicio;
- evitar criar modulos so porque existiam na v1;
- reaproveitar a v1 como aprendizagem funcional, nao como arquitetura.

## Decisao Tecnica Inicial

Stack recomendada:

- Backend: Python
- Framework: FastAPI
- Base de dados: PostgreSQL
- ORM/migracoes: SQLAlchemy + Alembic
- Frontend inicial: templates server-side ou frontend leve sobre API
- Documentos: metadados na base de dados, ficheiros fora da base de dados
- Storage futuro: OneDrive, SharePoint, S3 ou equivalente
- Deploy: Render ou alternativa equivalente

Motivo:

FastAPI favorece contratos de dados claros, validacao, modularidade e APIs
preparadas para integracoes futuras. PostgreSQL permite robustez, historico,
constraints, indices e crescimento sem as limitacoes praticas do SQLite.

## Conceitos Estruturais

### Entidades permanentes

Sao entidades que continuam a existir mesmo quando mudam de estado.

Exemplos:

- viatura;
- utilizador;
- fornecedor;
- cliente;
- documento;
- artigo de stock, se o modulo de stock for mantido.

Uma entidade permanente nao deve ser apagada por importacoes.

### Dados importados

Sao dados vindos de sistemas externos, especialmente Rentway.

Devem ser guardados com:

- origem;
- ficheiro;
- data de importacao;
- utilizador responsavel;
- linha original;
- dados brutos;
- dados normalizados;
- erros e avisos.

Dados importados podem atualizar campos derivados ou snapshots, mas nao devem
apagar dados internos.

### Dados internos

Sao decisoes, comentarios, tarefas, estados, anexos, observacoes, auditoria e
classificacoes criadas dentro da CarFast v2.

Dados internos devem prevalecer sobre importacoes quando representam decisao ou
follow-up humano.

### Processos temporarios

Sao campanhas, analises, projetos operacionais, selecoes ou processos com inicio
e fim.

Nao devem contaminar o nucleo permanente da viatura. Devem ligar-se a viaturas,
documentos e tarefas por relacao.

## Parametrizacao Desde O Inicio

Tudo o que pode mudar na empresa deve ser parametrizado e nao codificado fixo.

Exemplos:

- areas de trabalho autorizadas;
- localizacoes / estacoes / lojas;
- equipas de tarefa;
- funcoes;
- categorias de tarefas;
- estados de tarefas;
- estados de lifecycle;
- estados operacionais;
- tipos de documentos;
- tipos de importacao;
- fornecedores;
- categorias de incidentes;
- regras de permissao;
- tipos de processo.

Isto evita ter de alterar codigo sempre que a organizacao muda.

## Modelo Base De Parametrizacao

### organizational_units

Representa a arvore organizacional da CarFast.

Na v2, o conceito principal para acesso nao deve ser "departamento" fixo, mas
sim "area de trabalho autorizada". Isto permite que um utilizador tenha acesso a
uma ou mais areas da aplicacao sem ficar preso a uma estrutura departamental
rigida.

As equipas devem existir sobretudo para atribuicao e acompanhamento de tarefas.

Campos iniciais:

- id
- name
- code
- unit_type
- parent_id
- active
- sort_order
- created_at
- updated_at

Tipos possiveis:

- workspace_area
- team
- location
- station
- business_area

Exemplos:

- Manutencao
- Frota
- Stock
- Administracao
- Gestao
- Lisboa
- Porto
- Aeroporto

### settings_catalogs

Agrupa listas configuraveis.

Exemplos:

- task_status
- task_category
- vehicle_lifecycle_status
- vehicle_operational_status
- document_type
- import_type
- incident_category

### settings_values

Valores de cada lista configuravel.

Campos iniciais:

- id
- catalog_id
- code
- label
- description
- active
- sort_order
- color
- is_system
- metadata_json
- created_at
- updated_at

### teams

Representa equipas operacionais usadas em tarefas, follow-ups e workflows.

Campos iniciais:

- id
- name
- code
- organizational_unit_id
- active
- created_at
- updated_at

Uma equipa pode pertencer a uma area de trabalho ou localizacao, mas nao deve
ser usada como substituto direto de permissoes.

### permissions

Permissoes granulares.

Exemplos:

- vehicles.read
- vehicles.write
- imports.run
- imports.approve
- tasks.read
- tasks.write
- admin.manage_users

### roles

Perfis funcionais.

Exemplos iniciais:

- Admin
- Gestor
- Operador
- Consulta

Os nomes podem ser ajustados, mas a permissao real deve viver em `permissions`,
nao no nome do role.

## Nucleo Da Fase 1

A primeira fase deve criar apenas a fundacao.

Inclui:

- utilizadores;
- roles e permissoes;
- unidades organizacionais;
- catalogos configuraveis;
- viaturas permanentes;
- importacoes auditaveis;
- documentos por metadados;
- audit log;
- tarefas simples.

Nao inclui ainda:

- oficina completa;
- stock completo;
- relatorios avancados;
- dashboards complexos;
- workflows sofisticados;
- motor documental SharePoint completo.

Esses modulos devem encaixar depois sobre a fundacao.

## Modelo Inicial De Dados

### Administracao e acesso

- users
- roles
- permissions
- role_permissions
- user_roles
- organizational_units
- user_organizational_units
- teams
- team_members

### Parametrizacao

- settings_catalogs
- settings_values

### Auditoria

- audit_log

### Documentos

- documents
- document_links

### Importacoes

- import_batches
- import_files
- import_raw_rows
- import_errors
- import_mappings

### Frota

- vehicles
- vehicle_identifiers
- vehicle_lifecycle_events
- vehicle_operational_status_events
- vehicle_manual_fields
- vehicle_external_snapshots

### Tarefas e follow-up

- tasks
- task_comments
- task_documents
- task_history

## Regra Para Importacoes Rentway

Uma importacao pode:

- criar registos importados;
- atualizar snapshots externos;
- sugerir alteracoes;
- atualizar campos derivados marcados como sincronizaveis;
- gerar alertas;
- gerar tarefas.

Uma importacao nao pode:

- apagar comentarios internos;
- apagar tarefas;
- apagar anexos;
- apagar historico;
- apagar decisoes humanas;
- substituir estados internos sem regra explicita;
- eliminar uma viatura permanente.

## Perguntas De Decisao

Estas perguntas devem ser fechadas antes de programar a fase 1.

1. A estrutura da empresa deve comecar por departamentos simples ou por uma
   arvore unica de unidades organizacionais?
   Decisao: arvore unica de unidades organizacionais.
2. As estacoes/localizacoes devem ser tratadas como unidades organizacionais ou
   como entidade propria?
   Decisao inicial: unidades organizacionais, com possibilidade de tabela
   complementar se um dia precisarem de campos proprios.
3. Um utilizador pode pertencer a mais do que uma area de trabalho/local?
   Decisao: sim.
4. As permissoes devem ser apenas por role ou tambem por area/local?
   Decisao: role + areas de trabalho autorizadas.
5. A viatura deve ser identificada principalmente por matricula, VIN, Rentway
   UnitNr ou uma combinacao?
   Decisao: qualquer um dos tres identificadores deve poder localizar a viatura.
   Internamente, a viatura tera sempre um ID proprio.
6. Que dados da viatura sao internos e editaveis manualmente?
7. Que dados da viatura sao apenas importados/sincronizados?
8. As importacoes devem precisar de aprovacao antes de afetar dados
   normalizados?
9. Os documentos devem comecar em storage local e migrar depois para
   SharePoint/OneDrive, ou integrar externo desde o inicio?
10. O modulo de stock deve entrar na primeira fase ou ficar preparado mas
    inativo?
    Decisao: fica preparado para entrar depois.

## Decisao Para Areas De Trabalho E Locais

Usar uma tabela generica `organizational_units`.

Motivo:

areas de trabalho, lojas e estacoes podem mudar com o tempo. Criar uma
tabela demasiado especifica para cada conceito aumenta rigidez. Uma estrutura
hierarquica permite evoluir sem alterar a base.

Exemplo:

- CarFast
  - Operacoes
    - Frota
    - Oficina
    - Stock
  - Administracao
  - Localizacoes
    - Lisboa
    - Porto
    - Faro

Se no futuro for necessario, uma localizacao pode ganhar campos proprios numa
tabela complementar, sem quebrar o modelo principal.

As tarefas usam equipas operacionais. As permissoes usam roles e areas de
trabalho autorizadas.
