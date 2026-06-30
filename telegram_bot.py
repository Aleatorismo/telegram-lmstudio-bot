from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass

from telegram import Update
from telegram.constants import ChatAction, ChatType
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

from chat_logger import ChatLogEntry, ChatLogger
from config import Settings
from lmstudio_client import LMStudioClient, LMStudioError
from session_store import SessionStore

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

    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .request(request)
        .get_updates_request(get_updates_request)
        .build()
    )

    app.bot_data["settings"] = settings
    app.bot_data["session_store"] = session_store
    app.bot_data["lmstudio_client"] = lmstudio_client
    app.bot_data["chat_logger"] = chat_logger
    app.bot_data["polling_error_state"] = PollingErrorState()
    app.bot_data["restart_requested"] = False

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, chat_message)
    )
    app.add_error_handler(error_handler)
    return app


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    _reset_polling_error_state(context.application)
    await update.message.reply_text(
        "你好，我会把你的私聊消息转发给本地 LM Studio 模型，并把回复发回 Telegram。\n"
        "使用 /reset 可以清空当前会话历史。"
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    _reset_polling_error_state(context.application)
    session_store: SessionStore = context.application.bot_data["session_store"]
    chat_logger: ChatLogger = context.application.bot_data["chat_logger"]
    session_store.clear(update.effective_user.id)
    chat_logger.append_reset_marker(
        user_id=update.effective_user.id,
        display_name=_build_display_name(update),
    )
    await update.message.reply_text("当前会话历史已清空。")


async def chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None or update.effective_chat is None:
        return
    if update.effective_chat.type != ChatType.PRIVATE:
        return

    _reset_polling_error_state(context.application)

    user_id = update.effective_user.id
    user_message = update.message.text.strip()
    if not user_message:
        await update.message.reply_text("我只处理文本消息。")
        return

    session_store: SessionStore = context.application.bot_data["session_store"]
    lmstudio_client: LMStudioClient = context.application.bot_data["lmstudio_client"]
    chat_logger: ChatLogger = context.application.bot_data["chat_logger"]
    settings: Settings = context.application.bot_data["settings"]

    history = session_store.get_history(user_id)
    typing_task = asyncio.create_task(
        keep_typing(
            context=context,
            chat_id=update.effective_chat.id,
            interval=settings.telegram_typing_interval,
        )
    )

    try:
        reply = await lmstudio_client.chat(history=history, user_message=user_message)
    except LMStudioError as exc:
        LOGGER.warning("LM Studio request failed: %s", exc)
        typing_task.cancel()
        await _await_cancelled_task(typing_task)
        await update.message.reply_text(f"本地模型调用失败：{exc}")
        return

    typing_task.cancel()
    await _await_cancelled_task(typing_task)

    session_store.append_exchange(user_id, user_message, reply)
    chat_logger.append_exchange(
        ChatLogEntry(
            user_id=user_id,
            display_name=_build_display_name(update),
            user_message=user_message,
            assistant_message=reply,
        )
    )
    await reply_with_chunks(update, reply)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    LOGGER.exception("Unhandled Telegram bot error", exc_info=error)

    if update is None and isinstance(error, NetworkError):
        _handle_polling_network_error(context.application, error)
        return

    if isinstance(update, Update) and update.effective_message is not None:
        if isinstance(error, BadRequest) and "message is too long" in str(error).lower():
            await update.effective_message.reply_text("模型回复过长，请尝试让它简短一点。")
            return
        if isinstance(error, TimedOut):
            await update.effective_message.reply_text("Telegram 请求超时，请稍后重试。")
            return
        if isinstance(error, NetworkError):
            await update.effective_message.reply_text(
                "Telegram 网络访问失败，请确认 `http://127.0.0.1:7890` 代理可用。"
            )
            return

        await update.effective_message.reply_text("发生了未预期错误，请稍后再试。")


async def reply_with_chunks(update: Update, text: str) -> None:
    if update.message is None:
        return

    for chunk in split_message(text):
        await update.message.reply_text(chunk)


async def keep_typing(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    interval: float,
) -> None:
    try:
        while True:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        raise


async def _await_cancelled_task(task: asyncio.Task[None]) -> None:
    try:
        await task
    except asyncio.CancelledError:
        pass


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
    if limit < 1:
        raise ValueError("limit must be positive")
    if not text:
        return [""]
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current_parts: list[str] = []
    current_length = 0

    for paragraph in _iter_paragraphs(text):
        if len(paragraph) > limit:
            if current_parts:
                chunks.append("".join(current_parts))
                current_parts = []
                current_length = 0
            chunks.extend(_split_oversized_paragraph(paragraph, limit))
            continue

        if current_length + len(paragraph) > limit and current_parts:
            chunks.append("".join(current_parts))
            current_parts = [paragraph]
            current_length = len(paragraph)
        else:
            current_parts.append(paragraph)
            current_length += len(paragraph)

    if current_parts:
        chunks.append("".join(current_parts))

    return chunks


def _iter_paragraphs(text: str) -> Iterable[str]:
    parts = text.splitlines(keepends=True)
    if parts:
        return parts
    return [text]


def _split_oversized_paragraph(text: str, limit: int) -> list[str]:
    pieces: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = _find_split_point(remaining, limit)
        pieces.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        pieces.append(remaining)
    return pieces


def _find_split_point(text: str, limit: int) -> int:
    search_start = max(limit - 200, 1)
    newline = text.rfind("\n", search_start, limit + 1)
    if newline > 0:
        return newline + 1

    whitespace = text.rfind(" ", search_start, limit + 1)
    if whitespace > 0:
        return whitespace + 1

    return limit
