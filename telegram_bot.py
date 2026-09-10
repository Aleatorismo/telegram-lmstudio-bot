from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from telegram import Update
from telegram.constants import ChatType
from telegram.error import BadRequest, NetworkError, TimedOut
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from chat_logger import ChatLogger
from config import Settings
from lmstudio_client import LMStudioClient, LMStudioError
from session_store import SessionStore
from model_store import ModelConfigError, ModelStore, PARAMETERS
from generation import Generation, run_generation, shutdown_generations

LOGGER = logging.getLogger(__name__)
TELEGRAM_MESSAGE_LIMIT = 4096


@dataclass(slots=True)
class PollingErrorState:
    count: int = 0
    last_error_at: float = 0.0


def build_application(
    settings: Settings,
    session_store: SessionStore,
    lmstudio_client: LMStudioClient,
    chat_logger: ChatLogger,
) -> Application:
    request = HTTPXRequest(
        proxy=settings.telegram_proxy,
        connect_timeout=settings.telegram_connect_timeout,
        read_timeout=settings.telegram_read_timeout,
        write_timeout=settings.telegram_write_timeout,
        httpx_kwargs={"trust_env": False},
    )
    get_updates_request = HTTPXRequest(
        proxy=settings.telegram_proxy,
        connect_timeout=settings.telegram_connect_timeout,
        read_timeout=settings.telegram_read_timeout,
        write_timeout=settings.telegram_write_timeout,
        httpx_kwargs={"trust_env": False},
    )

    active_generations = {}
    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .request(request)
        .get_updates_request(get_updates_request)
        .post_init(register_commands)
        .post_stop(shutdown_generations)
        .build()
    )

    app.bot_data["settings"] = settings
    app.bot_data["session_store"] = session_store
    app.bot_data["lmstudio_client"] = lmstudio_client
    app.bot_data["chat_logger"] = chat_logger
    app.bot_data["polling_error_state"] = PollingErrorState()
    app.bot_data["restart_requested"] = False
    app.bot_data["active_generations"] = active_generations
    app.bot_data["model_store"] = ModelStore(
        settings.model_profiles_path, settings.model_selections_path, settings.lmstudio_model
    )

    for name, callback in (("start", start_command), ("reset", reset_command),
                           ("model", model_command), ("think", think_command),
                           ("settings", settings_command), ("params", params_command), ("undo", undo_command)):
        app.add_handler(CommandHandler(name, callback, filters=filters.ChatType.PRIVATE))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, chat_message)
    )
    app.add_error_handler(error_handler)
    return app


async def register_commands(application: Application) -> None:
    await application.bot.set_my_commands([
        ("start", "Show help"), ("reset", "Clear conversation history"),
        ("model", "List or switch models"), ("think", "Toggle thinking: on or off"),
        ("settings", "Show current model, mode and parameters"),
        ("params", "Edit parameters for the current model"),
        ("undo", "Remove your last turn from context"),
    ])
    try:
        await refresh_models(application)
    except ModelConfigError as exc:
        LOGGER.error("Model profiles could not be loaded: %s", exc)


async def refresh_models(application: Application) -> str:
    store = application.bot_data["model_store"]
    try:
        models = await application.bot_data["lmstudio_client"].list_models()
        store.merge_discovered(models)
        return "Live LM Studio model list (plus locally saved profiles)."
    except LMStudioError:
        store.merge_discovered([])
        return "LM Studio model list unavailable; showing locally saved profiles."


def format_settings(current: dict) -> str:
    lines = [f"Model: {current['model']}",
             f"Thinking: {'on' if current['mode'] == 'thinking' else 'off'}",
             f"Supported modes: {current['type'].replace('_', ' ')}"]
    if current["reasoning_effort"] is not None:
        lines.append(f"Reasoning effort: {current['reasoning_effort']}")
    lines.extend(f"{name}: {current['parameters'].get(name, 'LM Studio default')}" for name in PARAMETERS)
    return "\n".join(lines)


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    _reset_polling_error_state(context.application)
    store = context.application.bot_data["model_store"]
    try:
        source = await refresh_models(context.application)
        if context.args:
            store.select(update.effective_user.id, " ".join(context.args))
            text = "Model selected. Conversation history is preserved.\n" + format_settings(store.current(update.effective_user.id))
        else:
            models = store.profiles()["models"]
            text = source + "\nUsage: /model <model-id>\n"
            text += "\n".join(f"{key} [{value.get('type', 'unknown')}]" for key, value in models.items())
            if not models:
                text += "No models found. Add models to the local profile file or start LM Studio."
        await reply_with_chunks(update, text)
    except ModelConfigError as exc:
        await reply_with_chunks(update, str(exc))


