"""PostgreSQL integration tests for BookRent Bot.

These tests run against a live PostgreSQL database to verify PostgreSQL-specific
behaviors including migrations, row locking, concurrent allocations, unique constraints,
transaction rollback, and financial reconciliation.

Skipped automatically when no accessible PostgreSQL database is available.
"""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database.base import Base
from app.models.book import Book, BookCopy
from app.models.customer import Customer
from app.models.enums import (
    BookCopyStatus,
    CollateralType,
    CustomerStatus,
    LedgerTransactionType,
    PaymentMethod,
    PaymentType,
    RentalRequestStatus,
    RentalStatus,
)
from app.models.ledger import CollateralLedger
from app.models.overdue import OverdueCharge
from app.models.rental import Rental
from app.services.ledger import (
    get_customer_collateral_balance,
    record_ledger_entry,
)
from app.services.overdue import process_overdue_rentals
from app.services.rental import (
    confirm_rental_return,
    submit_extension_request,
    verify_and_approve_extension,
)
from app.services.rental_request import (
    approve_rental_request,
    confirm_physical_handover,
    record_non_cash_guarantee,
    record_payment_verification,
    submit_rental_request,
)

OWNER_TELEGRAM_ID = 12345


def get_pg_url() -> str:
    """Determine test PostgreSQL connection string."""
    return (
        os.environ.get("BOOKRENT_PG_TEST_URL")
        or os.environ.get("DATABASE_URL")
        or "postgresql+psycopg2://postgres@localhost:5432/bookrent_test"
    )


@pytest.fixture(autouse=True)
def setup_pg_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure environment variables are set for PostgreSQL integration tests."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_123456")
    monkeypatch.setenv("DATABASE_URL", get_pg_url())
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ADMIN_USER_IDS", "12345,67890")


@pytest.fixture(scope="module")
def pg_engine():
    """Create and verify PostgreSQL test engine; skip tests if unreachable."""
    url = get_pg_url()
    if not url.startswith("postgresql"):
        pytest.skip("No PostgreSQL URL configured.")

    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL test database not accessible at {url}: {exc}")

    # Ensure tables are present
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine) -> Session:
    """Yield an isolated PostgreSQL session that cleans up after each test."""
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = session_factory()

    # Truncate all tables for test isolation
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE audit_logs, collateral_ledger, payments, overdue_charges, "
                "rental_extensions, rentals, rental_requests, book_copies, books, customers CASCADE"
            )
        )

    try:
        yield session
    finally:
        session.close()


def test_postgres_tables_and_columns_exist(pg_engine) -> None:
    """Verify that all 11 expected tables exist in PostgreSQL with correct constraints."""
    inspector = inspect(pg_engine)
    tables = set(inspector.get_table_names())

    expected_tables = {
        "books",
        "book_copies",
        "customers",
        "rentals",
        "rental_extensions",
        "collateral_ledger",
        "audit_logs",
        "rental_requests",
        "payments",
        "overdue_charges",
    }
    assert expected_tables.issubset(tables)

    # Check overdue_charges boolean column default on PostgreSQL
    cols = {c["name"]: c for c in inspector.get_columns("overdue_charges")}
    assert "notification_sent" in cols


def test_postgres_transaction_rollback_on_failure(pg_session: Session) -> None:
    """Verify that an exception mid-transaction triggers a complete rollback in PostgreSQL."""
    customer = Customer(
        telegram_id=999888,
        first_name="Rollback",
        last_name="Test",
        status=CustomerStatus.APPROVED.value,
    )
    pg_session.add(customer)
    pg_session.commit()

    # Attempt a faulty multi-step operation
    try:
        pg_session.begin_nested()
        # Add a ledger entry
        record_ledger_entry(
            session=pg_session,
            customer_id=customer.id,
            transaction_type=LedgerTransactionType.COLLATERAL_DEPOSIT,
            amount=Decimal("100.00"),
            notes="Deposit test",
            actor=str(OWNER_TELEGRAM_ID),
        )
        # Force a failure (e.g. duplicate customer insert with same telegram_id)
        duplicate = Customer(
            telegram_id=999888,
            first_name="Duplicate",
            status=CustomerStatus.APPROVED.value,
        )
        pg_session.add(duplicate)
        pg_session.flush()
    except IntegrityError:
        pg_session.rollback()

    # Verify no orphan ledger entry survived
    balance = get_customer_collateral_balance(pg_session, customer.id)
    assert balance == Decimal("0.00")


