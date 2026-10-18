from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class Book:
    id: str
    title: str


class TelegramRentingBot:
    def __init__(self) -> None:
        self._catalog: Dict[str, Book] = {
            "1": Book(id="1", title="Clean Code"),
            "2": Book(id="2", title="The Pragmatic Programmer"),
            "3": Book(id="3", title="Designing Data-Intensive Applications"),
        }
        self._rentals: Dict[str, str] = {}

    def process_message(self, user_id: str, message: str) -> str:
        text = message.strip()
        if text.startswith("/start"):
            return "Welcome to BookRent Bot. Use /list to see books and /rent <book_id> to rent one."

        if text.startswith("/list"):
            return self._format_catalog()

        if text.startswith("/rent"):
            parts = text.split(maxsplit=1)
            if len(parts) != 2:
                return "Usage: /rent <book_id>"
            return self._rent_book(user_id=user_id, book_id=parts[1].strip())

        return "Unknown command. Try /start, /list, or /rent <book_id>."

    def _format_catalog(self) -> str:
        lines: List[str] = ["Available books:"]
        for book_id, book in self._catalog.items():
            renter = self._rentals.get(book_id)
            status = "available" if renter is None else "rented"
            lines.append(f"{book_id}. {book.title} - {status}")
        return "\n".join(lines)

    def _rent_book(self, user_id: str, book_id: str) -> str:
        if book_id not in self._catalog:
            return "Book not found. Use /list to see valid IDs."

        current_renter = self._rentals.get(book_id)
        if current_renter is None:
            self._rentals[book_id] = user_id
            return f"Rental confirmed: {self._catalog[book_id].title}"

        if current_renter == user_id:
            return "You already rented this book."

        return "Sorry, this book is currently rented by another user."
