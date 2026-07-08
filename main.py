from __future__ import annotations

import logging
import os
import time
import sys
import asyncio
import warnings

from telegram.error import NetworkError

from chat_logger import ChatLogger
from config import ConfigError, load_settings
from lmstudio_client import LMStudioClient
from session_store import SessionStore
from telegram_bot import build_application


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def run_bot_polling(app: object) -> None:
    # Keep the event loop alive so the outer restart loop can safely create a fresh Application.
    app.run_polling(drop_pending_updates=True, close_loop=False)


def cleanup_application(app: object, logger: logging.Logger) -> None:
    """Best-effort cleanup for failed or partially initialized Telegram applications."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        logger.debug("Skipping Telegram application cleanup because the event loop is running.")
        return

    loop.run_until_complete(_cleanup_application(app, logger))


async def _cleanup_application(app: object, logger: logging.Logger) -> None:
    if getattr(app, "running", False):
        try:
            await app.stop()
        except RuntimeError as exc:
            logger.debug("Ignoring Telegram application stop failure during cleanup: %s", exc)

    try:
        await app.shutdown()
    except RuntimeError as exc:
        logger.debug("Ignoring Telegram application shutdown failure during cleanup: %s", exc)


def is_recoverable_telegram_lifecycle_error(exc: RuntimeError) -> bool:
    message = str(exc)
    return (
        "ExtBot is not properly initialized" in message
        or "Application is not initialized" in message
    )


def main() -> None:
    configure_logging()

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    os.environ["NO_PROXY"] = settings.no_proxy
    os.environ["no_proxy"] = settings.no_proxy

    session_store = SessionStore(
        max_history_messages=settings.max_history_messages,
        storage_path=settings.session_store_path,
    )
    chat_logger = ChatLogger(settings.chat_log_dir)
    logger = logging.getLogger(__name__)

    while True:
        lmstudio_client = LMStudioClient(settings)
        app = build_application(settings, session_store, lmstudio_client, chat_logger)
        should_restart = False

        logger.info("Starting Telegram bot polling.")
        try:
            run_bot_polling(app)
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt. Exiting.")
            break
        except NetworkError as exc:
            should_restart = True
            logger.warning(
                "Telegram bot startup failed due to network error. "
                "Retrying in %.1f seconds: %s",
                settings.telegram_restart_delay,
                exc,
            )
        except RuntimeError as exc:
            if not is_recoverable_telegram_lifecycle_error(exc):
                raise
            should_restart = True
            logger.warning(
                "Telegram application entered a recoverable invalid lifecycle state. "
                "Rebuilding it in %.1f seconds: %s",
                settings.telegram_restart_delay,
                exc,
            )

        if not should_restart and not app.bot_data.get("restart_requested"):
            logger.info("Telegram bot polling stopped normally.")
            break

        cleanup_application(app, logger)

        if not should_restart:
            logger.warning(
                "Restarting Telegram bot application in %.1f seconds after polling client failure.",
                settings.telegram_restart_delay,
            )
        time.sleep(settings.telegram_restart_delay)


if __name__ == "__main__":
    main()
