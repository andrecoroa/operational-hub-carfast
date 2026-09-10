# Gate de captura — streaming anonimizado antes da transferência

## Estado e fronteira

Este artefacto é **um piloto de oito tabelas**, não um ensaio integral das 163 relações
inventariadas. Não permite concluir que a migração integral está validada.

Esta preparação é executável apenas com fixtures. Não abriu ligação à produção, não usou
segredos produtivos e não transmitiu dados reais ou derivados. O exportador final só poderá
correr dentro do serviço de produção, numa transação `READ ONLY`, com cursor server-side e
lotes limitados. Cada linha é transformada e validada antes de chegar a `stdout`; o HMAC usa
uma chave aleatória apenas em memória do processo, nunca registada, exportada ou persistida.

O transporte recomendado é um pipe autenticado e sem ficheiro intermédio entre duas sessões
Render CLI. Os bytes atravessam a memória do host do operador, mas o procedimento não cria
ficheiros, redirecionamentos, logs ou artifacts. `stdout` contém exclusivamente JSONL ASCII e
`stderr` nunca contém linhas ou valores. O pipe fornece backpressure: a leitura do cursor para quando o consumidor deixa de
aceitar bytes. No destino, o consumidor volta a validar cada envelope antes de inserir. O
PostgreSQL local corre no persistent disk e aceita apenas Unix socket; `listen_addresses` fica
vazio e não existe porta PostgreSQL pública. O PostgreSQL gerido temporário permanece sintético.

## Mapa exato do slice preparado

| Tabela | Preservado | Sintético estável no mesmo run | Omitido/substituído |
|---|---|---|---|
| `users` | `active` | `id`→`R-user-*`; `name`, `email` | `password_hash`; restantes campos fora do SELECT |
| `stock_suppliers` | `active` | `id`→`R-supplier-*`; nome/legal/NIF/registo/contactos | moradas, postal/cidade, website, notas |
| `vehicles` | estados canónicos, `active` | `id`→`R-vehicle-*`; `plate`, `vin` | notas e projeções pessoais/cliente/localização |
| `tasks` | estado canónico | `id`→`R-task-*`; FKs por namespace (`user`, `team`, `task`); cliente/contactos/plate | título, descrição e restantes textos livres |
| `management_processes` | estado/prioridade de allowlist fechada | `id`→`R-management_process-*`; `process_type_id`→namespace; fase→`Category-*`; referência/plate/pessoas | título, detalhe pendente, JSON bruto |
| `email_messages` | — | `id`→`R-email_message-*`; `thread_id`→`R-email_thread-*`; sender | recipients/cc/bcc, assunto, corpos, headers, snapshots |
| `documents` | estado de allowlist fechada | `id` e FKs por namespace; tipo/classificação→`Category-*`; sender/plate/pessoas | nomes/paths/keys/URL/hash/tamanho reais; fixture apenas se havia objeto lógico, com métricas/hash exclusivamente sintéticos |
| `audit_log` | `entity_type` de allowlist fechada | `id`, `user_id`; ação→`Category-*`; `entity_id` usa namespace derivado de `entity_type`, ou `null` se não mapeável | detalhe e before/after JSON |

Nenhum ID produtivo cru é exportado. A igualdade e as FKs são preservadas por HMAC efémero
namespaced, sem tabela de correspondência. Qualquer tabela ou campo não classificado falha fechado. O destino rejeita campos com nomes de
texto/OCR/body/path/secret/token e padrões reconhecíveis de email real, NIF, telefone ou matrícula.
O relatório final contém apenas contagens agregadas por tabela, bytes, hashes sintéticos, deltas e
estado de reconciliação.

## Testes e reversão

- estabilidade das substituições dentro do run sem mapping persistido;
- ausência de IDs crus e preservação referencial por surrogate namespaced;
- remoção de texto livre, OCR, corpos de email e localizações de documentos;
- rejeição de tabelas/campos desconhecidos e identificadores reconhecíveis;
- iteração JSONL incremental, limite de 1 MB por linha e validação dupla;
- preflight apenas de schema (`information_schema`) antes de abrir qualquer cursor de linhas;
  o contrato versionado v1 valida família PostgreSQL e nullability de todas as colunas do SELECT;
- contratos por campo para tipo, nullability, comprimento, intervalos e valores canónicos;
- staging tipado por tabela com PK/FK, contagens, joins e órfãos reconciliados;
- bloqueio process-level de sockets IP instalado antes de ler `stdin`;
- adversariais para IDs/threads/entity IDs crus, canonical adulterado, nested payload,
  Unicode/texto livre, socket IP, pipe quebrado e rollback transacional;
