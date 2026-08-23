"""Private one-shot database/storage transfer for an explicitly gated rehearsal."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlsplit

from app.platform.integral_storage_stream import pack_storage, unpack_storage
from app.platform.integral_tcp import (
    FramedReader,
    TcpTransferRejected,
    client_handshake,
    ensure_no_trailing,
    issue_tcp_token,
    server_handshake,
    write_framed,
)
from app.platform.integral_transfer import ChunkedReader, issue_token, verify_token

CHUNK_BYTES = 1024 * 1024
TARGET_MARKER = Path("/tmp/carfast-integral-target-prepared.json")


def database_dump_command(phase: str) -> list[str]:
    command = [
        "pg_dump",
        "-Fc",
        "--no-owner",
        "--no-privileges",
        "--serializable-deferrable",
        "--exclude-table-data=*seq",
    ]
    if phase == "migrated-target":
        command.extend(("--data-only", "--exclude-table-data=alembic_version"))
    elif phase != "source-staging":
        raise ValueError("invalid database dump phase")
    return command


def database_restore_command(phase: str, database: str, *, target_prepared: bool) -> list[str]:
    command = [
        "pg_restore",
        f"--dbname={database}",
        "--single-transaction",
        "--exit-on-error",
        "--no-owner",
        "--no-privileges",
    ]
    if phase == "staging":
        if not database.startswith("carfast_integral_staging_"):
            raise ValueError("staging database name is not isolated")
        command[1:1] = ["--clean", "--if-exists"]
    elif phase == "prepared-target":
        if not target_prepared:
            raise ValueError("Green target was not explicitly prepared")
        command.append("--data-only")
    else:
        raise ValueError("invalid database destination phase")
    return command


def valid_target_marker(path: Path, database: str, *, now: datetime | None = None) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        timestamp = datetime.fromisoformat(payload["timestamp"])
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        return False
    current = now or datetime.now(UTC)
    return (
        set(payload)
        == {"database", "release_sha", "relations", "service", "source_relations", "timestamp"}
        and payload["database"] == database == "carfast_green"
        and payload["release_sha"] == "9c691d332c80dff4a1d529d7f0d4ef16a71add46"
        and payload["service"] == "srv-da5dk9bm8hqs73camds0"
        and payload["relations"] == 166
        and payload["source_relations"] == 162
        and timestamp.tzinfo is not None
        and 0 <= (current - timestamp).total_seconds() <= 20 * 60
    )


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"missing {name}")
    return value


def transfer_key() -> bytes:
    key = required("INTEGRAL_TRANSFER_KEY").encode()
    if len(key) < 32:
        raise SystemExit("INTEGRAL_TRANSFER_KEY must contain at least 32 bytes")
    return key


def libpq_environment(database_url: str) -> dict[str, str]:
    parsed = urlsplit(database_url.replace("postgresql+psycopg", "postgresql", 1))
    expected_host = required("INTEGRAL_EXPECTED_DATABASE_HOST")
    expected_database = required("INTEGRAL_EXPECTED_DATABASE_NAME")
    if parsed.hostname != expected_host or parsed.path.lstrip("/") != expected_database:
        raise SystemExit("integral transfer database target mismatch")
    if not expected_host.startswith("dpg-"):
        raise SystemExit("integral transfer requires a private Render PostgreSQL host")
    environment = dict(os.environ)
    environment.update(
        PGHOST=parsed.hostname,
        PGPORT=str(parsed.port or 5432),
        PGDATABASE=expected_database,
        PGUSER=unquote(parsed.username or ""),
        PGPASSWORD=unquote(parsed.password or ""),
        PGSSLMODE="require",
    )
    return environment


def authorization(kind: str) -> str:
    return issue_token(
        transfer_key(),
        source=required("INTEGRAL_SOURCE_SERVICE"),
        destination=required("INTEGRAL_DESTINATION_SERVICE"),
        kind=kind,
    )


def post(kind: str, body: object) -> dict[str, object]:
    host = required("INTEGRAL_DESTINATION_HOST")
    if "://" in host or "/" in host or not host.startswith("carfast-"):
        raise SystemExit("invalid private destination hostname")
    port = int(os.environ.get("INTEGRAL_DESTINATION_PORT", "10001"))
    connection = http.client.HTTPConnection(host, port, timeout=20 * 60)
    connection.request(
        "POST",
        f"/integral/v1/{kind}",
        body=body,
        headers={"Authorization": f"Bearer {authorization(kind)}"},
        encode_chunked=True,
    )
    response = connection.getresponse()
    payload = response.read(64 * 1024)
    connection.close()
    if response.status != 200:
        raise SystemExit(f"private integral transfer rejected with HTTP {response.status}")
    return json.loads(payload)


def send_database() -> int:
    environment = libpq_environment(required("DATABASE_URL"))
    dump_phase = required("INTEGRAL_DATABASE_DUMP_PHASE")
    try:
        command = database_dump_command(dump_phase)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment
    )
    assert process.stdout is not None
    result = post("database", process.stdout)
    process.wait()
    if process.returncode:
        raise SystemExit("pg_dump failed without transfer acceptance")
    print(json.dumps(result, sort_keys=True))
    return 0


def send_storage(root: Path) -> int:
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, "rb")
    writer = os.fdopen(write_fd, "wb")
    failure: list[BaseException] = []

    def produce() -> None:
        try:
            pack_storage(root, writer)
        except BaseException as exc:  # propagated after the request terminates
            failure.append(exc)
        finally:
            writer.close()

    thread = threading.Thread(target=produce, daemon=True)
    thread.start()
    try:
        result = post("storage", reader)
    finally:
        reader.close()
        thread.join()
    if failure:
        raise failure[0]
    print(json.dumps(result, sort_keys=True))
    return 0


def serve(kind: str, staging_root: Path | None) -> int:
    expected_source = required("INTEGRAL_SOURCE_SERVICE")
    expected_destination = required("INTEGRAL_DESTINATION_SERVICE")
    key = transfer_key()
    database_url = os.environ.get("DATABASE_URL", "")

    state = {"accepted": False}

    class Handler(BaseHTTPRequestHandler):
        server_version = "CarFastIntegral/1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            try:
                if self.path != f"/integral/v1/{kind}":
                    raise ValueError("endpoint mismatch")
                if self.headers.get("Transfer-Encoding", "").lower() != "chunked":
                    raise ValueError("chunked transfer required")
                if self.headers.get("Content-Length") is not None:
                    raise ValueError("content length is forbidden")
                authorization_header = self.headers.get("Authorization", "")
                if not authorization_header.startswith("Bearer "):
                    raise ValueError("authorization required")
                verify_token(
                    authorization_header[7:],
                    key,
                    expected_source=expected_source,
                    expected_destination=expected_destination,
                    expected_kind=kind,
                )
                body = ChunkedReader(self.rfile)
                if kind == "storage":
                    assert staging_root is not None
                    count, size = unpack_storage(body, staging_root)
                    result = {"accepted": True, "kind": kind, "objects": count, "bytes": size}
                else:
                    environment = libpq_environment(database_url)
                    destination_phase = required("INTEGRAL_DATABASE_DESTINATION_PHASE")
                    expected_database = required("INTEGRAL_EXPECTED_DATABASE_NAME")
                    command = database_restore_command(
                        destination_phase,
                        expected_database,
                        target_prepared=(
                            os.environ.get("INTEGRAL_TARGET_PREPARED") == "true"
                            and valid_target_marker(TARGET_MARKER, expected_database)
                        ),
                    )
                    process = subprocess.Popen(
                        command,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        env=environment,
                    )
                    assert process.stdin is not None
                    total = 0
                    while chunk := body.read(CHUNK_BYTES):
                        total += len(chunk)
                        process.stdin.write(chunk)
                    process.stdin.close()
                    stderr = process.stderr.read() if process.stderr else b""
                    returncode = process.wait()
                    if returncode:
                        diagnostic = stderr.decode("utf-8", errors="replace")[-2_000:].strip()
                        raise RuntimeError(
                            f"pg_restore failed ({len(stderr)} stderr bytes): {diagnostic}"
                        )
                    if destination_phase == "prepared-target":
                        TARGET_MARKER.unlink(missing_ok=True)
                    result = {"accepted": True, "kind": kind, "bytes": total}
                payload = json.dumps(result, sort_keys=True).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                state["accepted"] = True
            except Exception as exc:
                if isinstance(exc, RuntimeError):
                    print(f"integral database restore rejected: {exc}", flush=True)
                else:
                    print(
                        f"integral receiver rejected before restore: {type(exc).__name__}",
                        flush=True,
                    )
                payload = b'{"accepted":false}'
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

    port = int(os.environ.get("INTEGRAL_DESTINATION_PORT", "10001"))
    server = HTTPServer(("0.0.0.0", port), Handler)
    deadline = time.monotonic() + 15 * 60
    server.timeout = 2
    while not state["accepted"] and time.monotonic() < deadline:
        server.handle_request()
    server.server_close()
    if not state["accepted"]:
        raise SystemExit("integral receiver closed without an accepted transfer")
    return 0


def _tcp_endpoint() -> tuple[str, int]:
    host = required("INTEGRAL_DESTINATION_HOST")
    port = int(required("INTEGRAL_DESTINATION_PORT"))
    if (
        host != required("INTEGRAL_EXPECTED_DESTINATION_HOST")
        or port != int(required("INTEGRAL_EXPECTED_DESTINATION_PORT"))
        or "://" in host
        or "/" in host
        or not host.startswith("carfast-")
        or not 1 <= port <= 65535
    ):
        raise SystemExit("invalid private TCP destination allowlist")
    return host, port


def _tcp_token(stream_type: str) -> str:
    return issue_tcp_token(
        transfer_key(),
        source=required("INTEGRAL_SOURCE_SERVICE"),
        destination=required("INTEGRAL_DESTINATION_SERVICE"),
        release=required("INTEGRAL_RELEASE_SHA"),
        cutoff=required("INTEGRAL_CUTOFF_ID"),
        stream_type=stream_type,
    )


def _send_tcp(stream_type: str, source: BinaryIO) -> dict[str, object]:
    host, port = _tcp_endpoint()
    with socket.create_connection((host, port), timeout=30) as connection:
        connection.settimeout(20 * 60)
        handle, session = client_handshake(connection, _tcp_token(stream_type), stream_type)
        frames, total, digest = write_framed(source, handle, transfer_key(), session)
        connection.shutdown(socket.SHUT_WR)
        if connection.recv(1) != b"\x01":
            raise SystemExit("private TCP transfer rejected")
    return {
        "accepted": True,
        "stream_type": stream_type,
        "frames": frames,
        "bytes": total,
        "sha256": digest,
    }


def send_database_tcp() -> int:
    environment = libpq_environment(required("DATABASE_URL"))
    try:
        command = database_dump_command(required("INTEGRAL_DATABASE_DUMP_PHASE"))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment
    )
    assert process.stdout is not None
    result = _send_tcp("database", process.stdout)
    process.wait()
    if process.returncode:
        raise SystemExit("pg_dump failed without TCP transfer acceptance")
    print(json.dumps(result, sort_keys=True))
    return 0


def send_storage_tcp(root: Path) -> int:
    read_fd, write_fd = os.pipe()
    reader, writer = os.fdopen(read_fd, "rb"), os.fdopen(write_fd, "wb")
    failure: list[BaseException] = []

    def produce() -> None:
        try:
            pack_storage(root, writer)
        except BaseException as exc:
            failure.append(exc)
        finally:
            writer.close()

    thread = threading.Thread(target=produce, daemon=True)
    thread.start()
    try:
        result = _send_tcp("storage", reader)
    finally:
        reader.close()
        thread.join()
    if failure:
        raise failure[0]
    print(json.dumps(result, sort_keys=True))
    return 0


def _receive_tcp_stream(
    connection: socket.socket,
    *,
    stream_type: str,
    staging_root: Path | None,
    key: bytes,
    source: str,
    destination: str,
    release: str,
    cutoff: str,
    used_nonces: set[str],
) -> None:
    handle, session = server_handshake(
        connection,
        key,
        source=source,
        destination=destination,
        release=release,
        cutoff=cutoff,
        stream_type=stream_type,
        used_nonces=used_nonces,
    )
    connection.settimeout(20 * 60)
    framed = FramedReader(handle, key, session)
    if stream_type == "database":
        database_url = os.environ.get("DATABASE_URL", "")
        environment = libpq_environment(database_url)
        database = environment["PGDATABASE"]
        command = database_restore_command(
            required("INTEGRAL_DATABASE_DESTINATION_PHASE"),
            database,
            target_prepared=(
                os.environ.get("INTEGRAL_TARGET_PREPARED") == "true"
                and valid_target_marker(TARGET_MARKER, database)
            ),
        )
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stderr=subprocess.PIPE, env=environment
        )
        assert process.stdin is not None
        while chunk := framed.read(CHUNK_BYTES):
            process.stdin.write(chunk)
        process.stdin.close()
        stderr = process.stderr.read() if process.stderr else b""
        if process.wait():
            diagnostic = stderr.decode("utf-8", errors="replace")[-2_000:].strip()
            raise RuntimeError(f"pg_restore failed ({len(stderr)} stderr bytes): {diagnostic}")
    elif stream_type == "storage":
        if staging_root is None:
            raise TcpTransferRejected("missing storage staging root")
        unpack_storage(framed, staging_root)
    else:
        raise TcpTransferRejected("unknown stream type")
    ensure_no_trailing(handle)


def serve_tcp_streams(stream_types: tuple[str, ...], staging_root: Path | None) -> int:
    key = transfer_key()
    source, destination = (
        required("INTEGRAL_SOURCE_SERVICE"),
        required("INTEGRAL_DESTINATION_SERVICE"),
    )
    release, cutoff = required("INTEGRAL_RELEASE_SHA"), required("INTEGRAL_CUTOFF_ID")
    _host, port = _tcp_endpoint()
    used_nonces: set[str] = set()
    deadline, accepted = time.monotonic() + 15 * 60, 0
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", port))
        listener.listen(8)
        listener.settimeout(2)
        while accepted < len(stream_types) and time.monotonic() < deadline:
            try:
                connection, _address = listener.accept()
            except TimeoutError:
                continue
            with connection:
                connection.settimeout(3)
                try:
                    _receive_tcp_stream(
                        connection,
                        stream_type=stream_types[accepted],
                        staging_root=staging_root,
                        key=key,
                        source=source,
                        destination=destination,
                        release=release,
                        cutoff=cutoff,
                        used_nonces=used_nonces,
                    )
                    connection.sendall(b"\x01")
                    accepted += 1
                    deadline = time.monotonic() + 15 * 60
                except Exception as exc:
                    if staging_root is not None:
                        shutil.rmtree(staging_root, ignore_errors=True)
                        staging_root.mkdir(parents=True, exist_ok=True)
                    reason = (
                        str(exc)
                        if isinstance(exc, (TcpTransferRejected, RuntimeError))
                        else type(exc).__name__
                    )
                    print(
                        f"integral TCP receiver rejected: {type(exc).__name__}: {reason}",
                        flush=True,
                    )
                    try:
                        connection.sendall(b"\x00")
                    except OSError:
                        pass
    if accepted != len(stream_types):
        raise SystemExit(f"integral TCP receiver accepted {accepted}/{len(stream_types)} streams")
    return 0


def serve_tcp(stream_type: str, staging_root: Path | None) -> int:
    return serve_tcp_streams((stream_type,), staging_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("send-database")
    send_storage_parser = subparsers.add_parser("send-storage")
    send_storage_parser.add_argument("--root", type=Path, required=True)
    subparsers.add_parser("receive-database")
    receive_storage_parser = subparsers.add_parser("receive-storage")
    receive_storage_parser.add_argument("--staging-root", type=Path, required=True)
    subparsers.add_parser("send-database-tcp")
    send_storage_tcp_parser = subparsers.add_parser("send-storage-tcp")
    send_storage_tcp_parser.add_argument("--root", type=Path, required=True)
    subparsers.add_parser("receive-database-tcp")
    receive_storage_tcp_parser = subparsers.add_parser("receive-storage-tcp")
    receive_storage_tcp_parser.add_argument("--staging-root", type=Path, required=True)
    receive_bundle_tcp_parser = subparsers.add_parser("receive-bundle-tcp")
    receive_bundle_tcp_parser.add_argument("--staging-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "send-database":
        return send_database()
    if args.command == "send-storage":
        return send_storage(args.root)
    if args.command == "receive-database":
        return serve("database", None)
    if args.command == "receive-storage":
        return serve("storage", args.staging_root)
    if args.command == "send-database-tcp":
        return send_database_tcp()
    if args.command == "send-storage-tcp":
        return send_storage_tcp(args.root)
    if args.command == "receive-database-tcp":
        return serve_tcp("database", None)
    if args.command == "receive-bundle-tcp":
        return serve_tcp_streams(("database", "storage"), args.staging_root)
    return serve_tcp("storage", args.staging_root)


if __name__ == "__main__":
    raise SystemExit(main())
