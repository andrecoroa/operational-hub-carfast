# CarFast — Estado canónico sanitizado

**Versão:** 2026-08-26.1  
**Atualizado em:** 2026-08-26, Europe/Lisbon

Este documento alinha execução local, Estratégia, Coordenação cloud e Operador cloud. Não contém segredos, credenciais, URLs privadas nem dados pessoais.

## Green

- Release live: `b06424e58eca1ad19a0a0532ebd03a1c45431e65`.
- Origem: `integration/modular-architecture`, merge do PR #79.
- Deploy manual: concluído exclusivamente no Green.
- Health Render: `live`.
- Smoke autenticado: UI Contract ativo; Centro de Tarefas com título canónico, dados reais preservados e sem overflow global no viewport verificado.
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
- CI do PR #79 e revisão independente sem P0/P1; deploy e smoke Green concluídos.

## Em curso

- PR #80, branch `codex/ui-contract-core-workspaces`, HEAD `6a17cc51`.
- Email: lista e preview/tratamento no mesmo contexto desktop; modal responsive em tablet/mobile; ações preservam o preview e o foco.
- Documentação: topbar e workbench lista/preview alinhados ao contrato canónico, preservando a triagem documental aprovada.
- Administração: composição mestre-detalhe e densidade transversal, mantendo RBAC fail-closed e rotas existentes.
- Dashboard e Parceiros: densidade, controlos e tabelas alinhados pelas mesmas primitives.
- Revisão independente do HEAD atual: GO, sem P0/P1; CI remoto ainda tem de fechar antes de merge.

## Bloqueios

- Nenhum bloqueio funcional conhecido.
- Gate atual: CI remoto verde do PR #80, seguido de merge, deploy apenas Green e smoke autenticado/runtime responsive.

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

1. CI remoto e revisão final do PR #80 verdes.
2. Merge em `integration/modular-architecture`.
3. Deploy manual apenas Green.
4. Smoke autenticado e responsive de Email, Documentação, Administração, Dashboard e Parceiros.
5. Atualizar este documento com o novo Green SHA somente depois do deploy/smoke.
6. Validação visual explícita antes de expandir o contrato às restantes superfícies.

## Limitações conhecidas

- O PR #80 possui cobertura funcional focada e testes estruturais do contrato; a cobertura browser/DOM automatizada para todos os comportamentos responsive continua parcial.
- Capturas antigas não substituem evidência do runtime após deploy do SHA final.
- Disponibilidade para QA não equivale a autorização de produção, DNS, domínio, integrações ou cutover.

## Instalação-base e cutover

- Instalação-base limpa nasce apenas de Alembic, seeds versionados e onboarding; nunca de limpar ou anonimizar Blue/Green CarFast.
- Deve conter zero dados operacionais, ficheiros, credenciais, tarefas/processos instanciados ou auditoria CarFast.
- O cutover exige release candidate imutável, reconciliação fresh de BD e delta determinístico do storage, efeitos externos ainda OFF, gate humano e rollback Blue preservado.
- DNS/domínio e ativação faseada de integrações são gates separados e continuam não autorizados nesta fase.
