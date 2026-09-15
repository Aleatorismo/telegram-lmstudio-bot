import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from lmstudio_client import LMStudioClient, LMStudioError
from model_store import PARAMETERS


def client_with_transport(monkeypatch, handler):
    original = httpx.AsyncClient
    def factory(**kwargs):
        assert kwargs['trust_env'] is False
        return original(**kwargs, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, 'AsyncClient', factory)
    return LMStudioClient(SimpleNamespace(lmstudio_base_url='http://localhost:1234/v1',
        lmstudio_system_prompt='system', lmstudio_model='default', lmstudio_timeout=30))


@pytest.mark.parametrize('parameters', [{}, dict.fromkeys(PARAMETERS), {k: '' for k in PARAMETERS}])
def test_defaults_are_omitted(monkeypatch, parameters):
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == '/v1/chat/completions'
        assert body == {'model': 'chosen', 'messages': [
            {'role': 'system', 'content': 'system'}, {'role': 'user', 'content': 'hello'}], 'stream': False}
        return httpx.Response(200, json={'choices': [{'message': {'content': 'answer'}}]})
    client = client_with_transport(monkeypatch, handler)
    assert asyncio.run(client.chat([], 'hello', model='chosen', parameters=parameters)) == 'answer'


@pytest.mark.parametrize('effort', ['none', 'medium', 'high'])
def test_model_sampling_reasoning_and_history_reach_api(monkeypatch, effort):
    params = dict(zip(PARAMETERS, [0, 4096, 0.95, 40, 0, -0.3]))
    def handler(request):
        body = json.loads(request.content)
        assert all(body[k] == v for k, v in params.items())
        assert body['reasoning_effort'] == effort
        assert body['model'] == 'chosen'
        assert body['messages'][1] == {'role': 'assistant', 'content': 'previous'}
        return httpx.Response(200, json={'choices': [{'message': {'content': 'answer'}}]})
    client = client_with_transport(monkeypatch, handler)
    asyncio.run(client.chat([{'role': 'assistant', 'content': 'previous'}], 'hi',
                            model='chosen', parameters=params, reasoning_effort=effort))


def test_native_discovery_types_and_embedding_filter(monkeypatch):
    def handler(request):
        assert request.url.path == '/api/v1/models'
        return httpx.Response(200, json={'models': [
            {'key': 'both', 'type': 'llm', 'capabilities': {'reasoning': {'allowed_options': ['on', 'off']}}},
            {'key': 'only', 'type': 'llm', 'capabilities': {'reasoning': {'allowed_options': ['low', 'high'], 'default': 'high'}}},
            {'key': 'plain', 'type': 'llm', 'capabilities': {}},
            {'key': 'embed', 'type': 'embedding'},
        ]})
    models = asyncio.run(client_with_transport(monkeypatch, handler).list_models())
    assert [m['type'] for m in models] == ['both', 'thinking', 'non_thinking']
    assert models[1]['thinking_effort'] == 'high'


def test_catalog_fallback(monkeypatch):
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.url.path != '/v1/models':
            return httpx.Response(404)
        return httpx.Response(200, json={'data': [{'id': 'old'}]})
    assert asyncio.run(client_with_transport(monkeypatch, handler).list_models())[0]['type'] == 'unknown'
    assert paths == ['/api/v1/models', '/api/v0/models', '/v1/models']


def test_unavailable_catalog(monkeypatch):
    client = client_with_transport(monkeypatch, lambda r: httpx.Response(503))
    with pytest.raises(LMStudioError):
        asyncio.run(client.list_models())


def test_malformed_chat_response(monkeypatch):
    client = client_with_transport(monkeypatch, lambda r: httpx.Response(200, text='not json'))
    with pytest.raises(LMStudioError):
        asyncio.run(client.chat([], 'hi'))


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('effort', ['xhigh', '', None])
def test_extended_parameters_reach_both_endpoints(monkeypatch, stream, effort):
    def handler(request):
        body = json.loads(request.content)
        assert body['repeat_penalty'] == 1.05
        assert 'repetition_penalty' not in body
        assert body['chat_template_kwargs'] == {'enable_thinking': True, 'preserve_thinking': False}
        assert body.get('reasoning_effort') == (effort or None)
        if not effort:
            assert 'reasoning_effort' not in body
        assert 'max_tokens' not in body and body['min_p'] == 0
        assert body['stream'] is stream
        if stream:
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"answer"}}]}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={'choices': [{'message': {'content': 'answer'}}]})
    client = client_with_transport(monkeypatch, handler)
    params = {'repetition_penalty': 1.05, 'max_tokens': None, 'min_p': 0,
              'chat_template_kwargs': {'enable_thinking': True, 'preserve_thinking': False},
              'reasoning_effort': effort}
    async def run():
        if stream:
            deltas = [d async for d in client.stream_chat([], 'hi', parameters=params, reasoning_effort='medium')]
            assert deltas[0].content == 'answer'
        else:
            assert await client.chat([], 'hi', parameters=params, reasoning_effort='medium') == 'answer'
    asyncio.run(run())


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('preserve', [True, False, None, ''])
def test_reasoning_history_on_wire_obeys_preservation_flag(monkeypatch, stream, preserve):
    original = [{'role': 'user', 'content': 'question', 'turn_id': 'secret', 'reasoning_content': 'not assistant'},
                {'role': 'assistant', 'content': 'answer', 'turn_id': 'secret', 'reasoning_content': 'thought'}]
    def handler(request):
        body = json.loads(request.content)
        assert body['messages'][1] == {'role': 'user', 'content': 'question'}
        expected = {'role': 'assistant', 'content': 'answer'}
        if preserve is True:
            expected.update(reasoning_content='thought', reasoning='thought')
        assert body['messages'][2] == expected
        if stream:
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"next"}}]}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={'choices': [{'message': {'content': 'next'}}]})
    client = client_with_transport(monkeypatch, handler)
    parameters = {'chat_template_kwargs': {'preserve_thinking': preserve, 'enable_thinking': False}}
    async def run():
        if stream:
            assert [d.content async for d in client.stream_chat(original, 'next question', parameters=parameters)] == ['next']
        else:
            assert await client.chat(original, 'next question', parameters=parameters) == 'next'
    asyncio.run(run())
    assert original[1]['reasoning_content'] == 'thought'
