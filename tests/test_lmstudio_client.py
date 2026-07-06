from __future__ import annotations

from types import SimpleNamespace

from lmstudio_client import LMStudioClient


def test_optional_sampling_params_are_omitted_when_unset() -> None:
    settings = SimpleNamespace(
        lmstudio_base_url="http://127.0.0.1:1234/v1",
        lmstudio_system_prompt="system",
        lmstudio_model="model",
        lmstudio_temperature=0.7,
        lmstudio_max_tokens=1024,
        lmstudio_top_p=None,
        lmstudio_top_k=None,
        lmstudio_min_p=None,
        lmstudio_presence_penalty=None,
    )

    client = LMStudioClient(settings)
    payload = {
        "model": settings.lmstudio_model,
        "messages": [],
        "temperature": settings.lmstudio_temperature,
        "max_tokens": settings.lmstudio_max_tokens,
        "stream": False,
    }

    client._apply_optional_sampling_params(payload)

    assert "top_p" not in payload
    assert "top_k" not in payload
    assert "min_p" not in payload
    assert "presence_penalty" not in payload


def test_optional_sampling_params_are_added_when_set() -> None:
    settings = SimpleNamespace(
        lmstudio_base_url="http://127.0.0.1:1234/v1",
        lmstudio_system_prompt="system",
        lmstudio_model="model",
        lmstudio_temperature=0.7,
        lmstudio_max_tokens=1024,
        lmstudio_top_p=0.9,
        lmstudio_top_k=40,
        lmstudio_min_p=0.05,
        lmstudio_presence_penalty=0.3,
    )

    client = LMStudioClient(settings)
    payload = {
        "model": settings.lmstudio_model,
        "messages": [],
        "temperature": settings.lmstudio_temperature,
        "max_tokens": settings.lmstudio_max_tokens,
        "stream": False,
    }

    client._apply_optional_sampling_params(payload)

    assert payload["top_p"] == 0.9
    assert payload["top_k"] == 40
    assert payload["min_p"] == 0.05
    assert payload["presence_penalty"] == 0.3
