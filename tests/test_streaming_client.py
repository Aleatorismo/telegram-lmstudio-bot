import asyncio
import json

import httpx
import pytest

from lmstudio_client import ChatDelta, LMStudioError
from test_lmstudio_client import client_with_transport


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks, hang=False):
        self.chunks, self.hang, self.closed = chunks, hang, False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.hang:
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


def test_sse_multibyte_fragmentation_reasoning_usage_and_done(monkeypatch):
    frames = ': keepalive\r\n\r\ndata: ' + json.dumps({'choices': [{'delta': {'reasoning_content': '想😀'}}]}, ensure_ascii=False)
    frames += '\r\n\r\ndata: ' + json.dumps({'choices': [{'delta': {'content': '回答'}, 'finish_reason': 'stop'}]}, ensure_ascii=False)
    frames += '\n\ndata: {"choices": [], "usage": {}}\n\ndata: [DONE]\n\n'
    wire = frames.encode()
    stream = Chunks([wire[i:i+3] for i in range(0, len(wire), 3)])
    def handler(request):
        payload = json.loads(request.content)
        assert payload['stream'] is True
        assert payload['reasoning_effort'] == 'medium'
        assert payload['model'] == 'chosen'
        assert payload['temperature'] == 0
        assert 'max_tokens' not in payload
        return httpx.Response(200, stream=stream)
    client = client_with_transport(monkeypatch, handler)
    async def run():
        return [d async for d in client.stream_chat([], 'hi', model='chosen',
                  parameters={'temperature': 0, 'max_tokens': ''}, reasoning_effort='medium')]
    assert asyncio.run(run()) == [ChatDelta(reasoning='想😀'), ChatDelta(content='回答')]
    assert stream.closed


@pytest.mark.parametrize('wire', [b'data: nope\n\n', b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'])
def test_malformed_or_truncated_sse_is_failure(monkeypatch, wire):
    client = client_with_transport(monkeypatch, lambda r: httpx.Response(200, stream=Chunks([wire])))
    async def run():
        return [d async for d in client.stream_chat([], 'hi')]
    with pytest.raises(LMStudioError):
        asyncio.run(run())


def test_cancel_closes_http_stream(monkeypatch):
    stream = Chunks([b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'], hang=True)
    client = client_with_transport(monkeypatch, lambda r: httpx.Response(200, stream=stream))
    async def run():
        seen = asyncio.Event()
        async def read():
            async for delta in client.stream_chat([], 'hi'):
                seen.set()
        task = asyncio.create_task(read())
        await seen.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())
    assert stream.closed
