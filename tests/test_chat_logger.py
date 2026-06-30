from __future__ import annotations

from pathlib import Path

from chat_logger import ChatLogEntry, ChatLogger


def test_append_exchange_writes_human_readable_log() -> None:
    log_dir = Path("tests_runtime/chat_logger_case_1")
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = ChatLogger(str(log_dir), timezone_name="UTC")

    path = logger.append_exchange(
        ChatLogEntry(
            user_id=123,
            display_name="alice",
            user_message="hello",
            assistant_message="hi there",
        )
    )

    content = path.read_text(encoding="utf-8")
    assert path.name == "alice_123.txt"
    assert "User (alice):\nhello" in content
    assert "Assistant:\nhi there" in content


def test_append_reset_marker_uses_same_file() -> None:
    log_dir = Path("tests_runtime/chat_logger_case_2")
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = ChatLogger(str(log_dir), timezone_name="UTC")

    path = logger.append_reset_marker(user_id=7, display_name="bob")

    content = path.read_text(encoding="utf-8")
    assert path.name == "bob_7.txt"
    assert "Conversation reset by user." in content
