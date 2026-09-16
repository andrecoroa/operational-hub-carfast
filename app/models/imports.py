from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class ImportBatch(TimestampMixin, Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_system: Mapped[str] = mapped_column(String(80), index=True)
    import_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    imported_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    created_rows: Mapped[int] = mapped_column(Integer, default=0)
    updated_rows: Mapped[int] = mapped_column(Integer, default=0)
    skipped_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str | None] = mapped_column(Text)


class ImportFile(TimestampMixin, Base):
    __tablename__ = "import_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"))
    original_name: Mapped[str] = mapped_column(String(255))
    file_name: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(Text)
    sheet_name: Mapped[str | None] = mapped_column(String(160))
    columns_json: Mapped[list | None] = mapped_column(JSON)


class ImportRawRow(TimestampMixin, Base):
    __tablename__ = "import_raw_rows"
    __table_args__ = (UniqueConstraint("batch_id", "row_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"))
    row_number: Mapped[int] = mapped_column(Integer)
    external_reference: Mapped[str | None] = mapped_column(String(160), index=True)
    raw_json: Mapped[dict] = mapped_column(JSON)
    row_hash: Mapped[str | None] = mapped_column(String(80), index=True)


class ImportError(TimestampMixin, Base):
    __tablename__ = "import_errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"))
    row_number: Mapped[int | None] = mapped_column(Integer)
    entity_type: Mapped[str | None] = mapped_column(String(120), index=True)
    error_message: Mapped[str] = mapped_column(Text)
    raw_json: Mapped[dict | None] = mapped_column(JSON)


class ImportMapping(TimestampMixin, Base):
    __tablename__ = "import_mappings"
    __table_args__ = (UniqueConstraint("source_system", "import_type", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_system: Mapped[str] = mapped_column(String(80), index=True)
    import_type: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(160))
    mapping_json: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProcessBatch(TimestampMixin, Base):
    """A resumable spreadsheet lot inside a reusable process case."""

    __tablename__ = "process_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','mapped','validated','in_progress','completed','cancelled')",
            name="ck_process_batches_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("task_cases.id", ondelete="RESTRICT"), index=True)
    process_instance_id: Mapped[int] = mapped_column(
        ForeignKey("process_instances.id", ondelete="RESTRICT"), index=True
    )
    import_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_files.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    mapping_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ProcessBatchRow(TimestampMixin, Base):
    __tablename__ = "process_batch_rows"
    __table_args__ = (
        UniqueConstraint("batch_id", "row_number", name="uq_process_batch_row_number"),
        CheckConstraint(
            "status IN ('pending','ready','in_progress','completed','excluded','error')",
            name="ck_process_batch_rows_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("process_batches.id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer)
    row_key: Mapped[str | None] = mapped_column(String(160), index=True)
    source_json: Mapped[dict] = mapped_column(JSON)
    treatment_json: Mapped[dict] = mapped_column(JSON, default=dict)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class ProcessBatchTaskRow(TimestampMixin, Base):
    """Links many batch rows to one task while preventing duplicate assignment."""

    __tablename__ = "process_batch_task_rows"
    __table_args__ = (
        UniqueConstraint("batch_row_id", name="uq_process_batch_task_row_assignment"),
        UniqueConstraint("task_id", "batch_row_id", name="uq_process_batch_task_row"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    batch_row_id: Mapped[int] = mapped_column(
        ForeignKey("process_batch_rows.id", ondelete="CASCADE"), index=True
    )
    linked_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ProcessBatchRowComment(Base):
    __tablename__ = "process_batch_row_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_row_id: Mapped[int] = mapped_column(
        ForeignKey("process_batch_rows.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    comment: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
