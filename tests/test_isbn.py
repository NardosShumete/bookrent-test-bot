"""Tests for ISBN validation, normalization, and cross-variant handling."""

import pytest
from app.models.exceptions import InvalidISBNError
from app.services.isbn import (
    clean_isbn,
    convert_isbn10_to_isbn13,
    normalize_isbn,
    validate_isbn10,
    validate_isbn13,
)


def test_clean_isbn_strips_hyphens_spaces_and_uppercases() -> None:
    """Verify clean_isbn eliminates formatting noise and uppercases check digits."""
    assert clean_isbn(" 978-0-306-40615-7 ") == "9780306406157"
    assert clean_isbn("0-8044-2957-x") == "080442957X"
    assert clean_isbn("978.1.86197.876.9") == "9781861978769"
    assert clean_isbn("0 306 40615 2") == "0306406152"


def test_clean_isbn_type_error() -> None:
    """Verify clean_isbn rejects non-string inputs."""
    with pytest.raises(InvalidISBNError):
        clean_isbn(1234567890)  # type: ignore[arg-type]


def test_validate_isbn10_valid_numeric_and_x_checksum() -> None:
    """Verify validate_isbn10 handles standard numeric and X check digits."""
    assert validate_isbn10("0306406152") is True
    assert validate_isbn10("080442957X") is True
    assert validate_isbn10("0471958697") is True


def test_validate_isbn10_invalid() -> None:
    """Verify validate_isbn10 rejects invalid lengths, characters, or bad checksums."""
    assert validate_isbn10("0306406153") is False  # Bad checksum
    assert validate_isbn10("080442957Y") is False  # Non-X letter
    assert validate_isbn10("12345") is False       # Too short
    assert validate_isbn10("0306406152123") is False  # Too long


def test_validate_isbn13_valid_and_invalid() -> None:
    """Verify validate_isbn13 correctly checks mod-10 check digit."""
    assert validate_isbn13("9780306406157") is True
    assert validate_isbn13("9781861978769") is True
    assert validate_isbn13("9780804429573") is True
    # Invalid check digits
    assert validate_isbn13("9780306406158") is False
    assert validate_isbn13("9781861978760") is False
    assert validate_isbn13("978030640615") is False  # 12 digits


def test_convert_isbn10_to_isbn13() -> None:
    """Verify ISBN-10 properly converts to equivalent canonical ISBN-13."""
    # 0-306-40615-2 -> 978-0-306-40615-7
    assert convert_isbn10_to_isbn13("0306406152") == "9780306406157"
    # 0-8044-2957-X -> 978-0-8044-2957-3
    assert convert_isbn10_to_isbn13("080442957X") == "9780804429573"


def test_convert_invalid_isbn10_raises() -> None:
    """Verify conversion raises InvalidISBNError on corrupt ISBN-10."""
    with pytest.raises(InvalidISBNError):
        convert_isbn10_to_isbn13("0306406159")


def test_normalize_isbn_variants_produce_identical_canonical_isbn() -> None:
    """Verify that different representations of the same title produce identical canonical ISBN."""
    canonical = "9780306406157"
    variants = [
        "0-306-40615-2",
        "0306406152",
        " 0 306 40615 2 ",
        "978-0-306-40615-7",
        "9780306406157",
        "978 0 306 40615 7",
        "978.0.306.40615.7",
    ]
    for variant in variants:
        assert normalize_isbn(variant) == canonical, f"Failed for variant: {variant}"


def test_normalize_isbn_invalid_inputs_raise() -> None:
    """Verify normalize_isbn rejects empty, invalid length, and corrupted inputs."""
    with pytest.raises(InvalidISBNError, match="cannot be empty"):
        normalize_isbn("   ")

    with pytest.raises(InvalidISBNError, match="Invalid ISBN length"):
        normalize_isbn("1234567")

    with pytest.raises(InvalidISBNError, match="Invalid ISBN-10 checksum"):
        normalize_isbn("0-306-40615-9")

    with pytest.raises(InvalidISBNError, match="Invalid ISBN-13 checksum"):
        normalize_isbn("978-0-306-40615-0")
