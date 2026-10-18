"""Customer domain service managing registration, approvals, rejections, and authorization."""

from datetime import datetime, timezone
from decimal import Decimal
import re
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from app.config import get_settings
from app.logging_config import mask_phone
from app.models.customer import Customer
from app.models.enums import CustomerStatus
from app.models.exceptions import (
    CustomerNotFoundError,
    InvalidCustomerStatusError,
    UnauthorizedError,
)
from app.services.audit import record_audit_log


def is_owner(telegram_id: Optional[int]) -> bool:
    """Check whether a given Telegram user ID has authorized owner privileges.

    Args:
        telegram_id: Telegram user ID.

    Returns:
        True if the user ID is in configured ADMIN_USER_IDS, False otherwise.
    """
    if telegram_id is None:
        return False
    admin_ids = get_settings().admin_user_ids
    return int(telegram_id) in admin_ids


def require_owner(actor_telegram_id: Optional[int]) -> None:
    """Enforce that the acting Telegram user has owner/admin privileges.

    Args:
        actor_telegram_id: Telegram user ID of the caller.

    Raises:
        UnauthorizedError: If user is not configured in ADMIN_USER_IDS.
    """
    if not is_owner(actor_telegram_id):
        raise UnauthorizedError(
            f"User {actor_telegram_id} is not an authorized library owner."
        )


def get_customer_by_telegram_id(session: Session, telegram_id: int) -> Optional[Customer]:
    """Retrieve customer record by Telegram user ID.

    Args:
        session: Active SQLAlchemy database session.
        telegram_id: Telegram user ID.

    Returns:
        Customer instance or None if not found.
    """
    return session.query(Customer).filter(Customer.telegram_id == telegram_id).first()


def register_customer(
    session: Session,
    telegram_id: int,
    first_name: str,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
) -> Tuple[Customer, bool]:
    """Register a new customer account or retrieve existing account.

    New customer accounts default to PENDING status and must be approved by
    an owner before book checkouts or catalogue searching are permitted.

    Args:
        session: Active SQLAlchemy database session.
        telegram_id: Telegram user ID.
        first_name: User first name.
        last_name: Optional user last name.
        username: Optional Telegram @username.

    Returns:
        Tuple of (Customer instance, created boolean flag).
    """
    existing = get_customer_by_telegram_id(session, telegram_id)
    if existing is not None:
        # Update names/username if changed
        updated = False
        if first_name and existing.first_name != first_name:
            existing.first_name = first_name
            updated = True
        if last_name is not None and existing.last_name != last_name:
            existing.last_name = last_name
            updated = True
        if username is not None and existing.username != username:
            existing.username = username
            updated = True
        if updated:
            session.flush([existing])
        return existing, False

    customer = Customer(
        telegram_id=telegram_id,
        first_name=first_name,
        last_name=last_name,
        username=username,
        status=CustomerStatus.PENDING.value,
    )
    session.add(customer)
    session.flush([customer])

    record_audit_log(
        session=session,
        entity_type="CUSTOMER",
        entity_id=customer.id,
        action="REGISTER",
        actor=str(telegram_id),
        new_values={
            "telegram_id": telegram_id,
            "username": username,
            "status": customer.status,
        },
    )

    return customer, True


def get_pending_customers(
    session: Session, actor_telegram_id: Optional[int] = None
) -> List[Customer]:
    """List all customer accounts awaiting owner approval.

    Args:
        session: Active SQLAlchemy database session.
        actor_telegram_id: Telegram user ID of the caller (must be an owner).

    Returns:
        List of Customer instances with PENDING status.

    Raises:
        UnauthorizedError: If actor_telegram_id is not an owner.
    """
    require_owner(actor_telegram_id)
    return (
        session.query(Customer)
        .filter(Customer.status == CustomerStatus.PENDING.value)
        .order_by(Customer.created_at.asc())
        .all()
    )


