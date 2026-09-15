import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from telegram.constants import ChatType

from lmstudio_client import LMStudioError, ChatDelta
from model_store import ModelStore
from telegram_bot import (PollingErrorState, model_command, think_command, settings_command,
                          params_command, chat_message, reset_command, start_command, parse_parameter_assignments)


def test_extended_parameter_commands(tmp_path):
    store, context, update = make_context(tmp_path)
    async def run():
        context.args = ['on', 'repetition_penalty=1.05', 'reasoning_effort=xhigh',
                        'chat_template_kwargs={"enable_thinking":', 'true,', '"preserve_thinking":', 'true}']
        await params_command(update, context)
        current = store.current(1)
        assert current['parameters']['repetition_penalty'] == 1.05
        assert current['reasoning_effort'] == 'xhigh'
        text = update.message.reply_text.call_args.args[0]
        assert 'Reasoning effort: xhigh' in text and '"enable_thinking": true' in text
        context.args = ['chat_template_kwargs.preserve_thinking=false', 'reasoning_effort=']
        await params_command(update, context)
        assert store.current(1)['parameters']['chat_template_kwargs'] == {'enable_thinking': True, 'preserve_thinking': False}
        assert store.current(1)['reasoning_effort'] is None
        context.args = ['off']
        await think_command(update, context)
        assert store.current(1)['reasoning_effort'] == 'none'
    asyncio.run(run())


@pytest.mark.parametrize('args', [
    ['temperature=1', 'temperature=0.5'], ['chat_template_kwargs={broken}'],
    ['chat_template_kwargs={}temperature=1'], ['temperature'],
])
def test_invalid_parameter_command_syntax(args):
    from model_store import ModelConfigError
    with pytest.raises(ModelConfigError):
        parse_parameter_assignments(args)


def make_context(tmp_path):
    store = ModelStore(str(tmp_path / 'models.json'), str(tmp_path / 'users.json'), 'dual')
    store.merge_discovered([{'id': 'dual', 'type': 'both'}, {'id': 'plain', 'type': 'non_thinking'}])
    async def stream(**kwargs):
        yield ChatDelta(content='answer')
    lm = SimpleNamespace(list_models=AsyncMock(side_effect=LMStudioError('offline')), stream_chat=Mock(side_effect=stream))
    sessions = SimpleNamespace(get_history=Mock(return_value=[]), append_exchange=Mock(), clear=Mock())
    context = SimpleNamespace(args=[], bot=SimpleNamespace(send_chat_action=AsyncMock(), do_api_request=AsyncMock(), send_message=AsyncMock(), send_message_draft=AsyncMock()), application=SimpleNamespace(bot_data={
        'model_store': store, 'lmstudio_client': lm, 'session_store': sessions,
        'chat_logger': SimpleNamespace(append_exchange=Mock(), end_conversation=Mock(), mark_undone=Mock()),
        'settings': SimpleNamespace(telegram_typing_interval=0.01, telegram_draft_interval=0.01, lmstudio_timeout=30), 'polling_error_state': PollingErrorState()}))
    update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock(), text='hello'),
        effective_user=SimpleNamespace(id=1, username='user', first_name='', last_name=''),
        effective_chat=SimpleNamespace(id=1, type=ChatType.PRIVATE))
    return store, context, update


def test_commands_to_chat_request_and_reset(tmp_path):
    store, context, update = make_context(tmp_path)
    async def run():
        await start_command(update, context)
        await model_command(update, context)
        assert 'locally saved' in update.message.reply_text.call_args.args[0]
        context.args = ['on', 'temperature=0.6', 'max_tokens=4096']
        await params_command(update, context)
        context.args = ['off', 'temperature=0.2']
        await params_command(update, context)
        context.args = ['off']
        await think_command(update, context)
        await chat_message(update, context)
        await context.application.bot_data['active_generations'][1].worker
        saved_id = context.application.bot_data['session_store'].append_exchange.call_args.kwargs['turn_id']
        logged_entry = context.application.bot_data['chat_logger'].append_exchange.call_args.args[0]
        assert len(saved_id) == 32 and saved_id == logged_entry.turn_id
        context.application.bot_data['lmstudio_client'].stream_chat.assert_called_once_with(
            history=[], user_message='hello', model='dual', parameters={'temperature': 0.2}, reasoning_effort='none')
        await settings_command(update, context)
        assert 'Thinking: off' in update.message.reply_text.call_args.args[0]
        context.args = ['temperature=']
        await params_command(update, context)
        assert store.current(1)['parameters'] == {}
        context.args = ['dual']
        await model_command(update, context)
        assert store.current(1)['mode'] == 'thinking'
        await reset_command(update, context)
        context.application.bot_data['chat_logger'].end_conversation.assert_called_once_with(user_id=1)
        assert update.message.reply_text.call_args.args[0] == 'Your conversation history has been cleared.'
        assert store.current(1)['parameters']['temperature'] == 0.6
        for call in update.message.reply_text.call_args_list:
            assert call.args[0].isascii()
    asyncio.run(run())


def test_invalid_commands_preserve_state(tmp_path):
    store, context, update = make_context(tmp_path)
    async def run():
        before = store.current(1)
        for callback, args in [(model_command, ['missing']), (think_command, ['invalid']),
            (params_command, ['temperature=0.2', 'top_k=1.2']), (params_command, ['bad-format'])]:
            context.args = args
            await callback(update, context)
            assert store.current(1) == before
        context.args = ['plain']
        await model_command(update, context)
        context.args = ['on']
        await think_command(update, context)
        assert 'only supports' in update.message.reply_text.call_args.args[0]
    asyncio.run(run())


def test_group_chat_is_ignored(tmp_path):
    _, context, update = make_context(tmp_path)
    update.effective_chat.type = ChatType.GROUP
    asyncio.run(chat_message(update, context))
    context.application.bot_data['lmstudio_client'].stream_chat.assert_not_called()
