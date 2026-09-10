"""Bootstrap and hold the authorized empty/synthetic Render rehearsal."""

from __future__ import annotations

import json
import os
import socket
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from app.core.egress_guard import EgressDenied, install_process_egress_guard
from app.platform.capture_authorization import AuthorizationRejected, verify_and_consume
from scripts.validate_isolated_environment import main as validate_environment


def run(*command: str) -> None:
    subprocess.run(command, check=True, timeout=180)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = b'{"status":"empty-rehearsal-ready"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/internal/anonymized-pilot/v1":
            self.send_error(404)
            return
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        try:
            verify_and_consume(
                token,
                os.environ.get("CAPTURE_AUTHORIZATION_KEY", "").encode(),
                expected_source=os.environ.get("CAPTURE_SOURCE_SERVICE", ""),
                expected_destination=os.environ.get("CAPTURE_DESTINATION_SERVICE", ""),
            )
        except AuthorizationRejected:
            self.send_error(403)
            return
        if self.headers.get("Transfer-Encoding", "").lower() != "chunked":
            self.send_error(411)
            return
        command = [
            os.environ.get("PYTHON_BIN", "python"),
            "-m",
            "scripts.receive_anonymized_stream",
            "--dsn",
            os.environ.get("LOCAL_POSTGRES_DSN", os.environ["DATABASE_URL"]),
        ]
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        total = 0
        try:
            assert process.stdin is not None
            while True:
                line = self.rfile.readline(32)
                if not line or len(line) > 24:
                    raise ValueError("invalid stream framing")
                size = int(line.split(b";", 1)[0].strip(), 16)
                if size == 0:
                    self.rfile.readline(2)
                    break
                if size > 1024 * 1024 or total + size > 512 * 1024 * 1024:
                    raise ValueError("stream limit exceeded")
                chunk = self.rfile.read(size)
                if len(chunk) != size or self.rfile.read(2) != b"\r\n":
                    raise ValueError("truncated stream")
                process.stdin.write(chunk)
                process.stdin.flush()
                total += size
            process.stdin.close()
            process.stdin = None
            stdout, stderr = process.communicate(timeout=900)
            if process.returncode or stderr or len(stdout) > 64 * 1024:
                raise RuntimeError("receiver rejected stream")
            aggregate = json.loads(stdout)
            body = json.dumps(aggregate, sort_keys=True, separators=(",", ":")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ValueError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError):
            process.kill()
            process.wait(timeout=10)
            self.send_error(422)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> int:
    # Values pasted through a dashboard can retain harmless wrapping quotes.
    # Normalize only that outer transport formatting before any validation.
    os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "").strip().strip("\"'")
    validate_environment()
    parsed = urlsplit(os.environ["DATABASE_URL"].replace("postgresql+psycopg", "postgresql", 1))
    os.environ["REHEARSAL_DATABASE_HOST"] = parsed.hostname or ""

    run("python", "-m", "scripts.check_migration_heads")
    run("alembic", "upgrade", "head")
    run("python", "-m", "scripts.bootstrap_installation")
    run("python", "-m", "scripts.bootstrap_installation")
    run("python", "-m", "scripts.check_clean_install")
    run("python", "-m", "scripts.run_phase10_rehearsal")

    install_process_egress_guard()
    try:
        socket.create_connection(("example.com", 443), timeout=1)
    except EgressDenied:
        print("Application egress denial verified.")
    else:
        raise RuntimeError("application egress denial verification failed")

    port = int(os.environ.get("PORT", "10000"))
    ThreadingHTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
