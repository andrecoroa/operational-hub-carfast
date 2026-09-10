# Front A FUR desktop — evidência de fecho

Data: 2026-08-27. Candidato: `codex/front-a-preview-no-go-fix`, derivado de `e8d6ea2d`.

## Ambiente seguro

- Preview local: `http://127.0.0.1:18765`.
- Base SQLite e storage exclusivos em `.front-a-preview-runtime` (não versionados).
- Fixtures determinísticas sem dados reais: quatro conversas (incluindo uma com anexo de texto seguro), três documentos (baixa confiança, validado e bloqueado), três processos de Oficina, uma tarefa e um processo de gestão.
- Email inbound/outbound desativados; sem Blue, Green, DNS, integrações ou bases reais.
- Viewport de validação do browser: `1440 × 731` (confirmado por `window.innerWidth/innerHeight`).

## Capturas reais

- `administration-users-editor-first-fold-1440x731.png`
- `email-list-1440x731.png`
- `email-preview-treatment-1440x731.png`
- `email-attachment-treatment-1440x731.png`
- `documentation-list-1440x731.png`
- `documentation-preview-treatment-filled-1440x731.png`
- `workshop-first-fold-1440x731.png`
- `tasks-positive-fixture-1440x731.png`
- `processes-positive-fixture-1440x731.png`
- `GEOMETRY_1440x731.json`

Todas as capturas acima têm exatamente 1440×731 píxeis. O probe reproduzível `scripts/front_a_geometry_probe.js` inspeciona todos os descendentes visíveis, não apenas `body.scrollWidth`, e valida clipping ancestral de cada controlo; nos oito percursos medidos encontrou zero overflow não contido e confirmou documento 1440×731. Email usa apenas duas colunas de contexto: fila compacta e legível de 260px à esquerda e uma área de trabalho unificada de 922px à direita. Dentro desta área, mensagem e tratamento estão empilhados verticalmente, não constituem uma terceira coluna: a conversa mede x=493–1415/y=441–592 e o tratamento x=493–1415/y=592–688. O corpo sintético está realmente pintado; os quatro campos de classificação medem y=658–686 e estão integralmente utilizáveis. A ActionBar mede x=493–1415 e y=688–730; Guardar triagem, Validar classificação, Arquivar, Responder e Criar tarefa estão em y=694–724 com `fullyVisible: true`. Existe uma única ação Fechar preview. Guardar é neutro; Validar classificação é a ação primária canónica e revalidada no servidor. A ActionBar de Documentação mede x=1070–1392 e y=631–666, com os quatro controlos `fullyVisible: true`. Administração abre o editor mestre-detalhe na primeira dobra. Documentação mantém 3 itens na fila, consulta `document_action_compatibility` e mostra Guardar/Validar/Arquivar separadamente. Fixtures positivas de Tarefas e Processos foram renderizadas no candidato.

O percurso de anexos foi validado com `comprovativo-sintetico.txt`: o diálogo mede x=130–1310/y=58–673, com preview legível x=130–950 e tratamento x=950–1310, sem overflow global. O conteúdo `COMPROVATIVO SINTETICO / Sem dados reais / FRONT-A-ATTACHMENT-001` foi confirmado dentro do iframe. A classificação guardou tipo, natureza, destino, estado e auditoria `attachment_classified`; ação forjada foi rejeitada antes de mutação. A própria UI apresenta simultaneamente `Guardar classificação` (x=968–1277/y=576–611), `Abrir ficheiro` (x=968–1119/y=620–654) e `Descarregar` (x=1127–1277/y=620–654); todos têm `fullyVisible: true` e `textFits: true`. O download explícito devolveu o ficheiro original e fechar o diálogo preservou a conversa 4 e a fila selecionada.

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

`python -m pytest -q tests/test_foundation_api.py tests/test_email_triage_preview.py tests/test_clean_admin.py tests/test_front_a_fur_desktop_gate.py tests/test_clean_workshop_v2_flow.py tests/test_navigation_rbac.py tests/test_clean_documentation_architecture.py tests/test_process_center_runtime.py tests/test_clean_task_management_recurrence.py`

Resultado: **135 passed**, 5 warnings deprecatórias SWIG, zero falhas. A regressão inclui os cinco perfis/scopes operacionais exercitados pelos testes de navegação, Tarefas e Processos: administrador sem execução implícita, executor, coordenador de equipa, coordenador operacional e gestor com exceção auditada. Inclui também uma sequência positiva Guardar → Validar → Arquivar, validação explícita de classificação auditada, preview/download/classificação auditada de anexos, composição Email sem três colunas rígidas e rejeição fail-closed de ações forjadas, classificação em falta ou arquivo antes da validação pelo contrato server-side.

As revisões independentes anteriores detetaram lacunas P1 em save de fase adversarial, percursos enviar/aprovar com outbound OFF, visibilidade do editor administrativo, composição da evidência e geometria de Processos. Todas foram corrigidas com rejeição anterior à mutação, cobertura própria e evidência reproduzível. O resultado da re-revisão final é registado apenas após o SHA ficar congelado.

O reclose corrigiu ainda GET públicos de organização/configuração, confirmou autenticação do inventário, removeu rotas fantasma do percurso validado e acrescentou testes de contrato próprios para estas superfícies.
