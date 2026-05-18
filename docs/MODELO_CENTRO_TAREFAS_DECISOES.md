# Modelo do Centro de Tarefas

Documento de trabalho para guardar as decisões acordadas antes da implementação definitiva.

## Princípio base

O Centro de Tarefas deve ser organizado por espaços de trabalho, não apenas por filtros.

Estrutura de referência:

```text
Centro de Tarefas
├── Operacional
│   ├── Tarefas
│   └── Registos rápidos
├── Oficina
│   ├── Tarefas da oficina
│   ├── Registos rápidos
│   └── Auditoria
├── Gestão
│   ├── Tarefas
│   └── Registos rápidos
└── Administração
    ├── Tarefas
    └── Registos rápidos
```

A Oficina deve continuar a ser um módulo próprio. As tarefas da oficina devem usar o mesmo motor comum de tarefas, mas com visibilidade configurável: podem aparecer no Centro de Tarefas e no módulo Oficina, ou apenas no módulo Oficina.

Estrutura funcional da Oficina:

```text
Oficina
├── Processos
├── Tarefas da oficina
├── Registos rápidos
├── Auditoria
├── Evidências
└── Histórico técnico
```

## Registo rápido operacional

O registo rápido deve ser uma entrada leve para capturar situações sem obrigar a criar logo uma tarefa completa.

Tipos iniciais:

- Pedido
- Informação / Comunicação
- Anomalia / Incidente
- Reclamação
- Outro

O registo rápido pode evoluir para:

- tarefa operacional;
- incidente formal;
- processo de oficina;
- comunicação arquivada;
- sem ação necessária.

Também deve existir sempre a possibilidade de criar uma tarefa diretamente, para evitar trabalho duplicado quando já se sabe que existe execução concreta.

Os tipos de registo rápido devem poder evoluir por espaço de trabalho. A fase atual deixa a base preparada para que Operacional, Oficina, Gestão e Administração tenham listas próprias de tipos.

Na Oficina, a auditoria fica no fim da grelha para não se misturar com tarefas técnicas correntes e registos rápidos.

Implementação atual:

- Operacional: tarefas + registos rápidos;
- Oficina: tarefas da oficina + registos rápidos + auditoria;
- Gestão: tarefas + registos rápidos;
- Administração: tarefas + registos rápidos.

Cada centro tem URL próprio, tipos próprios e criação separada, mas usa o mesmo motor técnico para evitar duplicação.

## Responsabilidade e intervenção

Responsabilidade de execução e pedido de intervenção são conceitos separados.

Uma tarefa pode ter:

- equipa/fila responsável;
- responsável individual;
- supervisor;
- pedido de ajuda;
- pedido de decisão;
- notificados.

O SLA pertence sempre à equipa/fila ou pessoa responsável pela execução.

Um pedido de decisão não transfere a responsabilidade nem o SLA para o decisor.

## Pirâmide de atribuição

Regra de referência:

```text
Um utilizador pode atribuir responsabilidade a si próprio, a perfis do mesmo nível ou a perfis abaixo.
Um utilizador não pode atribuir responsabilidade de execução a perfis superiores.
```

Perfis superiores podem ser chamados através de:

- pedido de ajuda;
- pedido de decisão;
- pedido de validação;
- supervisão;
- notificação.

Pedidos de decisão devem exigir:

- contextualização obrigatória;
- sugestão de resolução obrigatória;
- prazo desejado opcional;
- anexos/evidências, quando existirem.

## Tarefas entre módulos

Modelo preferido:

```text
Tarefa mãe no módulo de origem
└── Tarefa filha / intervenção no módulo de destino
```

Isto permite que o módulo de destino execute a sua parte sem perder o contexto da tarefa principal.

Transferência total de tarefa só deve ser usada quando a tarefa foi criada no módulo errado ou deixa de pertencer ao módulo original.

## Subtarefas

Tarefas de gestão ou implementação podem ter subtarefas.

Exemplo:

```text
Implementar tarifas e extras no Rentway
├── Rever tabela atual
├── Criar estrutura de extras
├── Testar contratos
└── Atualizar manual
```

A tarefa mãe deve mostrar progresso, prazo global e contexto. As subtarefas devem ter responsáveis, prazos, prioridades e estados próprios.

## Tarefas recorrentes

Tarefa recorrente deve ser um modelo/agendamento que cria tarefas normais.

Não deve ser uma tarefa que nunca fecha.

Campos futuros:

- título base;
- descrição base;
- espaço de trabalho;
- equipa/fila;
- responsável opcional;
- prioridade;
- periodicidade;
- data de início;
- fim opcional;
- prazo relativo;
- criar com antecedência.

Criar e gerir recorrências deve exigir permissão específica.

## Decisões ainda por fechar

- nomes finais dos espaços no menu;
- se Oficina aparece também dentro do Centro de Tarefas ou apenas dentro do módulo Oficina;
- níveis concretos da pirâmide de atribuição;
- permissões para criar recorrências;
- campos definitivos do pedido de decisão;
- regras de dashboards para tarefas mãe e subtarefas.
