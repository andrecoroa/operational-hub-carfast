# CarFast — readiness de cutover e instalação-base

Estado deste documento: **plano executável; nenhuma ação de cutover autorizada ou executada**.

## Gate absoluto da release candidate

O cutover é `NO-GO` até existir uma release candidate imutável que prove cumulativamente:

- SHA de integração e artefacto/deploy Green congelados e iguais;
- CI e revisão independentes verdes;
- migrations com um único head, upgrade e downgrade ensaiados em PostgreSQL 17;
- bootstrap idempotente e `check_clean_install` verdes;
- UI Contract aprovado, incluindo Tarefas-tipo, Processos-modelo e Venda de Viatura Usada a Comerciante;
- inventário das 136 superfícies classificado e sem superfície canónica sem shell/asset/guard;
- testes funcionais, visuais, responsive, teclado, RBAC adversarial e paridade nominal da Oficina verdes;
- Green saudável, efeitos externos OFF e reconciliação baseline válida.

O responsável de Execução reúne a evidência; Estratégia e André dão o GO humano. Qualquer item sem evidência direta é `NO-GO`, não “aceite com reserva”.

## A. Cutover definitivo

| # | Fase e responsável | Evidência obrigatória | Duração alvo | Stopping condition / rollback |
|---|---|---|---:|---|
| A1 | Congelar RC e configuração — Execução | SHAs Blue/Green, Alembic head, image/command, feature flags, nomes booleanos de integrações OFF e fingerprints sanitizados | 20 min | Drift: NO-GO antes da janela |
| A2 | Aceitação prévia — QA + donos funcionais | Login com Executor, Coordenador de Equipa, Coordenador Operacional, Gestor e Administrador; jornadas críticas e negativas; relatório assinado | 60–90 min | Permissão indevida ou jornada crítica falha: NO-GO |
| A3 | Preparar cutoff — Execução | recovery hook/watchdog testados; comandos congelados; espaço/inodes; chaves efémeras; baseline Green e manifests preservados | 20 min | Watchdog/reversão não comprovados: não abrir janela |
| A4 | Quiesce comum Blue — Execução | timestamp inicial; drain; DB e storage sem writes; probes de escrita negados e leituras permitidas | até 10 min | Qualquer writer/open-FD ambíguo: reverter e NO-GO |
| A5 | Captura final — Execução | `pg_dump` fresh + manifest delta storage (new/changed/deleted), ciphertext, bytes e SHA-256; ACK comum | 20–40 min | Limite da janela, digest ou transferência falha: watchdog restaura Blue |
| A6 | Reabrir Blue — Execução | timestamp final; DB/storage writable, health e login; Blue continua produção/rollback | até 5 min | Falha de reversão: incidente prioritário, sem prosseguir Green |
| A7 | Aplicar dataset Green — Execução | restore fresh; Alembic; sequences; delta storage idempotente em staging e promoção atómica | 30–60 min | Erro de restore/migration/delta: Green não promovido; Blue permanece ativo |
| A8 | Reconciliação zero-tolerance — Dados + Execução | tabelas/colunas/PK/FK, IDs, sequences, contagens, órfãos e digests; documentos/anexos/processos/tarefas/emails/auditoria; paths/tamanho/SHA-256 storage | 30–60 min | Diferença inexplicada, perda ou efeito externo: NO-GO e rollback Green |
| A9 | Ligar e validar Green — Execução + QA | DATABASE_URL/storage final, mesma RC, deploy manual, health, login e smoke autenticado; efeitos externos ainda OFF | 20–30 min | Health/login/RBAC falha: reverter ligação/deploy |
| A10 | Gate humano — André + Estratégia | checklist nominal e relatório de reconciliação revistos | 15 min | Sem GO explícito: DNS/domínio permanecem inalterados |
| A11 | Domínio — action-time separado | DNS/TLS/hostnames, TTL e probes; Blue preservado | 15–45 min + propagação | Erro de routing/TLS: reverter DNS para Blue |
| A12 | Início controlado — Operações | monitorização, erros, latência, writes, filas; integrações continuam OFF | 2–4 h intensivas | Erros críticos, corrupção ou divergência: rollback Blue |

Email, jobs, webhooks, portais e tokens externos são gates independentes depois do início. Para cada integração: credencial própria, escopo mínimo, teste controlado, observabilidade, rollback e autorização action-time específica.

### Contrato do delta final

