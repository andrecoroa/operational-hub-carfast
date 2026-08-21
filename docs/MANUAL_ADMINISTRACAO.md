# Manual — Administração

## Funcionamento em poucas palavras

A Administração organiza configuração e controlo por domínios, mas reutiliza as fontes de verdade dos módulos. A experiência Clean oferece pesquisa e ligações para **Operações e Service Desk**, **Utilizadores e Acessos**, **Organização**, **Módulos Operacionais**, **Integrações**, **Sistema e Auditoria** e **Evolução da Aplicação**.

As páginas legacy continuam disponíveis por compatibilidade. Não são uma segunda base de dados e não devem ser removidas sem prova de desuso, revisão de dados e testes.

## Disponível agora

- Visão geral e pesquisa de áreas administrativas.
- Utilizadores, perfis, permissões, credenciais e estado.
- Unidades organizacionais, equipas e membros.
- Catálogos/configurações e valores ativos/inativos.
- Service Desk: hierarquia, tipos, políticas, SLA, supervisores, executores e defaults.
- Email: caixas base/adicionais, aliases, acessos, elegibilidade, regras, políticas e templates.
- Revisão de propostas provisórias de classificação, incluindo aprovação, associação, fusão e reclassificação auditada.
- Modelos/versionamento da Oficina e publicação controlada.
- Estado de integrações e superfícies de auditoria.
- Registo de Evolução com filtros, detalhes, comentários, documentos, histórico e conversão em tarefa.
- Ação global “Novo registo de evolução” para utilizadores com permissão de criação.
- Autorização no servidor e aliases de compatibilidade.

## Operador simples

O operador normal não vê a Administração salvo permissões específicas. Pode usar a ação global de Evolução com `admin.evolution.create`: escolhe tipo, título, descrição e prioridade; a aplicação preenche URL/módulo de origem. Criar um registo não concede leitura ou gestão de todo o backlog.

Quando tem leitura de uma área, consulta apenas os dados dessa área. Não pode criar utilizadores, alterar perfis, publicar modelos, gerir SLA ou editar integrações sem a permissão de gestão correspondente.

Anexos no registo rápido global não estão disponíveis. Na gestão completa, documentos existentes podem ser ligados por utilizadores autorizados.

## Executor

Na Administração, “executor” é normalmente o responsável por parametrização ou análise de Evolução, não um privilégio global. Deve:

1. Trabalhar apenas nas áreas autorizadas.
2. Registar motivo, impacto e evidência de cada alteração.
3. Usar estado/decisão do Registo de Evolução e ligar tarefa/branch/commit quando aplicável.
4. Testar alterações de configuração com um perfil representativo.
5. Pedir validação antes de publicar modelos, ativar regras ou alterar integrações.

Não deve editar diretamente dados para contornar a UI, a auditoria ou constraints.

## Supervisor/administrador

### Triagem e prioridades

No Registo de Evolução, o supervisor valida tipo, módulo, duplicados, prioridade, dependências e próximo passo. Pode atribuir análise a uma pessoa ou equipa, nunca simultaneamente a ambas. Deve agrupar comentários pequenos num tópico coerente.

### Validação, reabertura e auditoria

Use os estados Registado, Em análise, Aprovado, Adiado, Rejeitado, Em implementação e Concluído conforme evidência. Uma proposta ou mockup não passa a Concluído. Reabra quando uma entrega integrada falhar ou o âmbito aprovado não tiver sido satisfeito, explicando a alteração no histórico.

### Permissões e segregação

- Gestão de utilizadores/perfis não implica automaticamente gestão de Email, Service Desk ou Evolução.
- `admin.evolution.create`, `read` e `manage` têm finalidades distintas.
- A UI escondida não é segurança; valide sempre no servidor.
- Revise utilizadores sem perfil/âmbito, contas inativas e permissões administrativas acumuladas.

## Implementador/parametrizador

### Estruturas, tipos e classificações

- Identidade/RBAC: `users`, `roles`, `permissions`, relações de perfil e permissão.
- Organização: unidades, equipas, membros e âmbitos.
- Trabalho: `tasks`, comentários, documentos, histórico, atribuição e SLA.
- Classificação comum: filas, departamentos, categorias, subcategorias, tipos/políticas e elegibilidade.
- Processos: tipos, versões/associações, ações, evidências e histórico.
- Email: canais, acessos, regras, templates, threads, mensagens, entregas, anexos e eventos.
- Evolução: registos, comentários, histórico e documentos.

Preserve códigos e IDs técnicos; nomes podem ser editáveis. Prefira inativação a remoção quando existe histórico.

### Modelos, processos e publicação

Modelos da Oficina já possuem versões e publicação. Recorrências de tarefas usam modelos próprios. O Construtor de Fluxos e o editor genérico de modelos de tarefas são apenas mockups: não crie tabelas ou menus que os anunciem como disponíveis.

Antes de publicar uma versão, confirme referências, permissões, estado ativo e efeito em novas instâncias. Instâncias existentes devem conservar o snapshot/versionamento usado na criação.

### Caixas e automações de Email

Configure apenas endereços, aliases, `MailboxHash`, regras e modelos confirmados. Nunca invente dados externos. Alterações Microsoft 365/Postmark são passos administrativos separados do deploy e precisam de aprovação própria.

### Testes e reversão

1. Inventarie uso de páginas, campos, permissões, rotas e tabelas.
2. Faça migrações aditivas e bootstrap idempotente; não insira dezenas de registos operacionais por migração sem padrão comprovado.
3. Execute Alembic heads, testes focados, `py_compile`, Ruff e `git diff --check`.
4. Teste leitura/gestão separadas, perfis sem permissão e âmbito de dados.
5. Faça QA desktop/mobile e ensaio de upgrade em cópia de staging.
6. Reverta aplicação/configuração de forma conservadora; não use downgrade que apague histórico já criado.

## Importar o catálogo da Evolução

O catálogo versionado usa `origin = catalog:<external_key>` como chave estável. O importador também evita duplicados conservadores por título/módulo, commit e task ID. Por omissão, não escreve:

```powershell
python scripts/import_evolution_catalog.py --report work/evolution-dry-run.json
```

Após rever o relatório e apenas numa base autorizada:

```powershell
python scripts/import_evolution_catalog.py --apply --report work/evolution-apply.json
```

O relatório indica `created`, `updated` e `ignored`. Uma segunda execução deve ignorar todos os registos sem alterações. Não executar `--apply` em produção sem autorização explícita.

## Planeado/em implementação — não disponível agora

- Captura transversal de fotografia: em execução.
- Construtor de Fluxos e editor genérico de modelos/tarefas: apenas mockups.
- Programa **Gestão Diária e Performance Operacional**: dez registos planeados no catálogo, associados a `daily-management.program`. Inclui capacidade, plano diário, produtividade, reporting, alertas, Rentway analytics, passagem de turno, eventos comuns e IA futura. Nenhum destes itens é uma página ou funcionalidade disponível agora.

## Referências

- `docs/ADMIN_PERMISSION_MATRIX.md`
- `docs/ADMIN_REORGANIZATION_INVENTORY_2026-08-21.md`
- `docs/INVENTARIO_EVOLUCAO_RECENTE_2026-08-21.md`
- `data/evolution_catalog_2026-08-21.json`
