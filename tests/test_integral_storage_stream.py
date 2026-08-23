from __future__ import annotations

import io
import struct
from pathlib import Path

import pytest

from app.platform.integral_storage_stream import (
    MAGIC,
    StorageStreamError,
    pack_storage,
    unpack_storage,
)


def fixture_storage(root: Path) -> None:
    (root / "documents" / "nested").mkdir(parents=True)
    (root / "documents" / "one.pdf").write_bytes(b"synthetic-one")
    (root / "documents" / "nested" / "two.bin").write_bytes(b"\x00\x01fixture")


def test_storage_round_trip_preserves_paths_bytes_and_hashes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    fixture_storage(source)
    stream = io.BytesIO()
    assert pack_storage(source, stream) == (2, 22)
    stream.seek(0)
    assert unpack_storage(stream, target) == (2, 22)
    assert (target / "documents" / "one.pdf").read_bytes() == b"synthetic-one"
    assert (target / "documents" / "nested" / "two.bin").read_bytes() == b"\x00\x01fixture"


def test_truncated_stream_rolls_back_entire_staging_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    fixture_storage(source)
    stream = io.BytesIO()
    pack_storage(source, stream)
    broken = io.BytesIO(stream.getvalue()[:-5])
    with pytest.raises(StorageStreamError, match="truncated"):
        unpack_storage(broken, target)
    assert list(target.iterdir()) == []


def test_path_traversal_is_rejected_and_rolled_back(tmp_path: Path) -> None:
    header = b'{"path":"../escape","sha256":"' + b"0" * 64 + b'","size":0}'
    stream = io.BytesIO(MAGIC + struct.pack(">I", len(header)) + header + struct.pack(">I", 0))
    target = tmp_path / "target"
    with pytest.raises(StorageStreamError, match="unsafe"):
        unpack_storage(stream, target)
    assert not (tmp_path / "escape").exists()


def test_digest_mismatch_is_rejected_and_rolled_back(tmp_path: Path) -> None:
    header = b'{"path":"object","sha256":"' + b"0" * 64 + b'","size":1}'
    stream = io.BytesIO(
        MAGIC + struct.pack(">I", len(header)) + header + b"x" + struct.pack(">I", 0)
    )
    target = tmp_path / "target"
    with pytest.raises(StorageStreamError, match="digest mismatch"):
        unpack_storage(stream, target)
    assert list(target.iterdir()) == []
