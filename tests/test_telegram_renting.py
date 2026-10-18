import unittest

from telegram_renting import TelegramRentingBot


class TelegramRentingBotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bot = TelegramRentingBot()

    def test_list_shows_available_books(self) -> None:
        response = self.bot.process_message("u1", "/list")

        self.assertIn("Available books:", response)
        self.assertIn("1. Clean Code - available", response)

    def test_rent_book_success(self) -> None:
        response = self.bot.process_message("u1", "/rent 1")

        self.assertEqual(response, "Rental confirmed: Clean Code")

    def test_rent_book_already_rented_by_other_user(self) -> None:
        self.bot.process_message("u1", "/rent 1")
        response = self.bot.process_message("u2", "/rent 1")

        self.assertEqual(response, "Sorry, this book is currently rented by another user.")

    def test_rent_same_book_twice_same_user(self) -> None:
        self.bot.process_message("u1", "/rent 1")
        response = self.bot.process_message("u1", "/rent 1")

        self.assertEqual(response, "You already rented this book.")


if __name__ == "__main__":
    unittest.main()
