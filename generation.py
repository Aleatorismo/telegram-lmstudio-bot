"""Background inference jobs keep Telegram polling responsive."""
from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import aclosing
from dataclasses import dataclass

from telegram.error import TelegramError
from telegram.constants import ChatAction

from chat_logger import ChatLogEntry
from lmstudio_client import LMStudioError
from rich_output import RichBuffer, RichOutput

LOGGER = logging.getLogger(__name__)


@dataclass
class Generation:
    user_id: int
    chat_id: int
    message_thread_id: int | None = None
    draft_id: int = 0
    worker: asyncio.Task | None = None
    producer: asyncio.Task | None = None
    def __post_init__(self) -> None:
        self.draft_id = self.draft_id or secrets.randbelow(2**31 - 1) + 1

async def run_generation(job: Generation, application, bot, *, user_message: str,
                         history: list, current: dict, display_name: str) -> None:
    data = application.bot_data
    buffer = RichBuffer()
    output = RichOutput(bot, job.chat_id, job.draft_id, buffer, job.message_thread_id)

    async def typing() -> None:
        while True:
            try:
                await bot.send_chat_action(chat_id=job.chat_id, action=ChatAction.TYPING,
                                           message_thread_id=job.message_thread_id)
            except TelegramError:
                pass  # A failed activity indicator must not cancel inference.
            await asyncio.sleep(data["settings"].telegram_typing_interval)

    async def consume() -> None:
        client = data["lmstudio_client"]
        # Bound total time too; read timeouts alone reset on each received chunk.
        async with asyncio.timeout(data["settings"].lmstudio_timeout):
            async with aclosing(client.stream_chat(history=history, user_message=user_message,
                    model=current["model"], parameters=current["parameters"],
                    reasoning_effort=current["reasoning_effort"])) as stream:
                async for delta in stream:
                    buffer.append("reasoning", delta.reasoning)
                    buffer.append("answer", delta.content)
                    # Buffered SSE frames can otherwise run without an actual await.
                    await asyncio.sleep(0)

    typing_task = asyncio.create_task(typing())
    try:
        job.producer = asyncio.create_task(consume())
        await output.publish()
        while not job.producer.done():
            await asyncio.wait({job.producer}, timeout=data["settings"].telegram_draft_interval)
            if not job.producer.done():
                await output.publish()
        error = None
        if job.producer is not None:
            try:
                await job.producer
            except TimeoutError:
                error = "LM Studio took too long to respond."
            except LMStudioError as exc:
                error = str(exc)
        answer = buffer.answer
        reasoning = buffer.reasoning
        status = ""
        if error:
            status = "Generation interrupted: " + error
        elif not answer.strip():
            status = "The model returned no final answer. Its output limit may have been reached while thinking."
        if status:
            buffer.append("answer", "\n\n[" + status + "]")
        await output.publish(final=True)
        # Only displayed answer text is context; never feed reasoning back as an answer.
        if answer.strip() and not error:
            data["session_store"].append_exchange(job.user_id, user_message, answer)
        data["chat_logger"].append_exchange(ChatLogEntry(
            user_id=job.user_id, display_name=display_name, user_message=user_message,
            assistant_message=answer + ("\n\n[" + status + "]" if status else ""),
            reasoning_message=reasoning,
        ))
    except asyncio.CancelledError:
        raise
    except Exception:
        LOGGER.exception("Reply generation or delivery failed for user %s", job.user_id)
        await output.clear()
        try:
            await bot.send_message(chat_id=job.chat_id,
                text="Reply generation or delivery failed. Please try again later.",
                message_thread_id=job.message_thread_id)
        except TelegramError:
            LOGGER.warning("Could not deliver the generation error notification.")
    finally:
        typing_task.cancel()
        await asyncio.gather(typing_task, return_exceptions=True)
        if job.producer is not None:
            job.producer.cancel()
            await asyncio.gather(job.producer, return_exceptions=True)
        active = data.get("active_generations", {})
        if active.get(job.user_id) is job:
            active.pop(job.user_id, None)


async def shutdown_generations(application) -> None:
    """Cancel local jobs before closing Telegram clients, including restart cleanup."""
    jobs = list(getattr(application, "bot_data", {}).get("active_generations", {}).values())
    tasks = [job.worker for job in jobs if job.worker is not None]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    getattr(application, "bot_data", {}).get("active_generations", {}).clear()
