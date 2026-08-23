"""Bootstrap and hold the authorized empty/synthetic Render rehearsal."""

from __future__ import annotations

import os
import socket
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from app.core.egress_guard import EgressDenied, install_process_egress_guard
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

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> int:
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
