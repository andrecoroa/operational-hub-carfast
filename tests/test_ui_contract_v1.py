from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "app/templates/base.html").read_text(encoding="utf-8")
TASKS = (ROOT / "app/templates/clean_task_center.html").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/css/ui-contract-v1.css").read_text(encoding="utf-8")
ICONS = (ROOT / "app/static/icons/lucide-v3.svg").read_text(encoding="utf-8")


def test_contract_asset_is_global_for_foundation_surfaces() -> None:
    assert 'ui-contract-v1.css?v=20260826-contract-v1' in BASE
    assert 'class="ui-contract-v1"' in BASE


def test_shell_alignment_and_compact_first_fold_are_measurable() -> None:
    for contract in (
        "--visual-sidebar-width: 240px",
        "--visual-topbar-height: 48px",
        "white-space: nowrap",
        "min-height: 56px",
        "min-height: 34px",
        "--ui-row-height: 44px",
    ):
        assert contract in CSS
    assert "grid-template-columns: 18px minmax(0,1fr)" in CSS


def test_task_center_uses_canonical_language_and_lucide_family() -> None:
    assert "<h2>Centro de Tarefas</h2>" in TASKS
    for icon in ("inbox", "circle-check", "user-round", "clock", "triangle-alert"):
        assert f'lucide-v3.svg#{icon}' in TASKS
        assert f'id="{icon}"' in ICONS
    assert "Service Desk</h2>" not in TASKS
