# CarFast v2 - Produção e Separação de Workspaces

## Fonte de verdade

A CarFast v2 em produção deve usar apenas:

- Diretório local: `C:\carfast_v2`
- Repositório GitHub: `andrecoroa/operational-hub-carfast`
- Branch de produção: `v2/production`
- Serviço Render: `operational-hub-carfast`

O diretório `C:\Users\andre\OneDrive\Документы\New project` fica reservado para trabalho experimental, novo projeto, mockups, exploração de UI e funcionalidades ainda não promovidas.

## Regra de deploy

Nunca fazer deploy de branches experimentais para produção v2.

Branches a não usar diretamente em produção v2:

- `codex/workshop-fleet-linked-creation`
- `codex/workshop-fleet-linked-creation-renderfix`
- `codex/workshop-phased-process`
- `codex/workshop-ui-refinement`
- qualquer branch de protótipo ou trabalho em curso

A branch correta no Render deve ser:

```text
v2/production
```

## Base de dados Render

A app v2 precisa de uma connection string real do Render.

Opção preferida:

1. No serviço Render `operational-hub-carfast`, ir a `Environment`.
2. Criar/atualizar `DATABASE_URL` usando `Add from database`.
3. Selecionar a base PostgreSQL correta.
4. Usar a propriedade `Connection String`.

Opção alternativa:

1. Abrir a página da base PostgreSQL no Render.
2. Copiar o `External Database URL` completo.
3. No serviço Render, definir:

```text
CARFAST_DATABASE_URL=<External Database URL copiado do Render>
```

Não usar hosts internos curtos como:

```text
dpg-xxxxxxxxxxxx-a
```

Se aparecer esse host nos logs, a variável de ambiente está errada para este serviço/deploy.

## Como validar o deploy

Depois de `Manual Deploy -> Clear build cache & deploy latest commit`, confirmar no log:

```text
[render_start] Candidatos de base:
[render_start] candidato_1:
```

Se o log indicar host interno curto, corrigir a variável de base no Render.

Se o log indicar `scripts/render_start.py line 25`, o Render está a usar commit antigo ou branch errada.

## Promoção de trabalho experimental para v2

Qualquer alteração criada no workspace experimental deve seguir este caminho:

1. Identificar ficheiros e objetivo da alteração.
2. Criar branch própria a partir de `v2/production`.
3. Aplicar apenas os ficheiros necessários.
4. Validar localmente.
5. Só depois fazer merge/push para `v2/production`.

Não copiar alterações grandes ou não revistas diretamente do workspace experimental para produção.
