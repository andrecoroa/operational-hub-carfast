# Comparação CarFast v1 vs v2 - decisões para amanhã

## Objetivo

Este documento serve para comparar o que existia na v1 com a base atual da v2 e separar:

- essencial para piloto;
- importante para próxima fase;
- legado que deve ficar apenas como referência;
- decisões que devem ser tomadas antes de implementar.

## Estado atual da v2

Já existe base limpa com:

- autenticação;
- utilizadores e perfis;
- auditoria;
- árvore de unidades/áreas autorizadas;
- Dashboard simples;
- Frota permanente;
- importação de frota Rentway;
- Gestão de Tarefas;
- Oficina simplificada;
- evidências de oficina;
- feedback do piloto centralizado;
- deploy Render com PostgreSQL.

## Módulos relevantes encontrados na v1

| Área v1 | Existe na v2? | Decisão recomendada |
| --- | --- | --- |
| Centro de tarefas | Parcial | Reaproveitar conceito, não estrutura. A v2 deve evoluir o módulo `Gestão de Tarefas`. |
| Oficina/processos | Parcial | Manter fluxo simples da v2 e ir buscar apenas campos essenciais validados na v1. |
| Incidentes de frota | Não completo | Implementar como submódulo ligado a Frota/Oficina/Tarefas. Prioritário. |
| Anexos/evidências | Parcial | Manter fora da BD. Preparar para SharePoint/OneDrive. |
| Gestão documental | Não completo | Criar módulo transversal para classificar e arquivar documentos no 365. |
| Importações Rentway | Parcial | Prioridade: frota já existe. Depois impros, folhas de obra, faturas, sinistros e ARs. |
| Auditoria/timeline viatura | Parcial | Evoluir v2 para timeline por viatura com tarefas, oficina, incidentes e importações. |
| Stock | Não | Adiar, salvo necessidade operacional imediata. |
| Venda de usados | Não | Isolar. Não misturar com piloto oficina/tarefas. |
| Conhecimento/manual | Não | Recriar mais tarde como módulo próprio simples. |
| Protocolos/checklists | Não completo | Não copiar já. Reaproveitar como regras configuráveis quando o fluxo de oficina estabilizar. |
| Diagnósticos PDF | Não | Adiar até haver processo de oficina estabilizado. |

## Essenciais para piloto imediato

### 1. Gestão de Tarefas

Essencial:

- criação manual;
- filtros por estado, categoria, origem, responsável e estação;
- pesquisa por cliente, matrícula, reserva e contrato;
- responsável;
- prazo;
- comentários;
- histórico;
- pedir ajuda;
- relatar experiência.

Não implementar ainda:

- e-mail automático;
- WhatsApp automático;
- Webex automático;
- regras complexas de classificação;
- escalamentos automáticos.

Motivo: primeiro validar se a equipa entende o fluxo manual.

### 2. Frota

Essencial:

- listar por `Unit Nr` Rentway decrescente;
- pesquisar por matrícula, Unit Nr, VIN, marca e modelo;
- detalhe da viatura;
- notas internas;
- tarefas ligadas à viatura;
- histórico mínimo.

Próxima melhoria:

- filtros por estado operacional, lifecycle e estação;
- vista de timeline da viatura.

### 3. Oficina

Essencial:

- abrir processo por entrada ou marcação;
- estados simples;
- decisão;
- evidências foto/vídeo por anomalia;
- comentários/notas;
- fecho;
- folha de fecho.

Próxima melhoria:

- ligar incidentes ao processo;
- permitir criar tarefa a partir de decisão/estado;
- melhorar timeline.

## Tarefas em massa

### Opção A - Importação Excel

Mais rápida para piloto.

Permite importar linhas com:

- assunto;
- descrição;
- origem;
- categoria;
- prioridade;
- responsável;
- estação;
- matrícula;
- reserva;
- contrato;
- prazo.

Regras:

- não criar duplicados se existir `external_source_id`;
- se não existir ID externo, gerar chave por origem + assunto + matrícula/reserva/contrato;
- erros devem ir para `import_errors`;
- tarefas criadas devem ter histórico/auditoria.

Recomendação: implementar primeiro.

### Opção B - Ligação a Microsoft Lists

Mais escalável, mas exige decisão técnica.

Pode servir para:

- receber listas operacionais já usadas pela equipa;
- sincronizar pedidos;
- criar tarefas sem depender de ficheiros;
- manter origem externa.

Riscos:

- autenticação Microsoft/Graph;
- permissões;
- mapeamento de colunas;
- sincronização e duplicados;
- dependência de configuração externa.

Recomendação: desenhar já o modelo de ligação, mas implementar só depois do piloto manual/Excel.

## Gestão documental e arquivo 365

Objetivo: criar um mecanismo único para receber, classificar e arquivar documentos de qualquer módulo.

O documento pode chegar por:

- upload manual;
- importação;
- e-mail;
- Microsoft Lists;
- SharePoint/OneDrive;
- futuro conector externo.

### Princípio base

A app não deve guardar ficheiros binários na base de dados.

A app deve guardar:

- metadados;
- classificação;
- entidade associada;
- URL ou storage key no 365;
- histórico;
- auditoria;
- estado do arquivo.

### Fluxo recomendado

1. Documento entra em `Caixa de entrada documental`.
2. Utilizador confirma ou altera:
   - tipologia;
   - entidade associada;
   - matrícula;
   - cliente;
   - reserva;
   - contrato;
   - processo;
   - incidente;
   - tarefa;
   - fornecedor;
   - mês/ano;
   - confidencialidade;
   - retenção.
