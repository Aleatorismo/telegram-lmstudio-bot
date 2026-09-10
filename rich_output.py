"""Bot API 10.3 rich drafts, with bounded pages and format-error recovery.

https://core.telegram.org/bots/api#rich-message-formatting-options
https://core.telegram.org/bots/api#sendrichmessagedraft
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from dataclasses import dataclass
from datetime import timedelta

from telegram.error import BadRequest, NetworkError, RetryAfter, TelegramError

LOGGER = logging.getLogger(__name__)
# Official limits: 32768 text characters, 500 blocks, 16 levels. Bound encoded
# source more conservatively, reserve room for wrappers, and handle parser limits.
PAGE_BYTES = 24_000
PAGE_LINES = 160


def open_fence(text: str) -> str:
    opened = ""
    for line in text.splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if not match:
            continue
        marker, info = match.groups()
        if not opened:
            opened = marker + info
        elif marker[0] == opened[0] and len(marker) >= len(re.match(r'[`~]+', opened)[0]) and not info.strip():
            opened = ""
    return opened


def close_fence(text: str) -> str:
    fence = open_fence(text)
    return text + "\n" + re.match(r"[`~]+", fence)[0] if fence else text


@dataclass
class RichPage:
    reasoning: str = ""
    answer: str = ""
    code_prefix: str = ""
    used_bytes: int = 0
    lines: int = 0

    def rich_message(self, *, literal: bool = False) -> dict:
        if literal:
            blocks = []
            if self.reasoning:
                blocks.append({"type": "details", "summary": "Thinking", "blocks": [
                    {"type": "paragraph", "text": {"type": "italic", "text": self.reasoning}}]})
            if self.answer:
                blocks.append({"type": "paragraph", "text": self.answer})
            return {"blocks": blocks or [{"type": "paragraph", "text": "Generating..."}]}
        text = ""
        if self.reasoning:
            # Escaping prevents model-produced tags from breaking out of the collapse.
            text = ("<details><summary>Thinking</summary>\n<p><i>"
                    + html.escape(self.reasoning).replace("\n", "<br>")
                    + "</i></p>\n</details>\n\n")
        if self.answer:
            text += close_fence(self.code_prefix + self.answer)
        if len(text.encode("utf-8")) > 30_000:
            # Adversarial/unfinished fence delimiters can double the source when
            # closed for a preview. Literal blocks have no wrapper expansion.
            return self.rich_message(literal=True)
        return {"markdown": text or "Generating..."}


class RichBuffer:
    def __init__(self) -> None:
        self.pages = [RichPage()]
        self.answer_parts: list[str] = []
        self.reasoning_parts: list[str] = []

    @property
    def answer(self) -> str:
        return "".join(self.answer_parts)

    @property
    def reasoning(self) -> str:
        return "".join(self.reasoning_parts)

    def append(self, kind: str, text: str) -> None:
        if not text:
            return
        if kind not in ("answer", "reasoning"):
            raise ValueError("Unknown stream segment")
        (self.answer_parts if kind == "answer" else self.reasoning_parts).append(text)
        while text:
            page = self.pages[-1]
            available = PAGE_BYTES - page.used_bytes
            used = 0
            lines = 0
            count = 0
            for char in text:
                cost = len((html.escape(char) if kind == "reasoning" else char).encode("utf-8"))
                if used + cost > available or page.lines + lines >= PAGE_LINES:
                    break
                used += cost
                lines += char == "\n"
                count += 1
            if count:
                # Prefer complete lines when a page fills. Never discard whitespace.
                if count < len(text):
                    newline = text.rfind("\n", max(0, count - 500), count)
                    if newline >= 0:
                        count = newline + 1
                part, text = text[:count], text[count:]
                setattr(page, kind, getattr(page, kind) + part)
                page.used_bytes += len((html.escape(part) if kind == "reasoning" else part).encode("utf-8"))
                page.lines += part.count("\n")
            if text:
                fence = open_fence(page.code_prefix + page.answer)
                # Very long fence info is displayed literally on a continuation.
                prefix = fence + "\n" if fence and len(fence.encode("utf-8")) < 500 else ""
                self.pages.append(RichPage(code_prefix=prefix, used_bytes=len(prefix.encode("utf-8"))))


def retry_seconds(error: RetryAfter) -> float:
    delay = error.retry_after
    return delay.total_seconds() if isinstance(delay, timedelta) else float(delay)


class RichOutput:
    def __init__(self, bot, chat_id: int, draft_id: int, buffer: RichBuffer,
                 message_thread_id: int | None = None) -> None:
        self.bot, self.chat_id, self.draft_id, self.buffer = bot, chat_id, draft_id, buffer
        self.message_thread_id = message_thread_id
        self.sent = 0
        self.draft_retry_at = 0.0
        self.last_draft = None
        self.last_draft_at = 0.0

    async def _preview(self, page: RichPage) -> bool:
        """Bound replaceable previews without interrupting model inference."""
        try:
            await asyncio.wait_for(self._send(page, draft=True), timeout=5)
            return True
        except TimeoutError:
            return False

    def _target(self) -> dict:
        target = {"chat_id": self.chat_id}
        if self.message_thread_id is not None:
            target["message_thread_id"] = self.message_thread_id
        return target

    async def _send(self, page: RichPage, *, draft: bool) -> None:
        endpoint = "sendRichMessageDraft" if draft else "sendRichMessage"
        data = {**self._target(), "rich_message": page.rich_message()}
        if draft:
            data.update(draft_id=self.draft_id, can_stop=False)
        try:
            await self.bot.do_api_request(endpoint, api_kwargs=data)
        except BadRequest:
            # Rejected requests have not sent a message. Retry as shallow, literal
            # rich blocks (including a details block), preserving all source text.
            data["rich_message"] = page.rich_message(literal=True)
            await self.bot.do_api_request(endpoint, api_kwargs=data)

    async def _persist(self, page: RichPage) -> None:
        for attempt in range(3):
            try:
                await self._send(page, draft=False)
                self.last_draft = None  # Sending a message removes the current draft.
                return
            except RetryAfter as exc:
                if attempt == 2:
                    raise
                await asyncio.sleep(retry_seconds(exc) + 0.1)
        # Network timeouts are deliberately not retried: sendRichMessage has no
        # idempotency key, so an ambiguous response must not produce duplicates.

    async def publish(self, *, final: bool = False) -> None:
        end = len(self.buffer.pages) if final else len(self.buffer.pages) - 1
        while self.sent < end:
            page = self.buffer.pages[self.sent]
            if page.answer or page.reasoning:
                await self._persist(page)
            self.sent += 1
        if final:
            return
        now = time.monotonic()
        if now < self.draft_retry_at:
            return
        page = self.buffer.pages[-1]
        signature = (self.sent, page.reasoning, page.answer)
        if signature == self.last_draft and now - self.last_draft_at < 10:
            return  # Refresh idle drafts before their 30-second expiry.
        # Snapshot the mutable current page before awaiting the network.
        snapshot = RichPage(reasoning=page.reasoning, answer=page.answer, code_prefix=page.code_prefix)
        try:
            if await self._preview(snapshot):
                self.last_draft, self.last_draft_at = signature, now
        except RetryAfter as exc:
            self.draft_retry_at = time.monotonic() + retry_seconds(exc) + 0.1
        except NetworkError:
            # Drafts are replaceable previews; a later refresh recovers them.
            self.draft_retry_at = time.monotonic() + 3
            LOGGER.warning("Telegram draft update failed; retrying a later preview.")

    async def clear(self) -> None:
        try:
            await self.bot.send_message_draft(chat_id=self.chat_id, draft_id=self.draft_id,
                                              text="", message_thread_id=self.message_thread_id)
        except TelegramError:
            LOGGER.debug("Could not clear the temporary draft; it will expire.")
