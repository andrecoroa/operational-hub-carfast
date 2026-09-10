# Stock v3 — evidência local

- Implementação Stock: `0d1ff691`
- Navegação transversal v3: `b161302e`
- Asset carregado: `/static/css/visual-v2.css?v=20260826-elevation-v3`
- URL: `http://127.0.0.1:8765/v2-clean/stock/articles?availability=all`
- Dados: fixture integralmente sintética, SQLite em memória; sem Green, Blue ou dados reais.
- Zoom/font-size raiz: 100% / 16px.

## Capturas sem recorte

| Viewport | Ficheiro | Overflow global | Composição observada |
|---|---|---:|---|
| 1440 × 900 | `desktop-1440x900.png` | Não (`1425/1425`) | tabela 769px + preview sticky 384px, workspace 1169px |
| 1024 × 900 | `tablet-1024x900.png` | Não (`1009/1009`) | tabela e preview empilhados, largura útil 897px |
| 390 × 844 | `mobile-390x844.png` | Não (`375/375`) | conteúdo começa em y=0; sidebar drawer fixed/oculta; tabela com scroll local |

As três capturas carregam, por esta ordem, os grupos globais `Operação`,
`Operações de negócio` e `Sistema`. A sidebar desktop mostra Stock e Compras sob
Oficina. No tablet mantém o rail de 64px; no mobile transforma-se em drawer e
não ocupa espaço no fluxo da página.

## Limitações

- Esta é evidência visual local, não um deploy Green.
- A fixture valida composição e responsividade; não valida persistência nem
  integrações, deliberadamente desligadas.
- O screenshot mobile mostra o topo da página; a tabela e o preview continuam
  abaixo da dobra e usam apenas scroll local onde necessário.

As métricas DOM completas e o timestamp estão em `metrics.json`.
