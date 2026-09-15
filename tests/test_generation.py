import asyncio
from unittest.mock import Mock

from telegram import Update

from generation import shutdown_generations
from lmstudio_client import ChatDelta, LMStudioError
from telegram_bot import chat_message
from test_model_commands import make_context
from session_store import SessionStore


def test_failure_preserves_visible_partial_without_successful_history(tmp_path):
    _, ctx, update = make_context(tmp_path)
    async def stream(**kwargs):
        yield ChatDelta(reasoning='thinking', content='partial')
        raise LMStudioError('connection interrupted')
    ctx.application.bot_data['lmstudio_client'].stream_chat = Mock(side_effect=stream)
    async def run():
        await chat_message(update, ctx)
        await ctx.application.bot_data['active_generations'][1].worker
        ctx.application.bot_data['session_store'].append_exchange.assert_not_called()
        assert 'Generation interrupted' in str(ctx.bot.do_api_request.call_args)
    asyncio.run(run())


def test_busy_user_rejected_and_shutdown_closes_stream(tmp_path):
    _, ctx, update = make_context(tmp_path)
    async def run():
        ready, closed = asyncio.Event(), asyncio.Event()
        async def stream(**kwargs):
            try:
                yield ChatDelta(reasoning='thinking')
                ready.set()
                await asyncio.Event().wait()
            finally:
                closed.set()
        ctx.application.bot_data['lmstudio_client'].stream_chat = Mock(side_effect=stream)
        await chat_message(update, ctx)
        await ready.wait()
        await chat_message(update, ctx)
        assert 'already being generated' in update.message.reply_text.call_args.args[0]
        ctx.application.bot_data['lmstudio_client'].stream_chat.assert_called_once()
        await shutdown_generations(ctx.application)
        assert closed.is_set()
        assert not ctx.application.bot_data['active_generations']
        ctx.application.bot_data['session_store'].append_exchange.assert_not_called()
    asyncio.run(run())


def test_successful_reasoning_replays_after_restart_and_follows_current_model(tmp_path):
    models, ctx, update = make_context(tmp_path)
    path = tmp_path / 'sessions.json'
    sessions = SessionStore(20, str(path))
    sessions.append_exchange(2, 'other', 'other answer', reasoning_content='other private thought')
    ctx.application.bot_data['session_store'] = sessions
    histories = []
    async def stream(**kwargs):
        histories.append(kwargs['history'])
        yield ChatDelta(reasoning='first ')
        yield ChatDelta(reasoning='thought', content='answer')
    ctx.application.bot_data['lmstudio_client'].stream_chat = Mock(side_effect=stream)
    async def exchange():
        await chat_message(update, ctx)
        await ctx.application.bot_data['active_generations'][1].worker
    async def run():
        await exchange()  # Still store reasoning when preservation is off.
        assert histories == [[]]
        ctx.application.bot_data['session_store'] = SessionStore(20, str(path))
        models.update_params(1, {'chat_template_kwargs.preserve_thinking': 'true'})
        await exchange()
        assert histories[-1][-1] == {'role': 'assistant', 'content': 'answer', 'reasoning_content': 'first thought'}
        models.select(1, 'plain')
        await exchange()
        assert all('reasoning_content' not in message for message in histories[-1])
        models.select(1, 'dual')
        await exchange()
        assert sum('reasoning_content' in message for message in histories[-1]) == 3
        assert all('other private thought' not in str(history) for history in histories)
    asyncio.run(run())


