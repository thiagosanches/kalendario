"""Bot configuration: environment variables, paths, and shared clients."""

import os
from collections import defaultdict
from pathlib import Path

from openai import OpenAI

# ---------------------------------------------------------------------------
# Telegram / OpenAI credentials
# ---------------------------------------------------------------------------

BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
OPENAI_API_KEY: str | None = os.getenv('OPENAI_API_KEY') or None

if not BOT_TOKEN or BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
    raise ValueError("❌ TELEGRAM_BOT_TOKEN is not set. Please configure .env file")

if not OPENAI_API_KEY or OPENAI_API_KEY == 'YOUR_OPENAI_API_KEY_HERE':
    print("⚠️  OPENAI_API_KEY is not set. Voice messages will be disabled.")
    OPENAI_API_KEY = None

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

TEMP_DIR = Path('temp_audio')
TEMP_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

_raw_allowed = os.getenv('ALLOWED_USERS', '')
ALLOWED_USER_IDS: list[int] = []

if _raw_allowed:
    try:
        ALLOWED_USER_IDS = [int(uid.strip()) for uid in _raw_allowed.split(',') if uid.strip()]
        print(f"🔒 Whitelist enabled — {len(ALLOWED_USER_IDS)} authorised user(s)")
    except ValueError:
        print("⚠️  ALLOWED_USERS contains invalid values. Whitelist disabled.")
else:
    print("🌐 Whitelist disabled — any user can use the bot")

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

RATE_LIMIT_COMMANDS = 10   # max commands per window
RATE_LIMIT_WINDOW = 60     # seconds
user_command_timestamps: dict[int, list] = defaultdict(list)

# ---------------------------------------------------------------------------
# OpenAI client (None when key is absent)
# ---------------------------------------------------------------------------

openai_client: OpenAI | None = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# ---------------------------------------------------------------------------
# Startup log
# ---------------------------------------------------------------------------

print("✅ Telegram bot token configured")
if openai_client:
    print("✅ OpenAI API key configured — voice messages enabled")