def approve_customer(
    session: Session, customer_id: int, actor_telegram_id: int
) -> Customer:
    """Approve a pending customer account.

    Args:
        session: Active SQLAlchemy database session.
        customer_id: Internal ID of the customer.
        actor_telegram_id: Telegram user ID of approving owner.

    Returns:
        Updated Customer instance with APPROVED status.

    Raises:
        UnauthorizedError: If actor_telegram_id is not an owner.
        CustomerNotFoundError: If customer does not exist.
        InvalidCustomerStatusError: If customer is not currently PENDING.
    """
    require_owner(actor_telegram_id)

    customer = (
        session.query(Customer)
        .filter(Customer.id == customer_id)
        .with_for_update()
        .first()
    )
    if customer is None:
        raise CustomerNotFoundError(f"Customer #{customer_id} not found")

    if customer.status != CustomerStatus.PENDING.value:
        raise InvalidCustomerStatusError(
            f"Customer #{customer.id} has status '{customer.status}', only PENDING accounts can be approved."
        )

    customer.status = CustomerStatus.APPROVED.value
    session.flush([customer])

    record_audit_log(
        session=session,
        entity_type="CUSTOMER",
        entity_id=customer.id,
        action="APPROVE",
        actor=str(actor_telegram_id),
        new_values={"status": customer.status},
    )

    return customer


def reject_customer(
    session: Session,
    customer_id: int,
    actor_telegram_id: int,
    reason: Optional[str] = None,
) -> Customer:
    """Reject a pending customer registration.

    Args:
        session: Active SQLAlchemy database session.
        customer_id: Internal ID of the customer.
        actor_telegram_id: Telegram user ID of rejecting owner.
        reason: Optional explanation for rejection.

    Returns:
        Updated Customer instance with REJECTED status.

    Raises:
        UnauthorizedError: If actor_telegram_id is not an owner.
        CustomerNotFoundError: If customer does not exist.
        InvalidCustomerStatusError: If customer is not currently PENDING.
    """
    require_owner(actor_telegram_id)

    customer = (
        session.query(Customer)
        .filter(Customer.id == customer_id)
        .with_for_update()
        .first()
    )
    if customer is None:
        raise CustomerNotFoundError(f"Customer #{customer_id} not found")

    if customer.status != CustomerStatus.PENDING.value:
        raise InvalidCustomerStatusError(
            f"Customer #{customer.id} has status '{customer.status}', only PENDING accounts can be rejected."
        )

    customer.status = CustomerStatus.REJECTED.value
    customer.rejection_reason = reason
    customer.rejected_at = datetime.now(timezone.utc)
    session.flush([customer])

    record_audit_log(
        session=session,
        entity_type="CUSTOMER",
        entity_id=customer.id,
        action="REJECT",
        actor=str(actor_telegram_id),
        new_values={
            "status": customer.status,
            "rejection_reason": reason,
        },
        reason=reason,
    )

    return customer


def get_rejected_customers(
    session: Session, actor_telegram_id: Optional[int] = None
) -> List[Customer]:
    """List all customer accounts with REJECTED status.

    Args:
        session: Active SQLAlchemy database session.
        actor_telegram_id: Telegram user ID of the caller (must be an owner).

    Returns:
        List of Customer instances with REJECTED status, ordered by rejection time descending.

    Raises:
        UnauthorizedError: If actor_telegram_id is not an owner.
    """
    require_owner(actor_telegram_id)
    return (
        session.query(Customer)
        .filter(Customer.status == CustomerStatus.REJECTED.value)
        .order_by(Customer.rejected_at.desc().nullslast(), Customer.updated_at.desc())
        .all()
    )