async def think_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    _reset_polling_error_state(context.application)
    try:
        if len(context.args) > 1 or (context.args and context.args[0].lower() not in ("on", "off")):
            raise ModelConfigError("Usage: /think [on|off]. With no argument, toggle thinking.")
        mode = {"on": "thinking", "off": "non_thinking"}.get(context.args[0].lower()) if context.args else None
        store = context.application.bot_data["model_store"]
        store.set_mode(update.effective_user.id, mode)
        await reply_with_chunks(update, format_settings(store.current(update.effective_user.id)))
    except ModelConfigError as exc:
        await reply_with_chunks(update, str(exc))


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    _reset_polling_error_state(context.application)
    try:
        await reply_with_chunks(update, format_settings(context.application.bot_data["model_store"].current(update.effective_user.id)))
    except ModelConfigError as exc:
        await reply_with_chunks(update, str(exc))


async def params_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    _reset_polling_error_state(context.application)
    try:
        args = list(context.args)
        mode = None
        if args and args[0].lower() in ("on", "off"):
            mode = {"on": "thinking", "off": "non_thinking"}[args.pop(0).lower()]
        if not args:
            await reply_with_chunks(update,
                "Usage: /params [on|off] name=value [name=value ...]\n"
                "Example: /params on temperature=0.6 max_tokens=4096 top_p=0.95\n"
                "Use name=, name=null, or name=default to use the LM Studio default.\n"
                "Without on/off, edits apply to the current mode.\n"
                "Profiles are shared by all users of this bot.\nParameters: " + ", ".join(PARAMETERS))
            return
        changes = {}
        for arg in args:
            name, sep, value = arg.partition("=")
            if not sep or name in changes:
                raise ModelConfigError("Use unique name=value assignments, separated by spaces.")
            changes[name] = value
        store = context.application.bot_data["model_store"]
        store.update_params(update.effective_user.id, changes, mode)
        current = store.current(update.effective_user.id)
        target = mode or current["mode"]
        await reply_with_chunks(update, f"Saved {target.replace('_', ' ')} parameters for {current['model']}. "
                                "This profile is shared by all users.\nCurrent settings:\n" + format_settings(current))
    except ModelConfigError as exc:
        await reply_with_chunks(update, str(exc))


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    _reset_polling_error_state(context.application)
    await update.message.reply_text(
        "Send a private text message to chat with LM Studio.\n"
        "/model [model-id] - List or switch models\n"
        "/think [on|off] - Toggle or set thinking mode\n"
        "/settings - Show the current model, mode and parameters\n"
        "/params [on|off] name=value ... - Edit model parameters\n"
        "/reset - Clear your conversation history\n"
        "/undo - Remove your last turn from context\n"
        "Switching models enables thinking when supported and preserves history."
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    _reset_polling_error_state(context.application)
    if update.effective_user.id in context.application.bot_data.get("active_generations", {}):
        await update.message.reply_text("Please wait for your current reply to finish before resetting context.")
        return
    session_store: SessionStore = context.application.bot_data["session_store"]
    chat_logger: ChatLogger = context.application.bot_data["chat_logger"]
    session_store.clear(update.effective_user.id)
    chat_logger.append_reset_marker(
        user_id=update.effective_user.id,
        display_name=_build_display_name(update),
    )
    await update.message.reply_text("Your conversation history has been cleared.")


async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None or update.effective_chat is None:
        return
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    _reset_polling_error_state(context.application)
    if context.args:
        await update.message.reply_text("Usage: /undo (no arguments). Only your own context can be changed.")
        return
    user_id = update.effective_user.id
    if user_id in context.application.bot_data.get("active_generations", {}):
        await update.message.reply_text("Please wait for your current reply to finish before undoing a turn.")
        return
    removed = context.application.bot_data["session_store"].undo_last_turn(user_id)
    await update.message.reply_text(
        "Your last turn has been removed from context. Chat messages are unchanged."
        if removed else "There is no conversation context left to undo.")


async def chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None or update.effective_chat is None:
        return
    if update.effective_chat.type != ChatType.PRIVATE:
        return

    _reset_polling_error_state(context.application)

    user_id = update.effective_user.id
    user_message = update.message.text.strip()
    if not user_message:
        await update.message.reply_text("Please send a non-empty text message.")
        return

    session_store: SessionStore = context.application.bot_data["session_store"]

    try:
        current = context.application.bot_data["model_store"].current(user_id)
    except ModelConfigError as exc:
        await reply_with_chunks(update, str(exc))
        return

    active = context.application.bot_data.setdefault("active_generations", {})
    if user_id in active:
        await update.message.reply_text("A reply is already being generated. Please wait for it to finish.")
        return
    job = Generation(user_id=user_id, chat_id=update.effective_chat.id,
                     message_thread_id=getattr(update.message, "message_thread_id", None))
    active[user_id] = job
    job.worker = asyncio.create_task(run_generation(job, context.application, context.bot,
        user_message=user_message, history=session_store.get_history(user_id), current=current,
        display_name=_build_display_name(update)))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    LOGGER.exception("Unhandled Telegram bot error", exc_info=error)

    if update is None and isinstance(error, NetworkError):
        _handle_polling_network_error(context.application, error)
        return

    if isinstance(update, Update) and update.effective_message is not None:
        if isinstance(error, BadRequest) and "message is too long" in str(error).lower():
            await update.effective_message.reply_text("The model reply is too long. Please ask for a shorter reply.")
            return
        if isinstance(error, TimedOut):
            await update.effective_message.reply_text("Telegram request timed out. Please try again later.")
            return
        if isinstance(error, NetworkError):
            await update.effective_message.reply_text(
                "Telegram network request failed. Check that the local proxy is available."
            )
            return

        await update.effective_message.reply_text("An unexpected error occurred. Please try again later.")


async def reply_with_chunks(update: Update, text: str) -> None:
    if update.message is None:
        return

    for chunk in split_message(text):
        await update.message.reply_text(chunk)


def _build_display_name(update: Update) -> str:
    user = update.effective_user
    if user is None:
        return "unknown_user"
    if user.username:
        return user.username
    full_name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    if full_name:
        return full_name
    return f"user_{user.id}"


def _handle_polling_network_error(application: Application, error: NetworkError) -> None:
    settings: Settings = application.bot_data["settings"]
    state: PollingErrorState = application.bot_data["polling_error_state"]
    now = time.monotonic()

    if now - state.last_error_at > settings.telegram_network_error_window:
        state.count = 0

    state.count += 1
    state.last_error_at = now

    LOGGER.warning(
        "Telegram polling network error %s/%s within %.0f seconds: %s",
        state.count,
        settings.telegram_network_error_threshold,
        settings.telegram_network_error_window,
        error,
    )

    if state.count >= settings.telegram_network_error_threshold:
        application.bot_data["restart_requested"] = True
        LOGGER.error(
            "Telegram polling client appears stuck after repeated network errors. "
            "Requesting application restart to rebuild HTTP clients."
        )
        application.stop_running()


def _reset_polling_error_state(application: Application) -> None:
    state: PollingErrorState = application.bot_data["polling_error_state"]
    if state.count:
        LOGGER.info("Telegram polling recovered after %s network error(s).", state.count)
    state.count = 0
    state.last_error_at = 0.0


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Plain-message fallback: count UTF-16 units, including astral emoji."""
    if limit < 1:
        raise ValueError("limit must be positive")
    chunks = []
    while text:
        units = end = 0
        for char in text:
            width = 2 if ord(char) > 0xFFFF else 1
            if units + width > limit:
                break
            units += width
            end += 1
        if end == 0:
            raise ValueError("limit is too small for a single character")
        if end < len(text):
            newline = text.rfind("\n", 0, end)
            space = text.rfind(" ", max(0, end - 200), end)
            if newline >= 0:
                end = newline + 1
            elif space >= 0:
                end = space + 1
        chunks.append(text[:end])
        text = text[end:]
    return chunks or [""]
