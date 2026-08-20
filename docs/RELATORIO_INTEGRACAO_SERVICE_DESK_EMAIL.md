# Relatório de integração — Service Desk e Email operacional

## Entrega

- Worktree: `C:\Users\andre\.codex\worktrees\085e\New project`
- Branch: `codex/service-desk-email-operations`
- Base remota verificada: `origin/v2/production` em `c2840d9f`
- Push, merge, deploy e alterações externas: não efetuados

Commits funcionais:

1. `fd1f61c` — `feat: add Service Desk and Email operations foundation`
2. `a0e6c46` — `feat(email): route operational mailboxes with Postmark hashes`
3. `9461cdf` — `feat(service-desk): enforce scoped ticket operations`
4. Administração, UI e documentação final: consultar o histórico da branch.

## Migração e bootstrap

- Migração: `ffbe1e2f3a4c_add_service_desk_email_operations.py`
- `down_revision`: `ffad1e2f3a4b`, head remoto existente na base usada
- O teste da árvore Alembic confirmou `ffbe1e2f3a4c` como head único.
- Upgrade e downgrade PostgreSQL offline foram compilados pelo bloco de migração.
- Bootstrap idempotente cria os seis tipos de ticket, políticas base, permissões e
  as cinco caixas sem alterar classificações históricas de tarefas.
- Códigos técnicos não são editáveis; nomes e estado ativo podem mudar.

## Routing Postmark confirmado

| Caixa | `inbound_hash` | Encaminhamento Microsoft 365 |
|---|---|---|
| `hub@carfast.pt` | `hub` | `da0078240da719f585b6f441e02a1951+hub@inbound.postmarkapp.com` |
| `multas@carfast.pt` | `multas` | `da0078240da719f585b6f441e02a1951+multas@inbound.postmarkapp.com` |
| `oficina@carfast.pt` | `oficina` | `da0078240da719f585b6f441e02a1951+oficina@inbound.postmarkapp.com` |
| `sinistros@carfast.pt` | `sinistros` | `da0078240da719f585b6f441e02a1951+sinistros@inbound.postmarkapp.com` |
| `vvp@carfast.pt` | `vvp` | `da0078240da719f585b6f441e02a1951+vvp@inbound.postmarkapp.com` |

O inbound base sem hash é aceite apenas como compatibilidade histórica do hub.
Um hash desconhecido não cai silenciosamente no hub. O outbound usa a caixa
pública selecionada como `From` e `Reply-To`; nenhum segredo está no repositório.

## Validações executadas

- Email/Postmark: `25 passed` antes da consolidação final; inclui bootstrap das
  cinco caixas, `MailboxHash` principal e `ToFull`, endereços plus exatos,
  precedência, idempotência, fallback histórico do hub e `From`/`Reply-To`.
- Service Desk/SLA/permissões: `15 passed` focados e `43 passed` na regressão
  alargada do bloco; Ruff aprovado nesses ficheiros.
- Migração: `3 passed`; SQL PostgreSQL upgrade/downgrade e Ruff aprovados.
- Administração granular: compilação Python e balanceamento Jinja aprovados;
  `git diff --check` limpo no bloco.
- `git diff --check`: aprovado na consolidação, ignorando apenas avisos LF/CRLF.

O novo teste REST e as últimas correções integradas não puderam ser executados de
novo porque o executor Python externo atingiu o limite de aprovação da sessão.
Pelo mesmo motivo não foi possível arrancar a aplicação para QA visual real em
desktop/mobile. Estas duas validações são obrigatórias em staging antes do merge.

## Integração recomendada

1. Criar uma branch de integração a partir do head remoto atual.
2. Fazer cherry-pick dos commits desta branch pela ordem do histórico.
3. Resolver apenas conflitos reais; não colapsar a migração noutro head sem rever
   `down_revision` e repetir o teste de árvore Alembic.
4. Executar Ruff nas alterações, a suite completa e `git diff --check`.
5. Aplicar `alembic upgrade head` numa cópia de staging e executar bootstrap duas vezes.
6. Fazer QA desktop/mobile de Service Desk, Email e Administração.
7. Configurar webhooks/segredos manualmente; fazer piloto inbound numa caixa com
   outbound e auto-ticket desligados.
8. Só depois de aprovação ativar cada caixa Microsoft 365, uma de cada vez.

## Riscos residuais

- A migração é extensa e deve ser ensaiada com uma cópia representativa da base.
- A segurança cobre API REST, UI Clean e rotas `/task-board`, mas requer teste
  negativo autenticado com os perfis reais e a matriz de âmbitos de produção.
- O storage de anexos tem de ser persistente e privado no ambiente de destino.
- Inativar opções preserva histórico; as equipas devem validar a apresentação de
  classificações/executores inativos nos dados reais.
- Nenhuma configuração externa foi aplicada; erros de forwarding, permissões M365,
  DKIM ou Return-Path continuam dependentes da ativação manual.

## Manuais

O texto para o chat responsável pelos guias está em
`docs/MANUAIS_HANDOFF_SERVICE_DESK_EMAIL.md`. O runbook operacional Postmark está
em `docs/email-postmark/GUIA_CONFIGURACAO_ANDRE.md`.
