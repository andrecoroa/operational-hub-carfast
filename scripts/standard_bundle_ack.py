"""Emit or verify a closed HMAC ACK for a synthetic standard migration bundle."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import stat
import subprocess
import time
from pathlib import Path

SHAPE = {
    "bundle_id",
    "cutoff_utc",
    "source_release",
    "target_release",
    "preseed_manifest_sha256",
    "final_manifest_sha256",
    "deletion_count",
    "artifacts",
}
ARTIFACT_SHAPE = {
    "name",
    "ciphertext_sha256",
    "ciphertext_size",
    "plaintext_sha256",
    "plaintext_size",
}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def secret(path: Path) -> bytes:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise SystemExit("invalid_ack_secret")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise SystemExit("invalid_ack_secret_mode")
    value = path.read_bytes()
    if len(value) < 32:
        raise SystemExit("invalid_ack_secret_length")
    return value


def validate_manifest(manifest: dict, artifact_root: Path, identity: Path) -> None:
    if set(manifest) != SHAPE or not isinstance(manifest["artifacts"], list):
        raise SystemExit("invalid_bundle_manifest_shape")
    names: set[str] = set()
    for artifact in manifest["artifacts"]:
        if set(artifact) != ARTIFACT_SHAPE:
            raise SystemExit("invalid_bundle_artifact_shape")
        name = artifact["name"]
        if not isinstance(name, str) or Path(name).name != name or not name.endswith(".age"):
            raise SystemExit("invalid_bundle_artifact_name")
        if name in names:
            raise SystemExit("duplicate_bundle_artifact")
        names.add(name)
        path = artifact_root / name
        if path.is_symlink() or digest_file(path) != (
            artifact["ciphertext_size"],
            artifact["ciphertext_sha256"],
        ):
            raise SystemExit("ciphertext_evidence_mismatch")
        process = subprocess.Popen(
            ["age", "-d", "-i", str(identity), str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert process.stdout is not None
        digest = hashlib.sha256()
        size = 0
        while chunk := process.stdout.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
        if process.wait(timeout=900) != 0 or (size, digest.hexdigest()) != (
            artifact["plaintext_size"],
            artifact["plaintext_sha256"],
        ):
            raise SystemExit("plaintext_evidence_mismatch")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("emit", "verify"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--secret", type=Path, required=True)
    parser.add_argument("--ack", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--identity", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    key = secret(args.secret)
    manifest_sha = hashlib.sha256(canonical(manifest)).hexdigest()
    if args.mode == "emit":
        if args.artifact_root is None or args.identity is None:
            raise SystemExit("receiver_inputs_missing")
        validate_manifest(manifest, args.artifact_root, args.identity)
        payload = {
            "ack": "BUNDLE_CAPTURED",
            "bundle_id": manifest["bundle_id"],
            "cutoff_utc": manifest["cutoff_utc"],
            "source_release": manifest["source_release"],
            "target_release": manifest["target_release"],
            "manifest_sha256": manifest_sha,
            "issued_at": int(time.time()),
        }
        output = {
            **payload,
            "hmac_sha256": hmac.new(key, canonical(payload), hashlib.sha256).hexdigest(),
        }
        args.ack.write_text(json.dumps(output, sort_keys=True) + "\n", encoding="utf-8")
        return
    ack = json.loads(args.ack.read_text(encoding="utf-8"))
    signature = ack.pop("hmac_sha256", "")
    expected = hmac.new(key, canonical(ack), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise SystemExit("ack_hmac_mismatch")
    if (
        ack
        != {
            "ack": "BUNDLE_CAPTURED",
            "bundle_id": manifest["bundle_id"],
            "cutoff_utc": manifest["cutoff_utc"],
            "source_release": manifest["source_release"],
            "target_release": manifest["target_release"],
            "manifest_sha256": manifest_sha,
            "issued_at": ack["issued_at"],
        }
        or abs(int(time.time()) - ack["issued_at"]) > 300
    ):
        raise SystemExit("ack_claim_mismatch")
    print(f"bundle_id={ack['bundle_id']} ack=BUNDLE_CAPTURED valid=true")


if __name__ == "__main__":
    main()
