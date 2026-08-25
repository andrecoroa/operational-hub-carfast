from __future__ import annotations

import pytest

from scripts import render_start


def test_resolvable_render_private_hostname_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render_start, "host_resolvable", lambda host: host == "dpg-private-a")
    render_start.assert_render_database_url(
        "DATABASE_URL", "postgresql://user:secret@dpg-private-a/carfast_green"
    )


def test_unresolvable_database_hostname_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render_start, "host_resolvable", lambda _host: False)
    with pytest.raises(RuntimeError, match="sem resolução DNS"):
        render_start.assert_render_database_url(
            "DATABASE_URL", "postgresql://user:secret@dpg-private-a/carfast_green"
        )
