"""Audit logging service for tracking entity mutations and lifecycle events."""

from typing import Any, Optional
from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def record_audit_log(
    session: Session,
    entity_type: str,
    entity_id: str | int,
    action: str,
    actor: Optional[str] = "SYSTEM",
    old_values: Optional[dict[str, Any]] = None,
    new_values: Optional[dict[str, Any]] = None,
    reason: Optional[str] = None,
) -> AuditLog:
    """Create and persist an immutable audit trail entry.

    Args:
        session: Active SQLAlchemy database session.
        entity_type: Model or domain name (e.g. "BOOK", "BOOK_COPY", "RENTAL").
        entity_id: Identifier of the subject entity.
        action: Descriptive verb for the mutation (e.g. "CREATE", "STATUS_CHANGE", "APPROVE").
        actor: Identity of who performed the action (e.g. Telegram ID or "SYSTEM").
        old_values: JSON-serializable dictionary of previous attribute values.
        new_values: JSON-serializable dictionary of updated attribute values.
        reason: Optional human-readable justification or context.

    Returns:
        The newly created AuditLog record.
    """
    audit = AuditLog(
        entity_type=str(entity_type).upper(),
        entity_id=str(entity_id),
        action=str(action).upper(),
        actor=actor,
        old_values=old_values,
        new_values=new_values,
        reason=reason,
    )
    session.add(audit)
    session.flush([audit])
    return audit
