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
from app.platform.integral_tcp import FramedReader, write_framed

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
    total = int(os.environ.get("SYNTHETIC_SPOOL_BYTES", MINIMUM_BYTES))
    if total < MINIMUM_BYTES:
        raise SystemExit("synthetic payload below 1.17 GiB gate")
    spool = Path(os.environ.get("SYNTHETIC_SPOOL_PATH", "/tmp/carfast-synthetic.spool"))
    key = bytearray(os.urandom(32))
    started = time.monotonic()
    address = ("0.0.0.0", int(os.environ.get("PORT", "10000")))
    health = http.server.ThreadingHTTPServer(address, Health)
    thread = threading.Thread(target=health.serve_forever, daemon=True)
    thread.start()
    try:
        expected = synthetic_digest(total)
        transfer_key = b"synthetic-transfer-key-material-32b"
        session = "synthetic-session-abcdefghijklmnop"
        sender, receiver = socket.socketpair()
        outcome: dict[str, tuple[int, int, str]] = {}

        def send() -> None:
            with sender:
                outcome["result"] = write_framed(
                    SyntheticReader(total),
                    sender.makefile("wb", buffering=0),
                    transfer_key,
                    session,
                )
                sender.shutdown(socket.SHUT_WR)

        sending = threading.Thread(target=send)
        sending.start()
        with receiver:
            framed = FramedReader(
                receiver.makefile("rb", buffering=0), transfer_key, session
            )
            evidence = encrypt_verified_stream(
                framed, spool, key, max_bytes=total
            )
        sending.join(timeout=120)
        if sending.is_alive() or outcome["result"][1:] != (total, expected):
            raise SystemExit("synthetic framed sender evidence mismatch")
        encrypted_size = spool.stat().st_size
        observed = hashlib.sha256()
        observed_bytes = 0
        for chunk in iter_decrypted_spool(spool, key, evidence):
            observed.update(chunk)
            observed_bytes += len(chunk)
        if observed_bytes != total or observed.hexdigest() != expected:
            raise SystemExit("synthetic decrypted evidence mismatch")
        elapsed = time.monotonic() - started
        print(f"synthetic_spool_bytes={total}", flush=True)
        print(f"synthetic_encrypted_bytes={encrypted_size}", flush=True)
        print(f"synthetic_chunks={evidence.chunks}", flush=True)
        print(f"synthetic_digest={expected}", flush=True)
        print(f"synthetic_elapsed_seconds={elapsed:.3f}", flush=True)
        print("synthetic_health_listener_separate=true", flush=True)
        print("synthetic_rehearsal_passed=true", flush=True)
    finally:
        health.shutdown()
        destroy_spool(spool, key)
        print(f"synthetic_spool_absent={str(not spool.exists()).lower()}", flush=True)
        print(f"synthetic_key_zeroed={str(key == bytearray(32)).lower()}", flush=True)
        print(f"synthetic_free_bytes={shutil.disk_usage(spool.parent).free}", flush=True)


if __name__ == "__main__":
    main()
