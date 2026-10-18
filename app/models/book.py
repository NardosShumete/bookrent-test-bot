"""SQLAlchemy models for Book and BookCopy."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import BookCopyStatus, VALID_COPY_TRANSITIONS
from app.models.exceptions import InvalidStatusTransitionError


class Book(Base):
    """Represents a catalogued book title.

    A single Book entity represents a bibliographic title and holds metadata
    (ISBN, title, author, category, rental pricing). Physical inventory is
    represented by child BookCopy entities.
    """

    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    isbn: Mapped[str] = mapped_column(String(17), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    author: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rental_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    copies: Mapped[List["BookCopy"]] = relationship(
        "BookCopy",
        back_populates="book",
        cascade="all, delete-orphan",
        order_by="BookCopy.copy_number",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint("rental_price >= 0", name="ck_books_rental_price_non_negative"),
        CheckConstraint(
            "page_count IS NULL OR page_count > 0",
            name="ck_books_page_count_positive",
        ),
    )

    def __repr__(self) -> str:
        return f"<Book id={self.id} isbn='{self.isbn}' title='{self.title[:30]}'>"


class BookCopy(Base):
    """Represents an individual physical hardcopy of a book title.

    Tracks physical condition and lifecycle status (ON_SHELF, RESERVED,
    RENTED, OVERDUE, DAMAGED, LOST) with strict transition validation.
    """

    __tablename__ = "book_copies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True
    )
    copy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    barcode: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default=BookCopyStatus.ON_SHELF.value,
        nullable=False,
        index=True,
    )
    condition_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    book: Mapped["Book"] = relationship("Book", back_populates="copies")
    rentals: Mapped[List["Rental"]] = relationship(  # type: ignore[name-defined]
        "Rental",
        back_populates="copy",
        order_by="Rental.checkout_time.desc()",
    )

    __table_args__ = (
        UniqueConstraint("book_id", "copy_number", name="uq_book_copies_book_id_copy_number"),
        CheckConstraint(
            f"status IN ('{BookCopyStatus.ON_SHELF.value}', '{BookCopyStatus.RESERVED.value}', "
            f"'{BookCopyStatus.RENTED.value}', '{BookCopyStatus.OVERDUE.value}', "
            f"'{BookCopyStatus.DAMAGED.value}', '{BookCopyStatus.LOST.value}')",
            name="ck_book_copies_status_valid",
        ),
        CheckConstraint("copy_number > 0", name="ck_book_copies_copy_number_positive"),
    )

    def can_transition_to(self, new_status: BookCopyStatus | str) -> bool:
        """Check whether the copy can legally transition to the given status."""
        target = new_status if isinstance(new_status, BookCopyStatus) else BookCopyStatus(new_status)
        current = BookCopyStatus(self.status)
        if current == target:
            return True
        return target in VALID_COPY_TRANSITIONS.get(current, set())

    def transition_to(self, new_status: BookCopyStatus | str, reason: Optional[str] = None) -> None:
        """Execute a validated lifecycle status transition on the physical copy.

        Args:
            new_status: Target BookCopyStatus enum or string value.
            reason: Optional explanation or note logged to condition_notes.

        Raises:
            InvalidStatusTransitionError: If the transition is disallowed by state rules.
        """
        target = new_status if isinstance(new_status, BookCopyStatus) else BookCopyStatus(new_status)
        if not self.can_transition_to(target):
            raise InvalidStatusTransitionError(
                f"Cannot transition copy #{self.id} (barcode: {self.barcode}) "
                f"from {self.status} to {target.value}"
            )
        self.status = target.value
        if reason:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
            entry = f"[{ts}] {self.status}: {reason}"
            self.condition_notes = f"{self.condition_notes}\n{entry}" if self.condition_notes else entry

    def __repr__(self) -> str:
        return f"<BookCopy id={self.id} book_id={self.book_id} barcode='{self.barcode}' status='{self.status}'>"
