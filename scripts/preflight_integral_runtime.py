"""Fail-closed runtime/staging preflight performed before any Blue mutation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import psycopg

EXPECTED_PG_MAJOR = 17
MIN_FREE_MARGIN = 128 * 1024 * 1024


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"missing {name}")
    return value


def tool_major(name: str) -> tuple[int, str]:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"missing runtime tool: {name}")
    result = subprocess.run(
        [path, "--version"], capture_output=True, check=False, timeout=10
    )
    evidence = result.stdout + result.stderr
    if result.returncode or not evidence:
        raise RuntimeError(f"runtime tool version failed: {name}")
    match = re.search(r"\b(\d+)(?:\.\d+)?\b", evidence.decode("ascii", "ignore"))
    if not match:
        raise RuntimeError(f"runtime tool version unreadable: {name}")
    return int(match.group(1)), hashlib.sha256(evidence).hexdigest()


def main() -> int:
    if required("INTEGRAL_DATABASE_DUMP_PHASE") != "source-staging":
        raise RuntimeError("database dump phase must be source-staging")
    snapshot = required("INTEGRAL_HMAC_SNAPSHOT_SHA256")
    expected_snapshot = required("INTEGRAL_EXPECTED_HMAC_SNAPSHOT_SHA256")
    if len(snapshot) != 64 or snapshot != expected_snapshot:
        raise RuntimeError("deployed HMAC snapshot mismatch")

    versions: dict[str, dict[str, object]] = {}
    for name in ("pg_dump", "pg_restore", "psql"):
        major, fingerprint = tool_major(name)
        if major != EXPECTED_PG_MAJOR:
            raise RuntimeError(f"runtime tool major mismatch: {name}")
        versions[name] = {"major": major, "fingerprint": fingerprint}

    database_url = required("STAGING_DATABASE_URL").replace(
        "postgresql+psycopg", "postgresql", 1
    )
    parsed = urlsplit(database_url)
    database = parsed.path.lstrip("/")
    if not database.startswith("carfast_integral_staging_"):
        raise RuntimeError("staging database is not isolated")
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        row = connection.execute(
            """
            SELECT current_user, current_database(), current_setting('server_version_num'),
                   current_setting('search_path'),
                   pg_get_userbyid(datdba),
                   has_database_privilege(current_user, current_database(), 'CREATE'),
                   has_schema_privilege(current_user, 'public', 'CREATE'),
                   (SELECT count(*) FROM pg_tables WHERE schemaname='public')
              FROM pg_database WHERE datname=current_database()
            """
        ).fetchone()
    assert row is not None
    (
        role,
        observed_database,
        server_version,
        search_path,
        owner,
        db_create,
        schema_create,
        tables,
    ) = row
    if int(server_version) // 10000 != EXPECTED_PG_MAJOR:
        raise RuntimeError("PostgreSQL server major mismatch")
    if observed_database != database or owner != role:
        raise RuntimeError("staging database must be owned by its temporary role")
    normalized_search_path = search_path.replace('"', "").replace(" ", "")
    if normalized_search_path not in {"public", "$user,public"}:
        raise RuntimeError("staging search_path mismatch")
    if not db_create or not schema_create or int(tables) != 0:
        raise RuntimeError("staging ownership/grants/empty contract mismatch")

    spool_root = Path(required("INTEGRAL_SPOOL_ROOT"))
    declared = int(required("INTEGRAL_DECLARED_BUNDLE_BYTES"))
    free = shutil.disk_usage(spool_root).free
    if declared <= 0 or free < declared + MIN_FREE_MARGIN:
        raise RuntimeError("insufficient spool space")

    print(
        json.dumps(
            {
                "database": database,
                "python": sys.version_info[:3],
                "postgres_server_major": EXPECTED_PG_MAJOR,
                "role_owns_database": True,
                "schema_create": True,
                "search_path": normalized_search_path,
                "staging_tables": 0,
                "spool_declared_bytes": declared,
                "spool_free_bytes": free,
                "tools": versions,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
