from __future__ import annotations

from main import cleanup_application, is_recoverable_telegram_lifecycle_error, run_bot_polling


class DummyApp:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_polling(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


def test_run_bot_polling_keeps_event_loop_open_for_restart() -> None:
    app = DummyApp()

    run_bot_polling(app)

    assert app.calls == [{"drop_pending_updates": True, "close_loop": False}]


class CleanupApp:
    def __init__(self, *, running: bool) -> None:
        self.running = running
        self.stop_calls = 0
        self.shutdown_calls = 0

    async def stop(self) -> None:
        self.stop_calls += 1
        self.running = False

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


class DummyLogger:
    def __init__(self) -> None:
        self.debug_messages: list[tuple[object, ...]] = []

    def debug(self, *args: object) -> None:
        self.debug_messages.append(args)


def test_cleanup_application_shuts_down_partially_initialized_app() -> None:
    app = CleanupApp(running=False)

    cleanup_application(app, DummyLogger())

    assert app.stop_calls == 0
    assert app.shutdown_calls == 1


def test_cleanup_application_stops_running_app_before_shutdown() -> None:
    app = CleanupApp(running=True)

    cleanup_application(app, DummyLogger())

    assert app.stop_calls == 1
    assert app.shutdown_calls == 1


def test_extbot_not_initialized_error_is_recoverable() -> None:
    error = RuntimeError(
        "ExtBot is not properly initialized. "
        "Call `ExtBot.initialize` before accessing this property."
    )

    assert is_recoverable_telegram_lifecycle_error(error) is True
