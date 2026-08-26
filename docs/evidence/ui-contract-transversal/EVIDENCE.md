# UI Contract transversal — evidência local

## Âmbito e proveniência

- Branch: `codex/ui-contract-transversal-fidelity`
- Base: `integration/modular-architecture@1083b4001d144cc9ab53507ac28215495a2dcce7`
- Dados: fixtures exclusivamente sintéticas; nenhum contacto com Blue, Green ou dados reais.
- Referências: `UI_CONTRACT_V1.md`, protótipo executável aprovado e comparação canónica do workbench documental.
- Captura: browser real, zoom 100%, viewport completo, sem recorte nem redimensionamento posterior.

## Resultados objetivos

| Gate | Valor observado | Resultado |
|---|---:|---|
| Sidebar desktop | 208 px | PASS |
| Topbar | 52 px | PASS |
| Centro de Tarefas, linhas completas na primeira dobra 1440×731 | 6 × 44 px | PASS |
| Centro de Processos desktop | 260 px / flex / 300 px | PASS |
| Email desktop | 250 px / flex / 350 px, simultâneos | PASS |
| Documentação desktop | 250 px / flex / 350 px, simultâneos | PASS |
| Administração desktop | 280 px / detalhe flexível, editor real | PASS |
| Overflow global | 0 em todas as 21 combinações | PASS |
| Documentação tablet/mobile | fila, preview e validação na mesma rota, empilhados | PASS |
| Email tablet/mobile | lista, conversa e triagem na mesma rota | PASS |
| Inventário HTML | 137 superfícies atuais contra baseline 136; classes canonical/detail/overlay/portal/adapter/legacy_blocked | PASS |
| Inventário executável | Cada superfície não-legada cruzada com path+handler live; legado cruzado com implementação nominal preservada | PASS |
| Pixel gate do RC | 21 capturas determinísticas, viewport integral, diferença permitida <2% | **NO-GO — correção em curso** |
| Regressão focada | 17 testes; inclui HTTP nominal 125/125 superfícies não-legadas | PASS |

As medidas completas e os retângulos observados estão em `metrics-v1j.json`. `python -m scripts.check_ui_contract_evidence` é fail-closed e compara o viewport integral contra goldens independentes; não mascara a área útil da aplicação. A revisão independente detetou diferenças acima do limite, sobretudo em Documentação e Email, pelo que PR/deploy permanecem bloqueados.

## Capturas da aplicação

Cada superfície tem `1440x731`, `1024x900` e `390x844`:

- `dashboard-*`
- `tasks-*`
- `processes-*`
- `email-*`
- `documents-*`
- `admin-*`
- `partners-*`

## Capturas canónicas

- `reference-dashboard-1440x731.jpg`
- `reference-tasks-1440x731.jpg`
- `reference-processes-1440x731.jpg`
- `reference-email-1440x731.jpg`
- `reference-documents-1440x731.jpg`
- `reference-admin-1440x731.jpg`
- `reference-partners-1440x731.jpg`

## Alterações estruturais comprovadas

- Sidebar global usa grelha fixa `16px + label`, Lucide real, labels sem quebra e navegação canónica por domínio.
- Centro de Processos recebeu catálogo/fila, execução e contexto/histórico como três zonas reais.
- Email carrega automaticamente a primeira conversa e mantém lista, conversa/composer e triagem simultaneamente; o diálogo ficou apenas fallback legado sem foundation.
- Documentação mantém fila, preview/OCR e classificação/arquivo simultaneamente; em tablet/mobile as três zonas permanecem na mesma rota.
- Administração usa diretório mestre e um detalhe operacional real; a evidência abre Perfis e permissões com matriz editável e Guardar no mesmo contexto.
- Parceiros expõe apenas Parceiros, Tipos e serviços, Contratos e Configuração; Utilizadores, Perfis, Categorias e Email permanecem exclusivos de Administração.

## Limitações honestas

- A evidência local não prova autenticação nem integração runtime do Render; isso pertence ao smoke autenticado pós-deploy Green.
- Os previews usam ficheiros/corpos sintéticos reais servidos pelas mesmas rotas; a evidência falha se aparecer `404` ou se o artefacto não existir.
- A captura do protótipo preserva defeitos de encoding do ficheiro exportado de referência; não foram copiados para a aplicação.
- Nenhuma comparação visual foi declarada PASS por um diff bruto artificialmente mascarado. O merge/deploy continua bloqueado até revisão independente sem P0/P1, CI remoto verde e smoke Green.
