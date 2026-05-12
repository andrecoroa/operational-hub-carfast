# Formacao - Processo de Oficina

Este guia descreve um processo completo de oficina para treino da equipa na CarFast v2.
O objetivo e mostrar o caminho simples: abrir processo, acompanhar estados, tomar decisao,
registar notas, fechar e confirmar o historico na viatura.

## Dados de teste

Use uma viatura ja importada em Frota. Para treino, o exemplo usado foi:

- Matricula: BZ81SC
- Marca/modelo: FIAT 600 Hibrido
- VIN: ZFA5FBAT0SJ079652
- KM entrada: 3673
- Motivo: ruido anormal na travagem

## Passo a passo

### 1. Abrir a area Oficina

1. Entrar na aplicacao.
2. No menu lateral, escolher `Oficina`.
3. Confirmar que aparece a pagina de processos de oficina.

Durante o piloto existem dois botoes de apoio:

- `Pedir ajuda`: usar quando houver uma duvida durante a execucao.
- `Relatar experiencia`: usar para indicar dificuldades, melhorias ou algo que correu bem.

Quando usados dentro de um processo, estes registos ficam ligados ao processo de oficina.

### 2. Criar processo

Preencher o formulario de novo processo:

- Viatura: escolher a matricula de teste.
- Titulo: preencher apenas se ja existir um titulo claro.
- Abertura: preencher se a origem ja for conhecida.
- KM entrada: preencher se estiver disponivel.
- Prioridade: ajustar se for relevante.
- Saida prevista: preencher apenas se existir data prevista.
- Nota inicial: `Cliente reporta ruido anormal na travagem.`

Selecionar `Criar processo`.

Resultado esperado:

- o processo fica criado;
- o estado inicial fica em `Abertura`;
- se o titulo ficar vazio, a app usa a primeira linha da nota inicial ou um titulo automatico;
- o processo aparece na lista de Oficina;
- a ficha da viatura passa a mostrar processo de oficina aberto.

### 3. Abrir detalhe do processo

1. Na lista de Oficina, clicar no titulo do processo.
2. Confirmar o resumo:
   - estado;
   - tipo de abertura;
   - prioridade;
   - viatura;
   - KM entrada;
   - saida prevista;
   - nota inicial.

### 4. Passar para Rececao

No bloco `Atualizar estado`:

- Estado: `Rececao`.
- Decisao: `Sem decisao`.
- Nota da decisao: `Viatura recebida e ruido confirmado em teste curto.`

Selecionar `Atualizar fluxo`.

Resultado esperado:

- o estado passa para `Rececao`;
- fica uma nota automatica de alteracao de fluxo.

### 5. Registar diagnostico em nota

No bloco `Adicionar nota`, escrever:

```text
Diagnostico: desgaste irregular em pastilhas dianteiras.
```

Selecionar `Gravar nota`.

Resultado esperado:

- a nota aparece no historico de notas do processo.

### 6. Registar evidencia de anomalia

No bloco `Registar evidencia`, preencher:

- Fase: `Diagnostico`.
- Tipo: `Foto`.
- Categoria: `Desgaste irregular`.
- Estado: `Registada`.
- Link externo: link do ficheiro em SharePoint/OneDrive/storage, se ja existir.
- Descricao: preencher apenas se houver detalhe util.

Selecionar `Gravar evidencia`.

Resultado esperado:

- a evidencia fica ligada ao processo de oficina;
- a evidencia fica ligada a viatura;
- o ficheiro nao fica guardado na base de dados, apenas o link externo;
- e criada uma nota automatica no historico do processo.

Regra de treino:

- sempre que houver algo anormal, visivel, audivel ou operacional, registar evidencia antes de decidir ou fechar.

### 7. Tomar decisao

No bloco `Atualizar estado`:

- Estado: `Aguardar material`.
- Decisao: `Encomendar material`.
- Nota da decisao: `Encomendar discos e pastilhas dianteiras.`

Selecionar `Atualizar fluxo`.

Resultado esperado:

- o processo fica com estado `Aguardar material`;
- a decisao fica como `Encomendar material`;
- a nota da decisao fica visivel no resumo.

### 8. Registar execucao

Quando o material estiver disponivel, adicionar nota:

```text
Material recebido. Intervencao concluida e teste de estrada OK.
```

Resultado esperado:

- a execucao fica registada no processo.

### 9. Fechar processo

No bloco `Atualizar estado`:

- Estado: `Fechado`.
- Decisao: manter `Encomendar material`.
- Nota da decisao: `Processo fechado apos validacao.`

Selecionar `Atualizar fluxo`.

Resultado esperado:

- o processo fica fechado;
- deixa de aparecer como processo aberto na lista principal de Oficina;
- continua acessivel por historico quando for criada a vista de arquivo.

### 10. Registar nota final na viatura

Na ficha da viatura, adicionar nota interna:

```text
Processo de oficina concluido. Viatura apta para operacao.
```

Resultado esperado:

- a viatura fica com historico interno associado;
- a decisao e notas do processo continuam separadas no processo de oficina.

### 11. Criar tarefa de follow-up

Na ficha da viatura, criar tarefa:

- Titulo: `Confirmar arquivo da intervencao`.
- Prioridade: `Normal`.
- Descricao: `Validar que a documentacao final ficou registada.`

Resultado esperado:

- a tarefa fica ligada a viatura;
- aparece no quadro de Tarefas;
- ainda nao e criada automaticamente por estado, por decisao consciente nesta fase.

## Resultado final esperado

No final do treino deve existir:

- 1 processo de oficina fechado;
- varias notas no processo;
- pelo menos 1 evidencia de anomalia, se existiu algo fora do normal;
- 1 decisao registada;
- 1 nota final na viatura;
- 1 tarefa de follow-up ligada a viatura;
- perguntas ou relatos de experiencia registados, se existirem;
- auditoria das acoes principais.

## Regras de utilizacao

- Nao criar processo duplicado para a mesma situacao.
- Usar `Aguardar material` quando a intervencao depende de pecas.
- Usar `Aguardar analise` quando ainda falta avaliacao tecnica.
- Usar `Sem intervencao necessaria` quando houve analise mas nao ha necessidade de atuar.
- Registar foto, video, documento ou nota tecnica sempre que existir uma anomalia.
- No piloto, nao forcar preenchimento de campos que ainda nao tenham informacao disponivel.
- Usar `Pedir ajuda` e `Relatar experiencia` durante a execucao real, nao apenas no fim.
- Fechar apenas quando o resultado final estiver claro.
