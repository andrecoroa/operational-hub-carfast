from __future__ import annotations

import hashlib
import io
import socket
import threading

import pytest

from app.platform.integral_tcp import (
    DATA_HEADER,
    MAX_FRAME,
    FramedReader,
    TcpTransferRejected,
    ensure_no_trailing,
    issue_tcp_token,
    verify_tcp_token,
    write_framed,
)

KEY = b"k" * 32
SOURCE = "srv-blue123"
DESTINATION = "srv-green456"
RELEASE = "a" * 40
CUTOFF = "cut-20260823T200000Z"


def _token(stream_type: str = "database") -> str:
    return issue_tcp_token(
        KEY,
        source=SOURCE,
        destination=DESTINATION,
        release=RELEASE,
        cutoff=CUTOFF,
        stream_type=stream_type,
    )


def test_tcp_token_is_scoped_and_one_use() -> None:
    used: set[str] = set()
    token = _token()
    verify_tcp_token(
        token,
        KEY,
        source=SOURCE,
        destination=DESTINATION,
        release=RELEASE,
        cutoff=CUTOFF,
        stream_type="database",
        used_nonces=used,
    )
    with pytest.raises(TcpTransferRejected, match="replay"):
        verify_tcp_token(
            token,
            KEY,
            source=SOURCE,
            destination=DESTINATION,
            release=RELEASE,
            cutoff=CUTOFF,
            stream_type="database",
            used_nonces=used,
        )
    with pytest.raises(TcpTransferRejected, match="endpoint"):
        verify_tcp_token(
            _token(),
            KEY,
            source=SOURCE,
            destination=DESTINATION,
            release="b" * 40,
            cutoff=CUTOFF,
            stream_type="database",
            used_nonces=set(),
        )


def _encoded(payload: bytes) -> bytes:
    target = io.BytesIO()
    write_framed(io.BytesIO(payload), target, KEY, "session-abcdefghijklmnopqrstuv")
    return target.getvalue()


def test_framed_roundtrip_and_final_digest() -> None:
    payload = (b"carfast-integral\x00" * 100_000) + b"tail"
    reader = FramedReader(io.BytesIO(_encoded(payload)), KEY, "session-abcdefghijklmnopqrstuv")
    restored = b"".join(iter(lambda: reader.read(65_537), b""))
    assert restored == payload
    assert reader.finished
    assert reader.total == len(payload)


def test_trailing_bytes_are_rejected() -> None:
    with pytest.raises(TcpTransferRejected, match="trailing"):
        ensure_no_trailing(io.BytesIO(b"unexpected"))


@pytest.mark.parametrize("mutation", ["reorder", "digest", "truncate", "unknown"])
def test_framed_adversarial_rejections(mutation: str) -> None:
    stream = bytearray(_encoded(b"a" * (MAX_FRAME + 20)))
    if mutation == "reorder":
        stream[1:9] = (2).to_bytes(8, "big")
    elif mutation == "digest":
        stream[DATA_HEADER.size] ^= 1
    elif mutation == "truncate":
        del stream[-10:]
    else:
        stream[0] = 99
    reader = FramedReader(io.BytesIO(stream), KEY, "session-abcdefghijklmnopqrstuv")
    with pytest.raises(TcpTransferRejected):
        while reader.read(64 * 1024):
            pass


class _LargeReader:
    def __init__(self, total: int) -> None:
        self.remaining = total

    def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        amount = min(self.remaining, MAX_FRAME if size < 0 else size)
        self.remaining -= amount
        return b"z" * amount


def test_stream_above_http_proxy_equivalent_with_backpressure() -> None:
    total = 101 * 1024 * 1024
    left, right = socket.socketpair()
    outcome: dict[str, object] = {}

    def produce() -> None:
        with left:
            outcome["result"] = write_framed(
                _LargeReader(total),
                left.makefile("wb", buffering=0),
                KEY,
                "session-abcdefghijklmnopqrstuv",
            )
            left.shutdown(socket.SHUT_WR)

    thread = threading.Thread(target=produce)
    thread.start()
    digest = hashlib.sha256()
    reader = FramedReader(right.makefile("rb", buffering=0), KEY, "session-abcdefghijklmnopqrstuv")
    while chunk := reader.read(MAX_FRAME):
        digest.update(chunk)
    thread.join(timeout=20)
    right.close()
    frames, observed, final = outcome["result"]
    assert not thread.is_alive()
    assert frames == 101
    assert observed == total == reader.total
    assert final == digest.hexdigest()
