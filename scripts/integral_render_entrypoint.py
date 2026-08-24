"""Single restart-safe Render entrypoint for integral synthetic/real rehearsals."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import psycopg

from app.platform.integral_config import validate_integral_config
from app.platform.integral_secrets import bootstrap_integral_secrets

ENTRYPOINT_VERSION = 1
PG_MAJOR = 17
ALLOWED_ROLES = {"receiver", "sender", "synthetic_orchestrator"}
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "rehearsal-postgres"}
FAILURE_PREFIX = "integral_entrypoint_failure"


def need(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"missing_{name.lower()}")
    return value


def external_private_host(url: str) -> str:
    parsed = urlsplit(url.replace("postgresql+psycopg", "postgresql", 1))
    host = parsed.hostname or ""
    expected = need("INTEGRAL_EXPECTED_DATABASE_HOST")
    suffix = need("INTEGRAL_PRIVATE_DATABASE_SUFFIX")
    if host != expected or host in LOCAL_HOSTS or not host.endswith(suffix):
        raise RuntimeError("external_private_database_host_rejected")
    return host


def tool_fingerprint(name: str) -> dict[str, str | int]:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"missing_runtime_tool_{name}")
    result = subprocess.run([path, "--version"], capture_output=True, timeout=10, check=False)
    evidence = result.stdout + result.stderr
    match = re.search(rb"\b(\d+)(?:\.\d+)?\b", evidence)
    if result.returncode or not match or int(match.group(1)) != PG_MAJOR:
        raise RuntimeError(f"runtime_tool_major_mismatch_{name}")
    return {"major": PG_MAJOR, "sha256": hashlib.sha256(evidence).hexdigest()}


class Health(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        status = 200 if self.path == "/health" else 404
        self.send_response(status)
        self.end_headers()
        self.wfile.write(b"ok" if status == 200 else b"not-found")

    def log_message(self, _format: str, *_args: object) -> None:
        return


def health_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "10000"))), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def hold_restart_blocked() -> None:
    threading.Event().wait()


def reserve_tombstone(path: Path) -> bool:
    """Atomically claim the one-shot before health, preflight, or network effects."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(
            {
                "version": ENTRYPOINT_VERSION,
                "release": need("INTEGRAL_RELEASE_SHA"),
                "result": "started",
            },
            stream,
            sort_keys=True,
        )
        stream.flush()
        os.fsync(stream.fileno())
    return True