3. App propõe pasta de destino.
4. Documento é arquivado no 365.
5. App guarda o registo documental.
6. App adiciona evento ao histórico da entidade.

### Tipologias iniciais

- Contrato;
- Reserva;
- Fatura cliente;
- Fatura fornecedor;
- Orçamento;
- Folha de obra;
- Diagnóstico;
- Foto de evidência;
- Vídeo de evidência;
- Áudio/nota de voz;
- Sinistro;
- Accident report;
- Comunicação cliente;
- Comunicação fornecedor;
- Documento de viatura;
- Documento interno;
- Outro.

### Estruturas de pastas possíveis

#### Opção A - Por matrícula

```text
CarFast/
  Viaturas/
    AA-00-AA/
      Oficina/
      Incidentes/
      Contratos/
      Faturas/
      Evidências/
```

Vantagem: excelente para histórico permanente da viatura.

Risco: documentos sem matrícula precisam de outra entrada.

#### Opção B - Por ano/mês

```text
CarFast/
  Documentos/
    2026/
      05/
        Faturas fornecedores/
        Comunicações/
        Importações/
```

Vantagem: simples para arquivo cronológico e financeiro.

Risco: pior para consultar histórico por viatura.

#### Opção C - Híbrida recomendada

```text
CarFast/
  Viaturas/
    AA-00-AA/
      2026/
        05/
          Oficina/
          Incidentes/
          Contratos/
          Evidências/

  Operação/
    2026/
      05/
        Tarefas/
        Comunicações/
        Sem matrícula/

  Financeiro/
    2026/
      05/
        Faturas fornecedores/
        Faturas clientes/
```

Recomendação: usar opção híbrida.

Regra:

- se houver matrícula, arquivar primeiro por viatura;
- se não houver matrícula, arquivar por área + ano/mês;
- se houver documento financeiro, permitir também área financeira;
- a app mantém a ligação lógica, mesmo que a pasta física esteja organizada de outra forma.

### Modelo de dados recomendado

Tabela `documents`:

- id;
- title;
- document_type;
- classification;
- source;
- original_filename;
- mime_type;
- file_size;
- storage_provider;
- storage_url;
- storage_key;
- folder_path;
- status;
- confidentiality_level;
- retention_policy;
- vehicle_id;
- task_id;
- workshop_process_id;
- incident_id;
- customer_id;
- supplier_id;
- reservation_number;
- contract_number;
- plate;
- document_date;
- archived_at;
- archived_by_id;
- created_by_id;
- created_at;
- updated_at.

Tabela `document_events`:

- id;
- document_id;
- action;
- old_value;
- new_value;
- user_id;
- created_at.

Tabela `document_links` opcional:

- document_id;
- entity_type;
- entity_id.

Usar `document_links` se um documento puder estar ligado a várias entidades.

### Estados documentais

- Recebido;
- Por classificar;
- Classificado;
- Arquivado;
- Com erro de arquivo;
- Duplicado;
- Ignorado;
- Substituído.

### Regras anti-duplicação

Comparar:

- ID externo, quando existir;
- nome original;
- tamanho;
- hash do ficheiro;
- matrícula;
- data do documento;
- tipo documental.

No piloto, podemos começar sem hash, mas o modelo deve prever.

### Integração 365

Fase inicial:

- guardar URL manual do SharePoint/OneDrive;
- gerar caminho sugerido;
- utilizador arquiva manualmente.

Fase seguinte:

- criar pasta automaticamente;
- mover/upload do ficheiro;
- guardar URL final;
- validar permissões.

Fase futura:

- Graph API;
- leitura de caixa documental;
- classificação assistida;
- OCR/transcrição.

## Incidentes no processo de manutenção

Recomendação: criar um submódulo `Incidentes` ligado a:

- viatura;
- processo de oficina;
- tarefa;
- evidências;
- histórico.

Campos mínimos:

- tipo/categoria;
- descrição;
- gravidade;
- estado;
- viatura;
- processo associado;
- responsável;
- data/hora;
- evidências;
- decisão/ação tomada.

Evidências:

- foto;
- vídeo;
- documento;
- link SharePoint/OneDrive.

Regra:

- ficheiros binários não entram na base de dados;
- guardar apenas metadados e URL/storage key;
- registar no histórico quem anexou e quando.

## Explicação por voz em incidentes

Boa ideia para operação real, mas deve entrar por fases.

### Fase 1

Campo de texto `descrição`.

### Fase 2

Anexo de áudio gravado fora da BD, com:

- tipo `audio`;
- URL/storage key;
- duração;
- autor;
- data/hora.

### Fase 3

Transcrição automática para texto.

Recomendação: preparar o modelo de dados para áudio já quando criarmos `incidents`, mas só implementar gravação/transcrição depois do piloto básico.

## Decisões para amanhã

1. Confirmar se `Unit Nr` Rentway deve ser sempre a ordenação principal da Frota.
2. Decidir se o primeiro importador de tarefas em massa será Excel.
3. Decidir se Microsoft Lists fica como integração futura ou prioridade imediata.
4. Confirmar campos mínimos de incidente.
5. Decidir se incidente nasce dentro da Oficina, da Frota ou da Gestão de Tarefas.
6. Confirmar se áudio entra já como anexo manual ou fica só preparado no modelo.

## Recomendação prática

Próxima implementação curta:

1. Filtros adicionais na Frota.
2. Importação Excel de tarefas.
3. Modelo inicial de incidentes com evidências.
4. Botão `Criar incidente` dentro do processo de oficina.
5. Ligação automática incidente -> tarefa de follow-up.
