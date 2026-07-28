# Diagnósticos documentais

## Problema reproduzido

Antes desta alteração, a ficha da viatura:

- criava todos os documentos diretos como `workshop_other`;
- misturava diagnósticos, faturas e restantes documentos na mesma lista;
- mostrava apenas os 20 registos mais recentes e usava o tamanho dessa lista como contagem;
- associava entradas do centro documental por igualdade literal da matrícula.

Assim, um relatório com `Unit 485`, uma matrícula escrita sem hífen ou um documento já existente
como o `#1522` podia ficar sem `vehicle_id`, fora da ficha e fora da contagem apresentada.

O teste `test_backfill_reproduces_and_repairs_unit_485_document_1522` reproduz esse cenário.

## Modelo

`documents` continua a guardar o ficheiro e os campos documentais comuns. A nova tabela
`diagnostic_documents` é uma extensão um-para-um e guarda exclusivamente:

- tipo e estado do diagnóstico;
- estado e método de associação à viatura;
- número do relatório, equipamento, série, técnico e quilometragem;
- matrícula e VIN detetados;
- estado, confiança, texto e payload do OCR;
- estado, notas, autor e data de validação.

Faturas não recebem esta extensão. A recuperação legada exclui explicitamente tipologias de fatura,
nota de crédito, recibo e comprovativo de pagamento.

## Tipologias identificadas

O inventário `diagnostic_reorganization_report/plano_movimentos.csv` existente no repositório de
trabalho mostrou as seguintes famílias:

- relatório de diagnóstico do veículo;
- códigos de avaria / teste global;
- informações de manutenção / BSI;
- informações de lubrificação do motor;
- reset / reposição de manutenção;
- síntese de diagnóstico;
- plano / limiar de manutenção;
- identificação de calculador;
- filtro de partículas / regeneração;
- campanhas técnicas do construtor;
- bateria / sistema de carga;
- plano de manutenção do construtor;
- programação / inicialização de componentes;
- sistema AdBlue / SCR;
- ficha técnica de lubrificante;
- verificação em portal técnico;
- documentação técnica do construtor;
- vídeo, imagem e documento auxiliar de diagnóstico;
- outro diagnóstico.

O catálogo fica centralizado em `app/services/diagnostic_documents.py` para poder crescer sem
alterar a tabela de faturas.

## Associação

A associação automática usa, por ordem:

1. `vehicle_id` já confirmado;
2. matrícula normalizada (ignora espaços, hífenes e pontos);
3. VIN detetado;
4. referência inequívoca `Unit N` ou `Unidade N` nos metadados do documento.

Conflitos não são resolvidos silenciosamente. A ficha da viatura também permite associar
manualmente um documento existente pelo ID.

## Atualização e recuperação legada

Aplicar a migração:

```powershell
python -m alembic upgrade head
```

Pré-visualizar a recuperação:

```powershell
python scripts/backfill_diagnostic_documents.py
```

Aplicar a recuperação:

```powershell
python scripts/backfill_diagnostic_documents.py --apply
```

O comando sem `--apply` termina sempre com rollback e apresenta apenas as contagens.
