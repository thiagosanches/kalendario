"""Environment variables, shared clients, and rate-limit state."""

import os
from collections import defaultdict
from pathlib import Path

from openai import OpenAI

# ---------------------------------------------------------------------------
# Credentials and paths
# ---------------------------------------------------------------------------

BOT_TOKEN      = os.getenv('TELEGRAM_BOT_TOKEN', '')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '') or None
ALLOWED_USERS  = os.getenv('ALLOWED_USERS', '')   # comma-separated user IDs (optional whitelist)

TEMP_DIR = Path('temp_audio')
TEMP_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

if not BOT_TOKEN or BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
    raise ValueError("❌ TELEGRAM_BOT_TOKEN is not set. Please configure .env file")

if not OPENAI_API_KEY or OPENAI_API_KEY == 'YOUR_OPENAI_API_KEY_HERE':
    print("⚠️  OPENAI_API_KEY is not set. Voice messages will be disabled.")
    OPENAI_API_KEY = None

print("✅ Telegram bot token configured")
if OPENAI_API_KEY:
    print("✅ OpenAI API key configured - voice messages enabled")

# ---------------------------------------------------------------------------
# Whitelist
# ---------------------------------------------------------------------------

ALLOWED_USER_IDS: list[int] = []
if ALLOWED_USERS:
    try:
        ALLOWED_USER_IDS = [int(uid.strip()) for uid in ALLOWED_USERS.split(',') if uid.strip()]
        print(f"🔒 Whitelist enabled! {len(ALLOWED_USER_IDS)} authorized user(s)")
    except ValueError:
        print("⚠️  ALLOWED_USERS contains invalid values. Whitelist disabled.")
        ALLOWED_USER_IDS = []
else:
    print("🌐 Whitelist disabled - any user can use the bot")

# ---------------------------------------------------------------------------
# OpenAI client
# ---------------------------------------------------------------------------

openai_client: OpenAI | None = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# ---------------------------------------------------------------------------
# Rate-limit state (mutable module-level — intentional)
# ---------------------------------------------------------------------------

RATE_LIMIT_COMMANDS = 10  # max commands per window
RATE_LIMIT_WINDOW   = 60  # seconds

user_command_timestamps: dict[int, list] = defaultdict(list)
