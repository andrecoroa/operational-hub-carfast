"""Offline synthetic rehearsal for resumable preseed plus bounded final delta."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

from app.platform.storage_preseed_delta import (
    assert_secure_storage_exact,
    assert_storage_exact,
    build_secure_storage_manifest,
    build_stable_storage_manifest,
    calculate_delta,
    secure_sync_manifest,
    storage_manifest_digest,
    sync_manifest,
)


def _write_pattern(path: Path, size: int, byte: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    chunk = bytes([byte]) * (1024 * 1024)
    with path.open("wb") as handle:
        remaining = size
        while remaining:
            part = chunk[:remaining]
            handle.write(part)
            remaining -= len(part)


def run(total_bytes: int, final_budget_seconds: float) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="carfast-preseed-delta-") as temporary:
        root = Path(temporary)
        source, staging = root / "source", root / "staging"
        source.mkdir()
        staging.mkdir(mode=0o700)
        portions = (total_bytes // 2, total_bytes // 3)
        _write_pattern(source / "documents" / "stable.bin", portions[0], 0x31)
        _write_pattern(source / "documents" / "mutable.bin", portions[1], 0x32)
        _write_pattern(source / "audit" / "removed.bin", total_bytes - sum(portions), 0x33)
        secure = os.name == "posix"
        build = build_secure_storage_manifest if secure else build_stable_storage_manifest
        sync = secure_sync_manifest if secure else sync_manifest
        assert_exact = assert_secure_storage_exact if secure else assert_storage_exact
        preseed = build(source, synthetic_only=True)
        interrupted = False
        try:
            sync(source, staging, preseed, interrupt_after=1, synthetic_only=True)
        except InterruptedError:
            interrupted = True
        resumed = sync(source, staging, preseed, synthetic_only=True)
        assert_exact(staging, preseed, synthetic_only=True) if secure else assert_exact(
            staging, preseed
        )

        (source / "documents" / "mutable.bin").write_bytes(b"final-mutated-object")
        (source / "audit" / "removed.bin").unlink()
        (source / "documents" / "stable.bin").rename(source / "documents" / "renamed.bin")
        _write_pattern(source / "documents" / "new.bin", 4 * 1024 * 1024, 0x34)
        started = time.monotonic()
        final = build(source, synthetic_only=True)
        delta = calculate_delta(preseed, final)
        applied = sync(source, staging, delta.copy, remove=delta.remove, synthetic_only=True)
        assert_exact(staging, final, synthetic_only=True) if secure else assert_exact(
            staging, final
        )
        elapsed = time.monotonic() - started
        if elapsed >= final_budget_seconds:
            raise RuntimeError("synthetic final delta exceeded its closed budget")
        return {
            "result": "PASS",
            "preseed_bytes": sum(item.size for item in preseed),
            "preseed_manifest_sha256": storage_manifest_digest(preseed),
            "interruption_observed": interrupted,
            "resume_copied": resumed.copied,
            "resume_skipped": resumed.skipped,
            "delta_copy_objects": len(delta.copy),
            "delta_remove_objects": len(delta.remove),
            "delta_bytes": applied.bytes_copied,
            "final_manifest_sha256": storage_manifest_digest(final),
            "final_phase_seconds": round(elapsed, 6),
            "final_budget_seconds": final_budget_seconds,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--final-budget-seconds", type=float, default=900.0)
    args = parser.parse_args()
    print(json.dumps(run(args.bytes, args.final_budget_seconds), sort_keys=True))


if __name__ == "__main__":
    main()
