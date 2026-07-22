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
- disco persistente montado em `/var/data`
- `DOCUMENT_ARCHIVE_ROOT=/var/data/carfast_documents`
- `DOCUMENT_INVOICE_INBOX_PATH=/var/data/carfast_documents/Frota/_POR_ASSOCIAR/_Entrada_Documental/Faturas`
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

O arquivo documental da v2-clean precisa de storage persistente. Se o plano do
Web Service nao permitir disco persistente, nao carregar documentos definitivos:
os ficheiros podem ficar apenas no filesystem efemero do deploy. Em producao,
confirmar no Render que o disco `carfast-documents` esta montado em `/var/data`
antes das importacoes.

Nota: `preDeployCommand` nao e suportado em servicos free. Por isso, no plano
free, as migracoes correm em `scripts/render_start.py` antes de iniciar o
Uvicorn.

## Arquivo Documental V2-Clean

Raiz fisica:

```text
/var/data/carfast_documents
```

Pastas principais:

```text
Frota/[MATRICULA]_[CHASSIS]/01_Documentacao_Financeira/Faturas
Frota/[MATRICULA]_[CHASSIS]/02_Documentacao_Tecnica/Processos/[PROCESSO]/01_Diagnosticos
Frota/[MATRICULA]_[CHASSIS]/02_Documentacao_Tecnica/Processos/[PROCESSO]/03_Fotos_Evidencias
Frota/[MATRICULA]_[CHASSIS]/03_Documentacao_Base_Viatura/Documentacao_Viatura
Frota/_POR_ASSOCIAR/99_Pendentes_Classificar
Frota/_POR_ASSOCIAR/_Entrada_Documental/Faturas
Frota/_Importacoes_Estruturadas
```

As listagens estruturadas em Excel ficam arquivadas como fontes em
`Frota/_Importacoes_Estruturadas`; as linhas de FO, contratos e impros ficam na
base de dados para classificacao e timeline.

## Recuperação de Falha: HOST DE BASE Invalido

Se o serviço falhar no arranque com erro `failed to resolve host ...`, faz isto:

1. Confirmar qual host está a ser usado no log (`[render_start] candidato_x: host=...`).
2. Em `Web Service` > `Environment`, definir:
   - `RENDER_DATABASE_URL` ou `CARFAST_DATABASE_URL` com a connection string atual do PostgreSQL do Render.
3. Remover `DATABASE_URL` manual antiga (se existir) e deixar o `fromDatabase` do `render.yaml` cuidar do valor.
4. `Manual Deploy` novamente.

O `scripts/render_start.py` tenta estes candidatos nesta ordem:
`DATABASE_URL`, `CARFAST_DATABASE_URL`, `DATABASE_URL_FALLBACK`, `RENDER_DATABASE_URL`.
Se o primeiro falhar, tenta o seguinte e indica no log qual candidato falhou.

Importante: **nunca** colocar credenciais sensíveis no código/repositório.
