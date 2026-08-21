# Manual — Centro de Tarefas / Service Desk

## Funcionamento em poucas palavras

O Centro de Tarefas usa um motor comum para registar, classificar, atribuir, executar e auditar trabalho. O Service Desk acrescenta tipos de ticket, âmbito por classificação, supervisor/executor, SLA de primeira resposta e resolução e operações específicas como **Assumir**, **Atribuir**, **Responder** e **Concluir**.

Uma tarefa pode estar ligada a Email, Processo, Oficina, viatura, documentos ou outras entidades. A ligação conserva contexto; não deve criar uma segunda cópia do trabalho.

## Disponível agora

- Espaços Operacional, Oficina, Gestão e Administração, sujeitos a permissões próprias.
- Tarefas e tickets com pesquisa, filtros, prioridade e estados.
- Tipos base do Service Desk: Tarefa, Pedido, Comunicação, Ajuda interna, Incidente e Aprovação.
- Hierarquia Fila → Departamento → Categoria → Subcategoria.
- Atribuição a utilizador/equipa, equipa “Por assumir” e situação “A aguardar atribuição”.
- Supervisor e executor como responsabilidades distintas.
- SLA de primeira resposta e resolução, com pausa configurável ao aguardar.
- Comentários, participantes, histórico, eventos de atribuição/SLA e documentos ligados.
- Pedidos de ajuda/decisão sem transferência automática da responsabilidade.
- Recorrências seguras que criam tarefas normais e fluxos guiados leves já definidos no código.
- Propostas provisórias de categoria/subcategoria, com semelhança, marcador Provisório e revisão administrativa.
- Permissões aplicadas no servidor e âmbito por fila/departamento/categoria/subcategoria.

## Operador simples

### O que vê e consulta

O operador vê apenas os espaços e registos permitidos pelo perfil, âmbito ou relação direta. “Minhas” é um filtro de conveniência; não substitui as regras de segurança. Pode abrir uma tarefa para consultar descrição, classificação, prioridade, responsável, SLA, comentários, anexos, ligações e histórico acessível.

### Criar e pesquisar

Quando tem permissão de criação/escrita, pode criar uma tarefa no espaço autorizado, indicar título, descrição, prioridade, classificação e contexto disponível. Deve pesquisar antes por palavras do título, referência, matrícula ou classificação para reduzir duplicados.

### Estados

Os estados atuais incluem: **Planeada**, **Nova**, **Em execução**, **Execução delegada**, **A aguardar**, **Execução concluída**, **Pronta para validação**, **Fechada**, **Cancelada** e **Sem ação necessária**. Registos antigos podem conservar estados legacy, apresentados com etiqueta própria.

### Anexos e limites

Pode consultar e ligar documentos quando a ação e o objeto estiverem autorizados. Não deve carregar dados pessoais desnecessários, ficheiros executáveis ou anexos fora do contexto. A captura transversal “Tirar fotografia” ainda não está disponível; encontra-se em implementação separada.

O operador simples não administra catálogos, SLA, permissões, executores elegíveis, regras de atribuição nem reabre/fecha trabalho fora das permissões concedidas.

## Executor

### Receber ou assumir trabalho

O trabalho pode chegar atribuído a si, a uma equipa ou “Por assumir”. **Assumir** só aparece para utilizadores elegíveis e com `service_desk.assume`. A atribuição e reatribuição ficam auditadas. Não contorne a elegibilidade pedindo alterações manuais de dados.

### Executar, checklist e SLA

1. Confirme contexto, classificação, prioridade, responsável e prazos.
2. Inicie a execução no estado adequado.
3. Se existir fluxo guiado, conclua os passos e evidências exigidos. O editor genérico de modelos/checklists visto nos mockups ainda não está disponível.
4. Registe primeira resposta quando aplicável; ela para o respetivo relógio de SLA.
5. Use **A aguardar** apenas com motivo e alvo corretos. A pausa de SLA depende da política configurada.
6. Registe bloqueios, retrabalho e decisões em comentário ou ação própria, sem apagar histórico.

### Comentários, anexos e ligações

