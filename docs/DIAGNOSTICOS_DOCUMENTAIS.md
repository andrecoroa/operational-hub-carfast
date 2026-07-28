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

Cada processamento de um PDF cria ainda uma linha imutável em `diagnostic_extractions`. Esta tabela
mantém o histórico de versões do leitor e não substitui a extração anterior. Guarda:

- máquina e código de família indicados pelo nome e confirmados pelo conteúdo;
- SHA-256, nome, número de páginas e metadados internos do PDF;
- texto nativo e texto reconstruído por página;
- palavras com coordenadas por página, para permitir reparsers futuros;
- texto, palavras, caixas e confiança do Tesseract quando o OCR é necessário;
- campos normalizados para operação e todos os campos dinâmicos, unidades, ajudas e códigos DTC;
- versão do extrator e do parser, método, confiança e avisos.

O PDF original continua a ser a fonte canónica e não é alterado.

## Corpus Autel e Stellantis

A pasta `Doc. originais` fornecida foi auditada em modo de leitura:

- 805 PDFs, 211 007 292 bytes;
- 364 nomes com origem Autel (`A_`);
- 441 nomes com origem Stellantis/DiagBox (`S_`);
- 20 códigos de família distintos, incluindo variantes como `ILM`, `IM`, `LD`, `PM`, `RDV`,
  `TEL`, `ILDE`, `PLM`, `SB`, `CAM` e `RVC0`;
- formatos de data completos, sem hora e `sem_data`.

Foram processadas duas amostras por combinação máquina/família (45 PDFs). Todas tinham camada de
texto, mas o leitor usa as coordenadas do PDF porque o formato Stellantis junta palavras na extração
linear. As tabelas Autel são lidas pela sequência numerada; as Stellantis são reconstruídas pelas
colunas Descrição, Valor, Unidade e Ajuda. Os códigos de família são sempre guardados literalmente,
mesmo quando ainda não existe significado funcional confirmado.

O número de medições não faz parte do esquema. Cada relatório pode ter zero ou muitas observações,
permitindo que a mesma máquina apresente campos diferentes conforme motor, ECU ou versão do
software.

## Estratégia OCR

O processamento segue esta ordem:

1. texto nativo do PDF;
2. reconstrução espacial com `pdfplumber`, incluindo palavras e coordenadas;
3. renderização da página a 300 dpi e Tesseract `por+eng` apenas se a página não tiver texto
   suficiente, ou quando a extração for forçada.

O fallback foi verificado também com um PDF apenas de imagem: recuperou VIN com espaçamento
imperfeito e código DTC. As localizações dos executáveis podem ser configuradas com
`CARFAST_PDFTOPPM` e `CARFAST_TESSERACT`.

O botão **Extrair PDF** na ficha do documento executa o leitor. A vista diária mostra os campos
normalizados; todas as medições, ajudas, DTC e metadados ficam num bloco recolhido
**Dados técnicos completos da extração**.

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

## Auditoria dos leitores

O analisador nunca altera os originais:

```powershell
python scripts/analyze_diagnostic_corpus.py "C:\caminho\Doc. originais" `
  --sample-per-family 2 `
  --output tmp\diagnostic_corpus_analysis.json
```

Adicionar `--all` processa todos os PDFs. Adicionar `--ocr` ativa o Tesseract apenas nas páginas que
não tenham texto nativo suficiente.
