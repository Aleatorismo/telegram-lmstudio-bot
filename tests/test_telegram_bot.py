from __future__ import annotations

from telegram_bot import split_message


def test_split_message_keeps_short_message_intact() -> None:
    assert split_message("hello", limit=10) == ["hello"]


def test_split_message_splits_long_text_on_newlines_when_possible() -> None:
    text = "A" * 8 + "\n" + "B" * 8 + "\n" + "C" * 8

    chunks = split_message(text, limit=10)

    assert chunks == ["AAAAAAAA\n", "BBBBBBBB\n", "CCCCCCCC"]


def test_split_message_splits_long_paragraph_without_losing_content() -> None:
    text = "x" * 25

    chunks = split_message(text, limit=10)

    assert chunks == ["x" * 10, "x" * 10, "x" * 5]
    assert "".join(chunks) == text
