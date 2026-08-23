# Gate de captura — streaming anonimizado antes da transferência

## Estado e fronteira

Esta preparação é executável apenas com fixtures. Não abriu ligação à produção, não usou
segredos produtivos e não transmitiu dados reais ou derivados. O exportador final só poderá
correr dentro do serviço de produção, numa transação `READ ONLY`, com cursor server-side e
lotes limitados. Cada linha é transformada e validada antes de chegar a `stdout`; o HMAC usa
uma chave aleatória apenas em memória do processo, nunca registada, exportada ou persistida.

O transporte recomendado é um pipe autenticado e sem ficheiro intermédio entre duas sessões
Render CLI. O pipe fornece backpressure: a leitura do cursor para quando o consumidor deixa de
aceitar bytes. No destino, o consumidor volta a validar cada envelope antes de inserir. O
PostgreSQL local corre no persistent disk e aceita apenas Unix socket; `listen_addresses` fica
vazio e não existe porta PostgreSQL pública. O PostgreSQL gerido temporário permanece sintético.

## Mapa exato do slice preparado

| Tabela | Preservado | Sintético estável no mesmo run | Omitido/substituído |
|---|---|---|---|
| `users` | `id`, `active` | `name`, `email` | `password_hash`; restantes campos fora do SELECT |
| `stock_suppliers` | `id`, `active` | `name`, `legal_name`, `tax_id`, `registration_number`, contactos | moradas, postal/cidade, website, notas |
| `vehicles` | `id`, estados, `active` | `plate`, `vin` | notas e projeções pessoais/cliente/localização |
| `tasks` | `id`, estado e FKs técnicas de utilizador/equipa/tarefa | cliente/contactos/plate | título, descrição e restantes textos livres |
| `management_processes` | `id`, `process_type_id`, estado/fase/prioridade | referência, plate, cliente/condutor | título, detalhe pendente, JSON bruto |
| `email_messages` | `id`, `thread_id` | sender | recipients/cc/bcc, assunto, corpos, headers, snapshots de template |
| `documents` | `id`, estado/tipo/classificação e FKs técnicas | sender, plate, cliente/fornecedor | nomes/paths/keys/URL/hash reais e texto; substituídos por contagem, bytes e SHA-256 de fixture sintética |
| `audit_log` | `id`, `user_id`, ação, tipo/id técnico | — | detalhe e before/after JSON |

Qualquer tabela ou campo não classificado falha fechado. O destino rejeita campos com nomes de
texto/OCR/body/path/secret/token e padrões reconhecíveis de email real, NIF, telefone ou matrícula.
O relatório final contém apenas contagens agregadas por tabela, bytes, hashes sintéticos, deltas e
estado de reconciliação.

## Testes e reversão

- estabilidade das substituições dentro do run sem mapping persistido;
- preservação de IDs/FKs explicitamente autorizados;
- remoção de texto livre, OCR, corpos de email e localizações de documentos;
- rejeição de tabelas/campos desconhecidos e identificadores reconhecíveis;
- iteração JSONL incremental, limite de 1 MB por linha e validação dupla;
- DSN destino limitada a Unix socket/loopback e base terminada em `_test`;
- container proposto com PostgreSQL 17 em `/var/data/postgresql`, socket
  `/var/run/postgresql`, sem listener TCP.

Rollback antes da captura: remover branch/serviço Docker proposto. Durante futuro ensaio:
interromper o pipe reverte a transação de ingestão atual; eliminar a tabela/base local descarta o
dataset anonimizado. O PostgreSQL gerido não é tocado.

## Comando final — NÃO executar sem nova autorização

Após auditoria do SELECT e criação de um `CAPTURE_AUTHORIZATION_ID` explícito, o operador usará
um pipe equivalente a:

```text
render ssh <SERVICO_PRODUCAO_CONFIRMADO> -- \
  env CAPTURE_AUTHORIZATION_ID=<ID_APROVADO> \
  python -m scripts.export_anonymized_dataset --read-only --batch-size 250 \
| render ssh srv-da56eogu01pc73e5nnh0 -- \
  python -m scripts.receive_anonymized_stream \
    --dsn 'postgresql:///carfast_anonymized_test?host=/var/run/postgresql'
```

Antes desse comando faltam autorização de captura, revisão das queries/colunas contra o schema
real, mecanismo para impedir outbound do processo que contém dados anonimizados e restrição da
regra externa herdada pela BD gerida. Nenhum destes gates é implicitamente aprovado aqui.
