from __future__ import annotations

from typing import Any

import httpx

from config import Settings


class LMStudioError(RuntimeError):
    """Raised when LM Studio cannot satisfy a chat request."""


class LMStudioClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = settings.lmstudio_base_url

    async def chat(self, history: list[dict[str, str]], user_message: str) -> str:
        messages = [{"role": "system", "content": self._settings.lmstudio_system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        payload = {
            "model": self._settings.lmstudio_model,
            "messages": messages,
            "temperature": self._settings.lmstudio_temperature,
            "max_tokens": self._settings.lmstudio_max_tokens,
            "stream": False,
        }
        self._apply_optional_sampling_params(payload)

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

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LMStudioError("LM Studio returned an unexpected response payload.") from exc

        if not isinstance(content, str) or not content.strip():
            raise LMStudioError("LM Studio returned an empty message.")
        return content.strip()

    def _apply_optional_sampling_params(self, payload: dict[str, Any]) -> None:
        optional_params = {
            "top_p": self._settings.lmstudio_top_p,
            "top_k": self._settings.lmstudio_top_k,
            "min_p": self._settings.lmstudio_min_p,
            "presence_penalty": self._settings.lmstudio_presence_penalty,
        }
        for key, value in optional_params.items():
            if value is not None:
                payload[key] = value


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