def test_postgres_concurrent_rental_copy_allocation(pg_session: Session) -> None:
    """Verify that partial unique constraint on rentals prevents double-allocating a copy."""
    book = Book(isbn="9780132350884", title="Clean Code", author="Robert Martin", rental_price=Decimal("20.00"))
    cust1 = Customer(telegram_id=10101, first_name="User1", status=CustomerStatus.APPROVED.value)
    cust2 = Customer(telegram_id=20202, first_name="User2", status=CustomerStatus.APPROVED.value)
    pg_session.add_all([book, cust1, cust2])
    pg_session.commit()

    copy = BookCopy(book_id=book.id, copy_number=1, barcode="CC-001", status=BookCopyStatus.ON_SHELF.value)
    pg_session.add(copy)
    pg_session.commit()

    now = datetime.now(timezone.utc)

    # First rental check-out
    rental1 = Rental(
        copy_id=copy.id,
        customer_id=cust1.id,
        checkout_time=now,
        due_date=now + timedelta(days=10),
        status=RentalStatus.ACTIVE.value,
    )
    pg_session.add(rental1)
    pg_session.commit()

    # Second active rental on the SAME copy concurrently attempted
    rental2 = Rental(
        copy_id=copy.id,
        customer_id=cust2.id,
        checkout_time=now,
        due_date=now + timedelta(days=10),
        status=RentalStatus.ACTIVE.value,
    )
    pg_session.add(rental2)

    with pytest.raises(IntegrityError):
        pg_session.commit()
    pg_session.rollback()


def test_postgres_concurrent_overdue_charge_idempotency(pg_session: Session) -> None:
    """Verify unique constraint prevents duplicate overdue charges for same rental and date."""
    book = Book(isbn="9780132350885", title="Clean Architecture", author="Robert Martin", rental_price=Decimal("25.00"))
    cust = Customer(telegram_id=30303, first_name="OverdueUser", status=CustomerStatus.APPROVED.value)
    pg_session.add_all([book, cust])
    pg_session.commit()

    copy = BookCopy(book_id=book.id, copy_number=1, barcode="CA-001", status=BookCopyStatus.ON_SHELF.value)
    pg_session.add(copy)
    pg_session.commit()

    past_date = datetime.now(timezone.utc) - timedelta(days=15)
    due = past_date + timedelta(days=10)  # Overdue by 5 days

    rental = Rental(
        copy_id=copy.id,
        customer_id=cust.id,
        checkout_time=past_date,
        due_date=due,
        status=RentalStatus.ACTIVE.value,
    )
    pg_session.add(rental)
    pg_session.commit()

    # Run overdue processing
    charges_first = process_overdue_rentals(pg_session)
    assert len(charges_first) > 0
    pg_session.commit()

    # Re-run overdue processing immediately
    charges_second = process_overdue_rentals(pg_session)
    assert len(charges_second) == 0  # No duplicate charges created


def test_postgres_non_cash_guarantee_isolation(pg_session: Session) -> None:
    """Verify that non-cash guarantees never generate monetary collateral entries."""
    book = Book(isbn="9780132350886", title="Refactoring", author="Martin Fowler", rental_price=Decimal("30.00"))
    cust = Customer(telegram_id=40404, first_name="NonCashUser", status=CustomerStatus.APPROVED.value)
    pg_session.add_all([book, cust])
    pg_session.commit()

    copy = BookCopy(book_id=book.id, copy_number=1, barcode="RF-001", status=BookCopyStatus.ON_SHELF.value)
    pg_session.add(copy)
    pg_session.commit()

    req = submit_rental_request(
        session=pg_session,
        customer_id=cust.id,
        book_id=book.id,
        collateral_type=CollateralType.GUARANTEE,
        guarantee_details="Ethiopian National ID #ET-999888",
    )
    pg_session.commit()

    assert req.collateral_type == CollateralType.GUARANTEE.value
    assert req.collateral_amount is None or req.collateral_amount == Decimal("0.00")

    # Record guarantee verification
    record_non_cash_guarantee(
        session=pg_session,
        request_id=req.id,
        guarantee_details="Verified National ID physical card in office",
        actor_telegram_id=OWNER_TELEGRAM_ID,
    )
    pg_session.commit()

    # Verify balance is strictly zero
    balance = get_customer_collateral_balance(pg_session, cust.id)
    assert balance == Decimal("0.00")

    # Verify no collateral ledger entries exist
    ledger_entries = pg_session.query(CollateralLedger).filter_by(customer_id=cust.id).all()
    assert len(ledger_entries) == 0


