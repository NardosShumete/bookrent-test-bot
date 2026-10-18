"""ISBN validation, normalization, and variant handling utilities."""

import re
from typing import Optional
from app.models.exceptions import InvalidISBNError


def clean_isbn(raw_isbn: str) -> str:
    """Strip whitespace, dashes, and periods from an ISBN string and uppercase letters.

    Args:
        raw_isbn: Raw ISBN string as supplied by user or scanner.

    Returns:
        Stripped uppercase string containing only alphanumeric characters.
    """
    if not isinstance(raw_isbn, str):
        raise InvalidISBNError("ISBN must be a string")
    return re.sub(r"[\s\-\.]+", "", raw_isbn).strip().upper()


def validate_isbn10(isbn10: str) -> bool:
    """Verify that an ISBN-10 has exactly 10 characters and a valid mod-11 checksum.

    Args:
        isbn10: Cleaned 10-character string.

    Returns:
        True if valid ISBN-10, False otherwise.
    """
    if len(isbn10) != 10:
        return False
    # First 9 characters must be digits; 10th can be digit or 'X'
    if not isbn10[:9].isdigit():
        return False
    if not (isbn10[9].isdigit() or isbn10[9] == "X"):
        return False

    total = 0
    for i, char in enumerate(isbn10):
        val = 10 if char == "X" else int(char)
        total += (10 - i) * val
    return total % 11 == 0


def calculate_isbn13_check_digit(digits12: str) -> str:
    """Calculate the mod-10 check digit for the first 12 digits of an ISBN-13.

    Args:
        digits12: 12-digit numeric string.

    Returns:
        Single character string ('0'-'9') representing the check digit.
    """
    if len(digits12) != 12 or not digits12.isdigit():
        raise InvalidISBNError("Expected 12 numeric digits to compute ISBN-13 check digit")
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits12))
    remainder = total % 10
    check_digit = (10 - remainder) % 10
    return str(check_digit)


def validate_isbn13(isbn13: str) -> bool:
    """Verify that an ISBN-13 has exactly 13 digits and a valid mod-10 checksum.

    Args:
        isbn13: Cleaned 13-character string.

    Returns:
        True if valid ISBN-13, False otherwise.
    """
    if len(isbn13) != 13 or not isbn13.isdigit():
        return False
    expected_check = calculate_isbn13_check_digit(isbn13[:12])
    return isbn13[12] == expected_check


def convert_isbn10_to_isbn13(isbn10: str) -> str:
    """Convert a valid cleaned ISBN-10 to its canonical ISBN-13 equivalent.

    Prepends '978', drops the ISBN-10 check digit, and appends the computed
    ISBN-13 check digit.

    Args:
        isbn10: Cleaned 10-character ISBN.

    Returns:
        Canonical 13-digit ISBN string.
    """
    if not validate_isbn10(isbn10):
        raise InvalidISBNError(f"Cannot convert invalid ISBN-10: '{isbn10}'")
    prefix = "978" + isbn10[:9]
    check_digit = calculate_isbn13_check_digit(prefix)
    return prefix + check_digit


def normalize_isbn(raw_isbn: str) -> str:
    """Normalize and validate an ISBN, returning its canonical 13-digit representation.

    Accepts ISBN-10 (with or without hyphens, including 'X' checksum) and ISBN-13
    (with or without hyphens). All valid ISBN-10 variants are converted to their
    canonical ISBN-13 format ('978...'). This guarantees that duplicate titles
    are not created for the same book when different ISBN formats are entered.

    Args:
        raw_isbn: Raw ISBN input string.

    Returns:
        Canonical 13-digit string.

    Raises:
        InvalidISBNError: If the input is empty, malformed, or fails checksum verification.
    """
    cleaned = clean_isbn(raw_isbn)
    if not cleaned:
        raise InvalidISBNError("ISBN cannot be empty")

    if len(cleaned) == 10:
        if not validate_isbn10(cleaned):
            raise InvalidISBNError(f"Invalid ISBN-10 checksum or format: '{raw_isbn}'")
        return convert_isbn10_to_isbn13(cleaned)

    if len(cleaned) == 13:
        if not validate_isbn13(cleaned):
            raise InvalidISBNError(f"Invalid ISBN-13 checksum or format: '{raw_isbn}'")
        return cleaned

    raise InvalidISBNError(
        f"Invalid ISBN length ({len(cleaned)} chars). Expected 10 or 13 digits: '{raw_isbn}'"
    )
