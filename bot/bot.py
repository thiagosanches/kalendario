#!/usr/bin/env python3
"""Kalendario Telegram Bot - thin entry point."""

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from config import BOT_TOKEN
from handlers.commands import (
    add_appointment,
    add_recurring,
    add_reminder,
    delete_appointment,
    delete_recurring,
    help_command,
    list_appointments,
    start,
    test_notification,
)
from handlers.voice import handle_voice
from reminders import post_init


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("help",     help_command))
    app.add_handler(CommandHandler("add",      add_appointment))
    app.add_handler(CommandHandler("reminder", add_reminder))
    app.add_handler(CommandHandler("list",     list_appointments))
    app.add_handler(CommandHandler("delete",   delete_appointment))
    app.add_handler(CommandHandler("addrec",   add_recurring))
    app.add_handler(CommandHandler("delrec",   delete_recurring))
    app.add_handler(CommandHandler("test",     test_notification))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    app.post_init = post_init

    print("Bot is running... Press Ctrl+C to stop.")
    print("Voice message support enabled!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