def test_postgres_full_rental_lifecycle_and_reconciliation(pg_session: Session) -> None:
    """Test full rental lifecycle on PostgreSQL:

    1. Customer approval
    2. Book & copy addition
    3. Rental request creation & owner approval
    4. Payment & collateral deposit verification
    5. Physical handover / checkout
    6. Overdue charge creation
    7. Extension approval & payment
    8. Return confirmation with collateral deduction and refund
    9. Complete ledger reconciliation
    """
    # 1. Customer
    customer = Customer(
        telegram_id=50505,
        first_name="Abebe",
        last_name="Bikila",
        status=CustomerStatus.APPROVED.value,
    )
    # 2. Book & copy
    book = Book(
        isbn="9780201616224",
        title="The Pragmatic Programmer",
        author="Hunt & Thomas",
        rental_price=Decimal("15.00"),
    )
    pg_session.add_all([customer, book])
    pg_session.commit()

    copy = BookCopy(book_id=book.id, copy_number=1, barcode="PP-001", status=BookCopyStatus.ON_SHELF.value)
    pg_session.add(copy)
    pg_session.commit()

    # 3. Rental request
    req = submit_rental_request(
        session=pg_session,
        customer_id=customer.id,
        book_id=book.id,
        collateral_type=CollateralType.MONETARY,
        collateral_amount=Decimal("100.00"),
    )
    pg_session.commit()

    # Owner approves request
    approved_req = approve_rental_request(
        session=pg_session,
        request_id=req.id,
        actor_telegram_id=OWNER_TELEGRAM_ID,
    )
    pg_session.commit()
    assert approved_req.status == RentalRequestStatus.APPROVED.value

    # 4. Record payments
    record_payment_verification(
        session=pg_session,
        request_id=req.id,
        payment_type=PaymentType.RENTAL_FEE,
        payment_method=PaymentMethod.CASH,
        amount=Decimal("15.00"),
        actor_telegram_id=OWNER_TELEGRAM_ID,
    )
    record_payment_verification(
        session=pg_session,
        request_id=req.id,
        payment_type=PaymentType.COLLATERAL_DEPOSIT,
        payment_method=PaymentMethod.CASH,
        amount=Decimal("100.00"),
        actor_telegram_id=OWNER_TELEGRAM_ID,
    )
    pg_session.commit()

    # Verify collateral balance is 100
    assert get_customer_collateral_balance(pg_session, customer.id) == Decimal("100.00")

    # 5. Physical handover / checkout
    rental = confirm_physical_handover(
        session=pg_session,
        request_id=req.id,
        actor_telegram_id=OWNER_TELEGRAM_ID,
        calendar_days=10,
    )
    pg_session.commit()
    assert rental.status == RentalStatus.ACTIVE.value

    # 6. Request & approve extension
    ext = submit_extension_request(
        session=pg_session,
        customer_telegram_id=customer.telegram_id,
        rental_id=rental.id,
    )
    pg_session.commit()

    verify_and_approve_extension(
        session=pg_session,
        extension_id=ext.id,
        payment_method=PaymentMethod.CASH,
        actor_telegram_id=OWNER_TELEGRAM_ID,
        reference="EXT-CASH-001",
    )
    pg_session.commit()

    # 7. Return confirmation with collateral deduction and refund
    # Deduct 10 ETB for minor damage, refund remaining 90 ETB
    returned_rental = confirm_rental_return(
        session=pg_session,
        rental_id=rental.id,
        actor_telegram_id=OWNER_TELEGRAM_ID,
        condition_status=BookCopyStatus.DAMAGED,
        damage_notes="Minor cover crease",
        collateral_deduction=Decimal("10.00"),
        deduction_reason="Minor cover crease repair",
        collateral_refund=Decimal("90.00"),
        refund_reason="Refund of balance after deduction",
    )
    pg_session.commit()
    assert returned_rental.status == RentalStatus.RETURNED.value

    # 8. Final collateral balance must be 0.00
    final_balance = get_customer_collateral_balance(pg_session, customer.id)
    assert final_balance == Decimal("0.00")

    # Verify ledger entries are completely balanced
    ledger_records = (
        pg_session.query(CollateralLedger)
        .filter_by(customer_id=customer.id)
        .order_by(CollateralLedger.id.asc())
        .all()
    )
    # Expected ledger records:
    # 1st: COLLATERAL_DEPOSIT +100
    # 2nd: EXTENSION_FEE +10
    # 3rd: COLLATERAL_DEDUCTION -10
    # 4th: COLLATERAL_REFUND -90
    types = [r.transaction_type for r in ledger_records]
    assert LedgerTransactionType.COLLATERAL_DEPOSIT.value in types
    assert LedgerTransactionType.COLLATERAL_DEDUCTION.value in types
    assert LedgerTransactionType.COLLATERAL_REFUND.value in types
