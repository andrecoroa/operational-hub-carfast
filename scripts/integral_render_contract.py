"""Canonical Render API and Blueprint contract for integral rehearsals.

This module is the only supported producer of Render resource payloads.  It is
deliberately free of HTTP calls so payloads can be reviewed and tested offline.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

WORKER_NAME = "carfast-integral-worker-action-time"
WORKER_TYPE_API = "private_service"
WORKER_TYPE_BLUEPRINT = "pserv"
WORKER_RUNTIME = "docker"
WORKER_REGION = "frankfurt"
WORKER_PLAN = "standard"
WORKER_BRANCH = "codex/integral-migration-rehearsal"
WORKER_DISK_NAME = "carfast-integral-spool"
WORKER_DISK_MOUNT = "/var/data"
WORKER_DISK_GB = 5
DOCKERFILE_PATH = "./deploy/integral/Dockerfile"

# Render already evaluates dockerCommand as the container command.  Supplying a
# second `/bin/sh -c '…'` wrapper causes its quoted body to be treated as one
# executable name.  Keep this value unquoted and wrapper-free.
DOCKER_COMMAND = (
    "umask 077 && exec /opt/carfast-venv/bin/python "
    "-m scripts.integral_render_entrypoint"
)

POSTGRES_NAME = "carfast-integral-staging-action-time"
POSTGRES_PLAN = "basic_256mb"
POSTGRES_REGION = "frankfurt"
POSTGRES_MAJOR = 17
POSTGRES_DISK_GB = 1

BASE_ENV = (
    {"key": "INTEGRAL_EXPECTED_SECRET_MOUNT_TYPE", "value": "tmpfs"},
    {"key": "INTEGRAL_EXPECTED_SPOOL_MOUNTPOINT", "value": WORKER_DISK_MOUNT},
)


def _env_vars(extra: Mapping[str, str] | None = None) -> list[dict[str, str]]:
    values = [dict(item) for item in BASE_ENV]
    values.extend(
        {"key": key, "value": value} for key, value in sorted((extra or {}).items())
    )
    if len({item["key"] for item in values}) != len(values):
        raise ValueError("duplicate Render environment key")
    return values


def worker_api_payload(
    *,
    owner_id: str,
    repo: str,
    name: str = WORKER_NAME,
    branch: str = WORKER_BRANCH,
    env: Mapping[str, str] | None = None,
    secret_files: Sequence[Mapping[str, str]] = (),
) -> dict[str, Any]:
    """Return the exact POST /v1/services JSON body."""
    if not owner_id or not repo:
        raise ValueError("owner_id and repo are required")
    return {
        "type": WORKER_TYPE_API,
        "name": name,
        "ownerId": owner_id,
        "repo": repo,
        "branch": branch,
        "autoDeploy": "no",
        "envVars": _env_vars(env),
        "secretFiles": [dict(item) for item in secret_files],
        "serviceDetails": {
            "runtime": WORKER_RUNTIME,
            "plan": WORKER_PLAN,
            "region": WORKER_REGION,
            "disk": {
                "name": WORKER_DISK_NAME,
                "mountPath": WORKER_DISK_MOUNT,
                "sizeGB": WORKER_DISK_GB,
            },
            "envSpecificDetails": {
                "dockerfilePath": DOCKERFILE_PATH,
                "dockerContext": ".",
                "dockerCommand": DOCKER_COMMAND,
            },
        },
    }


def postgres_api_payload(
    *, owner_id: str, name: str = POSTGRES_NAME
) -> dict[str, Any]:
    """Return the exact POST /v1/postgres JSON body with no public allowance."""
    if not owner_id:
        raise ValueError("owner_id is required")
    return {
        "name": name,
        "ownerId": owner_id,
        "plan": POSTGRES_PLAN,
        "region": POSTGRES_REGION,
        "postgresMajorVersion": POSTGRES_MAJOR,
        "diskSizeGB": POSTGRES_DISK_GB,
        "ipAllowList": [],
    }


def blueprint_document() -> dict[str, Any]:
    """Return the checked-in Blueprint representation of the same worker."""
    return {
        "services": [
            {
                "type": WORKER_TYPE_BLUEPRINT,
                "name": WORKER_NAME,
                "runtime": WORKER_RUNTIME,
                "region": WORKER_REGION,
                "plan": WORKER_PLAN,
                "autoDeployTrigger": "off",
                "dockerfilePath": DOCKERFILE_PATH,
                "dockerCommand": DOCKER_COMMAND,
                "healthCheckPath": "/health",
                "envVars": _env_vars(),
                "disk": {
                    "name": WORKER_DISK_NAME,
                    "mountPath": WORKER_DISK_MOUNT,
                    "sizeGB": WORKER_DISK_GB,
                },
            }
        ]
    }


def validate_worker_readback(value: Mapping[str, Any]) -> None:
    """Fail closed if API read-back differs from the creation contract."""
    details = value.get("serviceDetails") or {}
    expected = {
        "type": WORKER_TYPE_API,
        "name": value.get("name"),
        "autoDeploy": "no",
        "runtime": WORKER_RUNTIME,
        "plan": WORKER_PLAN,
        "region": WORKER_REGION,
        "dockerCommand": DOCKER_COMMAND,
        "dockerfilePath": DOCKERFILE_PATH,
    }
    observed = {
        "type": value.get("type"),
        "name": value.get("name"),
        "autoDeploy": value.get("autoDeploy"),
        "runtime": details.get("runtime"),
        "plan": details.get("plan"),
        "region": details.get("region"),
        "dockerCommand": (details.get("envSpecificDetails") or {}).get("dockerCommand"),
        "dockerfilePath": (details.get("envSpecificDetails") or {}).get("dockerfilePath"),
    }
    if observed != expected:
        raise ValueError("Render worker read-back contract mismatch")


def validate_postgres_readback(value: Mapping[str, Any]) -> None:
    """Validate all security/capacity fields and reject any public rule."""
    if value.get("plan") != POSTGRES_PLAN:
        raise ValueError("Render PostgreSQL plan mismatch")
    if value.get("region") != POSTGRES_REGION:
        raise ValueError("Render PostgreSQL region mismatch")
    if int(value.get("postgresMajorVersion", -1)) != POSTGRES_MAJOR:
        raise ValueError("Render PostgreSQL major mismatch")
    if int(value.get("diskSizeGB", -1)) != POSTGRES_DISK_GB:
        raise ValueError("Render PostgreSQL disk mismatch")
    if value.get("ipAllowList") not in ([], None):
        raise ValueError("Render PostgreSQL public allowance rejected")


def serialized_worker_api_payload(**kwargs: Any) -> str:
    return json.dumps(worker_api_payload(**kwargs), separators=(",", ":"), sort_keys=True)

