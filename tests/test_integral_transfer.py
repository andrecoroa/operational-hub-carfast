from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.platform.integral_transfer import (
    ChunkedReader,
    IntegralTransferRejected,
    issue_token,
    verify_token,
)
from scripts.integral_private_transfer import (
    database_dump_command,
    database_restore_command,
    valid_target_marker,
)

KEY = b"integral-fixture-key-material-32-bytes-minimum"
SOURCE = "srv-sourcefixture"
DESTINATION = "srv-destinationfixture"


def test_integral_token_is_signed_scoped_and_short_lived() -> None:
    token = issue_token(KEY, source=SOURCE, destination=DESTINATION, kind="storage")
    claims = verify_token(
        token,
        KEY,
        expected_source=SOURCE,
        expected_destination=DESTINATION,
        expected_kind="storage",
    )
    assert claims.expires_at - claims.issued_at == 600
    with pytest.raises(IntegralTransferRejected, match="endpoint mismatch"):
        verify_token(
            token,
            KEY,
            expected_source=SOURCE,
            expected_destination=DESTINATION,
            expected_kind="database",
        )


def test_chunked_reader_decodes_incrementally() -> None:
    raw = io.BytesIO(b"4\r\ntest\r\n3\r\ning\r\n0\r\n\r\n")
    reader = ChunkedReader(raw)
    assert reader.read(2) == b"te"
    assert reader.read(5) == b"sting"
    assert reader.read(1) == b""


@pytest.mark.parametrize(
    "raw",
    [
        b"x\r\n",
        b"4\ntest",
        b"4\r\ntes",
        b"1\r\nxNO",
    ],
)
def test_chunked_reader_fails_closed_on_bad_framing(raw: bytes) -> None:
    with pytest.raises(IntegralTransferRejected):
        ChunkedReader(io.BytesIO(raw)).read(8)


def test_clean_restore_is_allowed_only_for_isolated_staging() -> None:
    assert "--exclude-table=alembic_version" in database_dump_command("source-staging")
    staging = database_restore_command(
        "staging", "carfast_integral_staging_fixture", target_prepared=False
    )
    assert "--clean" in staging
    assert "--dbname=carfast_integral_staging_fixture" in staging
    with pytest.raises(ValueError, match="not isolated"):
        database_restore_command("staging", "carfast_green", target_prepared=False)


def test_prepared_green_restore_is_data_only_and_never_clean() -> None:
    target = database_restore_command("prepared-target", "carfast_green", target_prepared=True)
    assert "--data-only" in target
    assert "--dbname=carfast_green" in target
    assert "--clean" not in target
    assert "--data-only" in database_dump_command("migrated-target")
    with pytest.raises(ValueError, match="not explicitly prepared"):
        database_restore_command("prepared-target", "carfast_green", target_prepared=False)


def test_target_marker_is_exact_and_short_lived(tmp_path) -> None:
    now = datetime.now(UTC)
    marker = tmp_path / "marker.json"
    marker.write_text(
        json.dumps(
            {
                "database": "carfast_green",
                "release_sha": "9c691d332c80dff4a1d529d7f0d4ef16a71add46",
                "relations": 166,
                "service": "srv-da5dk9bm8hqs73camds0",
                "source_relations": 162,
                "timestamp": now.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    assert valid_target_marker(marker, "carfast_green", now=now)
    assert not valid_target_marker(marker, "carfast_green", now=now + timedelta(minutes=21))
