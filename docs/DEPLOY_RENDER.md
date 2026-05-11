# Deploy Render - Operational Hub Carfast

## Arquitetura Recomendada

- GitHub repo: `operational-hub-carfast`
- Render Web Service: `operational-hub-carfast`
- Render PostgreSQL: `operational-hub-carfast-db`

## Blueprint

O ficheiro `render.yaml` define:

- Web Service Python/FastAPI
- Render PostgreSQL
- `DATABASE_URL` vindo do Postgres interno do Render
- `APP_SECRET_KEY` gerado pelo Render
- migracoes Alembic no arranque do servico
- health check em `/health`

## Criar No Render

1. Enviar este projeto para GitHub.
2. No Render, criar um novo Blueprint.
3. Selecionar o repo `operational-hub-carfast`.
4. Confirmar os recursos:
   - `operational-hub-carfast`
   - `operational-hub-carfast-db`
5. Fazer deploy.

## Admin Inicial No Plano Free

O plano free do Render nao suporta one-off jobs nem shell. Para criar o admin,
definir estas environment variables no Web Service:

```text
CARFAST_ADMIN_EMAIL=admin@carfast.local
CARFAST_ADMIN_PASSWORD=alterar-esta-password
```

Depois fazer redeploy. O `scripts/render_start.py` corre as migracoes e cria o
admin automaticamente se essas variaveis existirem. Se o admin ja existir, nao
cria duplicado.

Depois do admin estar criado, remover `CARFAST_ADMIN_PASSWORD` das environment
variables e fazer novo redeploy.

## Nota Sobre Free Plan

O blueprint usa `plan: free` para web e Postgres. Segundo a documentacao atual
do Render, Postgres free expira apos 30 dias e nao deve ser usado para producao.
Para uso real da empresa, trocar a base para plano pago antes de carregar dados
importantes.

Nota: `preDeployCommand` nao e suportado em servicos free. Por isso, no plano
free, as migracoes correm em `scripts/render_start.py` antes de iniciar o
Uvicorn.
