from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from .admin import register_admin_handlers
from .ai_client import AIClient
from .archiver import archive_message
from .config import load_settings
from .database import Database
from .mediator import conversation_message, register_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            ("help", "Show commands and the privacy notice"),
            ("status", "Show archive and AI status (admin)"),
            ("archive_on", "Enable archiving (admin)"),
            ("archive_off", "Disable archiving (admin)"),
            ("set_archive", "Set this group as the archive (admin)"),
            ("source_add", "Register this group as a source (admin)"),
            ("source_remove", "Remove this source group (admin)"),
            ("whoami", "Show your Telegram ID in a private chat"),
            ("consent", "Consent to AI mediation for this group"),
            ("withdraw", "Withdraw mediation consent and clear context"),
            ("mediate", "Start an agreed mediation session"),
            ("pause", "Pause mediation"),
            ("resume", "Resume mediation"),
            ("summary", "Fairly summarize the current discussion"),
            ("explain", "Explore a possible misunderstanding"),
            ("rephrase", "Suggest calmer wording for the last message"),
        ]
    )


async def post_shutdown(application: Application) -> None:
    ai: AIClient = application.bot_data["ai"]
    await ai.close()


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    logger.error("Update processing failed (error=%s)", type(error).__name__ if error else "unknown")


def main() -> None:
    settings = load_settings()
    db = Database(settings.database_path)
    if not db.get_setting("ai_enabled", ""):
        db.set_setting("ai_enabled", "true" if settings.ai_enabled else "false")
    if not db.get_setting("archive_enabled", ""):
        db.set_setting("archive_enabled", "false")

    ai = AIClient(settings)
    application = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.bot_data.update({"settings": settings, "db": db, "ai": ai})

    application.add_handler(MessageHandler(filters.ALL, archive_message), group=0)
    register_admin_handlers(application)
    register_handlers(application)
    application.add_handler(MessageHandler(filters.ALL, conversation_message), group=2)
    application.add_error_handler(handle_error)

    logger.info("Bot starting in long-polling mode. Message bodies and credentials are not logged.")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == "__main__":
    main()
