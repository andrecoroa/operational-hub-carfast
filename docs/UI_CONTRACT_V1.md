# CarFast UI Contract v1 — referência canónica

Os goldens independentes em `docs/evidence/ui-contract-transversal/canonical-golden/` são a referência visual executável.

## Shell e famílias

- Desktop `1440×731`, zoom 100%; sidebar 208 px; topbar 52 px; zero overflow global.
- Shell branca do protótipo aprovado; adaptações navy não prevalecem quando divergem.
- Famílias: Dashboard; lista/tabela; lista→preview→tratamento; mestre–detalhe; processo/workbench; formulário/modal; estados especiais.
- Email e Documentação: 250 px + área flexível + tratamento 350 px.
- Administração: mestre 280 px + detalhe.
- Processos: catálogo 260 px + execução flexível + contexto 300 px.

## Gate

- Diff full-frame por família `<2,00%`, sem máscaras, recortes, resize ou golden derivado da aplicação.
- Geometria ±2 px desktop, primeira dobra e densidade conformes.
- Persistência, RBAC fail-closed, teclado/foco, estados e inventário executável PASS.
- Revisão independente sem P0/P1 antes de PR/deploy.
