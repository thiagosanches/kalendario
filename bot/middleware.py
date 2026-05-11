"""Authorization and rate-limiting middleware."""

from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from config import ALLOWED_USER_IDS, RATE_LIMIT_COMMANDS, RATE_LIMIT_WINDOW, user_command_timestamps


def is_user_allowed(user_id: int) -> bool:
    """Return *True* if the user may use the bot.

    When ``ALLOWED_USER_IDS`` is empty every user is allowed.
    """
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


async def check_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Reply with an access-denied message and return *False* if not authorised."""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "Usuário"

    if not is_user_allowed(user_id):
        await update.message.reply_text(
            f"🚫 Acesso Negado\n\n"
            f"Olá {user_name}! Este bot é de uso restrito.\n\n"
            f"Seu User ID: {user_id}\n\n"
            f"Se você acha que deveria ter acesso, peça ao administrador "
            f"para adicionar seu User ID à lista ALLOWED_USERS."
        )
        print(f"🚫 Access denied for user {user_id} ({user_name})")
        return False
    return True


async def rate_limit_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return *False* and warn the user if they exceed the rate limit."""
    user_id = update.effective_user.id
    now = datetime.now()

    user_command_timestamps[user_id] = [
        ts for ts in user_command_timestamps[user_id]
        if (now - ts).total_seconds() < RATE_LIMIT_WINDOW
    ]

    if len(user_command_timestamps[user_id]) >= RATE_LIMIT_COMMANDS:
        await update.message.reply_text(
            "⚠️ Você está enviando comandos muito rapidamente. "
            "Por favor, aguarde um momento."
        )
        return False

    user_command_timestamps[user_id].append(now)
    return True
