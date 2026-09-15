from __future__ import annotations

import json
import pytest
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


def test_thinking_persists_but_only_replays_when_enabled(tmp_path):
    path = tmp_path / 'sessions.json'
    store = SessionStore(10, str(path))
    store.append_exchange(1, 'question', 'answer', turn_id='turn', reasoning_content='thinking\n<details>')
    store.append_exchange(2, 'other', 'other answer', reasoning_content='other thoughts')
    store = SessionStore(10, str(path))
    assert store.get_history(1) == [{'role': 'user', 'content': 'question'}, {'role': 'assistant', 'content': 'answer'}]
    enabled = store.get_history(1, preserve_thinking=True)
    assert enabled[-1] == {'role': 'assistant', 'content': 'answer', 'reasoning_content': 'thinking\n<details>'}
    assert all('turn_id' not in message for message in enabled)
    enabled[-1]['reasoning_content'] = 'mutated copy'
    assert store.get_history(1, preserve_thinking=True)[-1]['reasoning_content'] == 'thinking\n<details>'
    store.undo_last_turn(1)
    assert not store.get_history(1, preserve_thinking=True)
    assert store.get_history(2, preserve_thinking=True)[-1]['reasoning_content'] == 'other thoughts'
    store.clear(2)
    assert not SessionStore(10, str(path)).get_history(2, preserve_thinking=True)


def test_old_cache_and_truncated_turns_remain_compatible(tmp_path):
    path = tmp_path / 'sessions.json'
    path.write_text(json.dumps({'version': 1, 'users': {'1': [
        {'role': 'user', 'content': 'legacy question'}, {'role': 'assistant', 'content': 'legacy answer'}]}}), encoding='utf-8')
    store = SessionStore(3, str(path))
    assert store.get_history(1, preserve_thinking=True) == store.get_history(1)
    store.append_exchange(1, 'new', 'answer', reasoning_content='thought')
    assert len(store.get_history(1, preserve_thinking=True)) == 3
    store.append_exchange(1, 'newer', 'newer answer', reasoning_content='newer thought')
    store.undo_last_turn(1)
    assert store.get_history(1, preserve_thinking=True) == [
        {'role': 'assistant', 'content': 'answer', 'reasoning_content': 'thought'}]
    store.undo_last_turn(1)
    assert not store.get_history(1, preserve_thinking=True)


def test_failed_append_or_undo_preserves_saved_reasoning(tmp_path, monkeypatch):
    path = tmp_path / 'sessions.json'
    store = SessionStore(2, str(path))
    store.append_exchange(1, 'question', 'answer', reasoning_content='thought')
    before = path.read_bytes()
    def fail():
        raise OSError('disk failure')
    monkeypatch.setattr(store, '_save_messages', fail)
    for operation in (lambda: store.append_exchange(1, 'next', 'next answer', reasoning_content='new thought'),
                      lambda: store.undo_last_turn(1)):
        with pytest.raises(OSError):
            operation()
        assert store.get_history(1, preserve_thinking=True)[-1]['reasoning_content'] == 'thought'
        assert path.read_bytes() == before
