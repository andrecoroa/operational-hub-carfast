from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.platform.integral_reconciliation import IntegralReconciliationError, StorageEvidence
from app.platform.storage_preseed_delta import storage_manifest_digest, validate_storage_manifest
from scripts.standard_bundle_ack import (
    _digest_fd,
    _open_regular,
    _safe_member,
    canonical,
    secret,
    validate_manifest,
)


def _manifest() -> dict:
    before = (StorageEvidence("-leading.bin", 1, "1" * 64),)
    after = (StorageEvidence("new.bin", 2, "2" * 64),)
    deletions = ["-leading.bin"]
    artifacts = [
        {
            "name": f"{role}-1.age",
            "role": role,
            "ciphertext_sha256": "3" * 64,
            "ciphertext_size": 1,
            "plaintext_sha256": "4" * 64,
            "plaintext_size": 1,
        }
        for role in ("preseed", "db", "delta")
    ]
    return {
        "bundle_id": "synthetic-1",
        "cutoff_utc": datetime.now(UTC).isoformat(),
        "source_release": "a" * 40,
        "target_release": "b" * 40,
        "preseed_manifest_sha256": storage_manifest_digest(before),
        "final_manifest_sha256": storage_manifest_digest(after),
        "preseed_objects": [
            {"path": item.path, "size": item.size, "sha256": item.sha256} for item in before
        ],
        "final_objects": [
            {"path": item.path, "size": item.size, "sha256": item.sha256} for item in after
        ],
        "deletion_paths": deletions,
        "deletion_manifest_sha256": hashlib.sha256(canonical(deletions)).hexdigest(),
        "deletion_count": 1,
        "artifacts": artifacts,
    }


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda value: value.update(extra=True), "invalid_bundle_manifest_shape"),
        (lambda value: value.update(source_release="not-a-sha"), "invalid_bundle_release"),
        (lambda value: value.update(cutoff_utc="not-a-date"), "invalid_bundle_cutoff"),
        (lambda value: value.update(deletion_count=0), "deletion_manifest_mismatch"),
        (lambda value: value.update(deletion_paths=[]), "deletion_manifest_mismatch"),
        (lambda value: value["artifacts"].pop(), "incomplete_bundle_artifacts"),
        (
            lambda value: value["artifacts"][1].update(role="preseed"),
            "invalid_bundle_artifact_role",
        ),
    ],
)
def test_bundle_contract_fails_closed_before_artifact_consumption(mutation, error, tmp_path: Path):
    manifest = _manifest()
    mutation(manifest)
    with pytest.raises(SystemExit, match=error):
        validate_manifest(
            manifest,
            tmp_path,
            tmp_path / "identity",
            tmp_path / "plaintext",
            expected_bundle_id=manifest["bundle_id"],
            expected_cutoff_utc=manifest["cutoff_utc"],
            expected_source_release=manifest["source_release"],
            expected_target_release=manifest["target_release"],
        )


def test_storage_contract_accepts_leading_dash_but_rejects_control_characters():
    validate_storage_manifest((StorageEvidence("-leading.bin", 1, "1" * 64),))
    with pytest.raises(IntegralReconciliationError, match="unsafe storage path"):
        validate_storage_manifest((StorageEvidence("line\nbreak.bin", 1, "1" * 64),))


@pytest.mark.parametrize(
    ("claim", "wrong"),
    (
        ("bundle_id", "synthetic-2"),
        ("cutoff_utc", None),
        ("source_release", "c" * 40),
        ("target_release", "d" * 40),
    ),
)
def test_receiver_expected_claims_fail_before_opening_artifacts(
    tmp_path: Path, claim: str, wrong: str | None
):
    manifest = _manifest()
    expected = {
        "bundle_id": manifest["bundle_id"],
        "cutoff_utc": manifest["cutoff_utc"],
        "source_release": manifest["source_release"],
        "target_release": manifest["target_release"],
    }
    expected[claim] = wrong
    with pytest.raises(SystemExit, match="bundle_expected_claim_mismatch"):
        validate_manifest(
            manifest,
            tmp_path,
            tmp_path / "identity",
            tmp_path / "plaintext",
            expected_bundle_id=expected["bundle_id"],
            expected_cutoff_utc=expected["cutoff_utc"],
            expected_source_release=expected["source_release"],
            expected_target_release=expected["target_release"],
        )


