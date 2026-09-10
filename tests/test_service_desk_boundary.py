from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from app.models import Base
from app.models.email import EmailChannel, EmailThread
from app.models.management_center import ManagementProcess, ManagementProcessType
from app.models.tasks import Task as LegacyTask
from app.platform.composer import CompositionResult, compose
from app.platform.manifest import ModuleState
from app.platform.registry import ManifestRegistry
from app.service_desk import (
    SERVICE_DESK_MANIFEST,
    EmailOriginCommand,
    ServiceDeskFacade,
    ServiceDeskReference,
    TaskRecord,
    decide_service_desk_permission,
)


def test_service_desk_references_are_stable_per_capability() -> None:
    for capability in ("task", "process", "email"):
        reference = ServiceDeskReference(capability, 12)
        assert ServiceDeskReference.parse(reference.value) == reference
    assert ServiceDeskReference("task", 12).value == "service-desk:task:v1:12"


def test_task_compatibility_uses_same_mapper_table_and_id(db_session) -> None:
    task = TaskRecord(title="Ticket sintético", status="new", task_type="task")
    ServiceDeskFacade(db_session).create_task(task)
    db_session.commit()
    assert TaskRecord is LegacyTask
    assert TaskRecord.__tablename__ == "tasks"
    assert db_session.get(LegacyTask, task.id) is task


def test_email_to_task_contract_preserves_origin_and_history(db_session) -> None:
    task = TaskRecord(title="Email sintético", status="new", task_type="operational_task")
    facade = ServiceDeskFacade(db_session)
    facade.create_task(task)
    facade.link_email_origin(
        task.id,
        EmailOriginCommand(
            message_id="synthetic-message-1",
            sender="sender@example.invalid",
            recipients=[{"Email": "sandbox@example.invalid"}],
            subject="Pedido sintético",
            received_at=datetime.now(UTC),
            mailbox="sandbox@example.invalid",
            source_url="/v2-clean/email/1",
        ),
    )
    db_session.commit()
    assert (
        db_session.scalar(
            select(func.count()).select_from(Base.metadata.tables["task_email_origins"])
        )
        == 1
    )
    assert (
        db_session.scalar(
            select(func.count()).select_from(Base.metadata.tables["task_assignment_events"])
        )
        >= 1
    )


def test_task_process_and_email_summaries_reconcile(db_session) -> None:
    process_type = ManagementProcessType(code="synthetic", name="Sintético")
    db_session.add(process_type)
    db_session.flush()
    process = ManagementProcess(
        process_type_id=process_type.id,
        internal_reference="SYN-1",
        title="Processo sintético",
        status="open",
    )
    channel = EmailChannel(code="synthetic", name="Sintético", active=True)
    db_session.add_all([process, channel])
    db_session.flush()
    thread = EmailThread(channel_id=channel.id, subject="Conversa sintética", status="triage")
    task = TaskRecord(title="Tarefa sintética", status="new", task_type="task")
    db_session.add_all([thread, task])
    db_session.commit()
    facade = ServiceDeskFacade(db_session)

    assert facade.process_summary(process).reference.id == process.id
    assert facade.email_summary(thread).reference.id == thread.id
    snapshot = facade.task_summary(task).snapshot()
    assert facade.historical_summary(snapshot, can_read=False) is None
    assert facade.historical_summary(snapshot, can_read=True).reference.id == task.id


def test_manifest_capabilities_are_independent_and_legacy_is_default() -> None:
    SERVICE_DESK_MANIFEST.validate()
    registry = ManifestRegistry([SERVICE_DESK_MANIFEST])
    legacy = CompositionResult((), (), (), (), source="legacy")
    states = {"service_desk": ModuleState.ACTIVE}
    assert (
        compose(
            legacy=legacy,
            registry=registry,
            module_states=states,
            permission_codes={"service_desk.tasks.read"},
        )
        is legacy
    )
    active = compose(
        legacy=legacy,
        registry=registry,
        module_states=states,
        permission_codes={"service_desk.tasks.read", "service_desk.email.read"},
        enabled=True,
    )
    assert [item.code for item in active.navigation] == [
        "service_desk.tasks",
        "service_desk.email",
    ]


def test_canonical_permissions_preserve_current_effective_access() -> None:
    assert decide_service_desk_permission("service_desk.tasks.read", {"tasks.read"}).allowed
    assert decide_service_desk_permission("service_desk.email.reply", {"email.reply"}).allowed
    assert not decide_service_desk_permission("service_desk.email.reply", {"email.read"}).allowed
    assert not decide_service_desk_permission("service_desk.unknown", {"admin.manage"}).allowed


def test_service_desk_history_and_links_remain_reconcilable() -> None:
    table_names = set(Base.metadata.tables)
    required = {
        "tasks",
        "task_history",
        "task_assignment_events",
        "task_sla_events",
        "task_email_origins",
        "management_processes",
        "management_history",
        "email_threads",
        "email_messages",
        "email_message_deliveries",
        "email_audit_events",
    }
    assert required <= table_names


def test_priority_email_task_writers_use_service_desk_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in ("app/web/email.py", "app/services/email_postmark.py"):
        source = (root / relative).read_text(encoding="utf-8")
        assert "ServiceDeskFacade" in source
        assert "TaskEmailOrigin(" not in source


def test_touched_surfaces_keep_visual_foundation_gated() -> None:
    root = Path(__file__).resolve().parents[1]
    task_template = (root / "app/templates/clean_task_center.html").read_text(encoding="utf-8")
    process_template = (root / "app/templates/clean_process_center.html").read_text(
        encoding="utf-8"
    )
    email_template = (root / "app/templates/clean_email_inbox.html").read_text(encoding="utf-8")
    for template in (task_template, process_template, email_template):
        assert "foundation_ui_enabled" in template
        assert "ui-page-shell" in template
    assert "ui-table-container" in email_template
