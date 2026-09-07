# Fecho da auditoria técnica de faturas

## Resultado pretendido

O processo termina quando todas as faturas técnicas existentes têm uma natureza definida, ficheiro físico reconciliado, extração utilizável ou exceção explícita, serviços versionados e rastreabilidade suficiente para reproduzir qualquer decisão. Uma exceção aberta é um resultado válido; um documento silenciosamente ignorado não é.

## Princípios obrigatórios

- O PDF, o texto extraído e as classificações anteriores são imutáveis como evidência.
- Sugestões automáticas nunca substituem decisões humanas.
- Serviço, componente, motivo, cobertura e alerta documental são dimensões diferentes.
- Uma visita contém acontecimentos; um acontecimento contém linhas de peças, mão de obra, fluidos e consumíveis.
- Indicadores contam `service_event_id`, nunca linhas.
- Reprocessamento é sempre precedido por simulação sem escrita e relatório de impacto.

## Fluxo operacional

1. **Inventário no Render**
   - reconciliar registo, caminho físico e hash;
   - identificar ficheiros ausentes e hashes em falta;
   - recolher o último estado de extração e as classificações guardadas.
2. **Definição do universo**
   - `technical`: fatura operacional candidata ao histórico da viatura;
   - `excluded`: stock, IUC, financeiro, venda ou outro documento não técnico;
   - `review`: natureza ainda não confirmada.
3. **Guardrails do classificador**
   - bloquear falsos positivos de Vidros, Calços, Revisão e Pneus;
   - mover Telecarregamento para diagnóstico/eletrónica;
   - tratar Sinistro como motivo e Garantia como cobertura;
   - manter operações auxiliares fora da contagem técnica.
4. **Simulação sem escrita**
   - executar `python scripts/audit_invoices_dry_run.py`;
   - no PostgreSQL, a própria transação é marcada `READ ONLY`;
   - o relatório declara `write_operations: 0` e inclui proposta, evidência e bloqueios por documento.
5. **Fila de exceções**
   - prioridade P0: conflitos matrícula/VIN, duplicados fortes e documentos misturados;
   - prioridade P1: faturas técnicas sem ficheiro, sem linhas ou com extração falhada;
   - prioridade P2: quilometragem regressiva, linhas contaminadas e campos incompletos;
   - prioridade P3: classificação semântica pendente sem risco documental.
6. **Reprocessamento controlado**
   - trabalhar por fornecedor e layout;
   - começar pelas verdadeiras falhas, nunca por todos os documentos;
   - comparar antes/depois e bloquear divergências;
   - aplicar apenas após aprovação expressa do relatório de impacto.
7. **Produtos finais**
   - tabela geral de documentos;
   - tabelas por tipologia de serviço;
   - intervalos por data e quilometragem;
   - fornecedores e valores;
   - duplicados e inconsistências;
   - possíveis garantias;
   - FO sem fatura e faturas sem FO;
   - comparação entre manutenções faturadas e diagnósticos.

## Taxonomia v1.1

A v1.1 é a baseline de auditoria. Antes de ser declarada estável:

- `FLUID.WASHER` tem precedência e bloqueia `GLASS.REPLACE`;
- eixo e lado são atributos, não sufixos improvisados no código;
- códigos legados são lidos por uma tabela de compatibilidade;
- cada resultado guarda versão, origem, confiança e evidência;
- classificações humanas recebem bloqueio de substituição.

## Comando de execução no Render

Primeira execução, rápida e sem recalcular hashes:

```text
python scripts/audit_invoices_dry_run.py --output /var/data/carfast_documents/_audit/invoice-audit-dry-run.json
```

Verificação posterior que recalcula os hashes físicos e compara-os com os valores guardados:

```text
python scripts/audit_invoices_dry_run.py --hash-files --output /var/data/carfast_documents/_audit/invoice-audit-with-hashes.json
```

Criar o ficheiro JSON altera apenas a pasta de relatórios no disco persistente. A base de dados e os documentos originais permanecem inalterados.

## Gates de autorização

- **Gate A — agora:** código e testes; nenhuma escrita de negócio.
- **Gate B:** executar simulação no Render e apresentar o relatório.
- **Gate C:** aprovar documentos e regras afetados.
- **Gate D:** reprocessar um lote piloto.
- **Gate E:** aplicar restantes lotes e gerar as tabelas finais.

Rollback de código é feito pelo PR/commit. Dados só podem ser alterados depois do Gate C e através de operações auditadas e idempotentes.
