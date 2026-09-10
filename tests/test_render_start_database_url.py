import pytest

from scripts import render_start


def test_resolvable_render_private_hostname_is_allowed(monkeypatch) -> None:
    monkeypatch.setattr(render_start, "host_resolvable", lambda hostname: hostname.startswith("dpg-"))

    render_start.assert_render_database_url(
        "DATABASE_URL",
        "postgresql://user:secret@dpg-da6d4d2jnfac73e2cl40-a:5432/carfast",
    )


def test_unresolvable_render_private_hostname_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(render_start, "host_resolvable", lambda _hostname: False)

    with pytest.raises(RuntimeError, match="host interno curto"):
        render_start.assert_render_database_url(
            "DATABASE_URL",
            "postgresql://user:secret@dpg-missing-a:5432/carfast",
        )


def test_unresolvable_fully_qualified_hostname_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(render_start, "host_resolvable", lambda _hostname: False)

    with pytest.raises(RuntimeError, match="sem resolução DNS"):
        render_start.assert_render_database_url(
            "DATABASE_URL",
            "postgresql://user:secret@db.invalid.example:5432/carfast",
        )


def test_unresolvable_short_non_render_hostname_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(render_start, "host_resolvable", lambda _hostname: False)

    with pytest.raises(RuntimeError, match="sem resolução DNS"):
        render_start.assert_render_database_url(
            "DATABASE_URL",
            "postgresql://user:secret@postgres:5432/carfast",
        )
