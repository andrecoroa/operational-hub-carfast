"""Produce sanitized ciphertext/plaintext evidence for one synthetic age artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def digest_stream(handle) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.artifact.is_symlink() or args.identity.is_symlink():
        raise SystemExit("symlink_forbidden")
    with args.artifact.open("rb") as handle:
        ciphertext_size, ciphertext_sha = digest_stream(handle)
    process = subprocess.Popen(
        ["age", "-d", "-i", str(args.identity), str(args.artifact)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert process.stdout is not None
    plaintext_size, plaintext_sha = digest_stream(process.stdout)
    if process.wait(timeout=120) != 0:
        raise SystemExit("age_decrypt_failed")
    payload = {
        "name": args.artifact.name,
        "ciphertext_sha256": ciphertext_sha,
        "ciphertext_size": ciphertext_size,
        "plaintext_sha256": plaintext_sha,
        "plaintext_size": plaintext_size,
    }
    args.output.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
