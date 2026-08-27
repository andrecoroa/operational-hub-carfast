# CarFast — Desktop exit readiness

Estado deste checkpoint: **NO-GO para abandonar o Desktop como única estação de execução**.

## Fontes versionadas

- `docs/CARFAST_CURRENT_STATE.md`
- `docs/UI_CONTRACT_V1.md`
- `docs/architecture/HTML_SURFACE_INVENTORY.json`
- `docs/architecture/UI_SURFACE_FAMILY_MANIFEST.json`
- `docs/evidence/ui-contract-transversal/`
- `scripts/serve_ui_contract_evidence.py`

## Dependências a reproduzir na cloud

- Python e PostgreSQL isolado conforme o repositório.
- Chromium compatível para screenshot a zoom 100% e DPR registado.
- PyMuPDF para preview documental e Pillow para fixtures/evidência.
- Sessão autenticada apenas para smoke runtime; cookies nunca são versionados.
- Secrets somente pelo secret store da plataforma: base isolada, sessão sintética e credenciais de automação autorizadas. Nunca versionar valores, URLs privadas, tokens ou chaves.

## Comandos

```powershell
python -m pip install -r requirements-dev.txt
python scripts/check_migration_heads.py
python -m alembic upgrade head
python -m scripts.bootstrap_installation
python -m scripts.check_clean_install
python -m compileall -q app scripts
python -m pytest -q tests/test_ui_contract_transversal_fidelity.py tests/test_ui_surface_family_manifest.py
python -m scripts.serve_ui_contract_evidence
python -m scripts.check_ui_contract_evidence
```

## Gate

- NO-GO enquanto qualquer família desktop tiver MAE `>=2,00%` ou revisão P0/P1.
- NO-GO se clone limpo cloud não reproduzir bootstrap, testes, captura e comparação.
- Este checkpoint é **NOT FOR MERGE OR DEPLOY**.
