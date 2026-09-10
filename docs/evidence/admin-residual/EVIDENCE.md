# Administração residual — evidência Green

- Branch de implementação: `codex/green-admin-residual-closeout`
- HEAD funcional: `5bd302ef`
- PR funcional: `#74`
- Merge/deploy Green: `56628566a39d4d0683c1856173bb0b0044efb35e`
- Serviço: Green apenas (`srv-da5dk9bm8hqs73camds0`)
- Blue: intocado

## Runtime autenticado

As oito rotas foram abertas numa sessão autenticada do Green e apresentaram heading correto, navegação residual única com oito destinos, ligação ao Setup preservada e ausência de overflow global:

1. `/v2-clean/admin/audit`
2. `/v2-clean/admin/evolution`
3. `/v2-clean/admin/integrations`
4. `/v2-clean/admin/operations`
5. `/v2-clean/admin/organization`
6. `/v2-clean/admin/security`
7. `/v2-clean/admin/settings`
8. `/v2-clean/admin/workshop-models`

## Capturas reais, sem recorte

| Evidência | Viewport | body `scrollWidth/clientWidth` | Navegação `scrollWidth/clientWidth` | Resultado |
|---|---:|---:|---:|---|
| `admin-settings-desktop-1440x900.png` | 1440×900 | 1425/1425 | 1119/1119 | PASS |
| `admin-settings-tablet-1024x900.png` | 1024×900 | 1009/1009 | 882/847 | PASS; scroll apenas local |
| `admin-settings-mobile-390x844.png` | 390×844 | 375/375 | 882/309 | PASS; scroll apenas local |

Inspeção visual: composição material e consistente nos três breakpoints; grelha desktop, reorganização tablet e fluxo mobile legível; sem overflow global. O scroll horizontal da navegação residual em tablet/mobile é local e preserva todos os destinos.

## Testes

- 64 testes focados PASS, incluindo as oito rotas, RBAC fail-closed, estados vazios, formulários, diálogos, foco inicial, Escape/retorno de foco, Setup intocado e inventário 53/53.
- CI remoto: 1/1 PASS.
- Baseline conhecido, reproduzido sem regressão: `test_evolution_creation_permission_does_not_grant_management` espera redirect 303, enquanto a aplicação devolve 403 fail-closed. A tranche não enfraquece esta proteção.

## Resultado

PASS funcional, runtime e responsive. Não foi feita qualquer mutação no Blue. As 53 rotas canónicas deixam de ter conteúdo classificado como parcial ou legado; pendências históricas de captura externa não são classificadas como dívida de conteúdo.
