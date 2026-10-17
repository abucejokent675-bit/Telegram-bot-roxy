from __future__ import annotations

import asyncio
import html
import logging
from datetime import timezone

from telegram import Update
from telegram.error import NetworkError, RetryAfter, TelegramError
from telegram.ext import ContextTypes

from .database import Database

logger = logging.getLogger(__name__)


def _message_has_copyable_content(message: object) -> bool:
    return bool(
        getattr(message, "text", None)
        or getattr(message, "caption", None)
        or getattr(message, "effective_attachment", None)
    )


def _source_link(chat: object, message_id: int) -> str | None:
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"
    chat_id = getattr(chat, "id", 0)
    chat_id_text = str(chat_id)
    if chat_id_text.startswith("-100"):
        return f"https://t.me/c/{chat_id_text[4:]}/{message_id}"
    return None


def _sender_name(message: object) -> str:
    user = getattr(message, "from_user", None)
    if user:
        return " ".join(part for part in (user.first_name, user.last_name) if part).strip() or "Unknown sender"
    sender_chat = getattr(message, "sender_chat", None)
    if sender_chat and getattr(sender_chat, "title", None):
        return f"{sender_chat.title} (as a group/channel)"
    return "Unknown sender"


async def _send_details_with_one_retry(context: ContextTypes.DEFAULT_TYPE, archive_chat_id: int, text: str) -> None:
    try:
        await context.bot.send_message(
            chat_id=archive_chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except RetryAfter as error:
        await asyncio.sleep(min(float(error.retry_after) + 1, 60))
        await context.bot.send_message(
            chat_id=archive_chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


async def _copy_with_one_retry(context: ContextTypes.DEFAULT_TYPE, target: int, source: int, message_id: int):
    try:
        return await context.bot.copy_message(
            chat_id=target,
            from_chat_id=source,
            message_id=message_id,
        )
    except RetryAfter as error:
        await asyncio.sleep(min(float(error.retry_after) + 1, 60))
        return await context.bot.copy_message(
            chat_id=target,
            from_chat_id=source,
            message_id=message_id,
        )
    except NetworkError:
        await asyncio.sleep(2)
        return await context.bot.copy_message(
            chat_id=target,
            from_chat_id=source,
            message_id=message_id,
        )


async def archive_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat or chat.type not in {"group", "supergroup"}:
        return

    db: Database = context.application.bot_data["db"]
    if db.get_setting("archive_enabled", "false") != "true":
        return
    if not db.is_source(chat.id):
        return

    archive_chat_id = db.get_archive_chat_id()
    if not archive_chat_id:
        return

    if db.was_archived(chat.id, message.message_id):
        return

    if not _message_has_copyable_content(message):
        return

    try:
        copied = await _copy_with_one_retry(context, archive_chat_id, chat.id, message.message_id)
        db.mark_archived(chat.id, message.message_id, copied.message_id if copied else None)

        sender = html.escape(_sender_name(message))
        title = html.escape(getattr(chat, "title", None) or "Unknown group")
        when = message.date.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if message.date else "unknown time"
        link = _source_link(chat, message.message_id)
        link_html = f' • <a href="{html.escape(link)}">original</a>' if link else ""

        details = (
            f"<b>Archive</b>\n"
            f"From: <b>{title}</b>\n"
            f"Sender: {sender}\n"
            f"Time: {when}{link_html}"
        )
        await _send_details_with_one_retry(context, archive_chat_id, details)
    except TelegramError as error:
        logger.warning("Archive failed for chat %s message %s: %s", chat.id, message.message_id, type(error).__name__)
