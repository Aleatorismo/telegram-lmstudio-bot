import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import BadRequest, RetryAfter, TimedOut

from rich_output import RichBuffer, RichOutput, PAGE_BYTES, PAGE_LINES
from telegram_bot import split_message


def test_unicode_and_reasoning_are_lossless_and_bounded():
    b = RichBuffer()
    reasoning = ('<&> "思考😀"\n' * 7000)
    answer = ('# Heading\n\n正文😀\n' * 8000)
    for start in range(0, len(reasoning), 71):
        b.append('reasoning', reasoning[start:start+71])
    for start in range(0, len(answer), 77):
        b.append('answer', answer[start:start+77])
    assert b.answer == answer
    assert b.reasoning == reasoning
    assert ''.join(p.answer for p in b.pages) == answer
    assert ''.join(p.reasoning for p in b.pages) == reasoning
    for page in b.pages:
        assert page.used_bytes <= PAGE_BYTES
        assert page.lines <= PAGE_LINES
        assert len(page.rich_message()['markdown'].encode('utf-8')) < 32768


def test_reasoning_cannot_escape_details_and_no_draft_only_thinking_tag():
    b = RichBuffer()
    b.append('reasoning', '</pre></details><tg-thinking>not markup</tg-thinking>')
    b.append('answer', '# Answer\n**bold**\n| A | B |\n|---|---|\n| 1 | 2 |')
    md = b.pages[0].rich_message()['markdown']
    assert md.count('</details>') == 1
    assert '<details>' in md and '<details open' not in md
    assert '<tg-thinking>' not in md
    assert '**bold**' in md and '| A | B |' in md


def test_reasoning_uses_consistent_plain_paragraph_inside_details():
    buffer = RichBuffer()
    text = 'First\n\n> quote\n```python\ncode\n```\n</p><pre>injection'
    buffer.append('reasoning', text)
    md = buffer.pages[0].rich_message()['markdown']
    assert '<p><i>' in md and '</i></p>' in md and '<pre>' not in md and '<blockquote>' not in md
    assert 'First<br><br>&gt; quote' in md
    assert md.count('</p>') == 1
    assert buffer.pages[0].rich_message(literal=True)['blocks'][0]['blocks'][0] == {
        'type': 'paragraph', 'text': {'type': 'italic', 'text': text}}


def test_code_fences_survive_page_boundaries():
    b = RichBuffer()
    source = '```python\n' + 'print("hello")\n' * 2000 + '```\nEnd.'
    b.append('answer', source)
    assert ''.join(p.answer for p in b.pages) == source
    assert len(b.pages) > 1
    assert b.pages[1].code_prefix == '```python\n'
    assert b.pages[0].rich_message()['markdown'].endswith('```')
    assert b.pages[-1].rich_message()['markdown'].endswith('End.')


def test_final_pages_sent_exactly_once_and_draft_has_no_stop():
    async def run():
        bot = SimpleNamespace(do_api_request=AsyncMock())
        b = RichBuffer()
        b.append('reasoning', 'thinking')
        out = RichOutput(bot, 123, 45, b)
        await out.publish()
        call = bot.do_api_request.call_args
        assert call.args[0] == 'sendRichMessageDraft'
        assert call.kwargs['api_kwargs']['can_stop'] is False
        assert 'keep_on_stop' not in call.kwargs['api_kwargs']
        b.append('answer', 'a' * 60000)
        await out.publish()
        await out.publish(final=True)
        await out.publish(final=True)
        finals = [c for c in bot.do_api_request.call_args_list if c.args[0] == 'sendRichMessage']
        assert len(finals) == len(b.pages)
        for call in finals:
            assert 'draft_id' not in call.kwargs['api_kwargs']
    asyncio.run(run())


def test_bad_markdown_falls_back_to_shallow_rich_blocks():
    async def run():
        bot = SimpleNamespace(do_api_request=AsyncMock(side_effect=[BadRequest('too many nested blocks'), True]))
        b = RichBuffer()
        b.append('reasoning', 'thoughts')
        b.append('answer', '> ' * 50 + 'deep')
        await RichOutput(bot, 123, 45, b).publish(final=True)
        blocks = bot.do_api_request.call_args.kwargs['api_kwargs']['rich_message']['blocks']
        assert blocks[0]['type'] == 'details'
        assert blocks[1]['text'] == b.answer
    asyncio.run(run())


def test_draft_throttles_after_rate_limit_and_network_error(monkeypatch):
    monkeypatch.setenv('PTB_TIMEDELTA', '1')
    async def run():
        for error in (RetryAfter(3), TimedOut()):
            bot = SimpleNamespace(do_api_request=AsyncMock(side_effect=error))
            output = RichOutput(bot, 1, 2, RichBuffer())
            await output.publish()
            await output.publish()
            assert bot.do_api_request.await_count == 1
    asyncio.run(run())


def test_extreme_fence_uses_bounded_literal_blocks():
    buffer = RichBuffer()
    buffer.append('answer', '`' * 24000)
    rich = buffer.pages[0].rich_message()
    assert 'blocks' in rich
    assert rich['blocks'][0]['text'] == buffer.answer


def test_final_rate_limit_retry_and_ambiguous_timeout_no_retry(monkeypatch):
    monkeypatch.setenv('PTB_TIMEDELTA', '1')
    import pytest
    async def run():
        buffer = RichBuffer()
        buffer.append('answer', 'answer')
        bot = SimpleNamespace(do_api_request=AsyncMock(side_effect=[RetryAfter(0), True]))
        await RichOutput(bot, 1, 2, buffer).publish(final=True)
        assert bot.do_api_request.await_count == 2
        bot.do_api_request = AsyncMock(side_effect=TimedOut())
        with pytest.raises(TimedOut):
            await RichOutput(bot, 1, 2, buffer).publish(final=True)
        assert bot.do_api_request.await_count == 1
    asyncio.run(run())


def test_plain_message_unicode_and_boundary_newlines():
    for text in ['😀' * 5000, 'a' * 4096 + '\nrest', 'x' * 4096 + ' tail']:
        chunks = split_message(text)
        assert ''.join(chunks) == text
        assert all(len(c.encode('utf-16-le')) // 2 <= 4096 for c in chunks)
