from pathlib import Path


def test_clean_home_uses_live_operational_metrics():
    source = (
        Path(__file__).resolve().parents[1] / "app" / "web" / "router.py"
    ).read_text(encoding="utf-8")

    start = source.index("def clean_experience_home")
    end = source.index("PROCESS_CENTER_PERMISSIONS", start)
    home_source = source[start:end]

    assert 'WorkshopPhasedProcessAlert.status == "open"' in home_source
    assert "task_visibility_filter" in home_source
    assert "Task.closed_at.is_(None)" in home_source
    assert 'VehicleHistoryAudit.status != "closed"' in home_source
    assert '"tasks": area_cards[0]["open"]' not in home_source
