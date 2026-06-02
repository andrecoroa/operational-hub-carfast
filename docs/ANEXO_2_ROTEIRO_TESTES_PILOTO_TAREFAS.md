# Anexo 2 - Roteiro dos testes piloto Gestão de Tarefas

## Teste 1 - Criar uma tarefa operacional

Objetivo: perceber se a criação de tarefas é clara e se os campos fazem sentido.

Passos:

1. Entrar na aplicação.
2. Abrir `Gestão de Tarefas`.
3. Criar uma nova tarefa.
4. Preencher apenas a informação disponível.
5. Gravar a tarefa.

Campos sugeridos:

- origem;
- assunto;
- categoria;
- subcategoria, se fizer sentido;
- cliente;
- contacto;
- e-mail;
- telefone;
- matrícula;
- reserva;
- contrato;
- estação;
- responsável;
- data limite;
- departamento/fila;
- descrição.

No fim, responder:

```text
Foi fácil criar a tarefa?
O formulário tem campos a mais?
Faltou algum campo importante?
A linguagem usada é clara?
```

## Teste 2 - Gerir o backlog

Objetivo: perceber se a lista, os indicadores e os filtros ajudam a encontrar trabalho.

Passos:

1. Abrir `Gestão de Tarefas`.
2. Observar os indicadores:
   - abertas;
   - sem responsável;
   - vencidas;
   - limite hoje.
3. Clicar em `Sem responsável`.
4. Clicar em `Vencidas`.
5. Usar a pesquisa para procurar por:
   - cliente;
   - matrícula;
   - reserva;
   - contrato.
6. Experimentar filtrar por:
   - estado;
   - categoria;
   - origem;
   - responsável;
   - estação.

No fim, responder:

```text
Os indicadores ajudam?
Os filtros são fáceis de usar?
Encontraste rapidamente uma tarefa?
Falta algum filtro?
A lista mostra informação suficiente?
```

## Teste 3 - Acompanhar e fechar uma tarefa

Objetivo: validar se a tarefa funciona como um caso operacional.

Passos:

1. Abrir uma tarefa.
2. Confirmar se o resumo é claro:
   - origem;
   - estado;
   - categoria;
   - cliente;
   - matrícula;
   - reserva/contrato;
   - responsável;
   - prazo.
3. Atualizar o estado da tarefa.
4. Alterar ou confirmar:
   - responsável;
   - data limite;
   - categoria;
   - estação;
   - departamento/fila.
5. Adicionar um comentário interno.
6. Fechar a tarefa ou marcar como `Sem ação necessária`, se fizer sentido.
7. Confirmar se o histórico ficou compreensível.

No fim, responder:

```text
O detalhe da tarefa é claro?
Os estados fazem sentido?
Percebe-se onde atualizar e onde comentar?
O histórico ajuda?
O que mudarias?
```

## Resultado esperado

No final dos três testes, queremos perceber:

- se a Gestão de Tarefas pode funcionar como centro operacional;
- se os campos são suficientes;
- se existem campos a mais;
- se os estados fazem sentido;
- se os filtros ajudam a gerir o trabalho;
- se o detalhe da tarefa parece um caso operacional;
- se a equipa consegue usar sem explicação prévia;
- que melhorias devem ser feitas antes de integrar e-mail, WhatsApp, Webex ou Rentway.
