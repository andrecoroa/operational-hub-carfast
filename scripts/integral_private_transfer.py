"""Private one-shot database/storage transfer for an explicitly gated rehearsal."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import subprocess
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.platform.integral_storage_stream import pack_storage, unpack_storage
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
                        command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE, env=environment
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


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("send-database")
    send_storage_parser = subparsers.add_parser("send-storage")
    send_storage_parser.add_argument("--root", type=Path, required=True)
    subparsers.add_parser("receive-database")
    receive_storage_parser = subparsers.add_parser("receive-storage")
    receive_storage_parser.add_argument("--staging-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "send-database":
        return send_database()
    if args.command == "send-storage":
        return send_storage(args.root)
    if args.command == "receive-database":
        return serve("database", None)
    return serve("storage", args.staging_root)


if __name__ == "__main__":
    raise SystemExit(main())