def reapprove_customer(
    session: Session, customer_id: int, actor_telegram_id: int
) -> Customer:
    """Reconsider and reapprove a previously rejected (or pending) customer account.

    Args:
        session: Active SQLAlchemy database session.
        customer_id: Internal ID of the customer.
        actor_telegram_id: Telegram user ID of approving owner.

    Returns:
        Updated Customer instance with APPROVED status and cleared rejection fields.

    Raises:
        UnauthorizedError: If actor_telegram_id is not an owner.
        CustomerNotFoundError: If customer does not exist.
        InvalidCustomerStatusError: If customer is already APPROVED.
    """
    require_owner(actor_telegram_id)

    customer = (
        session.query(Customer)
        .filter(Customer.id == customer_id)
        .with_for_update()
        .first()
    )
    if customer is None:
        raise CustomerNotFoundError(f"Customer #{customer_id} not found")

    if customer.status == CustomerStatus.APPROVED.value:
        raise InvalidCustomerStatusError(
            f"Customer #{customer.id} is already APPROVED."
        )

    previous_status = customer.status
    previous_reason = customer.rejection_reason

    customer.status = CustomerStatus.APPROVED.value
    customer.rejection_reason = None
    customer.rejected_at = None
    session.flush([customer])

    record_audit_log(
        session=session,
        entity_type="CUSTOMER",
        entity_id=customer.id,
        action="REAPPROVE",
        actor=str(actor_telegram_id),
        old_values={"status": previous_status, "rejection_reason": previous_reason},
        new_values={"status": customer.status},
        reason="Admin reapproved rejected customer account",
    )

    return customer


def get_customer_language(session: Session, telegram_id: int) -> Optional[str]:
    """Retrieve saved language preference for a customer or administrator.

    Args:
        session: Active SQLAlchemy database session.
        telegram_id: Telegram user ID.

    Returns:
        Language code (e.g. 'en', 'am') or None if not set.
    """
    customer = get_customer_by_telegram_id(session, telegram_id)
    if customer is not None and customer.language:
        return customer.language
    return None


def set_customer_language(
    session: Session,
    telegram_id: int,
    language: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
) -> Customer:
    """Save or update language preference for a customer or administrator.

    Ensures administrators who do not yet have a customer record are registered
    with APPROVED status so their preferences persist without table duplication.

    Args:
        session: Active SQLAlchemy database session.
        telegram_id: Telegram user ID.
        language: Language code ('en' or 'am').
        first_name: Optional user first name.
        last_name: Optional user last name.
        username: Optional Telegram username.

    Returns:
        Persisted Customer instance.
    """
    customer = get_customer_by_telegram_id(session, telegram_id)
    if customer is None:
        is_admin = is_owner(telegram_id)
        status = CustomerStatus.APPROVED.value if is_admin else CustomerStatus.PENDING.value
        customer = Customer(
            telegram_id=telegram_id,
            first_name=first_name or ("Admin" if is_admin else "Customer"),
            last_name=last_name,
            username=username,
            status=status,
            language=language,
        )
        session.add(customer)
        session.flush([customer])

        record_audit_log(
            session=session,
            entity_type="CUSTOMER",
            entity_id=customer.id,
            action="SET_LANGUAGE",
            actor=str(telegram_id),
            new_values={"language": language, "status": customer.status},
        )
    else:
        customer.language = language
        if first_name and not customer.first_name:
            customer.first_name = first_name
        if last_name and not customer.last_name:
            customer.last_name = last_name
        if username and not customer.username:
            customer.username = username
        session.flush([customer])

    return customer


def normalize_phone_number(raw_phone: Optional[str]) -> Optional[str]:
    """Normalize and validate phone numbers without hardcoding a single country code.

    Supports Ethiopian formats:
      - '0911223344' -> '+251911223344'
      - '0711223344' -> '+251711223344'
      - '251911223344' -> '+251911223344'
      - '+251911223344' -> '+251911223344'
    Supports international formats:
      - '+14155552671' -> '+14155552671'
      - '00441234567890' -> '+441234567890'

    Returns:
        E.164-style normalized string with leading '+', or None if invalid.
    """
    if not raw_phone:
        return None

    cleaned = re.sub(r"[\s\-\(\)\.]", "", raw_phone.strip())
    if not cleaned:
        return None

    # Handle international prefix 00 -> +
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]

    # Handle Ethiopian local prefixes: 09... or 07... (10 digits)
    if re.match(r"^0[97]\d{8}$", cleaned):
        return "+251" + cleaned[1:]

    # Handle Ethiopian prefix without plus: 2519... or 2517... (12 digits)
    if re.match(r"^251[97]\d{8}$", cleaned):
        return "+" + cleaned

    # Handle already + formatted E.164: + followed by 7 to 15 digits
    if re.match(r"^\+[1-9]\d{6,14}$", cleaned):
        return cleaned

    # Pure numeric between 9 and 15 digits: assume international if >9 digits
    if re.match(r"^[1-9]\d{8,14}$", cleaned):
        return "+" + cleaned

    return None


