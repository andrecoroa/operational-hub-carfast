# Plano de Reset Documental V2

## Objetivo

Garantir um arranque limpo da experiencia v2 sem perder historico sensivel nem apagar ficheiros reais por engano.

Hoje existem duas fontes distintas a alimentar a experiencia documental:

1. `vehicle_document_records` e tabelas auxiliares:
   usados no importador estruturado, nos contadores globais de `/v2-clean/documents` e em parte da ficha documental por viatura.
2. `documents`:
   usados para anexos reais, uploads de oficina e algumas listagens de arquivo por viatura.

Isto significa que um reset parcial pode deixar:

- dashboard global com contadores > 0
- ficha da viatura vazia
- ou o inverso

## Decisao recomendada

Fazer o reset em **2 niveis**, sempre com verificacao previa:

| Nivel | O que limpa | O que preserva | Quando usar |
| --- | --- | --- | --- |
| A. Reset estrutural | `vehicle_document_records`, `vehicle_document_record_tags`, `vehicle_document_alerts`, `vehicle_document_pending_actions`, `vehicle_document_audit_fields` | documentos reais na tabela `documents`, ficheiros fisicos, uploads de oficina | quando queremos repor contadores e imports estruturados da v2 |
| B. Revisao de anexos reais | nada automatico por defeito; apenas listagem e confirmacao manual | tudo | quando queremos decidir se documentos reais criados em testes da v2 devem ficar ou sair |

## O que **nao** deve ser apagado automaticamente

Estes dados devem ficar fora do reset por defeito:

- tabela `documents`
- `document_links`
- `document_events`
- ficheiros em `uploads/vehicle_documents/...`
- documentos ligados a oficina, tarefas, incidentes ou auditorias

Motivo:
um reset cego destes objetos pode quebrar historico de oficina, evidencias ou ligacoes a outros modulos.

## Tabelas afetadas no reset estrutural

| Tabela | Papel |
| --- | --- |
| `vehicle_document_records` | base dos imports estruturados (FO, impros, contratos, etc.) |
| `vehicle_document_record_tags` | classificacoes e etiquetas por registo/documento |
| `vehicle_document_alerts` | alertas manuais do modulo documental |
| `vehicle_document_pending_actions` | pendentes e acoes manuais |
| `vehicle_document_audit_fields` | campos auditados manualmente por viatura |

## Resultado esperado apos reset estrutural

- `/v2-clean/documents` volta a zero nos contadores estruturados
- fichas documentais deixam de mostrar imports estruturados antigos
- permanecem apenas os anexos reais que existirem em `documents`
- timeline documental fica limpa do lado estruturado e pronta para nova importacao validada

## Sequencia segura

1. Correr auditoria de contagens antes do reset
2. Guardar output dessa auditoria
3. Aplicar reset estrutural
4. Confirmar contagens a zero nas tabelas estruturais
5. Rever se existem documentos reais residuais na tabela `documents`
6. Decidir manualmente se esses anexos de teste ficam ou nao

## Script de suporte

O script de suporte fica em:

`scripts/reset_v2_document_module.py`

Funciona assim:

- sem flags: apenas mostra auditoria
- `--vehicle-id N`: audita ou limpa apenas uma viatura
- `--apply`: executa o reset estrutural

Exemplos:

```powershell
python scripts/reset_v2_document_module.py
python scripts/reset_v2_document_module.py --vehicle-id 247
python scripts/reset_v2_document_module.py --apply
python scripts/reset_v2_document_module.py --vehicle-id 247 --apply
```

## Criterio de decisao final

Se a v2 vai arrancar do zero, a recomendacao e:

- aplicar reset estrutural global
- manter anexos reais fora do reset automatico
- so depois importar novamente contratos, FO, impros e restantes listagens validadas

Isto da-nos uma base limpa sem destruir o que ainda pode ser necessario rever manualmente.
