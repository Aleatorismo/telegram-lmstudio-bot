from __future__ import annotations

from types import SimpleNamespace

from telegram.error import NetworkError

from telegram_bot import PollingErrorState, _handle_polling_network_error


class DummyApplication:
    def __init__(self) -> None:
        self.bot_data = {
            "settings": SimpleNamespace(
                telegram_network_error_threshold=3,
                telegram_network_error_window=120.0,
            ),
            "polling_error_state": PollingErrorState(),
            "restart_requested": False,
        }
        self.stop_calls = 0

    def stop_running(self) -> None:
        self.stop_calls += 1


def test_restarts_after_reaching_threshold() -> None:
    app = DummyApplication()

    _handle_polling_network_error(app, NetworkError("one"))
    _handle_polling_network_error(app, NetworkError("two"))
    _handle_polling_network_error(app, NetworkError("three"))

    assert app.bot_data["restart_requested"] is True
    assert app.stop_calls == 1
