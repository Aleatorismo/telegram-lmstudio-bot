from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


@dataclass(slots=True)
class Settings:
    telegram_bot_token: str
    telegram_proxy: str
    lmstudio_base_url: str
    lmstudio_model: str
    lmstudio_system_prompt: str
    lmstudio_temperature: float
    lmstudio_max_tokens: int
    max_history_messages: int
    no_proxy: str
    chat_log_dir: str
    session_store_path: str
    telegram_connect_timeout: float = 15.0
    telegram_read_timeout: float = 30.0
    telegram_write_timeout: float = 30.0
    lmstudio_timeout: float = 900.0
    telegram_typing_interval: float = 4.0
    telegram_network_error_threshold: int = 4
    telegram_network_error_window: float = 120.0
    telegram_restart_delay: float = 3.0


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a float.") from exc


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc


def _validate_url(name: str, value: str) -> str:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise ConfigError(f"{name} must be a valid URL, got: {value!r}")
    return value.rstrip("/")


def load_settings() -> Settings:
    load_dotenv()

    telegram_proxy = (
        os.getenv("TELEGRAM_PROXY")
        or os.getenv("HTTPS_PROXY")
        or os.getenv("HTTP_PROXY")
        or ""
    ).strip()
    if not telegram_proxy:
        raise ConfigError(
            "Telegram proxy is required. Set TELEGRAM_PROXY or HTTP_PROXY/HTTPS_PROXY."
        )

    lmstudio_base_url = _validate_url(
        "LMSTUDIO_BASE_URL",
        os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1").strip(),
    )

    settings = Settings(
        telegram_bot_token=_require_env("TELEGRAM_BOT_TOKEN"),
        telegram_proxy=_validate_url("TELEGRAM_PROXY", telegram_proxy),
        lmstudio_base_url=lmstudio_base_url,
        lmstudio_model=_require_env("LMSTUDIO_MODEL"),
        lmstudio_system_prompt=os.getenv(
            "LMSTUDIO_SYSTEM_PROMPT",
            "You are a helpful assistant running locally through LM Studio.",
        ).strip(),
        lmstudio_temperature=_get_float("LMSTUDIO_TEMPERATURE", 0.7),
        lmstudio_max_tokens=_get_int("LMSTUDIO_MAX_TOKENS", 1024),
        max_history_messages=_get_int("MAX_HISTORY_MESSAGES", 20),
        no_proxy=os.getenv("NO_PROXY", "127.0.0.1,localhost").strip(),
        chat_log_dir=os.getenv("CHAT_LOG_DIR", "chat_logs").strip(),
        session_store_path=os.getenv("SESSION_STORE_PATH", "session_store.json").strip(),
        lmstudio_timeout=_get_float("LMSTUDIO_TIMEOUT", 900.0),
        telegram_typing_interval=_get_float("TELEGRAM_TYPING_INTERVAL", 4.0),
        telegram_network_error_threshold=_get_int("TELEGRAM_NETWORK_ERROR_THRESHOLD", 4),
        telegram_network_error_window=_get_float("TELEGRAM_NETWORK_ERROR_WINDOW", 120.0),
        telegram_restart_delay=_get_float("TELEGRAM_RESTART_DELAY", 3.0),
    )

    if settings.max_history_messages < 2:
        raise ConfigError("MAX_HISTORY_MESSAGES must be at least 2.")
    if settings.lmstudio_max_tokens < 1:
        raise ConfigError("LMSTUDIO_MAX_TOKENS must be positive.")
    if settings.lmstudio_timeout < 1:
        raise ConfigError("LMSTUDIO_TIMEOUT must be positive.")
    if settings.telegram_typing_interval <= 0:
        raise ConfigError("TELEGRAM_TYPING_INTERVAL must be positive.")
    if not settings.chat_log_dir:
        raise ConfigError("CHAT_LOG_DIR must not be empty.")
    if not settings.session_store_path:
        raise ConfigError("SESSION_STORE_PATH must not be empty.")
    if settings.telegram_network_error_threshold < 1:
        raise ConfigError("TELEGRAM_NETWORK_ERROR_THRESHOLD must be at least 1.")
    if settings.telegram_network_error_window <= 0:
        raise ConfigError("TELEGRAM_NETWORK_ERROR_WINDOW must be positive.")
    if settings.telegram_restart_delay < 0:
        raise ConfigError("TELEGRAM_RESTART_DELAY must not be negative.")

    return settings
