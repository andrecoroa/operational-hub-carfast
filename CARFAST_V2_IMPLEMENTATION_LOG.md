# Operational Hub Carfast - Implementation Log

## Estado Atual

Projeto oficial:

```text
C:\carfast_v2
```

A v1 permanece intacta em:

```text
C:\carfast_stock_mvp
```

## Fundacao Criada

- FastAPI
- SQLAlchemy
- Alembic
- PostgreSQL por `DATABASE_URL`
- SQLite em memoria apenas para validacao tecnica
- Health endpoint
- Modelos base
- Schemas Pydantic
- Seed inicial
- Script de validacao da fundacao
- Hashing de passwords
- Script de criacao de admin inicial
- Servico interno de autorizacao por permissoes e areas
- Autenticacao API por bearer token assinado

## Dominios Ja Modelados

- users
- roles
- permissions
- organizational_units
- teams
- settings_catalogs
- settings_values
- audit_log
- documents
- imports
- vehicles
- tasks

## APIs Iniciais

### Health

- `GET /health`

### Auth

- `POST /auth/login`
- `GET /auth/me`

### Admin

- `GET /admin/roles`
- `GET /admin/permissions`

### Organizacao

- `GET /organization/units`
- `POST /organization/units`
- `PATCH /organization/units/{unit_id}`
- `GET /organization/teams`
- `POST /organization/teams`
- `PATCH /organization/teams/{team_id}`

### Parametrizacao

- `GET /settings/catalogs`
- `POST /settings/catalogs`
- `PATCH /settings/catalogs/{catalog_id}`
- `GET /settings/catalogs/{catalog_code}/values`
- `POST /settings/catalogs/{catalog_code}/values`
- `PATCH /settings/values/{value_id}`

### Viaturas

- `GET /vehicles`
- `POST /vehicles`
- `GET /vehicles/lookup`
- `GET /vehicles/{vehicle_id}`
- `PATCH /vehicles/{vehicle_id}`

### Importacoes

- `GET /imports/batches`
- `POST /imports/batches`
- `GET /imports/batches/{batch_id}`
- `PATCH /imports/batches/{batch_id}`
- `GET /imports/batches/{batch_id}/raw-rows`
- `POST /imports/batches/{batch_id}/raw-rows`
- `GET /imports/batches/{batch_id}/errors`
- `POST /imports/batches/{batch_id}/errors`

### Tarefas

- `GET /tasks`
- `POST /tasks`
- `GET /tasks/{task_id}`
- `PATCH /tasks/{task_id}`
- `GET /tasks/{task_id}/comments`
- `POST /tasks/{task_id}/comments`

## Validacao

Executar:

```powershell
python scripts/check_foundation.py
```

Resultado atual:

```text
Foundation check passed.
```

O check valida:

- seed inicial;
- login e perfil de utilizador atual;
- roles e permissoes;
- areas de trabalho autorizadas;
- equipas;
- criacao de admin;
- hashing/verificacao de password;
- calculo de permissoes por role;
- calculo de areas autorizadas;
- criacao, lookup e update de viatura;
- criacao e fecho de batch de importacao;
- raw rows e erros de importacao.
- criacao, fecho e comentarios de tarefas.

## Decisoes Aplicadas

- Areas de trabalho autorizadas substituem departamentos rigidos.
- Equipas sao usadas para atribuicao e acompanhamento de tarefas.
- Permissoes devem combinar role + areas autorizadas.
- Viatura tem ID interno permanente.
- Matricula, VIN ou Rentway UnitNr podem localizar uma viatura.
- Stock fica preparado, mas nao entra na fase 1.
- Importacoes guardam raw rows e erros sem apagar dados internos.
- Passwords usam PBKDF2-SHA256 com salt.
- Tarefas podem ligar-se genericamente a entidades por `entity_type` e `entity_id`.

## Proximos Passos Recomendados

1. Criar repo GitHub `operational-hub-carfast`.
2. Enviar commit inicial.
3. Criar Blueprint no Render a partir de `render.yaml`.
4. Criar admin inicial no Render.
5. Criar importador inicial de frota Rentway usando a estrutura v1 como referencia.

## Bloqueios Atuais

- `pytest` e `httpx` ainda nao foram instalados no ambiente global.
- PostgreSQL ainda nao esta configurado.
- Autenticacao atual usa token assinado simples, suficiente para fundacao mas a rever antes de producao.

## Render Preparado

Foram adicionados:

- `render.yaml`
- `Procfile`
- `scripts/render_start.py`
- `docs/DEPLOY_RENDER.md`

O `render.yaml` cria:

- Web Service `operational-hub-carfast`
- PostgreSQL `operational-hub-carfast-db`
- `DATABASE_URL` a partir do Postgres interno do Render
- `APP_SECRET_KEY` gerado automaticamente
- migracoes Alembic antes do deploy

Nota: Render Postgres free expira apos 30 dias segundo a documentacao atual.
Para dados reais da empresa, trocar para plano pago antes de importar dados
importantes.
