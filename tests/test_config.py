from __future__ import annotations

import pytest

from config import ConfigError, load_settings


def test_load_settings_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("LMSTUDIO_MODEL", "local-model")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")

    with pytest.raises(ConfigError):
        load_settings()


def test_load_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("LMSTUDIO_MODEL", "local-model")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("TELEGRAM_PROXY", raising=False)
    monkeypatch.setenv("MAX_HISTORY_MESSAGES", "20")
    monkeypatch.setenv("CHAT_LOG_DIR", "chat_logs")
    monkeypatch.setenv("SESSION_STORE_PATH", "session_store.json")
    monkeypatch.setenv("LMSTUDIO_TIMEOUT", "900")
    monkeypatch.setenv("TELEGRAM_TYPING_INTERVAL", "4")
    monkeypatch.setenv("TELEGRAM_NETWORK_ERROR_THRESHOLD", "4")
    monkeypatch.setenv("TELEGRAM_NETWORK_ERROR_WINDOW", "120")
    monkeypatch.setenv("TELEGRAM_RESTART_DELAY", "3")

    settings = load_settings()

    assert settings.telegram_proxy == "http://127.0.0.1:7890"
    assert settings.lmstudio_base_url == "http://127.0.0.1:1234/v1"
    assert settings.max_history_messages == 20
    assert settings.chat_log_dir == "chat_logs"
    assert settings.session_store_path == "session_store.json"
    assert settings.lmstudio_timeout == 900.0
    assert settings.telegram_typing_interval == 4.0
    assert settings.telegram_network_error_threshold == 4
    assert settings.telegram_network_error_window == 120.0
    assert settings.telegram_restart_delay == 3.0