def test_tar_root_member_is_canonical():
    assert _safe_member("./") == "."
    assert _safe_member(".") == "."


@pytest.mark.parametrize("name", ("../escape", "/absolute", "line\nbreak", "a/../../b"))
def test_tar_member_paths_fail_closed(name: str):
    with pytest.raises(SystemExit, match="unsafe_tar_member"):
        _safe_member(name)


def test_standard_rehearsal_uses_nul_verbatim_tar_file_list():
    source = Path("scripts/run_storage_preseed_delta_standard_rehearsal.sh").read_text()
    assert "--null --verbatim-files-from --files-from=" in source
    assert 'handle.write(path.encode("utf-8") + b"\\0")' in source


def test_receiver_validator_imports_with_stdlib_only():
    result = subprocess.run(
        [sys.executable, "-S", "-c", "import scripts.standard_bundle_ack"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name != "posix", reason="requires Linux openat/O_NOFOLLOW")
def test_open_descriptor_survives_path_replacement(tmp_path: Path):
    original = tmp_path / "artifact.age"
    original.write_bytes(b"validated")
    original.chmod(0o600)
    descriptor = _open_regular(original)
    try:
        replacement = tmp_path / "replacement"
        replacement.write_bytes(b"attacker")
        replacement.chmod(0o600)
        replacement.replace(original)
        assert _digest_fd(descriptor) == (9, hashlib.sha256(b"validated").hexdigest())
    finally:
        os.close(descriptor)


@pytest.mark.skipif(os.name != "posix", reason="requires Linux openat/O_NOFOLLOW")
def test_secret_consumes_open_inode_when_name_is_replaced(tmp_path: Path, monkeypatch):
    path = tmp_path / "secret"
    path.write_bytes(b"A" * 32)
    path.chmod(0o600)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"B" * 32)
    replacement.chmod(0o600)
    real_read = os.read
    replaced = False

    def swapping_read(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        if not replaced:
            replacement.replace(path)
            replaced = True
        return real_read(descriptor, size)

    monkeypatch.setattr(os, "read", swapping_read)
    assert secret(path) == b"A" * 32


@pytest.mark.skipif(os.name != "posix", reason="requires Linux openat/O_NOFOLLOW")
def test_symlink_and_non_regular_inputs_fail_closed(tmp_path: Path):
    regular = tmp_path / "regular"
    regular.write_bytes(b"x")
    regular.chmod(0o600)
    (tmp_path / "link").symlink_to(regular)
    with pytest.raises(SystemExit, match="invalid_regular_input"):
        _open_regular(tmp_path / "link")
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, mode=0o600)
    with pytest.raises(SystemExit, match="invalid_regular_input"):
        _open_regular(fifo)


def test_standard_rehearsal_materializes_before_ack_and_requires_digest():
    source = Path("scripts/run_storage_preseed_delta_standard_rehearsal.sh").read_text()
    assert "--plaintext-root" in source
    assert "--expected-bundle-id" in source
    assert "--expected-cutoff-utc" in source
    assert "<\"${work}/preseed-${run}.age\"" not in source
    assert "<\"${work}/delta-${run}.age\"" not in source
    assert "CARFAST_POSTGRES_IMAGE must be an immutable RepoDigest" in source
    assert "@sha256:[0-9a-f]{64}" in source
    receiver = Path("scripts/standard_bundle_ack.py").read_text()
    main = receiver[receiver.index("def main()") :]
    assert main.index("validate_manifest(") < main.index("args.ack.write_text(")
