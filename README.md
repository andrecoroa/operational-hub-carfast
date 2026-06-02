# CarFast v2

Nova base da plataforma operacional CarFast.

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
python scripts/bootstrap_db.py
uvicorn app.main:app --reload
```

Antes de usar em ambiente real, configurar `DATABASE_URL` para PostgreSQL.

## Oficina por Fases

- Lista: `/workshop/processes-ui`
- Novo processo: `/workshop/new-process`
- Painel operacional: `/workshop/processes-ui/{id}/manage`

## Deploy

O projeto inclui `render.yaml`. O comando de arranque executa migracoes e inicia
o servidor:

```powershell
python scripts/start.py
```

Em producao, configurar `DATABASE_URL` e `APP_SECRET_KEY`.
