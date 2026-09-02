from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.email import EmailChannel, EmailChannelAlias
from app.services.bootstrap import seed_initial_data
from scripts import bootstrap_installation, reconcile_email_channels


def _session_factory(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'bootstrap.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_versioned_bootstrap_keeps_clean_install_without_email_channels(
    tmp_path, monkeypatch
):
    session_factory = _session_factory(tmp_path)
    monkeypatch.setattr(bootstrap_installation, "SessionLocal", session_factory)
    bootstrap_installation.main()
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(EmailChannel)) == 0


def test_runtime_reconciliation_creates_central_on_empty_schema(tmp_path, monkeypatch):
    session_factory = _session_factory(tmp_path)
    monkeypatch.setattr(reconcile_email_channels, "SessionLocal", session_factory)
    reconcile_email_channels.main()
    with session_factory() as db:
        central = db.scalar(select(EmailChannel).where(EmailChannel.code == "central"))
        alias = db.scalar(select(EmailChannelAlias).where(EmailChannelAlias.address == "central@carfast.pt"))
        assert central is not None
        assert central.from_address == "central@carfast.pt"
        assert central.from_name == "CarFast — Central"
        assert central.reply_to_address == "central@carfast.pt"
        assert alias.channel_id == central.id


def test_runtime_reconciliation_repairs_missing_central_idempotently(
    tmp_path, monkeypatch
):
    session_factory = _session_factory(tmp_path)
    monkeypatch.setattr(reconcile_email_channels, "SessionLocal", session_factory)
    with session_factory() as db:
        seed_initial_data(db)
        oficina = db.scalar(select(EmailChannel).where(EmailChannel.code == "oficina"))
        oficina.address = "central@carfast.pt"
        oficina.default_reply_address = "central@carfast.pt"
        oficina.from_address = "human-sender@carfast.pt"
        oficina.from_name = "Nome humano preservado"
        oficina.reply_to_address = "resposta-oficina@carfast.pt"
        db.execute(delete(EmailChannel).where(EmailChannel.code == "central"))
        db.commit()
    reconcile_email_channels.main()
    reconcile_email_channels.main()
    with session_factory() as db:
        central_count = db.scalar(select(func.count()).select_from(EmailChannel).where(EmailChannel.code == "central"))
        central_alias_count = db.scalar(select(func.count()).select_from(EmailChannelAlias).where(EmailChannelAlias.address == "central@carfast.pt"))
        central = db.scalar(select(EmailChannel).where(EmailChannel.code == "central"))
        oficina = db.scalar(select(EmailChannel).where(EmailChannel.code == "oficina"))
        assert central_count == 1
        assert central_alias_count == 1
        assert central.from_address == "central@carfast.pt"
        assert central.from_name == "CarFast — Central"
        assert central.reply_to_address == "central@carfast.pt"
        assert central.address is None
        assert central.default_reply_address is None
        assert oficina.address == "central@carfast.pt"
        assert oficina.default_reply_address == "central@carfast.pt"
        assert oficina.from_address == "human-sender@carfast.pt"
        assert oficina.from_name == "Nome humano preservado"
        assert oficina.reply_to_address == "resposta-oficina@carfast.pt"


def test_runtime_reconciliation_does_not_take_human_alias_from_another_channel(
    tmp_path, monkeypatch
):
    session_factory = _session_factory(tmp_path)
    monkeypatch.setattr(reconcile_email_channels, "SessionLocal", session_factory)
    with session_factory() as db:
        seed_initial_data(db)
        central = db.scalar(select(EmailChannel).where(EmailChannel.code == "central"))
        oficina = db.scalar(select(EmailChannel).where(EmailChannel.code == "oficina"))
        alias = db.scalar(select(EmailChannelAlias).where(EmailChannelAlias.address == "central@carfast.pt"))
        db.delete(alias)
        db.delete(central)
        db.flush()
        db.add(EmailChannelAlias(channel_id=oficina.id, address="central@carfast.pt", label="Alias humano preservado", active=True))
        db.commit()
    reconcile_email_channels.main()
    reconcile_email_channels.main()
    with session_factory() as db:
        central = db.scalar(select(EmailChannel).where(EmailChannel.code == "central"))
        alias = db.scalar(select(EmailChannelAlias).where(EmailChannelAlias.address == "central@carfast.pt"))
        oficina = db.scalar(select(EmailChannel).where(EmailChannel.code == "oficina"))
        assert central is not None
        assert central.address is None
        assert central.from_address == "central@carfast.pt"
        assert central.from_name == "CarFast — Central"
        assert central.reply_to_address == "central@carfast.pt"
        assert alias.channel_id == oficina.id
        assert alias.label == "Alias humano preservado"
