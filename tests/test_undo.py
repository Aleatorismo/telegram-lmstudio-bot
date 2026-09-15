import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from uuid import uuid4

from chat_logger import ChatLogger, ChatLogEntry

from session_store import SessionStore
from telegram_bot import undo_command, reset_command
from test_model_commands import make_context


def test_repeated_undo_persists_and_preserves_other_users(tmp_path):
    path = tmp_path / 'sessions.json'
    store = SessionStore(5, str(path))
    for i in range(3):
        store.append_exchange(1, f'u{i}', f'a{i}')
    store.append_exchange(2, 'other', 'untouched')
    other = store.get_history(2)
    assert store.undo_last_turn(1)
    assert len(store.get_history(1)) == 3
    assert store.undo_last_turn(1)
    assert len(store.get_history(1)) == 1
    assert store.undo_last_turn(1)  # Oldest turn was truncated by the history limit.
    assert not store.undo_last_turn(1)
    assert not store.undo_last_turn(999)
    reloaded = SessionStore(5, str(path))
    assert reloaded.get_history(1) == []
    assert reloaded.get_history(2) == other


def test_concurrent_users_undo_only_their_own_turns(tmp_path):
    store = SessionStore(100, str(tmp_path / 'sessions.json'))
    for uid in range(8):
        for i in range(10):
            store.append_exchange(uid, f'{uid}:{i}', 'answer')
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(store.undo_last_turn, range(8)))
    for uid in range(8):
        assert len(store.get_history(uid)) == 18
        assert store.get_history(uid)[-2]['content'] == f'{uid}:8'


def test_undo_failure_restores_in_memory_history(tmp_path, monkeypatch):
    store = SessionStore(10, str(tmp_path / 'sessions.json'))
    store.append_exchange(1, 'hello', 'world')
    before = store.get_history(1)
    def fail():
        raise OSError('disk failure')
    monkeypatch.setattr(store, '_save_messages', fail)
    with pytest.raises(OSError):
        store.undo_last_turn(1)
    assert store.get_history(1) == before


def test_undo_command_no_cross_user_target_or_message_deletion(tmp_path):
    _, ctx, update = make_context(tmp_path)
    store = SessionStore(10, str(tmp_path / 'sessions.json'))
    store.append_exchange(1, 'own', 'answer')
    store.append_exchange(2, 'other', 'answer')
    ctx.application.bot_data['session_store'] = store
    async def run():
        ctx.args = ['2']
        await undo_command(update, ctx)
        assert len(store.get_history(1)) == 2
        ctx.args = []
        await undo_command(update, ctx)
        assert store.get_history(1) == []
        assert len(store.get_history(2)) == 2
        await undo_command(update, ctx)
        assert 'no conversation context' in update.message.reply_text.call_args.args[0]
        ctx.application.bot_data['chat_logger'].append_exchange.assert_not_called()
        ctx.bot.do_api_request.assert_not_called()
    asyncio.run(run())


def test_context_changes_rejected_during_generation(tmp_path):
    _, ctx, update = make_context(tmp_path)
    ctx.application.bot_data['active_generations'] = {1: object()}
    async def run():
        await undo_command(update, ctx)
        await reset_command(update, ctx)
        ctx.application.bot_data['session_store'].clear.assert_not_called()
        assert 'wait' in update.message.reply_text.call_args.args[0]
    asyncio.run(run())


def test_archive_undo_ids_survive_restart_repeated_text_and_truncation(tmp_path):
    store = SessionStore(3, str(tmp_path / 'sessions.json'))
    logger = ChatLogger(str(tmp_path / 'logs'))
    ids = [uuid4().hex for _ in range(3)]
    for turn_id in ids[:2]:
        store.append_exchange(1, 'same question', 'same answer', turn_id=turn_id)
        path = logger.append_exchange(ChatLogEntry(1, 'alice', 'same question', 'same answer',
                                                   'private thinking', turn_id))
    # A failed generation has an archive but no context and must never be marked.
    logger.append_exchange(ChatLogEntry(1, 'alice', 'failed question', 'failed answer', turn_id=ids[2]))
    other = logger.append_exchange(ChatLogEntry(2, 'alice', 'other', 'untouched'))
    other_bytes = other.read_bytes()
    store = SessionStore(3, str(tmp_path / 'sessions.json'))
    logger = ChatLogger(str(tmp_path / 'logs'))
    assert all(set(m) == {'role', 'content'} for m in store.get_history(1))
    for turn_id in reversed(ids[:2]):
        removed = store.pop_last_turn(1)
        assert removed[0]['turn_id'] == turn_id
        logger.mark_undone(1, 'alice', removed)
        logger.mark_undone(1, 'alice', removed)  # Idempotent marks.
    assert not store.pop_last_turn(1)
    text = path.read_text(encoding='utf-8')
    assert text.count('WITHDRAWN FROM CONTEXT') == 2
    for turn_id in ids[:2]:
        section = text.split(f'<!-- turn:{turn_id} -->\n', 1)[1]
        assert section.split('\n\n', 1)[1].startswith('> [!WARNING]')
    assert f'<!-- turn:{ids[2]} -->\n## ' in text
    assert text.count('same answer') == 2 and text.count('private thinking') == 2
    assert other.read_bytes() == other_bytes
    before = path.read_bytes()
    logger.end_conversation(1)
    turn_id = uuid4().hex
    store.append_exchange(1, 'new', 'answer', turn_id=turn_id)
    new = logger.append_exchange(ChatLogEntry(1, 'alice', 'new', 'answer', turn_id=turn_id))
    logger.mark_undone(1, 'alice', store.pop_last_turn(1))
    assert path.read_bytes() == before
    assert 'WITHDRAWN FROM CONTEXT' in new.read_text(encoding='utf-8')


def test_command_reports_archive_failure_after_context_undo(tmp_path):
    _, ctx, update = make_context(tmp_path)
    store = SessionStore(10, str(tmp_path / 'sessions.json'))
    store.append_exchange(1, 'own', 'answer')
    ctx.application.bot_data['session_store'] = store
    ctx.application.bot_data['chat_logger'].mark_undone.side_effect = OSError('disk failure')
    asyncio.run(undo_command(update, ctx))
    assert not store.get_history(1)
    assert 'archive could not be marked' in update.message.reply_text.call_args.args[0]


def test_failed_context_persistence_never_marks_archive(tmp_path, monkeypatch):
    _, ctx, update = make_context(tmp_path)
    store = SessionStore(10, str(tmp_path / 'sessions.json'))
    store.append_exchange(1, 'own', 'answer')
    ctx.application.bot_data['session_store'] = store
    def fail():
        raise OSError('disk failure')
    monkeypatch.setattr(store, '_save_messages', fail)
    with pytest.raises(OSError):
        asyncio.run(undo_command(update, ctx))
    ctx.application.bot_data['chat_logger'].mark_undone.assert_not_called()
    assert len(store.get_history(1)) == 2
