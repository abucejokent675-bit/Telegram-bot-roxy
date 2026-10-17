from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from .config import Settings
from .database import Database

logger = logging.getLogger(__name__)


def _is_admin(user_id: int | None, settings: Settings) -> bool:
    return bool(user_id and user_id in settings.admin_user_ids)


async def _send(update: Update, text: str) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(text)


async def whoami_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    if update.effective_chat and update.effective_chat.type != "private":
        await _send(update, "Please use /whoami in a private chat with the bot.")
        return
    await _send(update, f"Your Telegram user ID is: {user.id}")


async def set_archive_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    user = update.effective_user
    chat = update.effective_chat
    if not _is_admin(user.id if user else None, settings):
        await _send(update, "Only configured admins can set the archive group.")
        return
    if not chat or chat.type not in {"group", "supergroup"}:
        await _send(update, "Run /set_archive inside the private archive group.")
        return
    db.set_archive_chat_id(chat.id)
    await _send(update, f"This group is now the archive destination (chat id {chat.id}).")


async def source_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    user = update.effective_user
    chat = update.effective_chat
    if not _is_admin(user.id if user else None, settings):
        await _send(update, "Only configured admins can add source groups.")
        return
    if not chat or chat.type not in {"group", "supergroup"}:
        await _send(update, "Run /source_add inside the group you want to archive.")
        return
    db.add_source(chat.id)
    await _send(update, f"This group is now registered as a source (chat id {chat.id}).")


async def source_remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    user = update.effective_user
    chat = update.effective_chat
    if not _is_admin(user.id if user else None, settings):
        await _send(update, "Only configured admins can remove source groups.")
        return
    if not chat or chat.type not in {"group", "supergroup"}:
        await _send(update, "Run /source_remove inside the group.")
        return
    db.remove_source(chat.id)
    await _send(update, "This group is no longer a source.")


async def archive_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    user = update.effective_user
    if not _is_admin(user.id if user else None, settings):
        await _send(update, "Only configured admins can enable archiving.")
        return
    if not db.get_archive_chat_id():
        await _send(update, "Set an archive group first with /set_archive.")
        return
    db.set_setting("archive_enabled", "true")
    await _send(update, "Archiving is now ON.")


async def archive_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    user = update.effective_user
    if not _is_admin(user.id if user else None, settings):
        await _send(update, "Only configured admins can disable archiving.")
        return
    db.set_setting("archive_enabled", "false")
    await _send(update, "Archiving is now OFF.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    user = update.effective_user
    if not _is_admin(user.id if user else None, settings):
        await _send(update, "Only configured admins can view status.")
        return
    archive_id = db.get_archive_chat_id()
    sources = db.get_setting("source_chat_ids", "") or "(none)"
    archive_on = db.get_setting("archive_enabled", "false")
    ai_on = db.get_setting("ai_enabled", "true")
    await _send(
        update,
        f"Archive chat: {archive_id or '(not set)'}\n"
        f"Sources: {sources}\n"
        f"Archiving: {archive_on}\n"
        f"AI enabled: {ai_on}\n"
        f"AI configured: {settings.ai_configured}",
    )


async def delete_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    user = update.effective_user
    if not _is_admin(user.id if user else None, settings):
        await _send(update, "Only configured admins can delete data.")
        return
    if not update.effective_chat or update.effective_chat.type != "private":
        await _send(update, "Run /delete_data CONFIRM in a private chat.")
        return
    args = context.args or []
    if not args or args[0].upper() != "CONFIRM":
        await _send(update, "To erase local database data, send: /delete_data CONFIRM")
        return
    db.delete_all_data()
    await _send(update, "Local database data has been erased. Archive messages in Telegram must be deleted manually.")


def register_admin_handlers(application: object) -> None:
    application.add_handler(CommandHandler("whoami", whoami_command), group=1)
    application.add_handler(CommandHandler("set_archive", set_archive_command), group=1)
    application.add_handler(CommandHandler("source_add", source_add_command), group=1)
    application.add_handler(CommandHandler("source_remove", source_remove_command), group=1)
    application.add_handler(CommandHandler("archive_on", archive_on_command), group=1)
    application.add_handler(CommandHandler("archive_off", archive_off_command), group=1)
    application.add_handler(CommandHandler("status", status_command), group=1)
    application.add_handler(CommandHandler("delete_data", delete_data_command), group=1)
