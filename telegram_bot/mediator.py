from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

from telegram import Update
from telegram.ext import ContextTypes

from .ai_client import AIClient, AIError
from .config import Settings
from .database import Database

logger = logging.getLogger(__name__)


def _is_group(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type in {"group", "supergroup"})


def _is_expected_participant(user_id: int | None, settings: Settings) -> bool:
    return bool(user_id and settings.participant_user_ids and user_id in settings.participant_user_ids)


def _both_consented(db: Database, chat_id: int, settings: Settings) -> bool:
    return bool(settings.participant_user_ids) and settings.participant_user_ids.issubset(db.consented_ids(chat_id))


def _ai_is_on(db: Database, ai: AIClient) -> bool:
    return ai.available and db.get_setting("ai_enabled", "true") == "true"


def _provider_label(settings: Settings) -> str:
    host = urlparse(settings.ai_base_url).hostname
    return host or "the configured AI provider"


async def _send(update: Update, text: str) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(text)


async def consent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    user = update.effective_user
    chat = update.effective_chat
    if not _is_group(update) or not user or not chat:
        await _send(update, "Please use /consent in the shared group.")
        return
    if not _is_expected_participant(user.id, settings):
        await _send(update, "Only the two configured participants can enable AI mediation.")
        return
    ai: AIClient = context.application.bot_data["ai"]
    if not _ai_is_on(db, ai):
        await _send(update, "AI mediation is currently unavailable or disabled.")
        return

    db.give_consent(chat.id, user.id)
    provider = _provider_label(settings)
    await _send(
        update,
        f"Consent recorded. The bot may send the most recent {settings.max_context_messages} "
        f"text/caption messages from this group to {provider}. "
        "Use /withdraw to remove consent. Use /mediate when both have consented.",
    )


async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    db.withdraw_consent(chat.id, user.id)
    db.clear_context(chat.id)
    db.set_chat_mode(chat.id, "paused")
    await _send(update, "Your consent has been withdrawn and local context cleared.")


async def mediate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    user = update.effective_user
    chat = update.effective_chat
    if not _is_group(update) or not user or not chat:
        await _send(update, "Use /mediate in the shared group.")
        return
    if not _is_expected_participant(user.id, settings):
        await _send(update, "Only the configured participants can start mediation.")
        return
    if not _both_consented(db, chat.id, settings):
        await _send(update, "Both participants must run /consent first.")
        return
    db.set_chat_mode(chat.id, "active")
    await _send(update, "Mediation session is now active. Use /summary, /explain, /rephrase, or /pause.")


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    chat = update.effective_chat
    if not chat:
        return
    db.set_chat_mode(chat.id, "paused")
    await _send(update, "Mediation paused.")


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    chat = update.effective_chat
    if not chat:
        return
    if not _both_consented(db, chat.id, settings):
        await _send(update, "Both participants must still have consent.")
        return
    db.set_chat_mode(chat.id, "active")
    await _send(update, "Mediation resumed.")


async def _run_ai(update: Update, context: ContextTypes.DEFAULT_TYPE, instruction: str) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    ai: AIClient = context.application.bot_data["ai"]
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return
    if not _is_expected_participant(user.id, settings):
        await _send(update, "Only the configured participants can use AI commands.")
        return
    if not _both_consented(db, chat.id, settings):
        await _send(update, "Both participants must consent first.")
        return
    if not _ai_is_on(db, ai):
        await _send(update, "AI is currently disabled.")
        return

    context_rows = db.get_context(chat.id, settings.max_context_messages)
    if not context_rows:
        await _send(update, "No recent messages in context yet.")
        return

    transcript = "\n".join(
        f"{row.get('username') or row.get('user_id') or 'User'}: {row['text']}"
        for row in context_rows
    )
    messages = [
        {"role": "user", "content": f"{instruction}\n\nTranscript:\n{transcript}"},
    ]
    try:
        reply = await ai.chat(messages)
        await _send(update, reply)
    except AIError:
        await _send(update, "Sorry, the AI request failed. Please try again later.")


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_ai(update, context, "Please provide a fair, neutral summary of the discussion so far.")


async def explain_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_ai(update, context, "Please explore a possible misunderstanding in the discussion and suggest clarifying questions.")


async def rephrase_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_ai(update, context, "Please suggest a calmer, clearer rephrasing of the most recent message while preserving its meaning.")


async def ai_toggle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    ai: AIClient = context.application.bot_data["ai"]
    user = update.effective_user
    if not user or user.id not in settings.admin_user_ids:
        await _send(update, "Only admins can toggle AI.")
        return
    command = (update.effective_message.text or "").split("@")[0].lstrip("/").lower()
    if command == "ai_off":
        db.set_setting("ai_enabled", "false")
        db.pause_and_clear_context()
        await _send(update, "AI mediation is off.")
        return
    if not ai.available:
        await _send(update, "AI is not configured yet.")
        return
    db.set_setting("ai_enabled", "true")
    await _send(update, "AI mediation is enabled (still requires consent).")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send(
        update,
        "ARCHIVE COMMANDS (admins)\n"
        "/set_archive, /source_add, /source_remove\n"
        "/archive_on, /archive_off, /status\n"
        "/ai_on, /ai_off, /delete_data CONFIRM\n\n"
        "MEDIATION COMMANDS (participants)\n"
        "/consent, /withdraw, /mediate, /pause, /resume\n"
        "/summary, /explain, /rephrase\n\n"
        "/whoami — show your Telegram ID in private chat.",
    )


async def conversation_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or chat.type not in {"group", "supergroup"}:
        return
    text = message.text or message.caption
    if not text:
        return

    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    if not settings.participant_user_ids:
        return
    if not _both_consented(db, chat.id, settings):
        return

    state = db.get_chat_state(chat.id)
    if state["mode"] != "active":
        return

    db.add_context(
        chat.id,
        user.id if user else None,
        (user.username if user else None) or (user.full_name if user else None),
        text,
        time.time(),
    )


def register_handlers(application: object) -> None:
    from telegram.ext import CommandHandler

    application.add_handler(CommandHandler("consent", consent_command), group=1)
    application.add_handler(CommandHandler("withdraw", withdraw_command), group=1)
    application.add_handler(CommandHandler("mediate", mediate_command), group=1)
    application.add_handler(CommandHandler("pause", pause_command), group=1)
    application.add_handler(CommandHandler("resume", resume_command), group=1)
    application.add_handler(CommandHandler("summary", summary_command), group=1)
    application.add_handler(CommandHandler("explain", explain_command), group=1)
    application.add_handler(CommandHandler("rephrase", rephrase_command), group=1)
    application.add_handler(CommandHandler(["ai_on", "ai_off"], ai_toggle_command), group=1)
    application.add_handler(CommandHandler("help", help_command), group=1)
