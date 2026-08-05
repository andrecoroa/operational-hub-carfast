# Operação das tarefas recorrentes

Os modelos recorrentes são administrados em `/v2-clean/tasks/recurring` por utilizadores com
`tasks.recurring.manage`. A criação/edição também valida a permissão de criação na fila escolhida e
as regras correntes de hierarquia para o responsável.

## Execução atual

Cada visita ao Centro de Tarefas tenta a geração, no máximo, uma vez a cada cinco minutos por
processo web. A tentativa faz apenas uma consulta indexada a modelos ativos e vencidos. A página de
modelos também processa ocorrências vencidas imediatamente.

Para uma cadência independente do tráfego, agendar o comando idempotente:

```powershell
python scripts/generate_recurring_tasks.py
```

Uma execução por minuto é suficiente. O comando pode ser repetido ou sobrepor-se: em PostgreSQL,
os modelos vencidos são obtidos com `FOR UPDATE SKIP LOCKED`; além disso, a base de dados impõe uma
chave única `(template_id, scheduled_for)`. Assim, reinícios, concorrência e duas instâncias do
comando não produzem a mesma ocorrência duas vezes.

As horas são introduzidas e calculadas em `Europe/Lisbon`, incluindo mudanças de hora legal, e são
persistidas como instantes timezone-aware. O modelo guarda a próxima e a última execução. A
ocorrência guarda o instante planeado e a tarefa normal criada, e ambas as alterações produzem
auditoria.

## Evolução futura

Quando existir infraestrutura de jobs, mover a chamada do comando para um worker dedicado (por
exemplo, um cron job Render ou uma fila de jobs). O serviço `generate_due_recurring_tasks` já é a
fronteira reutilizável; a evolução não exige alterar modelos, páginas ou regras de idempotência.
Depois de monitorizar o worker, a tentativa oportunística pode ser desativada.
