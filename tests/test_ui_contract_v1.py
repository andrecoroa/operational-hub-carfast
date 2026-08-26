from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "app/templates/base.html").read_text(encoding="utf-8")
TASKS = (ROOT / "app/templates/clean_task_center.html").read_text(encoding="utf-8")
PROCESSES = (ROOT / "app/templates/clean_process_center.html").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/css/ui-contract-v1.css").read_text(encoding="utf-8")
ICONS = (ROOT / "app/static/icons/lucide-v3.svg").read_text(encoding="utf-8")


def test_contract_asset_is_global_for_foundation_surfaces() -> None:
    assert 'ui-contract-v1.css?v=20260826-contract-v1' in BASE
    assert 'class="ui-contract-v1"' in BASE


def test_shell_alignment_and_compact_first_fold_are_measurable() -> None:
    for contract in (
        "--visual-sidebar-width: 208px",
        "--visual-sidebar-collapsed: 56px",
        "--visual-topbar-height: 52px",
        "--ui-control-compact: 32px",
        "white-space: nowrap",
        "min-height: 56px",
        "--ui-row-height: 40px",
    ):
        assert contract in CSS
    assert "grid-template-columns: 18px minmax(0,1fr)" in CSS
    assert ".ui-contract-v1.visual-nav-open #visual-sidebar { width: min(320px,88vw); }" in CSS


def test_task_center_uses_canonical_language_and_lucide_family() -> None:
    assert "<h2>Centro de Tarefas</h2>" in TASKS
    for icon in ("inbox", "circle-check", "user-round", "clock", "triangle-alert"):
        assert f'lucide-v3.svg#{icon}' in TASKS
        assert f'id="{icon}"' in ICONS
    assert "Service Desk</h2>" not in TASKS


def test_process_center_uses_global_shell_and_compact_workspace() -> None:
    assert '{% include "_visual_topbar.html" %}' in PROCESSES
    assert 'visual_page = "Centro de Processos"' in PROCESSES
    assert "process-command-kpis" in CSS
    assert ".process-command-kpis > a { display: grid;" in CSS
    assert ".visual-service-kpi-icon { position: static;" in CSS
    assert "process-command-toolbar { min-height: 48px" in CSS
    for icon in ("inbox", "triangle-alert", "user-round", "circle-check"):
        assert f'lucide-v3.svg#{icon}' in PROCESSES
