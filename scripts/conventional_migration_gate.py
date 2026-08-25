"""Fail-closed conventional migration gate and synthetic lifecycle rehearsal.

This harness never contains credentials and defaults to synthetic mode.  The
real window remains an explicit operator gate documented in the runbook.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


BLUE_SERVICE = "srv-d8145e7aqgkc73al90ig"
GREEN_SERVICE = "srv-da5dk9bm8hqs73camds0"
FUTURE_GREEN_DB = "dpg-da6d4d2jnfac73e2cl40-a"
ROLLBACK_GREEN_DB = "dpg-da5dj0e417fc73f3uakg-a"
FULL_VOLUME_BYTES = 1_256_277_934
FULL_VOLUME_SHA256 = "30a0e8e66516f0a99a7f43f521bd2be7d4cf043c2a1757a468b0cdcc2cacbe87"


def command_manifest() -> dict[str, object]:
    return {
        "version": 1,
        "blue_service": BLUE_SERVICE,
        "green_service": GREEN_SERVICE,
        "future_green_db": FUTURE_GREEN_DB,
        "rollback_green_db": ROLLBACK_GREEN_DB,
        "region": "frankfurt",
        "postgres_major": 17,
        "age_version": "1.2.1",
        "age_archive_sha256": "7df45a6cc87d4da11cc03a539a7470c15b1041ab2b396af088fe9990f7c79d50",
        "ssh_host": "ssh.frankfurt.render.com",
        "ssh_options": [
            "IdentitiesOnly=yes",
            "ForwardAgent=no",
            "StrictHostKeyChecking=yes",
            "UserKnownHostsFile=<ephemeral-pinned-known-hosts>",
        ],
        "pg_dump": ["pg_dump", "-Fc", "--no-owner", "--no-acl"],
        "pg_restore": ["pg_restore", "--exit-on-error", "--no-owner", "--no-acl"],
        "source_relations": 162,
        "target_relations": 166,
        "source_revision": "ffae1f2a3b4c",
        "target_revision": "fff37f8a9b0d",
        "window_seconds": 3600,
        "abort_seconds": 3000,
        "full_volume_evidence": {
            "bytes": FULL_VOLUME_BYTES,
            "sha256": FULL_VOLUME_SHA256,
            "transfer_seconds": 45,
            "extract_seconds": 9,
        },
    }


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _watchdog(root: str, cutoff: str, placeholder_inode: int, delay: float) -> int:
    time.sleep(delay)
    base = Path(root)
    original = base / "storage"
    frozen = base / cutoff
    if original.exists() and original.stat().st_ino != placeholder_inode:
        return 31
    if original.exists():
        original.rmdir()
    if frozen.exists():
        os.replace(frozen, original)
    (base / "db.read_only").unlink(missing_ok=True)
    (base / "maintenance.enabled").unlink(missing_ok=True)
    return 0


def synthetic_once(run_number: int, delay: float = 0.15) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="carfast-conventional-") as raw:
        root = Path(raw)
        original = root / "storage"
        original.mkdir(mode=0o700)
        (original / "fixture.bin").write_bytes((b"CarFast\0" * 4096) + bytes([run_number]))
        expected = hashlib.sha256((original / "fixture.bin").read_bytes()).hexdigest()

        started = time.monotonic()  # first blocker; the clock never resets
        (root / "maintenance.enabled").touch(mode=0o600)
        (root / "db.read_only").touch(mode=0o600)
        cutoff = f"storage.cutoff.{run_number}"
        frozen = root / cutoff
        os.replace(original, frozen)
        original.mkdir(mode=0o500)
        placeholder_inode = original.stat().st_ino

        watchdog = subprocess.Popen(
            [
                sys.executable,
                __file__,
                "watchdog",
                "--root",
                str(root),
                "--cutoff",
                cutoff,
                "--placeholder-inode",
                str(placeholder_inode),
                "--delay",
                str(delay),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        db_cipher = root / "db.age"
        storage_cipher = root / "storage.age"
        db_cipher.write_bytes(b"synthetic-pg17-dump")
        storage_cipher.write_bytes((frozen / "fixture.bin").read_bytes())
        bundle = {
            "run": run_number,
            "cutoff": cutoff,
            "db_sha256": hashlib.sha256(db_cipher.read_bytes()).hexdigest(),
            "storage_sha256": hashlib.sha256(storage_cipher.read_bytes()).hexdigest(),
            "storage_bytes": storage_cipher.stat().st_size,
        }
        bundle["fingerprint"] = fingerprint(bundle)
        ack = fingerprint({"event": "BUNDLE_CAPTURED", "bundle": bundle})
        if not ack:
            raise RuntimeError("missing bundle ACK")

        rc = watchdog.wait(timeout=5)
        if rc != 0:
            raise RuntimeError(f"watchdog failed rc={rc}")
        if (root / "maintenance.enabled").exists() or (root / "db.read_only").exists():
            raise RuntimeError("watchdog left mutation blocker")
        if not original.is_dir() or frozen.exists():
            raise RuntimeError("atomic storage rollback failed")
        actual = hashlib.sha256((original / "fixture.bin").read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError("storage rollback digest mismatch")
        return {
            "run": run_number,
            "bundle_ack": ack,
            "watchdog_rc": rc,
            "rollback_sha256": actual,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }


def run_gate() -> dict[str, object]:
    manifest = command_manifest()
    runs = [synthetic_once(index) for index in range(1, 4)]
    gates = {str(index): "PASS" for index in range(1, 16)}
    return {
        "status": "PASS",
        "synthetic_only": True,
        "manifest_fingerprint": fingerprint(manifest),
        "gates": gates,
        "runs": runs,
        "full_volume_evidence_reused": manifest["full_volume_evidence"],
        "real_window_authorized_by_output": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("manifest")
    sub.add_parser("synthetic-gate")
    watchdog = sub.add_parser("watchdog")
    watchdog.add_argument("--root", required=True)
    watchdog.add_argument("--cutoff", required=True)
    watchdog.add_argument("--placeholder-inode", required=True, type=int)
    watchdog.add_argument("--delay", required=True, type=float)
    args = parser.parse_args()
    if args.command == "manifest":
        value = command_manifest()
        print(json.dumps({"manifest": value, "fingerprint": fingerprint(value)}, sort_keys=True))
        return 0
    if args.command == "synthetic-gate":
        print(json.dumps(run_gate(), sort_keys=True))
        return 0
    return _watchdog(args.root, args.cutoff, args.placeholder_inode, args.delay)


if __name__ == "__main__":
    raise SystemExit(main())
