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
    monkeypatch.setenv("LMSTUDIO_TOP_P", "")
    monkeypatch.setenv("LMSTUDIO_TOP_K", "")
    monkeypatch.setenv("LMSTUDIO_MIN_P", "")
    monkeypatch.setenv("LMSTUDIO_PRESENCE_PENALTY", "")

    settings = load_settings()

    assert settings.telegram_proxy == "http://127.0.0.1:7890"
    assert settings.lmstudio_base_url == "http://127.0.0.1:1234/v1"
    assert settings.max_history_messages == 20
    assert settings.chat_log_dir == "chat_logs"
    assert settings.session_store_path == "session_store.json"
    assert settings.lmstudio_timeout == 900.0
    assert settings.telegram_typing_interval == 4.0
    assert settings.telegram_draft_interval == 1.0
    assert settings.telegram_network_error_threshold == 4
    assert settings.telegram_network_error_window == 120.0
    assert settings.telegram_restart_delay == 3.0


def test_legacy_sampling_env_is_ignored(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("LMSTUDIO_MODEL", "")
    monkeypatch.setenv("TELEGRAM_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("LMSTUDIO_TEMPERATURE", "invalid")
    monkeypatch.setenv("LMSTUDIO_MAX_TOKENS", "invalid")
    settings = load_settings()
    assert settings.lmstudio_model == ""
    assert settings.model_profiles_path == "model_profiles.json"
    assert not hasattr(settings, "lmstudio_temperature")


@pytest.mark.parametrize('interval', ['0', '0.1', '11', 'nan', 'inf'])
def test_invalid_draft_interval(monkeypatch, interval):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'token')
    monkeypatch.setenv('TELEGRAM_PROXY', 'http://127.0.0.1:7890')
    monkeypatch.setenv('TELEGRAM_DRAFT_INTERVAL', interval)
    with pytest.raises(ConfigError, match='TELEGRAM_DRAFT_INTERVAL'):
        load_settings()
