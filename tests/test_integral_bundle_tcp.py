from __future__ import annotations

import io
import socket
import threading
import time
from pathlib import Path

import pytest

import scripts.integral_private_transfer as transfer


def _port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _environment(monkeypatch: pytest.MonkeyPatch, port: int, timeout: int = 5) -> None:
    values = {
        "INTEGRAL_TRANSFER_KEY": "k" * 32,
        "INTEGRAL_SOURCE_SERVICE": "srv-bundle-blue",
        "INTEGRAL_DESTINATION_SERVICE": "srv-bundle-green",
        "INTEGRAL_RELEASE_SHA": "a" * 40,
        "INTEGRAL_CUTOFF_ID": "cut-bundle-test",
        "INTEGRAL_BUNDLE_ID": "bundle-test-one",
        "INTEGRAL_DESTINATION_HOST": "carfast-bundle-test",
        "INTEGRAL_EXPECTED_DESTINATION_HOST": "carfast-bundle-test",
        "INTEGRAL_DESTINATION_PORT": str(port),
        "INTEGRAL_EXPECTED_DESTINATION_PORT": str(port),
        "INTEGRAL_BUNDLE_TIMEOUT_SECONDS": str(timeout),
        "INTEGRAL_MAX_STREAM_BYTES": str(8 * 1024 * 1024),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(transfer, "_tcp_endpoint", lambda: ("127.0.0.1", port))


def _run_client(name: str, failures: list[BaseException]) -> None:
    try:
        transfer._send_tcp(name, io.BytesIO((name.encode() + b"-") * 200_000))
    except BaseException as exc:
        failures.append(exc)


def test_isolated_rehearsal_allows_only_explicit_loopback_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTEGRAL_ISOLATED_REHEARSAL", "true")
    monkeypatch.setenv("INTEGRAL_DESTINATION_HOST", "localhost")
    monkeypatch.setenv("INTEGRAL_EXPECTED_DESTINATION_HOST", "localhost")
    monkeypatch.setenv("INTEGRAL_DESTINATION_PORT", "10001")
    monkeypatch.setenv("INTEGRAL_EXPECTED_DESTINATION_PORT", "10001")
    assert transfer._tcp_endpoint() == ("localhost", 10001)


def test_bundle_accepts_inverse_order_then_consumes_database_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    port = _port()
    _environment(monkeypatch, port)
    consumed: list[str] = []
    monkeypatch.setattr(
        transfer,
        "_consume_tcp_spool",
        lambda pending, _root: (time.sleep(0.05), consumed.append(pending.stream_type)),
    )
    monkeypatch.setattr(transfer, "_reconcile_bundle", lambda _root: consumed.append("reconciled"))
    server_failures: list[BaseException] = []

    def server() -> None:
        try:
            transfer.serve_tcp_streams(("database", "storage"), tmp_path)
        except BaseException as exc:
            server_failures.append(exc)

    receiver = threading.Thread(target=server)
    receiver.start()
    time.sleep(0.05)
    client_failures: list[BaseException] = []
    storage = threading.Thread(target=_run_client, args=("storage", client_failures))
    database = threading.Thread(target=_run_client, args=("database", client_failures))
    storage.start()
    time.sleep(0.05)
    database.start()
    storage.join(timeout=5)
    database.join(timeout=5)
    receiver.join(timeout=5)
    assert not client_failures
    assert not server_failures
    assert consumed == ["database", "storage", "reconciled"]
    assert not storage.is_alive() and not database.is_alive() and not receiver.is_alive()


def test_bundle_reconciliation_orders_phase_a_upgrade_and_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INTEGRAL_RELEASE_SHA", "b" * 40)
    commands: list[list[str]] = []
    monkeypatch.setattr(
        transfer, "_run_bundle_gate", lambda command, _environment: commands.append(command)
    )
    transfer._reconcile_bundle(tmp_path)
    flattened = [" ".join(command) for command in commands]
    assert "validate_integral_migration_contract staging" in flattened[0]
    assert "--database-label source" in flattened[1]
    assert flattened[2].endswith("alembic upgrade fff37f8a9b0d")
    assert "reset_integral_target_sequences" in flattened[3]
    assert "validate_integral_migration_contract target" in flattened[4]
    assert "--database-label target" in flattened[5]
    assert "compare_integral_migration_manifests" in flattened[6]


@pytest.mark.parametrize("scenario", ["missing", "duplicate", "consumer-fail"])
def test_bundle_failures_are_closed_and_cleaned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, scenario: str
) -> None:
    port = _port()
    _environment(monkeypatch, port, timeout=1)
    if scenario == "consumer-fail":
        monkeypatch.setattr(
            transfer,
            "_consume_tcp_spool",
            lambda _pending, _root: (_ for _ in ()).throw(RuntimeError("consumer failed")),
        )
    else:
        monkeypatch.setattr(transfer, "_consume_tcp_spool", lambda _pending, _root: None)
    monkeypatch.setattr(transfer, "_reconcile_bundle", lambda _root: None)
    before = set(Path("/tmp").glob("carfast-integral-*.spool"))
    server_failures: list[BaseException] = []

    def server() -> None:
        try:
            transfer.serve_tcp_streams(("database", "storage"), tmp_path)
        except BaseException as exc:
            server_failures.append(exc)

    receiver = threading.Thread(target=server)
    receiver.start()
    time.sleep(0.05)
    client_failures: list[BaseException] = []
    names = {
        "missing": ["storage"],
        "duplicate": ["storage", "storage"],
        "consumer-fail": ["storage", "database"],
    }[scenario]
    clients = [threading.Thread(target=_run_client, args=(name, client_failures)) for name in names]
    for client in clients:
        client.start()
    for client in clients:
        client.join(timeout=4)
    receiver.join(timeout=4)
    assert server_failures
    assert client_failures
    assert set(Path("/tmp").glob("carfast-integral-*.spool")) == before
    assert list(tmp_path.iterdir()) == []


