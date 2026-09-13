from pathlib import Path


def test_clean_home_uses_live_operational_metrics():
    source = (
        Path(__file__).resolve().parents[1] / "app" / "web" / "router.py"
    ).read_text(encoding="utf-8")

    start = source.index("def clean_experience_home")
    end = source.index("PROCESS_CENTER_PERMISSIONS", start)
    home_source = source[start:end]

    assert 'WorkshopPhasedProcessAlert.status == "open"' in home_source
    assert "user_accessible_task_type_codes" in home_source
    assert "Task.task_type.in_(tuple(accessible_task_types))" in home_source
    assert "Task.closed_at.is_(None)" in home_source
    assert 'VehicleHistoryAudit.status != "closed"' in home_source
    assert '"tasks": area_cards[0]["open"]' not in home_source


def test_home_area_cards_and_workshop_alerts_are_live_and_active_only():
    source = (
        Path(__file__).resolve().parents[1] / "app" / "web" / "router.py"
    ).read_text(encoding="utf-8")

    cards_start = source.index("def clean_process_area_cards")
    cards_end = source.index("def clean_task_division_cards", cards_start)
    cards_source = source[cards_start:cards_end]
    home_start = source.index("def clean_experience_home")
    home_end = source.index("PROCESS_CENTER_PERMISSIONS", home_start)
    home_source = source[home_start:home_end]

    assert '"open": 0' not in cards_source
    assert '"critical": 0' not in cards_source
    assert 'Task.priority.in_({"high", "urgent"})' in cards_source
    assert 'VehicleHistoryAudit.priority.in_({"high", "urgent", "critical"})' in cards_source
    assert 'WorkshopPhasedProcess.status.notin_(("closed", "cancelled"))' in home_source
    assert ".join(" in home_source
