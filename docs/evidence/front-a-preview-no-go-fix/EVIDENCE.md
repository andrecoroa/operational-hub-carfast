# Front A FUR desktop — evidência de fecho

Data: 2026-08-27. Candidato: `codex/front-a-preview-no-go-fix`, derivado de `e8d6ea2d`.

## Ambiente seguro

- Preview local: `http://127.0.0.1:18765`.
- Base SQLite e storage exclusivos em `.front-a-preview-runtime` (não versionados).
- Fixtures determinísticas sem dados reais: três conversas, um documento e três processos de Oficina.
- Email inbound/outbound desativados; sem Blue, Green, DNS, integrações ou bases reais.
- Viewport de validação do browser: `1440 × 731` (confirmado por `window.innerWidth/innerHeight`).

## Capturas reais

- `administration-master-detail-1440x731.png`
- `email-list-1440x731.png`
- `email-preview-treatment-1440x731.png`
- `documentation-list-preview-1440x731.png`
- `workshop-first-fold-1440x731.png`

As medições DOM confirmaram ausência de overflow horizontal global nas cinco vistas. Email lista apresentou 3 linhas; a seleção manteve as 3 linhas acessíveis e abriu o painel amplo de triagem, validação e resposta na mesma página.

## Matriz binária

| Gate | Resultado | Evidência |
|---|---|---|
| 1. Sidebar alinhada, legível e com reserva de scrollbar | PASS | Capturas 1440×731; label `Alertas` curta; scroll independente visível. |
| 2. Oficina separada de Stock/configuração | PASS | Sidebar e testes de contrato; Stock global, modelos no domínio Administração. |
| 3. Ações compactas e `nowrap` | PASS | CSS transversal e capturas Email/Admin/Oficina. |
| 4. Primeira dobra Oficina operacional | PASS | `workshop-first-fold-1440x731.png`, 3 processos sintéticos. |
| 5. Duplicação administrativa removida no FUR | PASS | Mestre-detalhe com nove domínios; sem Tarefas/Processos operacionais internos. |
| 6. Email/Documentação fila + preview no mesmo contexto | PASS | Capturas preenchidas; testes de seleção e ReturnContext. |
| 7. RBAC server-side | PASS | Rotas web revalidam capacidades; regressão negativa incluída. |
| 8. Transições fail-closed | PASS | Ações forjadas e ordem adversarial rejeitadas; Email rejeita `submit` desconhecido. |
| 9. Efeitos externos OFF e auditoria | PASS | Flags inbound/outbound OFF; testes de auditoria para save/advance e transições. |

## Testes

Comando focado/regressão Front A:

`python -m pytest -q tests/test_email_triage_preview.py tests/test_clean_admin.py tests/test_front_a_fur_desktop_gate.py tests/test_clean_workshop_v2_flow.py tests/test_navigation_rbac.py tests/test_clean_documentation_architecture.py`

Resultado: **114 passed**, 5 warnings deprecatórias SWIG, zero falhas.

As revisões independentes detetaram lacunas P1 em save de fase adversarial e nos percursos enviar/aprovar com outbound OFF. Todas foram corrigidas com rejeição anterior à mutação e cobertas por testes negativos antes da revisão final.
