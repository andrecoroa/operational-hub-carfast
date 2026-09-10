# Frota — tranche mínima do vídeo

## Referência e âmbito

- Vídeo: `frota.mp4`
- SHA256: `F0BE025DAF293EDECF55C9B190F4193367FC1B00ADA303730FD28CFBD70FCEA4`
- Base canónica: `1579f8bbf4c267f483ce9c45c7ba09a8a65d0473`
- Branch: `codex/fleet-video-minimal`
- Dados: base SQLite descartável, conta e duas viaturas exclusivamente sintéticas.
- Efeitos externos: Email inbound/outbound OFF; sem webhooks, integrações, Green ou dados reais.

## Matriz requisito → prova

| Requisito aprovado | Implementação/prova |
| --- | --- |
| Pesquisa, âmbito e alertas visíveis; restantes filtros recolhidos | `clean_fleet.html`: controlos principais + `Mais filtros`; browser desktop/mobile |
| Ordenação operacional | `sort` server-side validado por allowlist; seletor e cabeçalhos de marca/modelo, estado, cliente, devolução e IPO |
| Cabeçalho fixo | `position: sticky`; read-back browser 1440×731 |
| Preview inline | Uma linha imediatamente abaixo da viatura, abrir/trocar/fechar/Escape/foco/hash; dados operacionais e financeiros existentes |
| Estado Rentway legível | Rótulo traduzido com o código original preservado |
| Alertas diferenciados | `Só com alertas` filtra IPO vencida/próxima; `Sem alertas` permanece discreto |
| Importação com pré-visualização | Fluxo canónico mantido; ausentes listadas como `review_only` e sem mutação |
| Ausentes não são desativadas automaticamente | Teste read-back preserva `active`, `lifecycle_status` e `operational_status` |
| Proposta de Venda/histórico preservados | Nenhum ficheiro/comportamento de Vendas alterado; falha ampliada de Vendas reproduzida igual na base |
| Exportação financeira | Já entregue na base canónica pelo PR #110; esta tranche apenas reutiliza `VehicleFinancialPlan` no preview |
| RBAC | Positivo com permissão e negativo `403` sem `vehicles.read/write`/`admin.manage` |

## Gates

- Focados Frota/visual/financeiro: `40 passed`.
- Suite CI canónica exata: `237 passed`.
- Compile/import: PASS.
- Ruff canónico: PASS.
- Baseline arquitetural: PASS.
- Alembic: head único `fff6ab1c2d3e`.
- Browser 1440×731: sem overflow horizontal, cabeçalho sticky, preview único, troca/fecho/Escape/foco PASS.
- Browser 390×844: sem overflow horizontal, layout em cartões, preview inline legível e ação Fechar PASS.
- Regressão ampliada de Vendas: uma falha de preço (`19300` esperado vs `19100`) reproduzida na base limpa `1579f8bb`; não causada por este diff e não alterada.

## Capturas

- `desktop-1440x731.png`
- `mobile-390x844.png`

## Limites

- Nenhuma importação real executada.
- Nenhuma viatura ausente é desativada automaticamente.
- Não houve schema/migration, alteração RBAC nominal, merge, deploy ou Green.
