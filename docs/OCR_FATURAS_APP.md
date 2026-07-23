# OCR de faturas — espaço de trabalho da app

Este documento concentra as decisões e o trabalho do OCR de faturas no
Operational Hub. O objetivo é manter este tema separado dos restantes fluxos da
aplicação e transformar cada decisão tomada neste espaço numa alteração
rastreável.

## Objetivo

Permitir que um utilizador envie uma fatura, obtenha uma proposta de dados
extraídos automaticamente e confirme ou corrija esses dados antes de os integrar
na operação. O OCR é um apoio à introdução de dados; nunca deve publicar uma
fatura sem validação humana.

## Âmbito do MVP

O primeiro incremento deve aceitar PDF, PNG e JPEG e extrair, quando presentes:

- fornecedor, NIF do fornecedor e número da fatura;
- data de emissão e data de vencimento;
- valor sem IVA, IVA e total;
- moeda;
- matrícula, número de contrato ou outra referência CarFast;
- linhas da fatura, com descrição, quantidade, preço e taxa de IVA;
- texto integral reconhecido e nível de confiança por campo.

Ficam fora do MVP a aprovação contabilística automática, pagamentos, lançamento
direto em software externo e aprendizagem automática a partir das correções.

## Fluxo funcional

1. O utilizador envia o ficheiro na área **Faturas · OCR**.
2. A app valida tipo, tamanho, duplicados e presença de malware antes de
   disponibilizar o documento ao motor de OCR.
3. O processamento decorre em segundo plano e apresenta os estados `recebida`,
   `a_processar`, `para_validar`, `validada` ou `com_erro`.
4. A app mostra o documento e a proposta de extração lado a lado, destacando
   campos ausentes ou com baixa confiança.
5. O utilizador corrige os dados e confirma a fatura.
6. A app guarda os valores originais, os valores confirmados, o utilizador e a
   data da alteração para auditoria.

Uma falha do fornecedor de OCR não deve perder o ficheiro nem obrigar a um novo
envio. O utilizador deve poder repetir o processamento.

## Princípios de implementação

- **Revisão humana obrigatória:** confiança elevada reduz trabalho, mas não
  substitui a confirmação.
- **Fornecedor substituível:** o domínio da app recebe um resultado normalizado;
  detalhes de Azure AI Document Intelligence, AWS Textract, Google Document AI
  ou outro motor ficam num adaptador.
- **Processamento assíncrono:** uploads e consultas não devem ficar bloqueados
  enquanto o OCR decorre.
- **Idempotência:** o hash do ficheiro e uma chave de processamento impedem
  submissões acidentais repetidas.
- **Rastreabilidade:** guardar resposta original do motor, versão do modelo,
  confiança, correções e transições de estado.
- **Privacidade:** limitar acesso pelas permissões de documentos, cifrar dados em
  trânsito e em repouso e definir retenção explícita para ficheiros e respostas.
- **Sem confiança em texto reconhecido:** o resultado do OCR é conteúdo não
  confiável e não pode executar instruções, construir SQL ou alterar permissões.

## Proposta de componentes

### Dados

- `invoice_ocr_jobs`: documento, estado, fornecedor, modelo, tentativas, erro e
  timestamps de início/fim;
- `invoice_extractions`: resposta normalizada, resposta original protegida,
  confiança global e versão do esquema;
- `invoice_fields`: campo, valor proposto, valor confirmado, confiança e origem;
- `invoice_line_items`: linhas propostas e confirmadas;
- `invoice_ocr_events`: transições, repetição, validação e utilizador responsável.

O registo deve referenciar `documents.id`, reutilizando o arquivo documental
existente em vez de criar um segundo repositório de ficheiros.

### Serviços

- adaptador comum `InvoiceOcrProvider`;
- serviço de submissão e deduplicação;
- worker de extração e normalização;
- regras de validação (NIF, datas, totais e soma das linhas);
- serviço de confirmação e auditoria.

### Interface e API

- lista de faturas com filtros por estado, fornecedor, data e matrícula;
- formulário de upload;
- ecrã de revisão lado a lado;
- ações para repetir, corrigir, validar e consultar histórico;
- endpoints protegidos para criar e consultar trabalhos, guardar correções e
  confirmar resultados.

## Critérios de aceitação do primeiro incremento

- um utilizador autorizado consegue enviar um formato suportado;
- o pedido recebe um identificador e muda de estado sem bloquear a interface;
- um erro é visível e pode ser repetido sem reenviar o ficheiro;
- campos e linhas extraídos podem ser corrigidos antes da confirmação;
- nenhuma extração é tratada como validada sem uma ação explícita;
- todas as correções e transições ficam auditadas;
- um utilizador sem permissão de documentos não consegue ver nem alterar uma
  fatura;
- testes cobrem submissão, duplicados, sucesso, erro, repetição, autorização e
  confirmação.

## Decisões necessárias antes de implementar

1. Qual é o motor de OCR preferido e em que região devem permanecer os dados?
2. Qual é o volume esperado de faturas por dia e o tamanho máximo de cada
   ficheiro?
3. Que formatos e idiomas aparecem nas faturas reais?
4. A matrícula deve associar automaticamente a fatura a uma viatura ou apenas
   sugerir a associação?
5. Que destino recebe uma fatura depois da validação (arquivo, tarefa, oficina,
   contabilidade ou integração externa)?
6. Qual é a política de retenção do ficheiro original e da resposta bruta do
   fornecedor?
7. Que perfis podem enviar, corrigir, validar e reprocessar faturas?

## Sequência recomendada

1. Recolher um conjunto anonimizado e representativo de faturas e responder às
   decisões em aberto.
2. Fazer uma prova técnica curta com dois motores e medir cobertura, qualidade,
   latência e custo nos mesmos documentos.
3. Fechar o esquema normalizado e o contrato do adaptador.
4. Implementar persistência, estados, permissões e auditoria.
5. Ligar o fornecedor escolhido através do worker.
6. Construir a revisão humana e executar um piloto controlado antes de qualquer
   integração contabilística.

