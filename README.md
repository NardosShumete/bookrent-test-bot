# bookrent-test-bot

Minimal Telegram-style renting bot logic for book rentals.

## Supported commands

- `/start` — shows quick help
- `/list` — lists available/rented books
- `/rent <book_id>` — rents a book by ID

## Run tests

```bash
python -m unittest tests/test_telegram_renting.py
```
