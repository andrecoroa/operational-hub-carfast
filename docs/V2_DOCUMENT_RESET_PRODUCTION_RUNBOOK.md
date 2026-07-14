# Runbook de auditoria e reset documental v2

## Objetivo

Usar a ferramenta de auditoria/reset documental da v2 no ambiente certo, sem apagar anexos reais nem criar perdas acidentais.

## Ferramenta

Script:

`scripts/reset_v2_document_module.py`

Documentação base:

`docs/V2_DOCUMENT_RESET_PLAN.md`

## O que a ferramenta faz

- audita contagens do módulo documental v2
- separa dados estruturados de documentos reais
- limpa apenas tabelas `vehicle_document_*` quando usamos `--apply`
- não apaga a tabela `documents`
- não apaga ficheiros físicos

## Pré-condições

Antes de correr no ambiente alvo:

1. confirmar que a `DATABASE_URL` aponta para a base da v2 correta
2. garantir que ninguém está a importar documentos ao mesmo tempo
3. guardar snapshot da auditoria antes do reset

## Verificação do alvo antes de aplicar

O script mostra sempre no topo:

- `env`
- `driver`
- `host`
- `db`

Exemplo esperado:

```text
Base ativa: env=production | driver=postgresql+psycopg | host=... | db=...
```

Se o alvo mostrado não for a base certa da v2, parar logo e não usar `--apply`.

## Auditoria sem alterações

### Global

```powershell
python scripts/reset_v2_document_module.py --snapshot-file exports/document-reset-audit-global.json
```

### Só uma viatura

```powershell
python scripts/reset_v2_document_module.py --vehicle-id 247 --snapshot-file exports/document-reset-audit-vehicle-247.json
```

## Reset estrutural

### Global

```powershell
python scripts/reset_v2_document_module.py --apply --snapshot-file exports/document-reset-apply-global.json
```

### Só uma viatura

```powershell
python scripts/reset_v2_document_module.py --vehicle-id 247 --apply --snapshot-file exports/document-reset-apply-vehicle-247.json
```

## Como interpretar o output

### Se queremos arranque limpo da v2

Depois do reset estrutural:

- `vehicle_document_records = 0`
- `vehicle_document_record_tags = 0`
- `vehicle_document_alerts = 0`
- `vehicle_document_pending_actions = 0`
- `vehicle_document_audit_fields = 0`

Pode continuar a existir:

- `documents_total > 0`
- `documents_workshop_v2_clean > 0`

Isso significa apenas que ainda há anexos reais preservados fora do reset estrutural.

## Pós-reset: validações visuais

Depois do reset, confirmar:

1. `/v2-clean/documents`
   - contadores estruturados a zero
2. `/v2-clean/fleet/{id}/documents`
   - sem linhas estruturadas antigas
3. dashboard documental
   - sem números residuais de imports antigos

## O que fazer se ainda aparecerem documentos

Se os contadores estruturados ficaram a zero mas a ficha documental ainda mostra conteúdo:

- esse conteúdo vem da tabela `documents`
- não é falha do reset
- é um conjunto de anexos reais preservados

Nesse caso, a decisão passa a ser funcional:

- manter esses anexos
- ou criar um segundo passo de limpeza só para documentos v2 de teste

Esse segundo passo deve ser sempre revisto em separado.

## Regra de segurança

Não correr um reset que mexa na tabela `documents` sem:

1. snapshot da auditoria
2. confirmação de quais documentos são só testes
3. confirmação de que não existem ligações úteis a oficina, tarefas, incidentes ou auditorias

## Resultado esperado

No fim, ficamos com:

- v2 documental estrutural limpa
- arquivo real preservado
- base pronta para nova importação validada
