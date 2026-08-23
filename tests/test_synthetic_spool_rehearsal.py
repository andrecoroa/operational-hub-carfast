from scripts.synthetic_spool_rehearsal import SyntheticReader, synthetic_digest


def test_synthetic_reader_is_deterministic_and_bounded() -> None:
    total = 2 * 1024 * 1024 + 13
    first = SyntheticReader(total)
    payload = b"".join(iter(lambda: first.read(256 * 1024), b""))
    second = SyntheticReader(total)
    assert payload == b"".join(iter(lambda: second.read(256 * 1024), b""))
    assert synthetic_digest(total) == __import__("hashlib").sha256(payload).hexdigest()
