from __future__ import annotations

import pytest

from scripts.post_anonymized_pilot import validate_read_only


class Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, privileged=False, writable=False):
        self.privileged = privileged
        self.writable = writable

    def execute(self, query, params=None):
        if "FROM pg_roles" in query:
            return Result((self.privileged, False, False, False, False))
        return Result((self.writable,))


def test_source_role_must_be_unprivileged_and_non_writable() -> None:
    validate_read_only(Connection())
    with pytest.raises(RuntimeError, match="privileged"):
        validate_read_only(Connection(privileged=True))
    with pytest.raises(RuntimeError, match="write privilege"):
        validate_read_only(Connection(writable=True))
