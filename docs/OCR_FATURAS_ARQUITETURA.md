# OCR de faturas por template

## Separação de responsabilidades

O OCR de faturas é uma etapa de **extração e validação técnica**. Não altera o estado,
a classificação, o arquivo ou a validação operacional de `Document`. O motor recebe
texto produzido por qualquer fornecedor de OCR e devolve dados estruturados; a decisão
operacional continua no fluxo documental existente.

## Identificação e templates

1. O fornecedor é identificado exclusivamente pelo NIF normalizado (nove algarismos).
2. O registo inicial contém Filinto Mota (`500115966`) e Gamobar (`500112967`).
3. Cada execução recebe uma chave de layout estável, formada pelo fornecedor e por uma
   impressão digital dos cabeçalhos. Assim, layouts diferentes do mesmo NIF não são
   validados em conjunto.
4. Um ecrã/repositório de validação deve agrupar por `supplier_tax_id + layout`, guardar
   exemplos, resultado extraído, falhas comunicadas, reprocessamentos e a confirmação
   humana do template. Essa confirmação nunca equivale a aprovar o documento.

## Contrato de dados

`InvoiceOCRResult` inclui apenas campos encontrados, linhas normalizadas e avisos. Os
valores monetários e quantitativos usam `Decimal` desde a leitura; ao serializar para
JSON são strings, evitando perda de precisão. Cada linha admite descrição, referência,
quantidade, unidade, preço unitário, desconto, valor/base e IVA.

O extrator ignora linhas com aparência de texto vertical ou marca de água. No template
Filinto, `FO / O.R.` é deliberadamente excluído de `work_order`: apenas um rótulo
explícito `Folha de obra` pode preencher esse campo.

## Integração seguinte

Persistir a resposta JSON juntamente com o texto OCR original e a versão do motor.
Reprocessar sempre a partir desse texto imutável, criando nova execução em vez de
sobrescrever evidência. A validação do template deve apontar para a execução aprovada e
guardar utilizador/data; falhas devem ser anexadas ao template/layout e permanecer no
histórico.
