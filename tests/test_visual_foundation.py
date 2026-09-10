from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.return_context import issue_return_context, resolve_return_context
from app.models.evolution import EvolutionRecord

ROOT = Path(__file__).resolve().parents[1]


def test_return_context_accepts_only_signed_authorized_internal_destinations() -> None:
    token = issue_return_context(
        "test-secret",
        path="/v2-clean/admin/evolution",
        query="status=approved&sort=updated",
        anchor="records",
        issued_at=1_000,
    )
    resolved = resolve_return_context(
        "test-secret",
        token,
        allowed_prefixes=("/v2-clean/admin/evolution",),
        now=1_100,
    )
    assert resolved is not None
    assert resolved.url == "/v2-clean/admin/evolution?status=approved&sort=updated#records"
    assert (
        resolve_return_context(
            "wrong-secret",
            token,
            allowed_prefixes=("/v2-clean/admin/evolution",),
            now=1_100,
        )
        is None
    )
    assert (
        resolve_return_context(
            "test-secret",
            token,
            allowed_prefixes=("/v2-clean/tasks",),
            now=1_100,
        )
        is None
    )


def test_return_context_rejects_external_tampered_future_and_expired_values() -> None:
    for unsafe in ("https://example.com", "//example.com/path", "/v2-clean\\evil"):
        try:
            issue_return_context("secret", path=unsafe)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Unsafe path accepted: {unsafe}")
    token = issue_return_context("secret", path="/v2-clean/admin/evolution", issued_at=1_000)
    assert (
        resolve_return_context(
            "secret",
            f"{token}x",
            allowed_prefixes=("/v2-clean/admin/evolution",),
            now=1_001,
        )
        is None
    )
    assert (
        resolve_return_context(
            "secret",
            token,
            allowed_prefixes=("/v2-clean/admin/evolution",),
            now=9_000,
        )
        is None
    )
    future = issue_return_context("secret", path="/v2-clean/admin/evolution", issued_at=2_000)
    assert (
        resolve_return_context(
            "secret",
            future,
            allowed_prefixes=("/v2-clean/admin/evolution",),
            now=1_000,
        )
        is None
    )


def test_visual_tokens_accessibility_and_responsive_harness_contract() -> None:
    css = (ROOT / "app" / "static" / "css" / "foundation.css").read_text(encoding="utf-8")
    required_tokens = (
        "--ui-color-canvas",
        "--ui-color-focus",
        "--ui-font-sans",
        "--ui-space-1: 4px",
        "--ui-control-md: 44px",
        "--ui-content-standard",
        "--ui-radius-md",
        "--ui-elevation-1",
        "--ui-motion-normal",
        "--ui-breakpoint-compact",
    )
    assert all(token in css for token in required_tokens)
    assert ":focus-visible" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "max-width: 48rem" in css
    assert "overflow-x: clip" in css
    assert ".ui-table-container" in css and "overflow-x: auto" in css
    assert ".ui-split-panel" in css and "minmax(0, 1fr)" in css


def test_evolution_representative_surfaces_use_gated_primitives(
    authenticated_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "visual_foundation_enabled", True)
    page = authenticated_client.get("/v2-clean/admin/evolution?status=registered")
    assert page.status_code == 200
    assert "foundation.css" in page.text
    assert "ui-foundation" in page.text
    assert "ui-filter-bar" in page.text
    assert "ui-table-container" in page.text
    assert "Registar e fechar" in page.text
    token = re.search(r'name="return_context" value="([^"]+)"', page.text)
    assert token


def test_create_and_save_close_return_to_signed_logical_context(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "visual_foundation_enabled", True)
    token = issue_return_context(
        settings.app_secret_key,
        path="/v2-clean/admin/evolution",
        query="status=registered&sort=title",
    )
    created = authenticated_client.post(
        "/v2-clean/admin/evolution",
        data={
            "record_type": "improvement",
            "module": "general",
            "priority": "normal",
            "title": "Teste de retorno",
            "description": "Contexto sintético",
            "submit_action": "save_close",
            "return_context": token,
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert created.headers["location"].startswith(
        "/v2-clean/admin/evolution?status=registered&sort=title&created=1"
    )
    record = db_session.scalar(
        select(EvolutionRecord).where(EvolutionRecord.title == "Teste de retorno")
    )
    assert record is not None

    detail = authenticated_client.get(
        f"/v2-clean/admin/evolution/{record.id}?return_context={token}"
    )
    assert detail.status_code == 200
    assert "ui-split-panel" in detail.text
    assert "Guardar e fechar" in detail.text
    assert 'href="/v2-clean/admin/evolution?status=registered&amp;sort=title"' in detail.text

    updated = authenticated_client.post(
        f"/v2-clean/admin/evolution/{record.id}",
        data={
            "record_type": record.record_type,
            "module": record.module,
            "priority": record.priority,
            "status": record.status,
            "title": "Teste de retorno atualizado",
            "description": record.description,
            "submit_action": "save_close",
            "return_context": token,
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303
    assert updated.headers["location"].startswith(
        "/v2-clean/admin/evolution?status=registered&sort=title&saved=1"
    )
    db_session.expire_all()
    assert db_session.get(EvolutionRecord, record.id).title == "Teste de retorno atualizado"


def test_legacy_gate_preserves_existing_default_save_destination(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "visual_foundation_enabled", False)
    created = authenticated_client.post(
        "/v2-clean/admin/evolution",
        data={
            "record_type": "improvement",
            "module": "general",
            "priority": "normal",
            "title": "Compatibilidade legado",
            "description": "Sem gate",
        },
        follow_redirects=False,
    )
    record = db_session.scalar(
        select(EvolutionRecord).where(EvolutionRecord.title == "Compatibilidade legado")
    )
    assert record is not None
    assert created.headers["location"].startswith(f"/v2-clean/admin/evolution/{record.id}")
    page = authenticated_client.get("/v2-clean/admin/evolution")
    assert "foundation.css" not in page.text
    assert "Registar e fechar" not in page.text
