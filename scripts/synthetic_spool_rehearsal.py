"""Render-only synthetic load rehearsal for the encrypted spool receiver."""

from __future__ import annotations

import hashlib
import http.server
import os
import shutil
import socket
import threading
import time
from pathlib import Path

from app.platform.encrypted_spool import (
    CHUNK_BYTES,
    destroy_spool,
    encrypt_verified_stream,
    iter_decrypted_spool,
)
from app.platform.integral_tcp import (
    CONTROL_BUNDLE_SPOOL_ACCEPTED,
    CONTROL_CONSUMER_RESULT,
    FramedReader,
    client_handshake,
    ensure_no_trailing,
    issue_tcp_token,
    read_control,
    server_handshake,
    write_control,
    write_framed,
)

MINIMUM_BYTES = 1_256_277_934  # 1.17 GiB


class SyntheticReader:
    def __init__(self, total: int) -> None:
        self.remaining = total
        self.pattern = hashlib.sha256(b"carfast-synthetic-spool-v1").digest()

    def read(self, size: int = -1) -> bytes:
        if self.remaining == 0:
            return b""
        amount = min(self.remaining, CHUNK_BYTES if size < 0 else size)
        chunk = (self.pattern * ((amount + len(self.pattern) - 1) // len(self.pattern)))[:amount]
        self.remaining -= amount
        return chunk


def synthetic_digest(total: int) -> str:
    source = SyntheticReader(total)
    digest = hashlib.sha256()
    while chunk := source.read(CHUNK_BYTES):
        digest.update(chunk)
    return digest.hexdigest()


class Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/healthz":
            self.send_response(404)
        else:
            self.send_response(200)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    if os.environ.get("INTEGRAL_ENTRYPOINT_DELEGATED") != "1":
        raise SystemExit("synthetic_spool_direct_execution_rejected")
    total = int(os.environ.get("SYNTHETIC_SPOOL_BYTES", MINIMUM_BYTES))
    if total < MINIMUM_BYTES:
        raise SystemExit("synthetic payload below 1.17 GiB gate")
    spool_root = Path(os.environ.get("SYNTHETIC_SPOOL_ROOT", "/tmp"))
    started = time.monotonic()
    address = ("0.0.0.0", int(os.environ.get("PORT", "10000")))
    health = http.server.ThreadingHTTPServer(address, Health)
    thread = threading.Thread(target=health.serve_forever, daemon=True)
    thread.start()
    try:
        sizes = {"database": 208 * 1024 * 1024, "storage": total - 208 * 1024 * 1024}
        expected = {name: synthetic_digest(size) for name, size in sizes.items()}
        transfer_key = b"synthetic-transfer-key-material-32b"
        source, destination = "srv-synthetic-blue", "srv-synthetic-green"
        release, cutoff, bundle = "a" * 40, "cut-synthetic", "bundle-synthetic"
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        outcome: dict[str, tuple[int, int, str]] = {}
        pending: dict[str, tuple[object, object, str, FramedReader, Path, bytearray, object]] = {}

        def send(stream_type: str) -> None:
            with socket.create_connection(listener.getsockname(), timeout=30) as sender:
                token = issue_tcp_token(
                    transfer_key,
                    source=source,
                    destination=destination,
                    release=release,
                    cutoff=cutoff,
                    bundle_id=bundle,
                    stream_type=stream_type,
                )
                handle, session = client_handshake(sender, token, stream_type)
                result = write_framed(
                    SyntheticReader(sizes[stream_type]), handle, transfer_key, session
                )
                frames, sent, digest_hex = result
                digest = bytes.fromhex(digest_hex)
                read_control(
                    handle,
                    transfer_key,
                    session,
                    expected_phase=CONTROL_BUNDLE_SPOOL_ACCEPTED,
                    frames=frames,
                    total=sent,
                    digest=digest,
                )
                sender.shutdown(socket.SHUT_WR)
                read_control(
                    handle,
                    transfer_key,
                    session,
                    expected_phase=CONTROL_CONSUMER_RESULT,
                    frames=frames,
                    total=sent,
                    digest=digest,
                )
                outcome[stream_type] = result

        # Storage starts first to prove inverse-order acceptance.
        senders = [threading.Thread(target=send, args=(name,)) for name in ("storage", "database")]
        for sending in senders:
            sending.start()
        used_nonces: set[str] = set()
        for _ in range(2):
            receiver, _address = listener.accept()
            handle, session, stream_type = server_handshake(
                receiver,
                transfer_key,
                source=source,
                destination=destination,
                release=release,
                cutoff=cutoff,
                bundle_id=bundle,
                stream_type=None,
                used_nonces=used_nonces,
            )
            if stream_type in pending:
                raise SystemExit("synthetic duplicate bundle stream")
            framed = FramedReader(handle, transfer_key, session)
            spool = spool_root / f"carfast-synthetic-{stream_type}.spool"
            key = bytearray(os.urandom(32))
            evidence = encrypt_verified_stream(framed, spool, key, max_bytes=sizes[stream_type])
            pending[stream_type] = (receiver, handle, session, framed, spool, key, evidence)
        listener.close()
        if set(pending) != {"database", "storage"}:
            raise SystemExit("synthetic bundle incomplete")
        # No ACK is emitted until both encrypted spools are complete.
        for _stream_type, (
            _receiver,
            handle,
            session,
            framed,
            _spool,
            _key,
            evidence,
        ) in pending.items():
            digest = bytes.fromhex(evidence.sha256)
            write_control(
                handle,
                transfer_key,
                session,
                phase=CONTROL_BUNDLE_SPOOL_ACCEPTED,
                ok=True,
                frames=framed.expected_sequence,
                total=evidence.bytes,
                digest=digest,
            )
        for _stream_type, (
            _receiver,
            handle,
            _session,
            _framed,
            _spool,
            _key,
            _evidence,
        ) in pending.items():
            ensure_no_trailing(handle)
        encrypted_size = 0
        total_chunks = 0
        for stream_type, (
            _receiver,
            handle,
            session,
            framed,
            spool,
            key,
            evidence,
        ) in pending.items():
            digest = bytes.fromhex(evidence.sha256)
            observed = hashlib.sha256()
            observed_bytes = 0
            for chunk in iter_decrypted_spool(spool, key, evidence):
                observed.update(chunk)
                observed_bytes += len(chunk)
            if (
                observed_bytes != sizes[stream_type]
                or observed.hexdigest() != expected[stream_type]
            ):
                raise SystemExit("synthetic decrypted evidence mismatch")
            encrypted_size += spool.stat().st_size
            total_chunks += evidence.chunks
            write_control(
                handle,
                transfer_key,
                session,
                phase=CONTROL_CONSUMER_RESULT,
                ok=True,
                frames=framed.expected_sequence,
                total=evidence.bytes,
                digest=digest,
            )
        for sending in senders:
            sending.join(timeout=120)
        if any(sending.is_alive() for sending in senders):
            raise SystemExit("synthetic bundle sender timeout")
        for name in sizes:
            if outcome[name][1:] != (sizes[name], expected[name]):
                raise SystemExit("synthetic framed sender evidence mismatch")
        elapsed = time.monotonic() - started
        print(f"synthetic_spool_bytes={total}", flush=True)
        print(f"synthetic_encrypted_bytes={encrypted_size}", flush=True)
        print(f"synthetic_chunks={total_chunks}", flush=True)
        print(f"synthetic_database_digest={expected['database']}", flush=True)
        print(f"synthetic_storage_digest={expected['storage']}", flush=True)
        print("synthetic_bundle_spool_accepted=true", flush=True)
        print(f"synthetic_elapsed_seconds={elapsed:.3f}", flush=True)
        print("synthetic_health_listener_separate=true", flush=True)
        print("synthetic_rehearsal_passed=true", flush=True)
    finally:
        health.shutdown()
        for item in locals().get("pending", {}).values():
            receiver, _handle, _session, _framed, spool, key, _evidence = item
            destroy_spool(spool, key)
            receiver.close()
        absent = not any(spool_root.glob("carfast-synthetic-*.spool"))
        zeroed = all(item[5] == bytearray(32) for item in locals().get("pending", {}).values())
        print(f"synthetic_spool_absent={str(absent).lower()}", flush=True)
        print(f"synthetic_key_zeroed={str(zeroed).lower()}", flush=True)
        print(f"synthetic_free_bytes={shutil.disk_usage(spool_root).free}", flush=True)


if __name__ == "__main__":
    main()
