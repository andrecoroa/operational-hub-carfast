from types import SimpleNamespace

from app.web import router


def test_email_quick_record_uses_email_permissions(monkeypatch):
    user = SimpleNamespace(active=True)
    record = SimpleNamespace(entity_type="email_intake", workspace="operational")

    monkeypatch.setattr(router, "get_user_permission_codes", lambda _db, _user: {"email.read"})
    assert router.user_can_access_quick_record(object(), user, record)
    assert not router.user_can_access_quick_record(object(), user, record, write=True)

    monkeypatch.setattr(router, "get_user_permission_codes", lambda _db, _user: {"email.triage"})
    assert router.user_can_access_quick_record(object(), user, record, write=True)


def test_non_email_quick_record_keeps_workspace_authorization(monkeypatch):
    user = SimpleNamespace(active=True)
    record = SimpleNamespace(entity_type="vehicle", workspace="operational")
    calls = []

    def workspace_access(_db, _user, workspace, *, write=False, action=None):
        calls.append((workspace, write, action))
        return True

    monkeypatch.setattr(router, "user_can_access_task_workspace", workspace_access)

    assert router.user_can_access_quick_record(object(), user, record, write=True)
    assert calls == [("operational", True, None)]
