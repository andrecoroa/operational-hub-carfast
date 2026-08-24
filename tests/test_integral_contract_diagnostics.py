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
    script = open("scripts/run_integral_render_rehearsal.sh", encoding="utf-8").read()
    assert 'if [ -e "$one_shot_state" ]' in script
    assert 'render_integral_one_shot=blocked prior_state_present=true' in script
    assert 'finish_one_shot "no-go"' in script
    assert 'finish_one_shot "pass"' in script
    assert script.index('if [ -e "$one_shot_state" ]') < script.index(
        "scripts/run_integral_e2e_rehearsal.sh"
    )
