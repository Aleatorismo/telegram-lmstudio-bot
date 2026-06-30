from __future__ import annotations

from main import run_bot_polling


class DummyApp:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_polling(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


def test_run_bot_polling_keeps_event_loop_open_for_restart() -> None:
    app = DummyApp()

    run_bot_polling(app)

    assert app.calls == [{"drop_pending_updates": True, "close_loop": False}]
