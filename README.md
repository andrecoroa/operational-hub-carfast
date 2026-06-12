# Operational Hub Carfast

Nova base da plataforma operacional CarFast, tambem referida tecnicamente como
CarFast v2.

## Objetivo

A v2 nasce como hub operacional, auditoria, follow-up e decisao. Nao substitui o
Rentway e nao continua diretamente a estrutura tecnica da v1.

## Stack

- Python
- FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic

## Arranque local

```powershell
python -m pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

Antes de usar em ambiente real, configurar `DATABASE_URL` para PostgreSQL.

## Deploy Render

O projeto inclui `render.yaml` para criar:

- Web Service `operational-hub-carfast`
- PostgreSQL `operational-hub-carfast-db`
- migracoes Alembic antes do deploy

Instrucoes:

```text
docs/DEPLOY_RENDER.md
```

## Criar Admin Inicial

Depois de configurar a base de dados:

```powershell
$env:CARFAST_ADMIN_EMAIL="admin@carfast.local"
$env:CARFAST_ADMIN_PASSWORD="alterar-esta-password"
python scripts/create_admin.py
```

No Render free, como nao ha shell/one-off jobs, configurar temporariamente:

```text
CARFAST_ADMIN_EMAIL=andrecoroa@daccordinvest.pt
CARFAST_ADMIN_PASSWORD=uma-password-forte
```

Depois fazer redeploy. O admin e criado automaticamente no arranque.

## Autenticacao API

Login:

```text
POST /auth/login
```

Body:

```json
{
  "email": "admin@carfast.local",
  "password": "alterar-esta-password"
}
```

Usar o `access_token` devolvido como bearer token nas rotas protegidas.

## Validacao Rapida

Enquanto a base PostgreSQL nao estiver configurada, a fundacao pode ser validada
numa SQLite temporaria em memoria:

```powershell
python scripts/check_foundation.py
```

Este check valida seed inicial, areas de trabalho, equipas, viaturas e
importacoes auditaveis sem gravar ficheiros locais.

## Importar Frota Rentway

Importador inicial por script:

```powershell
python scripts/import_rentway_fleet.py C:\caminho\para\FROTA_TOTAL.xlsx
```

O importador guarda:

- batch de importacao;
- linhas raw;
- viaturas permanentes;
- snapshot externo Rentway por viatura.

Para correr a suite de testes, instalar primeiro as dependencias de
desenvolvimento:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Produção v2

Ver também: `docs/DEPLOY_V2_PRODUCTION.md`.

