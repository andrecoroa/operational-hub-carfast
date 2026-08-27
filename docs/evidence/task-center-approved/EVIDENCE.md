# Centro de Tarefas — evidência de implementação

## Candidato e isolamento

- Base imutável: `cfc11bd780cdf3a889dba97e846e42c22ebbfcd6`.
- Branch isolada: `codex/task-center-approved-implementation`.
- Runtime: `127.0.0.1:18766`, SQLite local descartável e fixtures exclusivamente sintéticas.
- Email inbound/outbound OFF; sem chaves, integrações, Green, Blue, DNS ou dados reais.

## Comparação com o mockup aprovado

PASS objetivo em viewport real 1440×731, zoom 100%:

- sidebar 208 px, topbar 52 px, cabeçalho 58 px;
- cinco contadores integrais em 62 px, separados dos filtros;
- filtros em 76 px, com categorias exclusivas e informação do default seguro;
- área lista/preview 62/38 (728/446 px úteis, gap 10 px);
- linha de 42 px com exatamente sete campos;
- preview inline e fila acessível, com quatro ações no máximo;
- `body.scrollWidth=1440`, `body.scrollHeight=731` e zero descendentes visíveis fora do viewport;
- zebra neutra, prioridade/estado com texto e símbolo, truncamento controlado.

As diferenças face ao PNG do protótipo limitam-se ao conteúdo real do shell atual (topbar/sidebar) e às fixtures server-side; composição, hierarquia, medidas e comportamento vinculativos foram preservados.

## Estados capturados

| Estado | Ficheiro | SHA-256 |
|---|---|---|
| initial | `initial-1440x731.png` | `b694d02567fdd57607e7aa27c09d11a9ac26efd27045d55b6b575a38aadee4a9` |
| selected | `selected-1440x731.png` | `7b1138799925e7fbeee0c1a612028f84a1333b8aed0e26696bfa4aec55ae618c` |
| workshop | `workshop-1440x731.png` | `cf2b0276c8981ba2a896aa823c48d9f23e9a66ff3d7be4d56afa5ee6447f1903` |
| closed | `closed-1440x731.png` | `9297af742b87760b7244d83f2824ef442ee67378426ac3839ca26f69482c613c` |
| empty | `empty-1440x731.png` | `7976f1cffcbedd84ea6ed386d374aeed6611792d3d128f697081c4a0b7fb605e` |

## Contratos funcionais

- Entrada inicial: Minhas + Documentação (fallback determinístico da última categoria) + estados ativos + qualquer prazo.
- Fechadas só entram por pedido explícito; `Limpar filtros` repõe a vista segura e mantém a última categoria de foco.
- Contadores e categorias são calculados no servidor sobre a mesma base de autorização da lista.
- Seleção por clique ou Enter abre preview sem navegação; fechar preserva filtros e URL; seleção é guardada em `sessionStorage` e hash para ReturnContext.
- Contadores são `button` nativos; categorias são radios exclusivas; foco visível está definido.
- As ações do preview são ocultadas sem `task_update_allowed_by_id`; abrir permanece disponível apenas para linhas já autorizadas pelo servidor. Mutações existentes continuam a revalidar RBAC server-side.

## Testes

- `54 passed`: contrato novo, defaults/fechadas, reconciliação de contadores, tarefas, notificações/acesso, Service Desk, RBAC e gates Frente A diretamente afetados.
- Suite completa recolhida: 811 testes; os primeiros FAILs são anteriores e reproduzíveis na base aceite em superfícies fora desta tranche. Não foram mascarados nem alterados.
- Browser: seleção por Enter, fechar sem perda de contexto, categoria Oficina + reset para Oficina, cinco estados e geometria sem overflow PASS.

## Segurança e efeitos

- Nenhuma migração ou alteração de schema.
- Nenhum efeito externo; email inbound/outbound OFF no runner.
- Nenhum PR, merge ou deploy efetuado durante esta evidência.
