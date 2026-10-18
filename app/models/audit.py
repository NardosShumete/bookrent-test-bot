"""SQLAlchemy model for AuditLog."""

from datetime import datetime
from typing import Any, Optional
from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class AuditLog(Base):
    """Represents an immutable audit trail entry for domain state changes and transactions."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    actor: Mapped[Optional[str]] = mapped_column(String(100), default="SYSTEM", nullable=True)
    old_values: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    new_values: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} entity={self.entity_type}:{self.entity_id} "
            f"action='{self.action}' actor='{self.actor}'>"
        )