Comentários devem explicar o que mudou, quem aguarda e qual o próximo passo. Anexos devem ser ligados à tarefa e, quando necessário, também à entidade de domínio por relações autorizadas. Uma tarefa de processo deve manter ligação bidirecional ao processo/fase, não uma descrição solta.

### Conclusão

Use **Execução concluída** quando terminou a sua parte e **Pronta para validação** quando é exigida validação. **Fechada** é o encerramento final. Antes de concluir, confirme checklist, evidências, pendências, SLA e ligações. Se faltar um requisito obrigatório, registe o motivo; não force o fecho.

## Supervisor

### Triagem e atribuição

O supervisor valida tipo, hierarquia, prioridade, impacto e responsável. “Outro” exige descrição e revisão; registos históricos “Por classificar” não devem ser convertidos automaticamente. Atribua apenas executores elegíveis e mantenha explícita a diferença entre executor, equipa e supervisor.

### Prioridade, SLA e escalamento

- Prioridades disponíveis: Baixa, Normal, Alta e Urgente, conforme a superfície.
- Reveja primeira resposta, resolução, aviso e política de pausa.
- Escale por pedido de ajuda/decisão quando a responsabilidade operacional não muda.
- Reatribua quando a execução muda, deixando motivo auditável.
- Não use prioridade urgente para compensar falta de planeamento sem registar o desvio.

### Validação, reabertura e auditoria

Na validação, confirme resultado, evidências e comunicação ao requerente. Uma reabertura deve indicar motivo e conservar o fecho anterior no histórico. Use eventos de atribuição/SLA, comentários e histórico para reconstruir decisões; a UI não deve ser a única evidência.

## Implementador/parametrizador

### Estruturas e classificações

- Reutilize `Task`, `TaskComment`, `TaskDocument`, `TaskHistory`, eventos de atribuição/SLA e participantes.
- Parametrize Fila, Departamento, Categoria e Subcategoria na Administração; preserve códigos técnicos e histórico.
- Configure tipos de ticket, políticas, supervisores, executores, defaults de origem e SLA.
- Não crie um catálogo paralelo para um módulo que possa usar a classificação comum.

### Modelos, processos e versões

- Recorrências: configure modelos que criam ocorrências normais; execute `scripts/generate_recurring_tasks.py` por scheduler controlado.
- Fluxos guiados atuais são leves/estáticos. O editor visual genérico de modelos, conjuntos e sequências existe apenas em mockup.
- Processos complexos pertencem ao Centro de Processos; a Oficina já possui modelos/versionamento próprios. Preserve snapshots usados por processos existentes.

### Permissões

Separe leitura, criação, assumir, atribuir, atualizar, responder, concluir, gerir SLA e administrar classificações. Confirme sempre o gate no servidor e o âmbito `RoleWorkScope`. Teste utilizadores sem permissão, fora de âmbito, elegíveis e não elegíveis.

### Automações, testes, publicação e reversão

1. Desenvolva em branch/worktree isolada.
2. Faça migrações aditivas; confirme um único head Alembic.
3. Teste criação, leitura, âmbito, atribuição, assumir, espera/pausa SLA, conclusão, reabertura, comentários, anexos e idempotência.
4. Execute `py_compile`, Ruff aplicável, testes focados e `git diff --check`.
5. Em staging, aplique Alembic e bootstrap idempotente duas vezes; faça QA desktop/mobile.
6. Publique apenas após aprovação e plano de reversão. Downgrade não deve apagar histórico; quando não for seguro, reverta a aplicação e mantenha o schema aditivo.

## Planeado/em implementação — não disponível agora

- Ação transversal “Tirar fotografia”: **em execução**.
- Editor visual de modelos/checklists/conjuntos/sequências: **apenas mockup**.
- Construtor de Fluxos: **apenas mockup**.
- Programa **Gestão Diária e Performance Operacional**: **planeado**. Poderá usar eventos, capacidade, Plano Operacional Diário, relatórios e passagem de turno, mas nenhuma destas áreas está disponível atualmente.

## Referências

- `docs/ADMIN_PERMISSION_MATRIX.md`
- `docs/TASK_RECURRENCE_OPERATIONS.md`
- `docs/MODELO_CENTRO_TAREFAS_DECISOES.md`
- `docs/INVENTARIO_EVOLUCAO_RECENTE_2026-08-21.md`