def write_tombstone(path: Path, result: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(
            {
                "version": ENTRYPOINT_VERSION,
                "release": need("INTEGRAL_RELEASE_SHA"),
                "result": result,
            },
            stream,
            sort_keys=True,
        )
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def runtime_preflight(role: str) -> dict[str, object]:
    previous_umask = os.umask(0o077)
    secret_sha = bootstrap_integral_secrets()
    config_role = "receiver" if role == "synthetic_orchestrator" else role
    config_sha = validate_integral_config(config_role)
    database_url = need("DATABASE_URL")
    host = external_private_host(database_url)
    with psycopg.connect(database_url.replace("postgresql+psycopg", "postgresql", 1)) as connection:
        server_major = int(connection.info.server_version // 10000)
    if server_major != PG_MAJOR:
        raise RuntimeError("postgres_server_major_mismatch")
    spool_root = Path(need("INTEGRAL_SPOOL_ROOT"))
    declared = int(need("INTEGRAL_DECLARED_BUNDLE_BYTES"))
    margin = int(os.environ.get("INTEGRAL_DISK_MARGIN_BYTES", str(128 * 1024 * 1024)))
    if not spool_root.is_dir() or shutil.disk_usage(spool_root).free < declared + margin:
        raise RuntimeError("spool_capacity_rejected")
    cgroup_limit = Path("/sys/fs/cgroup/memory.max")
    raw_limit = cgroup_limit.read_text().strip() if cgroup_limit.is_file() else ""
    if raw_limit and raw_limit != "max":
        memory_limit = int(raw_limit)
    elif os.environ.get("INTEGRAL_ISOLATED_REHEARSAL") == "true":
        memory_limit = int(need("INTEGRAL_MEMORY_LIMIT_BYTES"))
    else:
        raise RuntimeError("cgroup_memory_limit_unavailable")
    minimum_memory = int(os.environ.get("INTEGRAL_MIN_MEMORY_BYTES", str(256 * 1024 * 1024)))
    if memory_limit < minimum_memory:
        raise RuntimeError("memory_capacity_rejected")
    return {
        "config_sha256": config_sha,
        "database_host_sha256": hashlib.sha256(host.encode()).hexdigest(),
        "pg_tools": {name: tool_fingerprint(name) for name in ("pg_dump", "pg_restore", "psql")},
        "python": list(sys.version_info[:3]),
        "secret_sha256": secret_sha,
        "uid": os.geteuid() if hasattr(os, "geteuid") else -1,
        "gid": os.getegid() if hasattr(os, "getegid") else -1,
        "memory_limit_bytes": memory_limit,
        "postgres_server_major": server_major,
        "psycopg_version": psycopg.__version__,
        "umask": "077",
        "previous_umask": f"{previous_umask:03o}",
        "entrypoint_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def child_command(role: str) -> list[str]:
    if role == "synthetic_orchestrator":
        return [
            "sh",
            "scripts/run_integral_e2e_rehearsal.sh",
            need("INTEGRAL_RUN_ID"),
            need("INTEGRAL_STORAGE_BYTES"),
        ]
    if role == "receiver":
        return [
            sys.executable,
            "-m",
            "scripts.integral_private_transfer",
            "receive-bundle-tcp",
            "--staging-root",
            need("INTEGRAL_STORAGE_STAGING_ROOT"),
        ]
    return [
        sys.executable,
        "-m",
        "scripts.integral_private_transfer",
        "send-bundle-tcp",
        "--root",
        need("INTEGRAL_STORAGE_SOURCE_ROOT"),
    ]


def main() -> int:
    role = need("INTEGRAL_RUNTIME_ROLE")
    mode = need("INTEGRAL_MODE")
    if role not in ALLOWED_ROLES or mode not in {"synthetic", "real_rehearsal"}:
        raise RuntimeError("runtime_role_or_mode_rejected")
    if role == "synthetic_orchestrator" and mode != "synthetic":
        raise RuntimeError("synthetic_orchestrator_mode_rejected")
    tombstone = Path(need("INTEGRAL_TOMBSTONE_PATH"))
    if not reserve_tombstone(tombstone):
        print("integral_entrypoint_restart_blocked=true", flush=True)
        server = health_server()
        try:
            hold_restart_blocked()
        finally:
            server.shutdown()
        return 0
    server = health_server()
    result = "no-go"
    child: subprocess.Popen[bytes] | None = None
    previous_handlers: dict[int, object] = {}
    def terminate(_signum: int, _frame: object) -> None:
        nonlocal result
        result = "terminated"
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
        raise RuntimeError("external_termination")
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, terminate)
    try:
        evidence = runtime_preflight(role)
        print(json.dumps({"integral_entrypoint_preflight": evidence}, sort_keys=True), flush=True)
        os.environ["INTEGRAL_ENTRYPOINT_DELEGATED"] = "1"
        child = subprocess.Popen(child_command(role), start_new_session=True)
        timeout = int(need("INTEGRAL_ENTRYPOINT_DEADLINE_SECONDS"))
        return_code = child.wait(timeout=timeout)
        if return_code:
            raise RuntimeError(f"child_failed_rc_{return_code}")
        result = "pass"
        print("integral_entrypoint_result=pass", flush=True)
        return 0
    except subprocess.TimeoutExpired as exc:
        if child is not None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
        raise RuntimeError("child_deadline_exceeded") from exc
    finally:
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
        cleanup_errors = []
        try:
            write_tombstone(tombstone, result)
        except Exception as exc:
            cleanup_errors.append(type(exc).__name__)
        try:
            server.shutdown()
        except Exception as exc:
            cleanup_errors.append(type(exc).__name__)
        try:
            spool_root = Path(need("INTEGRAL_SPOOL_ROOT"))
            for pattern in ("carfast-integral-*.spool", "integral-private-secrets-*/*"):
                for item in spool_root.glob(pattern):
                    if item.is_file():
                        item.unlink(missing_ok=True)
        except Exception as exc:
            cleanup_errors.append(type(exc).__name__)
        try:
            for name in ("DATABASE_URL", "STAGING_DATABASE_URL", "INTEGRAL_TRANSFER_KEY"):
                os.environ.pop(name, None)
            private_root = Path(
                os.environ.get("INTEGRAL_PRIVATE_SECRET_ROOT", "/dev/shm/carfast-integral")
            )
            shutil.rmtree(private_root, ignore_errors=True)
        except Exception as exc:
            cleanup_errors.append(type(exc).__name__)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        if cleanup_errors:
            print(f"integral_cleanup_failures={len(cleanup_errors)}", file=sys.stderr)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        code = hashlib.sha256(str(exc).encode()).hexdigest()[:16]
        print(f"{FAILURE_PREFIX}={type(exc).__name__}:{code}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None
