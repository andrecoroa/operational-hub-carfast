# Unificação do histórico de Oficina

## Objetivo

Reunir os processos do modelo antigo e do modelo atual na Oficina atual, com uma sequência
global `OF-000001`, preservando referências, datas, documentos, tarefas e evidência de stock.

Esta evolução não altera os identificadores técnicos existentes e não move nem apaga ficheiros.

## Fase 1 — inventário sem escrita

Aplicar primeiro as migrações numa cópia PostgreSQL isolada e executar:

```bash
python -m scripts.preview_workshop_history_unification --output-dir output/workshop-history
```

O comando produz:

- `workshop_history_unification_plan.json`: plano integral legível por máquina;
- `workshop_history_reference_map.csv`: mapa para validação operacional;
- `WORKSHOP_HISTORY_UNIFICATION_REPORT.md`: resumo e contagens.

O campo `write_operations` tem de permanecer em `0`. Esta fase não cria processos, não altera
referências e não produz movimentos de stock.

## Critérios de revisão

Antes de autorizar a aplicação, confirmar todos os itens com `issues`, em especial:

- `possible_duplicate_same_vehicle_and_date`: dois registos da mesma viatura no mesmo dia;
- `legacy_non_terminal_status_requires_review`: processo antigo que não estava terminal;
- `missing_opened_at_used_fallback` ou `missing_opened_on_used_created_at`: data reconstruída;
- `missing_vehicle`: processo sem associação segura à viatura;
- `duplicate_existing_canonical_sequence`: conflito numa sequência já atribuída.

Uma coincidência de viatura e data é apenas um sinal de revisão. Nunca provoca fusão automática.

## Regras de preservação

- O `id` técnico de um processo existente não muda.
- A referência anterior é guardada como alias pesquisável.
- Um registo antigo fica ligado ao processo unificado por origem e ID, tornando a importação
  repetível sem duplicação.
- Processos históricos entram fechados ou cancelados e ficam apenas consultáveis.
- Documentos mantêm os caminhos e URLs atuais.
- Movimentos de stock existentes são ligados como histórico; nunca são reproduzidos.
- Datas originais são mantidas. Datas em falta ficam assinaladas para decisão humana.

## Barreiras antes de produção

1. Base de dados PostgreSQL isolada e cópia dos ficheiros de arquivo.
2. Uma única cabeça Alembic confirmada por `python scripts/check_migration_heads.py`.
3. Pré-visualização sem casos bloqueantes por decidir.
4. Validação por amostragem de viaturas com processos antigos, atuais, documentos e stock.
5. Reconciliação das contagens antes/depois por estado e por origem.
6. Plano de reversão validado antes de qualquer escrita.
7. Autorização explícita para migração e, separadamente, para deploy em produção.

## Fases seguintes

Depois da aprovação do mapa, implementar uma aplicação transacional e idempotente do plano numa
cópia de ensaio. Só após essa execução ser reconciliada deve ser preparado o corte de produção.
