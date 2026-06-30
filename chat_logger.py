from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(slots=True)
class ChatLogEntry:
    user_id: int
    display_name: str
    user_message: str
    assistant_message: str


class ChatLogger:
    """Append human-readable chat transcripts grouped by Telegram user."""

    def __init__(self, log_dir: str, timezone_name: str = "Asia/Shanghai") -> None:
        self._base_dir = Path(log_dir)
        self._timezone = ZoneInfo(timezone_name)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def append_exchange(self, entry: ChatLogEntry) -> Path:
        log_path = self._build_log_path(entry.user_id, entry.display_name)
        timestamp = datetime.now(self._timezone).strftime("%Y-%m-%d %H:%M:%S %Z")
        content = (
            f"[{timestamp}]\n"
            f"User ({entry.display_name}):\n{entry.user_message.rstrip()}\n\n"
            f"Assistant:\n{entry.assistant_message.rstrip()}\n"
            f"{'=' * 60}\n\n"
        )
        with log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        return log_path

    def append_reset_marker(self, user_id: int, display_name: str) -> Path:
        log_path = self._build_log_path(user_id, display_name)
        timestamp = datetime.now(self._timezone).strftime("%Y-%m-%d %H:%M:%S %Z")
        content = f"[{timestamp}] Conversation reset by user.\n{'=' * 60}\n\n"
        with log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        return log_path

    def _build_log_path(self, user_id: int, display_name: str) -> Path:
        safe_name = _sanitize_filename(display_name) or f"user_{user_id}"
        return self._base_dir / f"{safe_name}_{user_id}.txt"


def _sanitize_filename(value: str) -> str:
    sanitized = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in value)
    sanitized = sanitized.strip("_")
    while "__" in sanitized:
        sanitized = sanitized.replace("__", "_")
    return sanitized[:80]
