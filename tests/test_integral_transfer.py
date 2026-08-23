from __future__ import annotations

import io

import pytest

from app.platform.integral_transfer import (
    ChunkedReader,
    IntegralTransferRejected,
    issue_token,
    verify_token,
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
