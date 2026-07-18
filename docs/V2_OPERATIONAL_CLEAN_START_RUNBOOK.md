# Arranque limpo da V2

## Objetivo

Limpar apenas os dados operacionais criados na experiência V2 para começar testes reais com base limpa, sem apagar:

- frota
- utilizadores
- permissões
- configurações
- dados base de viatura importados
- ficheiros físicos no disco

## Ferramenta

```powershell
python scripts/reset_v2_operational_data.py
```

Por defeito a ferramenta corre em `dry-run`: mostra o que seria apagado e não altera a base.

## O que limpa

Quando executada com confirmação, limpa:

- processos de oficina V2 (`workshop_phased_*`)
- relatórios técnicos, leituras e verificações ligados aos processos V2
- tarefas/problemas criados pela V2 (`source=v2_clean` ou `workshop_v2_clean`)
- documentos de importação estruturada V2
- documentos/anexos de teste criados pela V2
- registos estruturados documentais (`vehicle_document_records`)
- tags, alertas, pendentes e campos auditados documentais

## O que não limpa

Não toca em:

- `vehicles`
- `users`
- `roles`
- `settings`
- tabelas de importação da frota
- documentos de origem antiga que não estejam marcados como V2
- ficheiros físicos no arquivo

## Auditoria local

```powershell
$env:DATABASE_URL='sqlite+pysqlite:///local-v2-test.db'
python scripts/reset_v2_operational_data.py --snapshot-file exports/v2-reset-dry-run-local.json
```

## Auditoria em produção

Usar a `DATABASE_URL` da base Render/Postgres correta.

```powershell
python scripts/reset_v2_operational_data.py --snapshot-file exports/v2-reset-dry-run-production.json
```

Antes de executar, confirmar no output:

- `app_env`
- `driver`
- `host`
- `database`
- contagens por módulo

## Execução

Só executar depois de validar a auditoria:

```powershell
python scripts/reset_v2_operational_data.py --execute --yes-i-understand --snapshot-file exports/v2-reset-executed-production.json
```

Em Postgres remoto/produção, a ferramenta exige uma confirmação adicional:

```powershell
python scripts/reset_v2_operational_data.py --execute --yes-i-understand --yes-production --snapshot-file exports/v2-reset-executed-production.json
```

## Opções de preservação

Se quisermos limpar por fases:

```powershell
python scripts/reset_v2_operational_data.py --preserve-documents
python scripts/reset_v2_operational_data.py --preserve-workshop
python scripts/reset_v2_operational_data.py --preserve-tasks
```

Estas opções também funcionam com `--execute`.

## Validação após reset

Confirmar:

1. `/v2-clean/workshop`
   - sem processos antigos de teste
2. `/v2-clean/processes`
   - sem processos V2 residuais
3. `/v2-clean/documents`
   - contadores estruturados a zero
4. `/v2-clean/fleet/{id}/documents`
   - sem importações antigas, sem fontes de teste e timeline vazia

## Regra de segurança

Se o dry-run mostrar dados que não reconhecemos como V2/teste, não executar. Primeiro revemos a origem e ajustamos o filtro.
