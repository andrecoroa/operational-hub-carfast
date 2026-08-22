from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base

MODULE_STATES = ("available", "active", "disabled", "retiring")


class ModuleDefinition(Base):
    __tablename__ = "module_definitions"

    code: Mapped[str] = mapped_column(String(80), primary_key=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModuleCapability(Base):
    __tablename__ = "module_capabilities"
    __table_args__ = (UniqueConstraint("module_code", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    module_code: Mapped[str] = mapped_column(
        ForeignKey("module_definitions.code", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    independently_switchable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ModuleDependency(Base):
    __tablename__ = "module_dependencies"
    __table_args__ = (UniqueConstraint("module_code", "dependency_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    module_code: Mapped[str] = mapped_column(
        ForeignKey("module_definitions.code", ondelete="CASCADE"), index=True
    )
    dependency_code: Mapped[str] = mapped_column(
        ForeignKey("module_definitions.code", ondelete="RESTRICT"), index=True
    )
    minimum_version: Mapped[str | None] = mapped_column(String(40))


class InstallationModule(Base):
    __tablename__ = "installation_modules"
    __table_args__ = (
        UniqueConstraint("installation_key", "module_code"),
        CheckConstraint(
            "state IN ('available','active','disabled','retiring')",
            name="installation_module_state",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    installation_key: Mapped[str] = mapped_column(String(80), nullable=False, default="default")
    module_code: Mapped[str] = mapped_column(
        ForeignKey("module_definitions.code", ondelete="RESTRICT"), index=True
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="available")
    configured_version: Mapped[str] = mapped_column(String(40), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
