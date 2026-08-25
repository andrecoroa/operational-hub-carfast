"""Emit or verify a closed HMAC ACK for a synthetic standard migration bundle."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
import tarfile
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

SHAPE = {
    "bundle_id", "cutoff_utc", "source_release", "target_release",
    "preseed_manifest_sha256", "final_manifest_sha256", "preseed_objects",
    "final_objects", "deletion_paths", "deletion_manifest_sha256",
    "deletion_count", "artifacts",
}
ARTIFACT_SHAPE = {
    "name", "role", "ciphertext_sha256", "ciphertext_size",
    "plaintext_sha256", "plaintext_size",
}
OBJECT_SHAPE = {"path", "size", "sha256"}
ROLES = {"preseed", "db", "delta"}
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
RELEASE = re.compile(r"[0-9a-f]{40}\Z")
BUNDLE = re.compile(r"synthetic-([1-9][0-9]*)\Z")


@dataclass(frozen=True, slots=True)
class StorageEvidence:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class StorageDelta:
    copy: tuple[StorageEvidence, ...]
    remove: tuple[str, ...]


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _open_regular(path: Path) -> int:
    try:
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            descriptor = os.open(
                path.name,
                os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
                dir_fd=parent,
            )
        finally:
            os.close(parent)
    except OSError:
        raise SystemExit("invalid_regular_input") from None
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        os.close(descriptor)
        raise SystemExit("invalid_regular_input")
    return descriptor


def _digest_fd(descriptor: int) -> tuple[int, str]:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    size = 0
    while chunk := os.read(descriptor, 1024 * 1024):
        size += len(chunk)
        digest.update(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return size, digest.hexdigest()


def secret(path: Path) -> bytes:
    descriptor = _open_regular(path)
    try:
        metadata = os.fstat(descriptor)
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise SystemExit("invalid_ack_secret_mode")
        value = os.read(descriptor, 4097)
    finally:
        os.close(descriptor)
    if len(value) < 32:
        raise SystemExit("invalid_ack_secret_length")
    return value


def _age_process(artifact: int, identity: int) -> subprocess.Popen[bytes]:
    os.lseek(artifact, 0, os.SEEK_SET)
    return subprocess.Popen(
        ["age", "-d", "-i", f"/proc/self/fd/{identity}"],
        stdin=artifact,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        pass_fds=(identity,),
    )


def _sha(value: object, error: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise SystemExit(error)
    return value


def _validate_objects(items: tuple[StorageEvidence, ...]) -> None:
    previous = ""
    folded: dict[str, str] = {}
    for item in items:
        path = PurePosixPath(item.path)
        if (
            not item.path
            or path.is_absolute()
            or ".." in path.parts
            or item.path != path.as_posix()
            or unicodedata.normalize("NFC", item.path) != item.path
            or any(ord(character) < 32 or ord(character) == 127 for character in item.path)
            or item.path <= previous
            or type(item.size) is not int
            or item.size < 0
            or HEX64.fullmatch(item.sha256) is None
        ):
            raise ValueError("invalid storage object")
        casefolded = item.path.casefold()
        if casefolded in folded and folded[casefolded] != item.path:
            raise ValueError("case-colliding storage object")
        folded[casefolded] = item.path
        previous = item.path


def _storage_manifest_digest(items: tuple[StorageEvidence, ...]) -> str:
    _validate_objects(items)
    return hashlib.sha256(canonical([asdict(item) for item in items])).hexdigest()


def _calculate_delta(
    preseed: tuple[StorageEvidence, ...], final: tuple[StorageEvidence, ...]
) -> StorageDelta:
    _validate_objects(preseed)
    _validate_objects(final)
    before = {item.path: item for item in preseed}
    after = {item.path: item for item in final}
    return StorageDelta(
        copy=tuple(after[path] for path in sorted(after) if before.get(path) != after[path]),
        remove=tuple(sorted(set(before) - set(after))),
    )


def _objects(value: object, error: str) -> tuple[StorageEvidence, ...]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SystemExit(error)
    if any(set(item) != OBJECT_SHAPE for item in value):
        raise SystemExit(error)
    try:
        result = tuple(StorageEvidence(**item) for item in value)
        _validate_objects(result)
    except (TypeError, ValueError):
        raise SystemExit(error) from None
    return result


def _safe_member(name: str) -> str:
    if name in {".", "./"}:
        return "."
    normalized = name.removeprefix("./")
    path = PurePosixPath(normalized)
    if (
        not normalized or path.is_absolute() or ".." in path.parts
        or normalized != path.as_posix()
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise SystemExit("unsafe_tar_member")
    return normalized


def _write_member(root: int, name: str, source) -> tuple[int, str]:
    parts = PurePosixPath(name).parts
    parent = os.dup(root)
    try:
        for component in parts[:-1]:
            try:
                os.mkdir(component, mode=0o700, dir_fd=parent)
            except FileExistsError:
                pass
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent,
            )
            os.close(parent)
            parent = child
        target = os.open(
            parts[-1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
        try:
            digest = hashlib.sha256()
            size = 0
            while chunk := source.read(1024 * 1024):
                view = memoryview(chunk)
                while view:
                    written = os.write(target, view)
                    if written <= 0:
                        raise SystemExit("short_materialized_write")
                    view = view[written:]
                size += len(chunk)
                digest.update(chunk)
            os.fsync(target)
            return size, digest.hexdigest()
        finally:
            os.close(target)
    finally:
        os.close(parent)


def _validate_tar(
    artifact: int,
    identity: int,
    expected: tuple[StorageEvidence, ...],
    destination: Path,
) -> None:
    expected_by_path = {item.path: item for item in expected}
    expected_directories = {"."}
    for item in expected:
        parent = PurePosixPath(item.path).parent
        while parent.as_posix() != ".":
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    observed: set[str] = set()
    destination.mkdir(mode=0o700)
    destination_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    process = _age_process(artifact, identity)
    assert process.stdout is not None
    failure: SystemExit | None = None
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|*") as archive:
            for member in archive:
                name = _safe_member(member.name)
                if member.isdir():
                    if name not in expected_directories:
                        raise SystemExit("invalid_tar_members")
                    continue
                if not member.isfile() or name in observed or name not in expected_by_path:
                    raise SystemExit("invalid_tar_members")
                source = archive.extractfile(member)
                if source is None:
                    raise SystemExit("invalid_tar_member_content")
                size, digest = _write_member(destination_fd, name, source)
                item = expected_by_path[name]
                if (size, digest) != (item.size, item.sha256):
                    raise SystemExit("tar_member_evidence_mismatch")
                observed.add(name)
    except SystemExit as error:
        failure = error
    except (OSError, tarfile.TarError):
        failure = SystemExit("invalid_tar_stream")
    finally:
        process.stdout.close()
        return_code = process.wait(timeout=900)
        os.fsync(destination_fd)
        os.close(destination_fd)
    if failure is not None:
        raise failure
    if return_code != 0 or observed != set(expected_by_path):
        raise SystemExit("tar_manifest_mismatch")


def _materialize_plaintext(
    artifact: int,
    identity: int,
    target: Path,
    expected: tuple[int, str],
) -> None:
    process = _age_process(artifact, identity)
    assert process.stdout is not None
    parent = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        size, digest = _write_member(parent, target.name, process.stdout)
        if process.wait(timeout=900) != 0 or (size, digest) != expected:
            os.unlink(target.name, dir_fd=parent)
            raise SystemExit("plaintext_materialization_mismatch")
    finally:
        os.close(parent)


def validate_manifest(
    manifest: dict,
    artifact_root: Path,
    identity: Path,
    plaintext_root: Path,
    *,
    expected_bundle_id: str,
    expected_cutoff_utc: str,
    expected_source_release: str,
    expected_target_release: str,
) -> None:
    if set(manifest) != SHAPE or not isinstance(manifest["artifacts"], list):
        raise SystemExit("invalid_bundle_manifest_shape")
    bundle_match = BUNDLE.fullmatch(manifest["bundle_id"])
    if bundle_match is None:
        raise SystemExit("invalid_bundle_id")
    if (
        manifest["bundle_id"] != expected_bundle_id
        or manifest["cutoff_utc"] != expected_cutoff_utc
        or manifest["source_release"] != expected_source_release
        or manifest["target_release"] != expected_target_release
    ):
        raise SystemExit("bundle_expected_claim_mismatch")
    if RELEASE.fullmatch(manifest["source_release"]) is None or RELEASE.fullmatch(
        manifest["target_release"]
    ) is None:
        raise SystemExit("invalid_bundle_release")
    try:
        cutoff = datetime.fromisoformat(manifest["cutoff_utc"])
    except (TypeError, ValueError):
        raise SystemExit("invalid_bundle_cutoff") from None
    if cutoff.tzinfo is None or abs((datetime.now(UTC) - cutoff).total_seconds()) > 300:
        raise SystemExit("invalid_bundle_cutoff")

    preseed = _objects(manifest["preseed_objects"], "invalid_preseed_manifest")
    final = _objects(manifest["final_objects"], "invalid_final_manifest")
    if _storage_manifest_digest(preseed) != _sha(
        manifest["preseed_manifest_sha256"], "invalid_preseed_digest"
    ) or _storage_manifest_digest(final) != _sha(
        manifest["final_manifest_sha256"], "invalid_final_digest"
    ):
        raise SystemExit("storage_manifest_digest_mismatch")
    delta = _calculate_delta(preseed, final)
    deletions = manifest["deletion_paths"]
    if (
        not isinstance(deletions, list)
        or any(not isinstance(path, str) for path in deletions)
        or deletions != list(delta.remove)
        or manifest["deletion_count"] != len(deletions)
        or hashlib.sha256(canonical(deletions)).hexdigest()
        != _sha(manifest["deletion_manifest_sha256"], "invalid_deletion_digest")
    ):
        raise SystemExit("deletion_manifest_mismatch")

    if len(manifest["artifacts"]) != len(ROLES):
        raise SystemExit("incomplete_bundle_artifacts")
    artifacts: dict[str, dict] = {}
    suffix = bundle_match.group(1)
    for artifact in manifest["artifacts"]:
        if not isinstance(artifact, dict) or set(artifact) != ARTIFACT_SHAPE:
            raise SystemExit("invalid_bundle_artifact_shape")
        role = artifact["role"]
        if role not in ROLES or role in artifacts:
            raise SystemExit("invalid_bundle_artifact_role")
        name = artifact["name"]
        if name != f"{role}-{suffix}.age" or Path(name).name != name:
            raise SystemExit("invalid_bundle_artifact_name")
        if type(artifact["ciphertext_size"]) is not int or artifact["ciphertext_size"] < 1:
            raise SystemExit("invalid_ciphertext_size")
        if type(artifact["plaintext_size"]) is not int or artifact["plaintext_size"] < 1:
            raise SystemExit("invalid_plaintext_size")
        _sha(artifact["ciphertext_sha256"], "invalid_ciphertext_digest")
        _sha(artifact["plaintext_sha256"], "invalid_plaintext_digest")
        artifacts[role] = artifact
    if set(artifacts) != ROLES:
        raise SystemExit("incomplete_bundle_artifacts")

    plaintext_root.mkdir(mode=0o700)
    identity_fd = _open_regular(identity)
    descriptors: dict[str, int] = {}
    try:
        for role, artifact in artifacts.items():
            descriptor = _open_regular(artifact_root / artifact["name"])
            descriptors[role] = descriptor
            if _digest_fd(descriptor) != (
                artifact["ciphertext_size"], artifact["ciphertext_sha256"],
            ):
                raise SystemExit("ciphertext_evidence_mismatch")
            process = _age_process(descriptor, identity_fd)
            assert process.stdout is not None
            digest = hashlib.sha256()
            size = 0
            while chunk := process.stdout.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
            if process.wait(timeout=900) != 0 or (size, digest.hexdigest()) != (
                artifact["plaintext_size"], artifact["plaintext_sha256"],
            ):
                raise SystemExit("plaintext_evidence_mismatch")
        _validate_tar(descriptors["preseed"], identity_fd, preseed, plaintext_root / "preseed")
        _validate_tar(descriptors["delta"], identity_fd, delta.copy, plaintext_root / "delta")
        db_artifact = artifacts["db"]
        _materialize_plaintext(
            descriptors["db"], identity_fd, plaintext_root / "db.dump",
            (db_artifact["plaintext_size"], db_artifact["plaintext_sha256"]),
        )
    finally:
        for descriptor in descriptors.values():
            os.close(descriptor)
        os.close(identity_fd)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("emit", "verify"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--secret", type=Path, required=True)
    parser.add_argument("--ack", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--identity", type=Path)
    parser.add_argument("--plaintext-root", type=Path)
    parser.add_argument("--expected-bundle-id")
    parser.add_argument("--expected-cutoff-utc")
    parser.add_argument("--expected-source-release")
    parser.add_argument("--expected-target-release")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    key = secret(args.secret)
    manifest_sha = hashlib.sha256(canonical(manifest)).hexdigest()
    if args.mode == "emit":
        if any(
            value is None
            for value in (
                args.artifact_root, args.identity, args.plaintext_root,
                args.expected_bundle_id, args.expected_cutoff_utc,
                args.expected_source_release, args.expected_target_release,
            )
        ):
            raise SystemExit("receiver_inputs_missing")
        validate_manifest(
            manifest, args.artifact_root, args.identity, args.plaintext_root,
            expected_bundle_id=args.expected_bundle_id,
            expected_cutoff_utc=args.expected_cutoff_utc,
            expected_source_release=args.expected_source_release,
            expected_target_release=args.expected_target_release,
        )
        payload = {
            "ack": "BUNDLE_CAPTURED", "bundle_id": manifest["bundle_id"],
            "cutoff_utc": manifest["cutoff_utc"], "source_release": manifest["source_release"],
            "target_release": manifest["target_release"], "manifest_sha256": manifest_sha,
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
    expected_ack = {
        "ack": "BUNDLE_CAPTURED", "bundle_id": manifest["bundle_id"],
        "cutoff_utc": manifest["cutoff_utc"], "source_release": manifest["source_release"],
        "target_release": manifest["target_release"], "manifest_sha256": manifest_sha,
        "issued_at": ack.get("issued_at"),
    }
    if (
        ack != expected_ack
        or type(ack["issued_at"]) is not int
        or abs(int(time.time()) - ack["issued_at"]) > 300
    ):
        raise SystemExit("ack_claim_mismatch")
    print(f"bundle_id={ack['bundle_id']} ack=BUNDLE_CAPTURED valid=true")


if __name__ == "__main__":
    main()
