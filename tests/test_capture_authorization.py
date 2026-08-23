from __future__ import annotations

import pytest

from app.platform.capture_authorization import (
    AuthorizationRejected,
    issue_fixture_token,
    reset_fixture_replay_cache,
    verify_and_consume,
)
from scripts import export_anonymized_dataset

KEY = b"fixture-capture-signing-key-32-bytes-minimum"
SOURCE = "fixture-origin"
DESTINATION = "fixture-destination"
NONCE = "fixture_nonce_1234567890abcdef"


@pytest.fixture(autouse=True)
def reset_replay() -> None:
    reset_fixture_replay_cache()


def token(*, issued_at: int = 1_000, expires_at: int = 1_600, source: str = SOURCE) -> str:
    return issue_fixture_token(
        KEY,
        source=source,
        destination=DESTINATION,
        nonce=NONCE,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def test_signed_scoped_token_is_consumed_once() -> None:
    value = token()
    claims = verify_and_consume(
        value, KEY, expected_source=SOURCE, expected_destination=DESTINATION, now=1_100
    )
    assert claims.nonce == NONCE
    with pytest.raises(AuthorizationRejected, match="replay"):
        verify_and_consume(
            value, KEY, expected_source=SOURCE, expected_destination=DESTINATION, now=1_100
        )


@pytest.mark.parametrize(
    "value,now,reason",
    [
        (token(expires_at=1_001), 1_001, "expired"),
        (token(issued_at=1_200, expires_at=1_300), 1_100, "future"),
        (token(expires_at=2_000), 1_100, "lifetime"),
        (token(source="wrong-origin"), 1_100, "endpoint mismatch"),
    ],
)
def test_time_and_scope_fail_closed(value: str, now: int, reason: str) -> None:
    with pytest.raises(AuthorizationRejected, match=reason):
        verify_and_consume(
            value, KEY, expected_source=SOURCE, expected_destination=DESTINATION, now=now
        )


def test_tampered_signature_and_short_key_are_rejected() -> None:
    value = token()
    with pytest.raises(AuthorizationRejected, match="invalid"):
        verify_and_consume(
            value + "x", KEY, expected_source=SOURCE, expected_destination=DESTINATION, now=1_100
        )
    with pytest.raises(AuthorizationRejected, match="invalid"):
        verify_and_consume(
            value, b"short", expected_source=SOURCE, expected_destination=DESTINATION, now=1_100
        )


def test_export_process_rejects_before_database_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.argv", ["export_anonymized_dataset", "--read-only"])
    monkeypatch.setenv("CAPTURE_AUTHORIZATION_ID", "invalid")
    monkeypatch.setenv("CAPTURE_AUTHORIZATION_KEY", KEY.decode())
    monkeypatch.setenv("CAPTURE_SOURCE_SERVICE", SOURCE)
    monkeypatch.setenv("CAPTURE_DESTINATION_SERVICE", DESTINATION)
    monkeypatch.setenv("DATABASE_URL", "must-not-be-used")

    def forbidden_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("database connection attempted before authorization")

    monkeypatch.setattr(export_anonymized_dataset.psycopg, "connect", forbidden_connect)
    with pytest.raises(SystemExit, match="invalid capture authorization"):
        export_anonymized_dataset.main()
