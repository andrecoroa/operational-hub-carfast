from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import sessionmaker

from app.models.audit import AuditLog
from app.models.email import EmailSecretReference
from app.services.microsoft365_oauth import EnvironmentAndDatabaseSecretReferenceStore


def test_env_reference_reads_client_secret(monkeypatch):
    monkeypatch.setenv("MICROSOFT365_CLIENT_SECRET", "client-secret")
    store = EnvironmentAndDatabaseSecretReferenceStore(Fernet.generate_key().decode())
    assert store.read("env://MICROSOFT365_CLIENT_SECRET") == "client-secret"


def test_db_reference_round_trip_is_encrypted(db_session):
    key = Fernet.generate_key().decode()
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    store = EnvironmentAndDatabaseSecretReferenceStore(key, session_factory=factory)
    store.write("db://microsoft365/transport/1/tokens", '{"access_token":"secret"}')

    row = db_session.query(EmailSecretReference).one()
    assert "access_token" not in row.ciphertext
    assert store.read("db://microsoft365/transport/1/tokens") == '{"access_token":"secret"}'
    audit = db_session.query(AuditLog).filter_by(action="microsoft365.secret.created").one()
    assert "secret" not in str(audit.after_json)


def test_store_rejects_writes_outside_database():
    store = EnvironmentAndDatabaseSecretReferenceStore(Fernet.generate_key().decode())
    with pytest.raises(RuntimeError, match="db://"):
        store.write("env://MICROSOFT365_CLIENT_SECRET", "no")


def test_expired_token_fails_closed(db_session):
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    store = EnvironmentAndDatabaseSecretReferenceStore(
        Fernet.generate_key().decode(), session_factory=factory
    )
    reference = "db://microsoft365/transport/1/expired"
    store.write(reference, "token", expires_at=datetime.now(UTC) - timedelta(seconds=1))
    with pytest.raises(RuntimeError, match="expirou"):
        store.read(reference)


def test_key_ring_rotates_and_preserves_old_key_for_rollback(db_session):
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    old_store = EnvironmentAndDatabaseSecretReferenceStore(old_key, session_factory=factory)
    reference = "db://microsoft365/transport/1/rotation"
    old_store.write(reference, "token")
    rotating_store = EnvironmentAndDatabaseSecretReferenceStore(
        f"{new_key},{old_key}", session_factory=factory
    )
    assert rotating_store.read(reference) == "token"
    rotating_store.rotate_encryption(reference)
    assert (
        EnvironmentAndDatabaseSecretReferenceStore(new_key, session_factory=factory).read(reference)
        == "token"
    )
