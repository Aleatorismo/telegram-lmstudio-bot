from datetime import datetime
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from chat_logger import ChatLogEntry, ChatLogger


def entry(uid=123, name='alice'):
    return ChatLogEntry(uid, name, 'hello\nsecond line', '**hi there**', 'Think <carefully>\nthen answer')


def fixed_time(logger, monkeypatch, day=12, hour=23):
    monkeypatch.setattr(logger, '_now', lambda: datetime(2026, 9, day, hour, 30, tzinfo=logger._timezone))


def test_markdown_layout_and_legacy_logs_are_untouched(tmp_path, monkeypatch):
    legacy = tmp_path / 'alice_123.txt'
    legacy.write_text('old log', encoding='utf-8')
    logger = ChatLogger(str(tmp_path))
    fixed_time(logger, monkeypatch)
    path = logger.append_exchange(entry())
    assert path.parent == tmp_path / 'alice_123' / '2026-09-12'
    assert path.suffix == '.md'
    text = path.read_text(encoding='utf-8')
    assert '# Conversation' in text
    assert '**Telegram user ID:** `123`' in text
    assert '### User\n\n> hello\n> second line' in text
    assert '### Assistant\n\n**hi there**' in text
    assert '<details>' in text and '<i>Think &lt;carefully&gt;' in text
    assert '+08:00' in text
    assert legacy.read_text(encoding='utf-8') == 'old log'


def test_conversation_survives_midnight_restart_and_rename(tmp_path, monkeypatch):
    logger = ChatLogger(str(tmp_path))
    fixed_time(logger, monkeypatch)
    first = logger.append_exchange(entry())
    fixed_time(logger, monkeypatch, day=13, hour=1)
    assert logger.append_exchange(entry(name='renamed')) == first
    restarted = ChatLogger(str(tmp_path))
    fixed_time(restarted, monkeypatch, day=14)
    assert restarted.append_exchange(entry()) == first
    assert first.read_text(encoding='utf-8').count('### Assistant') == 3
    assert len(list(tmp_path.rglob('*.md'))) == 1


def test_reset_defers_file_until_next_exchange_across_restart(tmp_path, monkeypatch):
    logger = ChatLogger(str(tmp_path))
    fixed_time(logger, monkeypatch)
    old = logger.append_exchange(entry())
    original = old.read_bytes()
    fixed_time(logger, monkeypatch, day=13)
    logger.end_conversation(123)
    logger.end_conversation(123)
    assert list(tmp_path.rglob('*.md')) == [old]
    assert not (old.parent.parent / '2026-09-13').exists()
    restarted = ChatLogger(str(tmp_path))
    fixed_time(restarted, monkeypatch, day=14)
    new = restarted.append_exchange(entry(name='renamed'))
    assert new != old and new.parent.name == '2026-09-14'
    assert new.parent.parent == old.parent.parent
    assert ChatLogger(str(tmp_path)).append_exchange(entry()) == new
    assert len(list(tmp_path.rglob('*.md'))) == 2
    assert old.read_bytes() == original


def test_users_with_same_name_are_isolated(tmp_path, monkeypatch):
    logger = ChatLogger(str(tmp_path))
    fixed_time(logger, monkeypatch)
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(lambda uid: logger.append_exchange(entry(uid, '../same')), range(1, 5)))
    assert len(set(paths)) == 4
    other = paths[1].read_bytes()
    logger.end_conversation(1)
    assert logger.append_exchange(entry(2)) == paths[1]
    assert paths[1].read_bytes().startswith(other)
    restarted = ChatLogger(str(tmp_path))
    assert restarted.append_exchange(entry(3)) == paths[2]


def test_reset_without_any_messages_creates_no_user_directory(tmp_path):
    logger = ChatLogger(str(tmp_path))
    logger.end_conversation(123)
    restarted = ChatLogger(str(tmp_path))
    restarted.end_conversation(123)
    assert not list(tmp_path.glob('*/'))
    assert not list(tmp_path.rglob('*.md'))
    path = restarted.append_exchange(entry())
    assert path.is_file()
    assert ChatLogger(str(tmp_path)).append_exchange(entry()) == path


def test_missing_current_log_creates_new_file(tmp_path):
    logger = ChatLogger(str(tmp_path))
    original = logger.append_exchange(entry())
    original.unlink()
    replacement = logger.append_exchange(entry())
    assert replacement.exists() and replacement != original


def test_invalid_index_cannot_target_another_user(tmp_path):
    (tmp_path / '.active_conversations.json').write_text(
        '{"version":1,"users":{"123":"user_456/2026-09-12/conversation.md"}}', encoding='utf-8')
    with pytest.raises(ValueError):
        ChatLogger(str(tmp_path))