def submit_customer_registration(
    session: Session,
    telegram_id: int,
    national_id_file_id: str,
    phone_number: str,
    phone_source: str,
    phone_verified: Optional[bool] = None,
    address: Optional[str] = None,
    latitude: Optional[Decimal] = None,
    longitude: Optional[Decimal] = None,
    consent_given: bool = True,
    consent_policy_version: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
    language: Optional[str] = None,
) -> Customer:
    """Submit complete customer verification details and place account into PENDING review.

    Args:
        session: Active SQLAlchemy database session.
        telegram_id: Telegram user ID.
        national_id_file_id: Telegram photo file ID of the National ID.
        phone_number: User phone number.
        phone_source: Source of phone ('TELEGRAM_CONTACT' or 'MANUAL').
        address: Human-readable location or address string.
        latitude: Optional GPS latitude coordinate.
        longitude: Optional GPS longitude coordinate.
        consent_given: Whether user gave explicit privacy consent.
        consent_policy_version: Policy version consented to.
        first_name: Optional first name.
        last_name: Optional last name.
        username: Optional username.

    Returns:
        Updated Customer instance.
    """
    if not national_id_file_id:
        raise ValueError("National ID photo file ID is required.")

    norm_phone = normalize_phone_number(phone_number)
    if not norm_phone:
        raise ValueError(f"Invalid phone number format: {phone_number}")

    if not address and (latitude is None or longitude is None):
        raise ValueError("Either readable address or GPS coordinates are required.")

    now = datetime.now(timezone.utc)
    policy_ver = consent_policy_version or get_settings().consent_policy_version

    customer = get_customer_by_telegram_id(session, telegram_id)
    if customer is None:
        customer = Customer(
            telegram_id=telegram_id,
            first_name=first_name or "Reader",
            last_name=last_name,
            username=username,
            status=CustomerStatus.PENDING.value,
        )
        session.add(customer)
    else:
        if first_name and not customer.first_name:
            customer.first_name = first_name
        if last_name and not customer.last_name:
            customer.last_name = last_name
        if username and not customer.username:
            customer.username = username
        customer.status = CustomerStatus.PENDING.value

    customer.phone_number = norm_phone
    if phone_verified is not None:
        customer.phone_verified = phone_verified
    else:
        customer.phone_verified = (phone_source == "TELEGRAM_CONTACT")
    customer.phone_source = phone_source
    if language:
        customer.language = language
    customer.address = address
    customer.latitude = latitude
    customer.longitude = longitude
    customer.national_id_file_id = national_id_file_id
    customer.national_id_uploaded_at = now
    customer.consent_given = consent_given
    customer.consent_timestamp = now
    customer.consent_policy_version = policy_ver
    customer.registration_completed_at = now

    session.flush([customer])

    record_audit_log(
        session=session,
        entity_type="CUSTOMER",
        entity_id=customer.id,
        action="SUBMIT_VERIFICATION",
        actor=str(telegram_id),
        new_values={
            "phone_source": phone_source,
            "has_id_photo": True,
            "has_location": bool(address or (latitude and longitude)),
            "consent_policy_version": policy_ver,
            "status": customer.status,
            "phone_masked": mask_phone(norm_phone),
        },
        reason="Customer completed verification submission",
    )

    return customer

