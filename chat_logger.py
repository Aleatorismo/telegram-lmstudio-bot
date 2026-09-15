from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import html
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from uuid import uuid4
from zoneinfo import ZoneInfo


@dataclass(slots=True)
class ChatLogEntry:
    user_id: int
    display_name: str
    user_message: str
    assistant_message: str
    reasoning_message: str = ""
    turn_id: str = ""


class ChatLogger:
    """One Markdown transcript per conversation, retained across days/restarts."""

    def __init__(self, log_dir: str, timezone_name: str = "Asia/Shanghai") -> None:
        self._base_dir = Path(log_dir).resolve()
        self._timezone = ZoneInfo(timezone_name)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._state_path = self._base_dir / ".active_conversations.json"
        self._lock = threading.RLock()
        self._pending_resets: set[str] = set()
        self._active = self._load_active()

    def _now(self) -> datetime:
        return datetime.now(self._timezone)

    def append_exchange(self, entry: ChatLogEntry) -> Path:
        with self._lock:
            now = self._now()
            self._user_directory(entry.user_id, entry.display_name)
            log_path = self._current_path(entry.user_id)
            if log_path is None:
                log_path = self._start_conversation(entry.user_id, entry.display_name, now)
            timestamp = now.isoformat(sep=" ", timespec="seconds")
            user_text = "\n".join("> " + line for line in entry.user_message.rstrip().split("\n"))
            content = (
                (f"<!-- turn:{entry.turn_id} -->\n" if entry.turn_id else "") +
                f"## {timestamp}\n\n"
                f"### User\n\n{user_text}\n\n"
                + ("<details>\n<summary>Thinking</summary>\n\n<p><i>"
                   + html.escape(entry.reasoning_message.rstrip()).replace("\n", "<br>\n")
                   + "</i></p>\n\n</details>\n\n" if entry.reasoning_message else "")
                + f"### Assistant\n\n{entry.assistant_message.rstrip()}\n\n---\n\n"
            )
            with log_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            return log_path

    def end_conversation(self, user_id: int) -> None:
        """Persist /reset without creating a transcript or losing the user's folder."""
        with self._lock:
            pending = self._pending_resets | {str(user_id)}
            self._save_active(self._active, pending_resets=pending)
            self._pending_resets = pending

    def _start_conversation(self, user_id: int, display_name: str, now: datetime) -> Path:
        directory = self._user_directory(user_id, display_name) / now.strftime("%Y-%m-%d")
        directory.mkdir(parents=True, exist_ok=True)
        log_path = directory / f"conversation_{now:%H-%M-%S-%f}_{uuid4().hex}.md"
        name = re.sub(r"([\\`*_{}\[\]()#+.!|>-])", r"\\\1", html.escape(display_name))
        content = (
            "# Conversation\n\n"
            f"- **User:** {name}\n"
            f"- **Telegram user ID:** `{user_id}`\n"
            f"- **Started:** {now.isoformat(sep=' ', timespec='seconds')}\n"
            f"- **Time zone:** {self._timezone.key}\n\n---\n\n"
        )
        with log_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        active = {**self._active, str(user_id): log_path.relative_to(self._base_dir).as_posix()}
        pending = self._pending_resets - {str(user_id)}
        self._save_active(active, pending_resets=pending)
        self._active = active
        self._pending_resets = pending
        return log_path

    def _validate_path(self, user_id: str, value: str) -> Path:
        relative = Path(value)
        path = (self._base_dir / relative).resolve()
        if (relative.is_absolute() or len(relative.parts) != 3
                or not relative.parts[0].endswith(f"_{user_id}")
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", relative.parts[1])
                or relative.suffix != ".md" or not path.is_relative_to(self._base_dir)
                or path != self._base_dir / relative):
            raise ValueError("Invalid path in chat log conversation index.")
        return path

    def _user_directory(self, user_id: int, display_name: str) -> Path:
        # Telegram usernames are preferred by the caller; full names are the fallback.
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', display_name).strip(' .')[:80] or 'user'
        desired = self._base_dir / f"{name}_{user_id}"
        value = self._active.get(str(user_id))
        existing = (self._validate_path(str(user_id), value).parent.parent if value
                    else self._base_dir / f"user_{user_id}")
        # Keep an established readable name stable when the Telegram name changes.
        # Upgrade the previous user_<id> layout when this user next interacts.
        if existing.name != f"user_{user_id}":
            return existing
        if existing != desired and existing.exists():
            if (existing.resolve().parent != self._base_dir
                    or desired.resolve().parent != self._base_dir):
                raise ValueError("Invalid user log directory.")
            if desired.exists():
                raise FileExistsError(f"Cannot migrate logs: destination already exists: {desired}")
            existing.rename(desired)
            if value:
                active = {**self._active, str(user_id):
                          (Path(desired.name) / Path(value).parts[1] / Path(value).name).as_posix()}
                try:
                    self._save_active(active)
                except Exception:
                    desired.rename(existing)
                    raise
                self._active = active
        if desired.resolve().parent != self._base_dir:
            raise ValueError("Invalid user log directory.")
        return desired

    def mark_undone(self, user_id: int, display_name: str, messages: list[dict[str, str]]) -> Path:
        """Mark an archived turn without removing any text or touching other users."""
        with self._lock:
            self._user_directory(user_id, display_name)
            path = self._current_path(user_id)
            if path is None:
                path = self._start_conversation(user_id, display_name, self._now())
            text = path.read_text(encoding="utf-8")
            stamp = self._now().isoformat(sep=" ", timespec="seconds")
            warning = (f"> [!WARNING]\n> **↩ WITHDRAWN FROM CONTEXT — {stamp}**\n"
                       "> This turn was removed with /undo. The original text is retained below.\n\n")
            turn_id = messages[0].get("turn_id", "") if messages else ""
            marker = f"<!-- turn:{turn_id} -->\n"
            offset = -1
            if re.fullmatch(r"[0-9a-f]{32}", turn_id) and marker in text:
                offset = text.index('\n\n', text.index(marker) + len(marker)) + 2
                if text[offset:].startswith("> [!WARNING]"):
                    return path  # Idempotent if the same withdrawal is retried.
            elif not turn_id:
                # Pre-upgrade transcripts have no IDs. Match only an unambiguous
                # complete exchange, never guess from the latest logged response.
                user = next((m['content'] for m in messages if m['role'] == 'user'), None)
                answer = next((m['content'] for m in messages if m['role'] == 'assistant'), None)
                if user is not None and answer is not None:
                    quoted = '\n'.join('> ' + line for line in user.rstrip().split('\n'))
                    candidates = []
                    boundaries = list(re.finditer(
                        r'^## (?:\d{4}-\d{2}-\d{2} |Context withdrawal)|^<!-- turn:[0-9a-f]{32} -->', text, re.M))
                    for index, match in enumerate(boundaries):
                        end = boundaries[index + 1].start() if index + 1 < len(boundaries) else len(text)
                        section = text[match.start():end]
                        body = section.partition('\n\n')[2]
                        if (body.startswith('### User\n\n' + quoted + '\n\n')
                                and section.endswith('### Assistant\n\n' + answer.rstrip() + '\n\n---\n\n')
                                and not re.search(r'<!-- turn:|WITHDRAWN FROM CONTEXT', section)
                                and not re.search(r'<!-- turn:[0-9a-f]{32} -->\n$', text[:match.start()])):
                            candidates.append(text.index('\n\n', match.start()) + 2)
                    if len(candidates) == 1:
                        offset = candidates[0]
            if offset >= 0:
                text = text[:offset] + warning + text[offset:]
            else:
                # Context may predate Markdown logging, or the original log may
                # have been manually deleted. Preserve an explicit withdrawal copy.
                text += (f"## Context withdrawal — {stamp}\n\n" + warning
                         + "Original archive entry could not be uniquely located. Removed context copy:\n\n")
                for message in messages:
                    quoted = '\n'.join('> ' + line for line in message['content'].split('\n'))
                    text += f"### {message['role'].title()}\n\n{quoted}\n\n"
                text += '---\n\n'
            temp = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                                 dir=path.parent, suffix='.tmp', delete=False) as handle:
                    temp = Path(handle.name)
                    handle.write(text)
                os.replace(temp, path)
            finally:
                if temp is not None:
                    temp.unlink(missing_ok=True)
            return path

    def _load_active(self) -> dict[str, str]:
        if not self._state_path.exists():
            return {}
        data = json.loads(self._state_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("users"), dict):
            raise ValueError("Invalid chat log conversation index.")
        for user_id, value in data["users"].items():
            if not user_id.isdigit() or not isinstance(value, str):
                raise ValueError("Invalid user in chat log conversation index.")
            self._validate_path(user_id, value)
        pending = data.get("pending_resets", [])
        if not isinstance(pending, list) or any(not isinstance(uid, str) or not uid.isdigit() for uid in pending):
            raise ValueError("Invalid pending resets in chat log conversation index.")
        self._pending_resets = set(pending)
        return data["users"]

    def _current_path(self, user_id: int) -> Path | None:
        if str(user_id) in self._pending_resets:
            return None
        value = self._active.get(str(user_id))
        if value is None:
            return None
        path = self._validate_path(str(user_id), value)
        return path if path.is_file() else None

    def _save_active(self, active: dict[str, str], *, pending_resets: set[str] | None = None) -> None:
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self._base_dir,
                                             suffix=".tmp", delete=False) as handle:
                temp = Path(handle.name)
                json.dump({"version": 1, "users": active,
                           "pending_resets": sorted(self._pending_resets if pending_resets is None else pending_resets)},
                          handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temp, self._state_path)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