def test_failed_index_write_does_not_switch_active_log(tmp_path, monkeypatch):
    logger = ChatLogger(str(tmp_path))
    original = logger.append_exchange(entry())
    index = (tmp_path / '.active_conversations.json').read_bytes()
    def fail(active, **kwargs):
        raise OSError('disk failure')
    monkeypatch.setattr(logger, '_save_active', fail)
    with pytest.raises(OSError):
        logger.end_conversation(123)
    assert logger.append_exchange(entry()) == original
    assert (tmp_path / '.active_conversations.json').read_bytes() == index


def test_legacy_directory_migration_preserves_files_and_restart(tmp_path):
    old = tmp_path / 'user_123' / '2026-09-12' / 'conversation.md'
    old.parent.mkdir(parents=True)
    old.write_text('existing conversation\n', encoding='utf-8')
    sibling = old.with_name('earlier.md')
    sibling.write_text('earlier conversation', encoding='utf-8')
    (tmp_path / '.active_conversations.json').write_text(json.dumps({
        'version': 1, 'users': {'123': old.relative_to(tmp_path).as_posix()}}), encoding='utf-8')
    logger = ChatLogger(str(tmp_path))
    new = logger.append_exchange(entry())
    assert new == tmp_path / 'alice_123' / '2026-09-12' / 'conversation.md'
    assert new.read_text(encoding='utf-8').startswith('existing conversation\n')
    assert new.with_name('earlier.md').read_text(encoding='utf-8') == 'earlier conversation'
    assert not old.parent.parent.exists()
    assert ChatLogger(str(tmp_path)).append_exchange(entry()) == new


def test_migration_rolls_back_if_index_cannot_be_saved(tmp_path, monkeypatch):
    old = tmp_path / 'user_123' / '2026-09-12' / 'conversation.md'
    old.parent.mkdir(parents=True)
    old.write_text('existing', encoding='utf-8')
    (tmp_path / '.active_conversations.json').write_text(json.dumps({
        'version': 1, 'users': {'123': old.relative_to(tmp_path).as_posix()}}), encoding='utf-8')
    logger = ChatLogger(str(tmp_path))
    def fail(active):
        raise OSError('disk failure')
    monkeypatch.setattr(logger, '_save_active', fail)
    with pytest.raises(OSError):
        logger.append_exchange(entry())
    assert old.read_text(encoding='utf-8') == 'existing'
    assert not (tmp_path / 'alice_123').exists()


def test_legacy_undo_marks_original_content_and_never_deletes_it(tmp_path):
    logger = ChatLogger(str(tmp_path))
    path = logger.append_exchange(entry())
    messages = [{'role': 'user', 'content': entry().user_message},
                {'role': 'assistant', 'content': entry().assistant_message}]
    logger.mark_undone(123, 'alice', messages)
    text = path.read_text(encoding='utf-8')
    assert text.count('### Assistant') == 1
    assert text.count('WITHDRAWN FROM CONTEXT') == 1
    assert text.index('WITHDRAWN FROM CONTEXT') < text.index('### User')
    assert '**hi there**' in text and 'Think &lt;carefully&gt;' in text


def test_missing_or_ambiguous_old_archive_keeps_withdrawal_copy(tmp_path):
    logger = ChatLogger(str(tmp_path))
    path = logger.append_exchange(entry())
    logger.append_exchange(entry())
    before = path.read_text(encoding='utf-8')
    logger.mark_undone(123, 'alice', [{'role': 'user', 'content': entry().user_message},
                                    {'role': 'assistant', 'content': entry().assistant_message}])
    text = path.read_text(encoding='utf-8')
    assert text.startswith(before)
    assert 'Original archive entry could not be uniquely located' in text
    assert text.count('**hi there**') == 3


def test_legacy_match_ignores_newer_identical_numbered_turn(tmp_path):
    logger = ChatLogger(str(tmp_path))
    path = logger.append_exchange(entry())
    numbered = entry()
    numbered.turn_id = 'a' * 32
    logger.append_exchange(numbered)
    messages = [{'role': 'user', 'content': entry().user_message},
                {'role': 'assistant', 'content': entry().assistant_message}]
    logger.mark_undone(123, 'alice', messages)
    text = path.read_text(encoding='utf-8')
    before, after = text.split('<!-- turn:' + 'a' * 32 + ' -->')
    assert 'WITHDRAWN FROM CONTEXT' in before
    assert 'WITHDRAWN FROM CONTEXT' not in after
    assert 'Removed context copy' not in text


def test_archive_replace_failure_preserves_original(tmp_path, monkeypatch):
    logger = ChatLogger(str(tmp_path))
    path = logger.append_exchange(entry())
    before = path.read_bytes()
    def fail(*args):
        raise OSError('disk failure')
    monkeypatch.setattr('chat_logger.os.replace', fail)
    with pytest.raises(OSError):
        logger.mark_undone(123, 'alice', [{'role': 'user', 'content': entry().user_message},
                                        {'role': 'assistant', 'content': entry().assistant_message}])
    assert path.read_bytes() == before
    assert not list(path.parent.glob('*.tmp'))