- DSN destino limitada a Unix socket e base terminada em `_test`;
- container proposto com PostgreSQL 17 em `/var/data/postgresql`, socket
  `/var/run/postgresql`, sem listener TCP.

Rollback antes da captura: remover branch/serviço Docker proposto. Durante futuro ensaio:
interromper o pipe reverte a transação de ingestão e não deixa staging parcial; eliminar a base local descarta o
dataset anonimizado. O PostgreSQL gerido não é tocado.

## Autorização verificável e replay

O exportador já não aceita um identificador meramente não vazio. Exige um token HMAC assinado
com payload fechado: versão, scope `pilot-eight-table`, origem, destino, `issued_at`, `expires_at`
e nonce. Rejeita assinatura inválida, endpoint/escopo errado, emissão futura, expiração, duração
superior a 15 minutos e reutilização do nonce durante a vida do processo. Token e chave nunca
são impressos.

A cache em memória impede replay no processo que detém o cursor, mas não consegue garantir uso
único absoluto entre processos/restarts. Essa garantia requer um ledger partilhado com operação
atómica `consume-if-unused`. O mecanismo mínimo recomendado é um registo de autorização separado
dos dados operacionais, com hash do nonce, expiração e estado consumido, consultado/consumido antes
do cursor. Criar esse ledger ou permitir uma escrita técnica na origem é um gate futuro específico;
não foi criado neste PR. Sem esse gate, a garantia é: token de 15 minutos, ligado a endpoints e
one-off único sem restart, mais replay bloqueado dentro do processo.

## Execução real na origem — gate obrigatório

Produção está em `58a150c7`; esse artefacto não contém o exportador deste PR. Por isso, o comando
antigo que invocava diretamente `python -m scripts.export_anonymized_dataset` no serviço produtivo
não é executável nem está aprovado.

O percurso recomendado é um **one-off source-side efémero construído exatamente do commit revisto**:

1. imagem/one-off imutável no mesmo ambiente/região da origem, sem URL e sem volume;
2. ligação PostgreSQL exclusivamente read-only disponibilizada no runtime de origem, sem exportar a
   credencial para operador ou destino;
3. token e chave de autorização injetados apenas nesse processo; integrações/jobs totalmente off;
4. `stdout` JSONL ligado diretamente ao receptor e `stderr` operacional sem dados;
5. processo termina após um uso, sem restart, filesystem efémero eliminado.

O CI prova este desenho apenas com fixtures: constrói a imagem do commit, executa autorização,
transformação antes do pipe, staging relacional e rollback. Não prova acesso à produção. Para o
ensaio real é necessária autorização separada para **criar/executar o one-off no Render ligado
read-only à BD produtiva e injetar os dois segredos efémeros**. Isso implica execução de código no
ambiente de produção, configuração/segredo temporário e possivelmente custo; é o gate exato onde
este trabalho para.

Uma alternativa sem novo serviço seria enviar um bundle revisto por stdin para uma sessão shell do
serviço produtivo e executá-lo em memória. Não é recomendada: tem menor auditabilidade e continua a
ser execução one-off de código em produção, exigindo a mesma autorização explícita. Nenhum destes
percursos foi executado.

## Comando conceptual — NÃO executável/não executar sem nova autorização

Após auditoria do SELECT e criação de um `CAPTURE_AUTHORIZATION_ID` explícito, o operador usará
um pipe equivalente a:

```text
render one-off <IMAGEM_EXATA_DO_COMMIT_REVISTO> -- \
  env CAPTURE_AUTHORIZATION_ID=<TOKEN_ASSINADO_EFEMERO> \
      CAPTURE_AUTHORIZATION_KEY=<CHAVE_EFEMERA> \
      CAPTURE_SOURCE_SERVICE=<ORIGEM_APROVADA> \
      CAPTURE_DESTINATION_SERVICE=<DESTINO_APROVADO> \
  python -m scripts.export_anonymized_dataset --read-only --batch-size 250 \
| render ssh <DESTINO_TEMPORARIO_APROVADO> -- \
  python -m scripts.receive_anonymized_stream \
    --dsn 'postgresql://postgres@/carfast_anonymized_test?host=/var/run/postgresql'
```

Antes desse comando faltam autorização de captura, revisão das queries/colunas contra o schema
real, mecanismo para impedir outbound do processo que contém dados anonimizados e restrição da
regra externa herdada pela BD gerida. Nenhum destes gates é implicitamente aprovado aqui.

O texto acima é uma topologia, não sintaxe Render confirmada nem autorização operacional. O token
será emitido no momento e não colocado numa linha de comandos histórica; a representação `env` é
apenas conceptual. Esta preparação não criou token, chave, ledger, serviço ou ligação real.
