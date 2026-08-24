from __future__ import annotations

import pytest

from scripts.validate_integral_migration_contract import _failure_code


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("target relation inventory mismatch; missing=['x']", "target_inventory"),
        ("target revision mismatch; expected=x, actual=('y',)", "target_revision"),
        ("additive column contract mismatch for x: []", "additive_columns"),
        ("additive primary-key contract mismatch for x: ()", "additive_primary_key"),
        ("additive unique contract mismatch for x: []", "additive_unique"),
        ("additive foreign-key contract mismatch for x: []", "additive_foreign_key"),
        ("additive seed count mismatch for x: 2", "additive_seed_count"),
        ("additive index contract mismatch for x: []", "additive_index"),
        ("installation_modules check contract mismatch: []", "additive_check"),
        ("module_definitions seed contract mismatch", "module_seed"),
        ("installation_modules seed contract mismatch", "installation_seed"),
        ("unexpected sensitive detail", "unclassified_contract"),
    ],
)
def test_contract_failure_codes_are_stable_and_non_sensitive(
    message: str, expected: str
) -> None:
    code = _failure_code(message)
    assert code == expected
    assert message not in code


def test_render_rehearsal_has_persistent_one_shot_guard() -> None:
    legacy = open("scripts/run_integral_render_rehearsal.sh", encoding="utf-8").read()
    entrypoint = open("scripts/integral_render_entrypoint.py", encoding="utf-8").read()
    assert "legacy_render_entrypoint_rejected=true" in legacy
    assert 'if tombstone.exists()' in entrypoint
    assert 'integral_entrypoint_restart_blocked=true' in entrypoint
    assert 'write_tombstone(tombstone, result)' in entrypoint
