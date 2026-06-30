from __future__ import annotations

import json
import threading
from pathlib import Path


Message = dict[str, str]


class SessionStore:
    """Persistent session storage keyed by Telegram user ID."""

    def __init__(self, max_history_messages: int, storage_path: str) -> None:
        self.max_history_messages = max_history_messages
        self._storage_path = Path(storage_path)
        self._lock = threading.RLock()
        self._messages = self._load_messages()

    def get_history(self, user_id: int) -> list[Message]:
        with self._lock:
            return [message.copy() for message in self._messages.get(user_id, [])]

    def append_exchange(self, user_id: int, user_message: str, assistant_message: str) -> None:
        with self._lock:
            history = self._messages.setdefault(user_id, [])
            history.extend(
                [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": assistant_message},
                ]
            )
            overflow = len(history) - self.max_history_messages
            if overflow > 0:
                del history[:overflow]
            self._save_messages()

    def clear(self, user_id: int) -> None:
        with self._lock:
            self._messages.pop(user_id, None)
            self._save_messages()

    def _load_messages(self) -> dict[int, list[Message]]:
        if not self._storage_path.exists():
            return {}

        with self._storage_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        if not isinstance(payload, dict):
            raise ValueError("Session store file must contain a JSON object.")

        users = payload.get("users", {})
        if not isinstance(users, dict):
            raise ValueError("Session store file field 'users' must be a JSON object.")

        messages_by_user: dict[int, list[Message]] = {}
        for user_id_text, history in users.items():
            try:
                user_id = int(user_id_text)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid user id in session store: {user_id_text!r}") from exc

            messages_by_user[user_id] = self._validate_history(history, user_id)
        return messages_by_user

    def _validate_history(self, history: object, user_id: int) -> list[Message]:
        if not isinstance(history, list):
            raise ValueError(f"Session history for user {user_id} must be a list.")

        validated: list[Message] = []
        for message in history:
            if not isinstance(message, dict):
                raise ValueError(f"Session message for user {user_id} must be an object.")

            role = message.get("role")
            content = message.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                raise ValueError(f"Invalid session message format for user {user_id}.")

            validated.append({"role": role, "content": content})
        return validated

    def _save_messages(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "users": {
                str(user_id): [message.copy() for message in history]
                for user_id, history in sorted(self._messages.items())
            },
        }
        temp_path = self._storage_path.with_suffix(f"{self._storage_path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        temp_path.replace(self._storage_path)
