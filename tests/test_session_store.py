from __future__ import annotations

import json
from pathlib import Path

from session_store import SessionStore


def test_append_exchange_keeps_recent_history() -> None:
    storage_path = Path("tests_runtime/session_case_1.json")
    storage_path.unlink(missing_ok=True)
    store = SessionStore(max_history_messages=4, storage_path=str(storage_path))

    store.append_exchange(1, "u1", "a1")
    store.append_exchange(1, "u2", "a2")
    store.append_exchange(1, "u3", "a3")

    assert store.get_history(1) == [
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
        {"role": "assistant", "content": "a3"},
    ]


def test_clear_removes_history() -> None:
    storage_path = Path("tests_runtime/session_case_2.json")
    storage_path.unlink(missing_ok=True)
    store = SessionStore(max_history_messages=6, storage_path=str(storage_path))
    store.append_exchange(7, "hello", "world")

    store.clear(7)

    assert store.get_history(7) == []


def test_persists_history_across_restarts() -> None:
    storage_path = Path("tests_runtime/session_case_3.json")
    storage_path.unlink(missing_ok=True)
    store = SessionStore(max_history_messages=6, storage_path=str(storage_path))
    store.append_exchange(42, "hello", "world")

    reloaded = SessionStore(max_history_messages=6, storage_path=str(storage_path))

    assert reloaded.get_history(42) == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]


def test_keeps_users_isolated_in_single_file() -> None:
    storage_path = Path("tests_runtime/session_case_4.json")
    storage_path.unlink(missing_ok=True)
    store = SessionStore(max_history_messages=6, storage_path=str(storage_path))
    store.append_exchange(1, "u1", "a1")
    store.append_exchange(2, "u2", "a2")

    payload = json.loads(storage_path.read_text(encoding="utf-8"))

    assert payload["users"]["1"][0]["content"] == "u1"
    assert payload["users"]["2"][0]["content"] == "u2"
    assert store.get_history(1) != store.get_history(2)