- O dump da BD é sempre integral e coerente sob o cutoff final; não se aplica um delta lógico artesanal à BD.
- O storage usa o manifest baseline Green e o manifest Blue quiescido: `create`, `replace` e `delete` por path normalizado, tamanho e SHA-256.
- Aplicação é idempotente, rejeita symlinks/special files/traversal/case ou NFC ambíguos e nunca promove parcialmente.
- O cutoff, release, bundle e ambos os manifests têm IDs vinculados; um par divergente é rejeitado.

### Autorizações action-time indispensáveis

1. Abrir a janela e ativar recovery hook/watchdog/read-only/barreira de storage Blue.
2. Criar/injetar/revogar credenciais técnicas efémeras e transferir a captura cifrada.
3. Aplicar restore/delta e ligar o Web Green ao dataset final.
4. GO humano para DNS/domínio (separado).
5. Uma autorização por família de efeitos externos.

### Retenção e rollback

- Blue e a BD Green vazia de rollback permanecem intactos durante QA e após o início.
- Proposta inicial: mínimo 14 dias e dois ciclos operacionais/financeiros completos; eliminação só com reconciliação final, backups/PITR comprovados, zero rollback ocorrido, aprovação André+Estratégia e ticket de destruição com IDs exatos.
- Nunca eliminar simultaneamente Blue e a BD de rollback. Dados temporários, chaves e captures cifradas são eliminados logo após evidência e PASS/NO-GO.

## B. Instalação-base limpa e reutilizável

A instalação-base é uma saída independente da mesma release. **Nunca** deriva de apagar, anonimizar ou copiar o Green/Blue CarFast.

1. Criar PostgreSQL 17 vazio e storage vazio num ambiente isolado.
2. Executar `alembic upgrade head`.
3. Executar apenas seeds versionados allowlisted e onboarding inicial.
4. Ativar módulos selecionados explicitamente; efeitos externos e credenciais ficam OFF/ausentes.
5. Executar bootstrap uma segunda vez e provar idempotência (zero alteração inesperada).
6. Produzir manifest das relações da release: 166 tabelas de aplicação mais relações técnicas explicitamente identificadas, sem assumir contagem histórica fixa se a RC adicionar schema aprovado.
7. Provar contagem zero em todas as tabelas operacionais/tenant e storage com zero objetos.
8. Executar `scripts/check_clean_install`, testes de login/onboarding, RBAC-base e seleção modular.
9. Exportar apenas runbook, manifest e biblioteca de templates; nunca dump de dados CarFast.

Allowlist: Core, catálogo de módulos, capacidades/permissões-base e referências estritamente versionadas. Denylist obrigatória: users de cliente, veículos, parceiros, documentos/anexos, emails, tarefas, processos/instâncias, auditoria operacional, tokens, credenciais e paths CarFast.

### Tarefas-tipo e Processos-modelo

- Estruturas genéricas podem integrar uma biblioteca opcional versionada, sempre sem usos, instâncias ou favoritos.
- “Venda de Viatura Usada a Comerciante” é inicialmente um **template de solução exportável e desativado**, não seed global ativo. O onboarding de uma empresa decide instalá-lo/publicá-lo e atribuir permissões; o bootstrap nunca inicia processos, envia email ou publica portal.

### Artefactos e gate futuro

- `clean-install-manifest.json`: relações, seeds allowlisted e contagens esperadas.
- `clean-install-runbook.md`: comandos parametrizados, sem secrets.
- teste automatizado de instalação, idempotência, denylist operacional e storage vazio.
- A criação de ambiente permanente, SKU ou domínio para uma nova empresa exige gate financeiro e action-time futuro.

## Checklist GO/NO-GO para início de utilização

- [ ] RC imutável cumpre integralmente o gate absoluto.
- [ ] Blue e Green identificados sem ambiguidade; Blue preservado.
- [ ] Reconciliação BD+storage final é tolerância zero.
- [ ] Green health/login/RBAC e jornadas críticas passam.
- [ ] Efeitos externos continuam OFF e ausentes onde aplicável.
- [ ] Monitorização e responsáveis de incidente estão ativos.
- [ ] Rollback para Blue foi ensaiado e continua disponível.
- [ ] André deu GO explícito; DNS/domínio têm autorização própria.
- [ ] Instalação-base foi gerada de migrations+seeds e passou denylist/idempotência.

Sem todos os pontos, a recomendação é **NO-GO**.
