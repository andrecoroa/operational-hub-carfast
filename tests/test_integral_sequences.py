from __future__ import annotations

from app.platform.integral_sequences import next_sequence_state


def test_empty_target_sequence_starts_at_one() -> None:
    assert next_sequence_state(None) == (1, False)


def test_populated_target_sequence_advances_past_maximum() -> None:
    value, called = next_sequence_state(918)
    assert (value, called) == (918, True)
