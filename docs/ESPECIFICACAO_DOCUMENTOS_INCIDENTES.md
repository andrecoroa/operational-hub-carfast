# Especificação inicial - Documentos e Incidentes

## Objetivo

Preparar dois módulos transversais:

- Gestão Documental;
- Incidentes.

Ambos devem servir Oficina, Frota, Gestão de Tarefas e futuras importações.

## Gestão Documental

### Responsabilidade do módulo

Receber, classificar, associar e arquivar documentos operacionais.

Não deve substituir o SharePoint/OneDrive. Deve organizar o processo e manter rastreabilidade.

### Entidades principais

#### Document

Representa um documento conhecido pela app.

Campos mínimos:

- título;
- tipo documental;
- classificação;
- origem;
- nome original;
- mime type;
- tamanho;
- provider de armazenamento;
- URL;
- caminho de pasta;
- estado;
- confidencialidade;
- matrícula;
- viatura;
- tarefa;
- processo de oficina;
- incidente;
- reserva;
- contrato;
- cliente;
- fornecedor;
- data do documento;
- data de arquivo;
- utilizador que arquivou.

#### DocumentEvent

Histórico do documento.

Eventos:

- recebido;
- classificado;
- associado;
- pasta sugerida;
- arquivado;
- erro;
- marcado duplicado;
- ignorado.

#### DocumentLink

Ligação flexível entre documento e qualquer entidade.

Usar quando um documento precisar de estar associado a mais do que uma entidade.

### Caixa de entrada documental

Vista operacional:

- documentos por classificar;
- documentos com erro;
- documentos arquivados hoje;
- documentos duplicados;
- pesquisa por matrícula, contrato, reserva, cliente, fornecedor ou título.

### Sugestão de pasta

Regra inicial:

```text
Se existir matrícula:
CarFast/Viaturas/{MATRICULA}/{ANO}/{MES}/{TIPO}/

Se não existir matrícula:
CarFast/{AREA}/{ANO}/{MES}/{TIPO}/
```

Exemplos:

```text
CarFast/Viaturas/AA-00-AA/2026/05/Oficina/
CarFast/Viaturas/AA-00-AA/2026/05/Incidentes/
CarFast/Operação/2026/05/Comunicações/
CarFast/Financeiro/2026/05/Faturas fornecedores/
```

### Fases de implementação

#### Fase 1

- criar modelo de dados;
- criar registo manual de documento;
- guardar URL SharePoint/OneDrive manual;
- associar a matrícula/tarefa/processo/incidente;
- mostrar documentos no detalhe da entidade.

#### Fase 2

- caixa de entrada documental;
- sugestão automática de pasta;
- classificação por tipologia;
- histórico documental.

#### Fase 3

- integração Microsoft Graph;
- criação automática de pastas;
- upload/move para SharePoint;
- validação de permissões.

#### Fase 4

- OCR;
- classificação assistida;
- transcrição de áudio/vídeo;
- regras de retenção.

## Incidentes

### Responsabilidade do módulo

Registar situações anormais que precisam de rastreabilidade, decisão ou follow-up.

Pode nascer em:

- processo de oficina;
- viatura;
- tarefa;
- importação Rentway;
- comunicação de cliente;
- comunicação interna.

### Campos mínimos

- título;
- descrição;
- tipo;
- categoria;
- gravidade;
- estado;
- viatura;
- processo de oficina;
- tarefa;
- origem;
- responsável;
- data/hora do incidente;
- local/estação;
- decisão;
- ação tomada;
- data de resolução;
- data de fecho.

### Estados iniciais

- Novo;
- Em análise;
- Em tratamento;
- A aguardar decisão;
- A aguardar fornecedor;
- Resolvido;
- Fechado;
- Sem ação necessária.

### Evidências

Tipos:

- foto;
- vídeo;
- documento;
- áudio;
- link externo.

Na base de dados guardar apenas:

- tipo;
- descrição;
- URL/storage key;
- provider;
- autor;
- data/hora;
- metadados.

### Voz

Fase inicial:

- permitir anexar áudio externo como evidência.

Fase seguinte:

- gravar áudio no browser;
- guardar no 365;
- transcrever para texto;
- usar transcrição como descrição ou comentário.

### Ligação com tarefas

Regra recomendada:

- incidente pode criar tarefa de follow-up;
- tarefa fica ligada ao incidente;
- fecho da tarefa não fecha automaticamente o incidente;
- fecho do incidente deve pedir decisão/ação tomada.

### Ligação com oficina

Dentro do processo de oficina:

- botão `Criar incidente`;
- incidente herda viatura, processo, estação e contexto;
- evidências do incidente aparecem também no processo;
- incidente aparece no histórico da viatura.

## Decisão recomendada para primeira implementação

Implementar primeiro:

1. Modelo `documents`;
2. Modelo `incidents`;
3. Registo manual de incidente dentro de processo de oficina;
4. Evidência do incidente por URL SharePoint/OneDrive;
5. Criação opcional de tarefa de follow-up.

Adiar:

- upload direto para 365;
- gravação de voz no browser;
- transcrição automática;
- classificação automática por IA;
- integração Microsoft Lists.

## MVP iniciado

Já ficou implementado o primeiro passo operacional:

- criação de incidente dentro do processo de oficina;
- ligação automática à viatura e ao processo;
- categoria, tipo e gravidade;
- evidência por URL externo;
- suporte a evidência de foto, vídeo, documento, link e áudio/nota de voz;
- registo em notas do processo;
- eventos internos do incidente;
- auditoria.

Ainda falta:

- página própria de detalhe do incidente;
- alteração de estado do incidente;
- criação opcional de tarefa de follow-up;
- ligação ao arquivo documental;
- upload/gravação direta para 365;
- gravação de voz no browser.
