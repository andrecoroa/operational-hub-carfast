# CarFast — Estado canónico sanitizado

**Versão:** 2026-08-27.1 — TRANSITION CHECKPOINT / NO-GO

**Atualizado em:** 2026-08-27, Europe/Lisbon

**Branch:** `codex/ui-contract-transversal-fidelity`

**Base:** `47694c0a5b200133e8d475afcf6ceda853e07351` + alterações do checkpoint

Este documento alinha execução local, Estratégia, Coordenação cloud e Operador cloud. Não contém segredos, credenciais, URLs privadas nem dados pessoais.

## Checkpoint de transição atual

- Este trabalho ainda não foi publicado no Green; PR, merge e deploy permanecem bloqueados.
- Gate desktop: sete famílias em `1440×731`, zoom 100%, cada uma com MAE full-frame `<2,00%`, sem máscaras.
- Métricas atuais: Dashboard 2,70%; Tarefas 3,54%; Processos 5,15%; Email 5,66%; Documentação 5,22%; Administração 3,93%; Parceiros 3,80%.
- Dashboard foi recomposto; Documentação usa preview real da primeira página PDF com RBAC/confidencialidade; Email mantém as três zonas sem faixas desktop redundantes.
- Ordem fechada: Documentação → Email → Tarefas → Processos → Administração → Dashboard → Parceiros.
- Tablet/mobile só retomam após validação explícita do desktop.
- GitHub é a fonte canónica; nenhuma prova pode depender exclusivamente de sessão de browser, `/dev/shm`, worktree ou ficheiro temporário.

## Green

- Release live: `5501277efc5b17f2767010650c313e54cca7f99e`.
- Origem: `integration/modular-architecture`, merge do PR #80.
- Deploy manual: concluído exclusivamente no Green.
- Health Render: `live`.
- Smoke autenticado: UI Contract ativo; Email, Documentação, Administração, Dashboard e Parceiros responderam na sessão real sem overflow global; preview Email inicia fechado nos viewports modais.
- Efeitos externos permanecem desligados.

## Blue preservado

- Blue continua a referência de produção e rollback.
- Nenhuma alteração Blue, deploy produtivo, DNS, domínio ou cutover faz parte da tranche visual atual.
- O estado funcional e os dados Blue devem permanecer intocados até gate explícito de cutover.

## Concluído

- Migração integral e cleanup concluídos; baseline Green reconciliado preservado.
- Shell e navegação transversais convergidas, incluindo agrupamentos Operação, Operações de negócio e Sistema.
- Instalação modular, Tarefas-tipo, Processos-modelo e modelo seguro de Venda de Viatura Usada a Comerciante integrados no Green, sem iniciar instâncias nem efeitos externos.
- UI Contract v1 aplicado à shell, Centro de Tarefas e Centro de Processos no PR #79.
- UI Contract v1 aplicado a Email, Documentação, Administração, Dashboard e Parceiros no PR #80.
- CI do PR #79 e revisão independente sem P0/P1; deploy e smoke Green concluídos.

## Em curso

- Validação visual humana e evidência responsive pós-deploy do Green `5501277e`.
- Email: lista e preview/tratamento no mesmo contexto desktop; modal responsive em tablet/mobile; ações preservam o preview e o foco.
- Documentação: topbar e workbench lista/preview alinhados ao contrato canónico, preservando a triagem documental aprovada.
- Administração: composição mestre-detalhe e densidade transversal, mantendo RBAC fail-closed e rotas existentes.
- Dashboard e Parceiros: densidade, controlos e tabelas alinhados pelas mesmas primitives.
- PR #80: CI verde, revisão independente GO, merge/deploy/smoke concluídos.

## Bloqueios

- Nenhum bloqueio funcional conhecido.
- Gate atual: evidência responsive pós-deploy e validação visual explícita antes de expandir às restantes superfícies.

## Decisões funcionais fechadas

- “Iniciar processo” cria uma instância a partir de um Processo-modelo.
- “Criar tarefa do processo” adiciona tarefa a um processo já existente.
- Tarefas-tipo aparecem no fluxo Criar tarefa e são geridas em Administração.
- Vendas é apresentado sob Frota; Stock e Compras sob Oficina, mantendo módulos, rotas, permissões e ativação independentes.
- Email não é filho de Tarefas ou Processos; são superfícies irmãs no grupo Operação.
- Preview e classificação permanecem no mesmo contexto em Email e Documentação nos viewports suportados.
- Oficina permanece zero-perdas; adaptações exigem paridade nominal.

## Perfis e RBAC

- Perfis canónicos: Executor, Coordenador de Equipa, Coordenador Operacional, Gestor e Administrador fora da hierarquia operacional.
- Leitura ou gestão não implica criação.
- Resolver server-side revalida capacidades e âmbito no POST, em default-deny.
- Gestor só executa excecionalmente com alerta, justificação e auditoria.
- Administrador não recebe acesso operacional implícito.

## Módulos e superfícies

- Inventário canónico: 136 superfícies, classificadas por tipo e compatibilidade; não usar o antigo “53/53” como prova de fidelidade visual integral.
- Núcleo já publicado: shell, Centro de Tarefas e Centro de Processos.
- Núcleo em PR #80: Email, Documentação, Administração, Dashboard e Parceiros.
- Demais superfícies só avançam após validação do núcleo e reutilizam tokens/primitives; não criam variantes locais.

## Efeitos externos

- Email outbound/inbound real, jobs, webhooks, portais, tokens e integrações externas: OFF.
- Nenhum bootstrap ou deploy pode iniciar processos, enviar email, publicar portal ou produzir efeitos externos.

## Próximos gates

1. Capturas e métricas responsive do Green `5501277e` em desktop, tablet e mobile.
2. Validação visual explícita de Email, Documentação, Administração, Dashboard e Parceiros.
3. Corrigir qualquer regressão factual na mesma tranche.
4. Só depois expandir tokens/primitives às restantes superfícies do inventário 136.

## Limitações conhecidas

- O PR #80 possui cobertura funcional focada e testes estruturais do contrato; a cobertura browser/DOM automatizada para todos os comportamentos responsive continua parcial.
- Capturas antigas não substituem evidência do runtime após deploy do SHA final.
- Disponibilidade para QA não equivale a autorização de produção, DNS, domínio, integrações ou cutover.

## Instalação-base e cutover

- Instalação-base limpa nasce apenas de Alembic, seeds versionados e onboarding; nunca de limpar ou anonimizar Blue/Green CarFast.
- Deve conter zero dados operacionais, ficheiros, credenciais, tarefas/processos instanciados ou auditoria CarFast.
- O cutover exige release candidate imutável, reconciliação fresh de BD e delta determinístico do storage, efeitos externos ainda OFF, gate humano e rollback Blue preservado.
- DNS/domínio e ativação faseada de integrações são gates separados e continuam não autorizados nesta fase.
