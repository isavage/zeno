import io
import os
import tempfile
import logging
from pathlib import Path
from typing import Optional
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from app.config import settings
from app.agent.core import zeno_agent
from app.agent.memory import memory_store
from app.voice.stt import stt_engine
from app.voice import tts_engine

logger = logging.getLogger(__name__)

def is_user_authorized(user_id: int) -> bool:
    """Verifies that the user ID is in the allowed whitelist."""
    allowed = settings.allowed_telegram_ids
    if not allowed:
        # If not set, log warning and allow for initial setup
        logger.warning("No TELEGRAM_ALLOWED_USER_IDS configured. Allowing user %s", user_id)
        return True
    return user_id in allowed

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_user_authorized(user.id):
        await update.message.reply_text("⛔ Unauthorized. Your Telegram ID is not registered in Zeno.")
        return

    greeting = (
        f"👋 Hello {user.first_name}! I am **Zeno**, your private personal AI assistant.\n\n"
        "• Send me any text question or instruction.\n"
        "• 🎙️ Send me a voice note to talk with me.\n"
        "• Use `/clear` to reset our conversation context.\n"
        "• Your data & memory are securely encrypted at rest."
    )
    await update.message.reply_markdown(greeting)

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_user_authorized(user.id):
        return

    session_id = f"tg_{user.id}"
    memory_store.clear_history(session_id)
    await update.message.reply_text("🧹 Conversation history cleared.")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_user_authorized(user.id):
        return

    user_text = update.message.text
    session_id = f"tg_{user.id}"

    # Send typing action
    await update.message.chat.send_action("typing")

    result = await zeno_agent.process_query(session_id, user_text)
    reply_text = result.get("response", "")

    # Send text response
    try:
        await update.message.reply_markdown(reply_text)
    except Exception:
        # Fallback to plain text if markdown parsing fails
        await update.message.reply_text(reply_text)

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_user_authorized(user.id):
        return

    session_id = f"tg_{user.id}"
    voice = update.message.voice or update.message.audio
    if not voice:
        return

    await update.message.chat.send_action("record_voice")

    # Download voice note bytes
    voice_file = await context.bot.get_file(voice.file_id)
    voice_bytes = await voice_file.download_as_bytearray()

    # Transcribe via open-source faster-whisper
    try:
        transcription = stt_engine.transcribe_bytes(bytes(voice_bytes), suffix=".oga")
    except Exception as e:
        logger.error(f"Voice transcription error: {e}")
        await update.message.reply_text("⚠️ Could not transcribe voice message.")
        return

    if not transcription:
        await update.message.reply_text("🔇 No speech detected.")
        return

    # Acknowledge user transcription
    await update.message.reply_markdown(f"🎙️ *You said:* \"_{transcription}_\"")

    # Process query
    await update.message.chat.send_action("typing")
    result = await zeno_agent.process_query(session_id, transcription)
    reply_text = result.get("response", "")

    # Attempt voice reply if enabled
    voice_sent = False
    if settings.ENABLE_TELEGRAM_VOICE_REPLIES:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
            tmp_path = Path(tmp_audio.name)

        try:
            audio_path = await tts_engine.synthesize_to_file(reply_text, tmp_path)
            if audio_path and audio_path.exists():
                await update.message.chat.send_action("upload_voice")
                with open(audio_path, "rb") as voice_fh:
                    await update.message.reply_voice(voice=voice_fh)
                voice_sent = True
        except Exception as e:
            logger.warning(f"Failed to generate voice reply: {e}")
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    # If voice not sent or in addition to voice, send formatted text
    try:
        await update.message.reply_markdown(reply_text)
    except Exception:
        await update.message.reply_text(reply_text)

class TelegramBotManager:
    """Manages the Telegram Bot lifecycle."""

    def __init__(self):
        self.app: Optional[Application] = None

    def build_application(self) -> Optional[Application]:
        if not settings.TELEGRAM_BOT_TOKEN:
            logger.info("TELEGRAM_BOT_TOKEN not configured. Telegram bot service disabled.")
            return None

        application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", start_command))
        application.add_handler(CommandHandler("clear", clear_command))
        application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message))
        application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_message))

        self.app = application
        return application

    async def start(self):
        if not self.app:
            self.build_application()
        if self.app:
            logger.info("Starting Telegram Bot long-polling...")
            await self.app.initialize()
            await self.app.start()
            try:
                await self.app.updater.start_polling()
            except Exception as e:
                # Telegram token errors (e.g., InvalidToken) raise generic Exception
                logger.error(f"Telegram bot failed to start: {e}. Bot will remain disabled.")
                # Disable the bot by clearing the app reference
                self.app = None


    async def stop(self):
        if self.app and self.app.updater:
            logger.info("Stopping Telegram Bot...")
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

telegram_manager = TelegramBotManager()
