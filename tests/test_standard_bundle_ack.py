from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.platform.integral_reconciliation import IntegralReconciliationError, StorageEvidence
from app.platform.storage_preseed_delta import storage_manifest_digest, validate_storage_manifest
from scripts.standard_bundle_ack import _safe_member, canonical, validate_manifest


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
        validate_manifest(manifest, tmp_path, tmp_path / "identity")


def test_storage_contract_accepts_leading_dash_but_rejects_control_characters():
    validate_storage_manifest((StorageEvidence("-leading.bin", 1, "1" * 64),))
    with pytest.raises(IntegralReconciliationError, match="unsafe storage path"):
        validate_storage_manifest((StorageEvidence("line\nbreak.bin", 1, "1" * 64),))


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