def test_send_bundle_negative_consumer_cancels_without_hang(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    port = _port()
    _environment(monkeypatch, port, timeout=2)
    monkeypatch.setenv("INTEGRAL_CLIENT_TIMEOUT_SECONDS", "4")
    monkeypatch.setenv("INTEGRAL_DATABASE_DUMP_PHASE", "source-staging")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://role:password@dpg-test/private_staging"
    )
    monkeypatch.setenv("INTEGRAL_EXPECTED_DATABASE_HOST", "dpg-test")
    monkeypatch.setenv("INTEGRAL_EXPECTED_DATABASE_NAME", "private_staging")
    monkeypatch.setattr(
        transfer, "_consume_tcp_spool", lambda *_args: (_ for _ in ()).throw(RuntimeError("no"))
    )
    monkeypatch.setattr(transfer, "_reconcile_bundle", lambda _root: None)

    class FakeProcess:
        def __init__(self, *_args, **_kwargs) -> None:
            self.stdout = io.BytesIO(b"synthetic-database" * 10_000)
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(transfer.subprocess, "Popen", FakeProcess)
    (tmp_path / "object.bin").write_bytes(b"synthetic-storage" * 10_000)
    server_failures: list[BaseException] = []

    def server() -> None:
        try:
            transfer.serve_tcp_streams(("database", "storage"), tmp_path / "staging")
        except BaseException as exc:
            server_failures.append(exc)

    receiver = threading.Thread(target=server)
    receiver.start()
    time.sleep(0.05)
    started = time.monotonic()
    with pytest.raises((RuntimeError, OSError, transfer.TcpTransferRejected)):
        transfer.send_bundle_tcp(tmp_path)
    elapsed = time.monotonic() - started
    receiver.join(timeout=3)
    assert elapsed < 3
    assert not receiver.is_alive()
    assert server_failures
    assert not list(Path("/tmp").glob("carfast-integral-*.spool"))
