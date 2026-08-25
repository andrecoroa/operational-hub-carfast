from __future__ import annotations

import hashlib
import io
import socket
import threading

import pytest

from app.platform.integral_tcp import (
    CONTROL_CONSUMER_RESULT,
    CONTROL_SPOOL_ACCEPTED,
    DATA_HEADER,
    MAX_FRAME,
    FramedReader,
    TcpTransferRejected,
    ensure_no_trailing,
    issue_tcp_token,
    read_control,
    verify_tcp_token,
    write_control,
    write_framed,
)

KEY = b"k" * 32
SOURCE = "srv-blue123"
DESTINATION = "srv-green456"
RELEASE = "a" * 40
CUTOFF = "cut-20260823T200000Z"
BUNDLE = "bundle-20260823T200000Z"


def _token(stream_type: str = "database") -> str:
    return issue_tcp_token(
        KEY,
        source=SOURCE,
        destination=DESTINATION,
        release=RELEASE,
        cutoff=CUTOFF,
        bundle_id=BUNDLE,
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
        bundle_id=BUNDLE,
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
            bundle_id=BUNDLE,
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
            bundle_id=BUNDLE,
            stream_type="database",
            used_nonces=set(),
        )
    with pytest.raises(TcpTransferRejected, match="endpoint"):
        verify_tcp_token(
            _token(),
            KEY,
            source=SOURCE,
            destination=DESTINATION,
            release=RELEASE,
            cutoff=CUTOFF,
            bundle_id="bundle-divergent",
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


class _PartialWriter(io.BytesIO):
    def write(self, value: bytes) -> int:
        return super().write(value[: max(1, min(4093, len(value)))])


def test_framed_writer_handles_partial_socket_writes() -> None:
    payload = b"partial-socket-write" * 100_000
    target = _PartialWriter()
    write_framed(io.BytesIO(payload), target, KEY, "session-abcdefghijklmnopqrstuv")
    reader = FramedReader(io.BytesIO(target.getvalue()), KEY, "session-abcdefghijklmnopqrstuv")
    assert b"".join(iter(lambda: reader.read(64 * 1024), b"")) == payload


def test_authenticated_two_phase_control_roundtrip() -> None:
    session = "session-abcdefghijklmnopqrstuv"
    digest = hashlib.sha256(b"payload").digest()
    wire = _PartialWriter()
    write_control(
        wire,
        KEY,
        session,
        phase=CONTROL_SPOOL_ACCEPTED,
        ok=True,
        frames=7,
        total=1234,
        digest=digest,
    )
    write_control(
        wire,
        KEY,
        session,
        phase=CONTROL_CONSUMER_RESULT,
        ok=True,
        frames=7,
        total=1234,
        digest=digest,
    )
    source = io.BytesIO(wire.getvalue())
    read_control(
        source,
        KEY,
        session,
        expected_phase=CONTROL_SPOOL_ACCEPTED,
        frames=7,
        total=1234,
        digest=digest,
    )
    read_control(
        source,
        KEY,
        session,
        expected_phase=CONTROL_CONSUMER_RESULT,
        frames=7,
        total=1234,
        digest=digest,
    )


def test_two_phase_real_tcp_ack_precedes_delayed_consumer() -> None:
    session = "session-abcdefghijklmnopqrstuv"
    digest = hashlib.sha256(b"payload").digest()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    accepted = threading.Event()
    finished = threading.Event()

    def server() -> None:
        connection, _ = listener.accept()
        with connection:
            handle = connection.makefile("rwb", buffering=0)
            write_control(
                handle,
                KEY,
                session,
                phase=CONTROL_SPOOL_ACCEPTED,
                ok=True,
                frames=1,
                total=7,
                digest=digest,
            )
            accepted.set()
            assert handle.read(1) == b""
            threading.Event().wait(0.15)
            write_control(
                handle,
                KEY,
                session,
                phase=CONTROL_CONSUMER_RESULT,
                ok=True,
                frames=1,
                total=7,
                digest=digest,
            )
            finished.set()

    thread = threading.Thread(target=server)
    thread.start()
    with socket.create_connection(listener.getsockname()) as client:
        handle = client.makefile("rwb", buffering=0)
        read_control(
            handle,
            KEY,
            session,
            expected_phase=CONTROL_SPOOL_ACCEPTED,
            frames=1,
            total=7,
            digest=digest,
        )
        assert not finished.is_set()
        assert accepted.wait(timeout=1)
        client.shutdown(socket.SHUT_WR)
        read_control(
            handle,
            KEY,
            session,
            expected_phase=CONTROL_CONSUMER_RESULT,
            frames=1,
            total=7,
            digest=digest,
        )
    thread.join(timeout=2)
    listener.close()
    assert finished.is_set() and not thread.is_alive()


@pytest.mark.parametrize("mutation", ["phase", "digest", "mac", "failed"])
def test_two_phase_control_rejects_adversarial_ack(mutation: str) -> None:
    session = "session-abcdefghijklmnopqrstuv"
    digest = hashlib.sha256(b"payload").digest()
    wire = io.BytesIO()
    write_control(
        wire,
        KEY,
        session,
        phase=CONTROL_SPOOL_ACCEPTED,
        ok=mutation != "failed",
        frames=1,
        total=7,
        digest=digest,
    )
    raw = bytearray(wire.getvalue())
    if mutation == "phase":
        raw[1] = CONTROL_CONSUMER_RESULT
    elif mutation == "digest":
        raw[20] ^= 1
    elif mutation == "mac":
        raw[-1] ^= 1
    with pytest.raises(TcpTransferRejected):
        read_control(
            io.BytesIO(raw),
            KEY,
            session,
            expected_phase=CONTROL_SPOOL_ACCEPTED,
            frames=1,
            total=7,
            digest=digest,
        )
