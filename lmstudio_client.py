from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from config import Settings
from model_store import sampling_params


class LMStudioError(RuntimeError):
    """Raised when LM Studio cannot satisfy a chat request."""


@dataclass(frozen=True, slots=True)
class ChatDelta:
    content: str = ""
    reasoning: str = ""


class LMStudioClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = settings.lmstudio_base_url

    async def list_models(self) -> list[dict]:
        """Prefer native capability metadata, then older native/OpenAI catalogs."""
        root = self._base_url.rstrip("/").removesuffix("/v1")
        urls = [(root + "/api/v1/models", "models"),
                (root + "/api/v0/models", "data"),
                (self._base_url.rstrip("/") + "/models", "data")]
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            for url, key in urls:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    rows = response.json()[key]
                    if not isinstance(rows, list):
                        raise ValueError("Invalid model list")
                    models = []
                    for row in rows:
                        if row.get("type") in ("embedding", "embeddings"):
                            continue
                        model_id = row.get("key") or row.get("id")
                        if not isinstance(model_id, str) or not model_id.strip():
                            continue
                        kind, effort = "unknown", "medium"
                        if key == "models":
                            reasoning = row.get("capabilities", {}).get("reasoning", {}) or {}
                            options = reasoning.get("allowed_options", [])
                            enabled = [x for x in options if x != "off"]
                            kind = ("both" if "off" in options else "thinking") if enabled else "non_thinking"
                            default = reasoning.get("default")
                            effort = default if default in ("low", "medium", "high") else next(
                                (x for x in enabled if x in ("low", "medium", "high")), "medium")
                        models.append({"id": model_id, "type": kind, "thinking_effort": effort})
                    return models
                except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                    continue
        raise LMStudioError("Could not fetch the model list. Using locally saved models.")

    async def chat(self, history: list[dict[str, str]], user_message: str, *,
                   model: str | None = None, parameters: dict | None = None,
                   reasoning_effort: str | None = None) -> str:
        messages = [{"role": "system", "content": self._settings.lmstudio_system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        payload = {
            "model": model or self._settings.lmstudio_model,
            "messages": messages,
            "stream": False,
        }
        payload.update(sampling_params(parameters or {}))
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort

        timeout = httpx.Timeout(
            connect=10.0,
            read=self._settings.lmstudio_timeout,
            write=30.0,
            pool=10.0,
        )

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=timeout,
                trust_env=False,
            ) as client:
                response = await client.post("/chat/completions", json=payload)
                response.raise_for_status()
        except httpx.ConnectError as exc:
            raise LMStudioError(
                "Could not connect to LM Studio. Confirm the local server is running."
            ) from exc
        except httpx.TimeoutException as exc:
            raise LMStudioError("LM Studio took too long to respond.") from exc
        except httpx.HTTPStatusError as exc:
            message = _extract_error_message(exc.response)
            raise LMStudioError(f"LM Studio returned an API error: {message}") from exc
        except httpx.HTTPError as exc:
            raise LMStudioError(f"Unexpected LM Studio HTTP error: {exc}") from exc

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LMStudioError("LM Studio returned an unexpected response payload.") from exc

        if not isinstance(content, str) or not content.strip():
            raise LMStudioError("LM Studio returned an empty message.")
        return content.strip()

    async def stream_chat(self, history: list[dict[str, str]], user_message: str, *,
                          model: str | None = None, parameters: dict | None = None,
                          reasoning_effort: str | None = None) -> AsyncIterator[ChatDelta]:
        """Consume SSE; cancelling/closing this iterator closes the inference connection."""
        payload = {
            "model": model or self._settings.lmstudio_model,
            "messages": [{"role": "system", "content": self._settings.lmstudio_system_prompt},
                         *history, {"role": "user", "content": user_message}],
            "stream": True,
            **sampling_params(parameters or {}),
        }
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort
        timeout = httpx.Timeout(connect=10, read=self._settings.lmstudio_timeout, write=30, pool=10)
        finished = False
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=timeout, trust_env=False) as client:
                async with client.stream("POST", "/chat/completions", json=payload) as response:
                    if response.is_error:
                        await response.aread()
                        response.raise_for_status()
                    async for event in _sse_data(response):
                        if event.strip() == "[DONE]":
                            finished = True
                            break
                        try:
                            data = json.loads(event)
                            if data.get("error"):
                                raise LMStudioError(f"LM Studio stream error: {data['error']}")
                            choices = data.get("choices", [])
                            if not choices:  # Usage-only SSE frames.
                                continue
                            choice = choices[0]
                            delta = choice.get("delta", {})
                            content = delta.get("content") or ""
                            reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
                            if not isinstance(content, str) or not isinstance(reasoning, str):
                                raise ValueError("Invalid text delta")
                            if choice.get("finish_reason") is not None:
                                finished = True
                        except (ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
                            raise LMStudioError("LM Studio returned an invalid streaming payload.") from exc
                        if content or reasoning:
                            yield ChatDelta(content=content, reasoning=reasoning)
        except httpx.ConnectError as exc:
            raise LMStudioError("Could not connect to LM Studio. Confirm the local server is running.") from exc
        except httpx.TimeoutException as exc:
            raise LMStudioError("LM Studio took too long to respond.") from exc
        except httpx.HTTPStatusError as exc:
            raise LMStudioError(f"LM Studio returned an API error: {_extract_error_message(exc.response)}") from exc
        except httpx.HTTPError as exc:
            raise LMStudioError("The LM Studio streaming connection failed.") from exc
        if not finished:
            raise LMStudioError("LM Studio disconnected before completing the reply.")


async def _sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """SSE frames can span TCP packets and contain several data lines."""
    lines: list[str] = []
    size = 0
    async for line in response.aiter_lines():
        if not line:
            if lines:
                yield "\n".join(lines)
                lines, size = [], 0
        elif line.startswith("data:"):
            value = line[5:].removeprefix(" ")
            size += len(value)
            if size > 1_000_000:
                raise LMStudioError("LM Studio returned an oversized streaming event.")
            lines.append(value)
    if lines:
        yield "\n".join(lines)

def _extract_error_message(response: httpx.Response) -> str:
    try:
        payload: Any = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return response.text or f"HTTP {response.status_code}"
