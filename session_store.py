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

    def get_history(self, user_id: int, *, preserve_thinking: bool = False) -> list[Message]:
        with self._lock:
            history = []
            for message in self._messages.get(user_id, []):
                item = {"role": message["role"], "content": message["content"]}
                if preserve_thinking and message["role"] == "assistant" and message.get("reasoning_content"):
                    item["reasoning_content"] = message["reasoning_content"]
                history.append(item)
            return history

    def append_exchange(self, user_id: int, user_message: str, assistant_message: str,
                        *, turn_id: str | None = None, reasoning_content: str = "") -> None:
        with self._lock:
            metadata = {"turn_id": turn_id} if turn_id else {}
            reasoning = {"reasoning_content": reasoning_content} if reasoning_content.strip() else {}
            previous = self._messages.get(user_id)
            history = list(previous or [])
            history.extend(
                [
                    {"role": "user", "content": user_message, **metadata},
                    {"role": "assistant", "content": assistant_message, **metadata, **reasoning},
                ]
            )
            overflow = len(history) - self.max_history_messages
            if overflow > 0:
                del history[:overflow]
            self._messages[user_id] = history
            try:
                self._save_messages()
            except Exception:
                if previous is None:
                    self._messages.pop(user_id, None)
                else:
                    self._messages[user_id] = previous
                raise

    def clear(self, user_id: int) -> None:
        with self._lock:
            self._messages.pop(user_id, None)
            self._save_messages()

    def undo_last_turn(self, user_id: int) -> bool:
        return bool(self.pop_last_turn(user_id))

    def pop_last_turn(self, user_id: int) -> list[Message]:
        """Remove only this user's latest retained turn, atomically and persistently."""
        with self._lock:
            history = self._messages.get(user_id)
            if not history:
                return []
            # History limits can leave an orphan assistant item at the beginning.
            # Remove that remaining fragment when no user item is left.
            start = next((i for i in range(len(history) - 1, -1, -1)
                          if history[i]["role"] == "user"), 0)
            self._messages[user_id] = history[:start]
            try:
                self._save_messages()
            except Exception:
                self._messages[user_id] = history
                raise
            return [message.copy() for message in history[start:]]

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

            item = {"role": role, "content": content}
            if isinstance(message.get("turn_id"), str) and message["turn_id"]:
                item["turn_id"] = message["turn_id"]
            if role == "assistant" and "reasoning_content" in message:
                if not isinstance(message["reasoning_content"], str):
                    raise ValueError(f"Invalid reasoning content for user {user_id}.")
                if message["reasoning_content"].strip():
                    item["reasoning_content"] = message["reasoning_content"]
            validated.append(item)
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
