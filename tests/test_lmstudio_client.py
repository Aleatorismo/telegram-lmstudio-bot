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
