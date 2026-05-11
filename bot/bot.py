#!/usr/bin/env python3
"""
Telegram Bot for Kalendario
Receives appointment information and saves to JSON files
Supports voice messages with transcription via OpenAI Whisper
Sends automatic reminders 24h and 2h before appointments
"""

import json
import os
import re
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

import calendar


# ---------------------------------------------------------------------------
# Recurrence helpers
# ---------------------------------------------------------------------------

FREQ_LABELS = {
    'weekly':   'semanal',
    'biweekly': 'quinzenal',
    'monthly':  'mensal',
    'yearly':   'anual',
}

FREQ_ALIASES = {
    'semanal': 'weekly', 'semana': 'weekly', 'semanalmente': 'weekly', 'weekly': 'weekly',
    'toda semana': 'weekly', 'todo semana': 'weekly',
    'quinzenal': 'biweekly', 'quinzenalmente': 'biweekly', 'biweekly': 'biweekly',
    'a cada duas semanas': 'biweekly', 'duas semanas': 'biweekly',
    'mensal': 'monthly', 'mensalmente': 'monthly', 'monthly': 'monthly',
    'todo mês': 'monthly', 'todo mes': 'monthly', 'todo o mês': 'monthly',
    'anual': 'yearly', 'anualmente': 'yearly', 'yearly': 'yearly',
    'todo ano': 'yearly', 'todo o ano': 'yearly',
}


def _add_months(dt, n):
    """Add n months to a datetime, clamping to the last day of the target month."""
    month = dt.month - 1 + n
    year = dt.year + month // 12
    month = month % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


def generate_occurrences(apt: dict, from_dt: datetime = None, to_dt: datetime = None):
    """
    Yield (occurrence_date_str, time_str) for a recurring appointment rule
    within the optional [from_dt, to_dt] window.
    Non-recurring entries yield their single (date, time) tuple.
    If recurrence_end is absent the series is treated as infinite;
    to_dt (or a 50-year safety cap) is used as the upper bound.
    """
    frequency = apt.get('recurrence')
    if not frequency:
        yield apt['date'], apt['time']
        return

    start = datetime.strptime(f"{apt['date']} {apt['time']}", '%Y-%m-%d %H:%M')
    end_str = apt.get('recurrence_end')
    if end_str:
        # Use end-of-day so occurrences on the end date itself are included
        end = datetime.strptime(end_str, '%Y-%m-%d').replace(hour=23, minute=59)
    elif to_dt:
        end = to_dt  # caller already bounds the window
    else:
        end = start.replace(year=start.year + 50)  # safety cap for unbounded calls

    current = start
    while current <= end:
        if (from_dt is None or current >= from_dt) and (to_dt is None or current <= to_dt):
            yield current.strftime('%Y-%m-%d'), apt['time']
        if frequency == 'weekly':
            current += timedelta(weeks=1)
        elif frequency == 'biweekly':
            current += timedelta(weeks=2)
        elif frequency == 'monthly':
            current = _add_months(current, 1)
        elif frequency == 'yearly':
            current = current.replace(year=current.year + 1)
        else:
            break


# ---------------------------------------------------------------------------
# Configuration
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ALLOWED_USERS = os.getenv('ALLOWED_USERS', '')  # Comma-separated list of user IDs (optional whitelist)

# Data directory - use /data in Docker, ../data when running locally
DATA_DIR = '/data' if os.path.exists('/data') else '../data'
APPOINTMENTS_FILE = os.path.join(DATA_DIR, 'appointments.json')
SENT_REMINDERS_FILE = os.path.join(DATA_DIR, 'sent_reminders.json')
TEMP_DIR = 'temp_audio'

# Validate required credentials
if not BOT_TOKEN or BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
    raise ValueError("❌ TELEGRAM_BOT_TOKEN is not set. Please configure .env file")

if not OPENAI_API_KEY or OPENAI_API_KEY == 'YOUR_OPENAI_API_KEY_HERE':
    print("⚠️  OPENAI_API_KEY is not set. Voice messages will be disabled.")
    OPENAI_API_KEY = None

print("✅ Telegram bot token configured")
print(f"📁 Data directory: {DATA_DIR}")
if OPENAI_API_KEY:
    print("✅ OpenAI API key configured - voice messages enabled")

# Parse allowed users list
ALLOWED_USER_IDS = []
if ALLOWED_USERS:
    try:
        ALLOWED_USER_IDS = [int(uid.strip()) for uid in ALLOWED_USERS.split(',') if uid.strip()]
        print(f"🔒 Whitelist enabled! {len(ALLOWED_USER_IDS)} authorized user(s)")
    except ValueError:
        print("⚠️  ALLOWED_USERS contains invalid values. Whitelist disabled.")
        ALLOWED_USER_IDS = []
else:
    print("🌐 Whitelist disabled - any user can use the bot")

# Initialize OpenAI client only if API key is set
openai_client = None
if OPENAI_API_KEY:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Create temp directory for audio files
os.makedirs(TEMP_DIR, exist_ok=True)

# Global application instance for sending messages
app_instance = None

# Rate limiting
from collections import defaultdict
user_command_timestamps = defaultdict(list)
RATE_LIMIT_COMMANDS = 10  # Max commands per minute
RATE_LIMIT_WINDOW = 60  # seconds

def is_user_allowed(user_id: int) -> bool:
    """
    Check if a user is authorized to use the bot.
    If ALLOWED_USER_IDS is empty, allows everyone.
    """
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS

async def rate_limit_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is within rate limit"""
    user_id = update.effective_user.id
    now = datetime.now()
    
    # Clean old timestamps
    user_command_timestamps[user_id] = [
        ts for ts in user_command_timestamps[user_id]
        if (now - ts).total_seconds() < RATE_LIMIT_WINDOW
    ]
    
    # Check rate limit
    if len(user_command_timestamps[user_id]) >= RATE_LIMIT_COMMANDS:
        await update.message.reply_text(
            "⚠️ Você está enviando comandos muito rapidamente. "
            "Por favor, aguarde um momento."
        )
        return False
    
    # Add current timestamp
    user_command_timestamps[user_id].append(now)
    return True

async def check_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Middleware to check authorization.
    Returns True if authorized, False otherwise.
    """
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

def load_appointments():
    """Carrega consultas existentes do arquivo JSON"""
    if os.path.exists(APPOINTMENTS_FILE):
        with open(APPOINTMENTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"appointments": []}

def save_appointments(data):
    """Salva consultas no arquivo JSON"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(APPOINTMENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_sent_reminders():
    """Carrega registro de lembretes já enviados"""
    if os.path.exists(SENT_REMINDERS_FILE):
        with open(SENT_REMINDERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"reminders": []}

def save_sent_reminder(appointment_id, reminder_type):
    """Salva registro de que um lembrete foi enviado"""
    data = load_sent_reminders()
    reminder_key = f"{appointment_id}_{reminder_type}"
    
    if reminder_key not in data['reminders']:
        data['reminders'].append(reminder_key)
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SENT_REMINDERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    return True

def was_reminder_sent(appointment_id, occurrence_date, reminder_type):
    """Verifica se um lembrete já foi enviado para uma ocorrência específica"""
    data = load_sent_reminders()
    reminder_key = f"{appointment_id}_{occurrence_date}_{reminder_type}"
    return reminder_key in data['reminders']


def save_sent_reminder_occurrence(appointment_id, occurrence_date, reminder_type):
    """Salva registro de lembrete enviado para uma ocorrência específica"""
    data = load_sent_reminders()
    reminder_key = f"{appointment_id}_{occurrence_date}_{reminder_type}"
    if reminder_key not in data['reminders']:
        data['reminders'].append(reminder_key)
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SENT_REMINDERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

def parse_flexible_date(date_str):
    """
    Parse date string flexibly - accepts formats with or without year.
    If year is not provided, uses current year.
    Validates date is reasonable (not too far in past or future).
    
    Accepts:
    - 2026-03-15 (YYYY-MM-DD)
    - 03-15 (MM-DD, uses current year)
    - 15/03 (DD/MM, uses current year)
    - 15/03/2026 (DD/MM/YYYY)
    """
    current_year = datetime.now().year
    today = datetime.now().date()
    parsed_date = None
    
    # Try YYYY-MM-DD format
    try:
        parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        pass
    
    # Try MM-DD format (add current year)
    if not parsed_date:
        try:
            date_obj = datetime.strptime(date_str, '%m-%d')
            parsed_date = date_obj.replace(year=current_year).date()
        except ValueError:
            pass
    
    # Try DD/MM format (add current year)
    if not parsed_date:
        try:
            date_obj = datetime.strptime(date_str, '%d/%m')
            parsed_date = date_obj.replace(year=current_year).date()
        except ValueError:
            pass
    
    # Try DD/MM/YYYY format
    if not parsed_date:
        try:
            date_obj = datetime.strptime(date_str, '%d/%m/%Y')
            parsed_date = date_obj.date()
        except ValueError:
            pass
    
    # If nothing works, raise error
    if not parsed_date:
        raise ValueError(f"Formato de data inválido: {date_str}")
    
    # Validate date is not in the past (allow same day)
    if parsed_date < today:
        raise ValueError(
            f"Data já passou: {parsed_date.strftime('%d/%m/%Y')}. "
            f"Por favor, use uma data atual ou futura."
        )
    
    # Validate date is not too far in the future (max 2 years)
    max_future_date = today + timedelta(days=730)
    if parsed_date > max_future_date:
        raise ValueError(
            f"Data muito distante: {parsed_date.strftime('%d/%m/%Y')}. "
            f"Máximo de 2 anos no futuro ({max_future_date.strftime('%d/%m/%Y')})."
        )
    
    return parsed_date.strftime('%Y-%m-%d')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Envia uma mensagem quando o comando /start é executado."""
    if not await check_authorization(update, context):
        return
    
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "Usuário"
    
    print(f"🚀 /start command received from user {user_id} ({user_name})")
    
    welcome_message = f"""
Bem-vindo ao Kalendario, {user_name}! 📅

👤 Seu User ID: {user_id}

✨ Recursos Multi-Usuário:
• Cada usuário tem seus próprios eventos
• Lembretes são enviados automaticamente apenas para você
• Seus eventos são privados e independentes

Comandos:
/add - Adicionar um novo evento
/reminder - Adicionar um lembrete
/addrec - Adicionar evento recorrente
/list - Listar todos os seus eventos e lembretes
/delete - Excluir um evento/lembrete por ID
/delrec - Excluir uma série recorrente por ID
/test - Testar se o bot está enviando mensagens
/help - Mostrar esta mensagem de ajuda

📝 Comandos de Texto:
Para adicionar um evento:
/add 15/03 14:30 | Reunião de equipe | Sala 205
ou
/add 2026-03-15 14:30 | Reunião de equipe | Sala 205

Para adicionar um lembrete:
/reminder 16/03 08:00 | Ligar para o banco | Trazer documentos

Formato evento: /add DATA HORA | TÍTULO | DESCRIÇÃO | LOCAL
Formato lembrete: /reminder DATA HORA | DESCRIÇÃO | OBSERVAÇÃO

💡 DICA: Você não precisa informar o ano! 
   Aceito formatos: 15/03, 03-15, ou 2026-03-15

🎤 Mensagens de Voz:
Você também pode enviar mensagens de voz! Basta falar algo como:
"Reunião com o cliente na sexta às 14h30 na sala 3"
"Lembrete para ligar para o banco amanhã às 8 da manhã"

O bot vai transcrever e adicionar automaticamente!

🔔 Lembretes Automáticos:
Você receberá notificações automáticas:
• 24 horas antes de cada evento
• 2 horas antes de cada evento
    """
    
    try:
        await update.message.reply_text(welcome_message)
        print(f"✅ Welcome message sent successfully to user {user_id}")
    except Exception as e:
        print(f"❌ ERROR: Failed to send welcome message to user {user_id}: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Envia uma mensagem quando o comando /help é executado."""
    await start(update, context)

async def add_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adiciona uma nova consulta"""
    print(f"📝 /add command received from user {update.effective_user.id}")
    
    if not await check_authorization(update, context):
        return
    if not await rate_limit_check(update, context):
        return
    
    try:
        # Parse the command: /add 15/03 14:30 | Dr. Silva | Consulta Geral | Sala 205
        text = update.message.text.replace('/add', '').strip()
        
        if not text:
            current_year = datetime.now().year
            await update.message.reply_text(
                f"Por favor, forneça os detalhes do evento:\n"
                f"/add 15/03 14:30 | Reunião de equipe | Sala 205\n\n"
                f"💡 Ano atual é {current_year}, não precisa informar!"
            )
            return
        
        parts = [p.strip() for p in text.split('|')]
        
        if len(parts) < 2:
            await update.message.reply_text(
                "Formato inválido. Use:\n"
                "/add DATA HORA | TÍTULO | DESCRIÇÃO | LOCAL\n\n"
                "Exemplo: /add 15/03 14:30 | Reunião | Pauta mensal | Sala 3"
            )
            return
        
        # Parse date and time
        datetime_parts = parts[0].split()
        if len(datetime_parts) < 2:
            await update.message.reply_text("Por favor, forneça data e hora")
            return
        
        date_input = datetime_parts[0]
        time_str = datetime_parts[1]
        
        # Parse date flexibly (with or without year)
        date_str = parse_flexible_date(date_input)
        
        # Validate time format
        datetime.strptime(time_str, '%H:%M')
        
        doctor = parts[1] if len(parts) > 1 else ""
        description = parts[2] if len(parts) > 2 else "Evento"
        location = parts[3] if len(parts) > 3 else ""
        
        # Load existing appointments
        data = load_appointments()
        
        # Generate ID
        appointment_id = max([apt.get('id', 0) for apt in data['appointments']], default=0) + 1
        
        # Create new appointment
        new_appointment = {
            "id": appointment_id,
            "user_id": update.effective_user.id,
            "username": update.effective_user.username or update.effective_user.first_name or "Usuário",
            "date": date_str,
            "time": time_str,
            "doctor": doctor,
            "description": description,
            "location": location,
            "type": "appointment",
            "created_at": datetime.now().isoformat()
        }
        
        data['appointments'].append(new_appointment)
        save_appointments(data)
        
        # Format date for display
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        date_display = date_obj.strftime('%d/%m/%Y')
        
        print(f"✅ Appointment saved: ID {appointment_id}, Date: {date_display} {time_str}, Title: {doctor}")
        
        try:
            await update.message.reply_text(
                f"✅ Evento adicionado com sucesso!\n"
                f"ID: {appointment_id}\n"
                f"Data: {date_display} às {time_str}\n"
                + (f"Título: {doctor}\n" if doctor else "")
                + f"Descrição: {description}\n"
                + (f"Local: {location}" if location else "")
            )
            print(f"✅ Confirmation message sent successfully for appointment ID {appointment_id}")
        except Exception as reply_error:
            print(f"❌ ERROR: Failed to send confirmation message: {reply_error}")
            print(f"   Appointment ID: {appointment_id}, User ID: {update.effective_user.id}")
        
    except ValueError as e:
        current_year = datetime.now().year
        await update.message.reply_text(
            f"❌ Formato de data/hora inválido.\n\n"
            f"Formatos aceitos para data:\n"
            f"• 15/03 (dia/mês - usa ano {current_year})\n"
            f"• 03-15 (mês-dia - usa ano {current_year})\n"
            f"• 2026-03-15 (ano-mês-dia)\n"
            f"• 15/03/2026 (dia/mês/ano)\n\n"
            f"Hora: HH:MM (exemplo: 14:30)\n\n"
            f"Erro: {str(e)}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao adicionar evento: {str(e)}")

async def add_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adiciona um novo lembrete"""
    print(f"⏰ /reminder command received from user {update.effective_user.id}")
    
    if not await check_authorization(update, context):
        return
    if not await rate_limit_check(update, context):
        return
    
    try:
        # Parse the command: /reminder 16/03 08:00 | Tomar medicamento | Em jejum
        text = update.message.text.replace('/reminder', '').strip()
        
        if not text:
            current_year = datetime.now().year
            await update.message.reply_text(
                f"Por favor, forneça os detalhes do lembrete:\n"
                f"/reminder 16/03 08:00 | Tomar medicamento - Losartana | Em jejum\n\n"
                f"💡 Ano atual é {current_year}, não precisa informar!"
            )
            return
        
        parts = [p.strip() for p in text.split('|')]
        
        if len(parts) < 2:
            await update.message.reply_text(
                "Formato inválido. Use:\n"
                "/reminder DATA HORA | DESCRIÇÃO | OBSERVAÇÃO\n\n"
                "Exemplo: /reminder 16/03 08:00 | Tomar remédio | Em jejum"
            )
            return
        
        # Parse date and time
        datetime_parts = parts[0].split()
        if len(datetime_parts) < 2:
            await update.message.reply_text("Por favor, forneça data e hora")
            return
        
        date_input = datetime_parts[0]
        time_str = datetime_parts[1]
        
        # Parse date flexibly (with or without year)
        date_str = parse_flexible_date(date_input)
        
        # Validate time format
        datetime.strptime(time_str, '%H:%M')
        
        description = parts[1] if len(parts) > 1 else "Lembrete"
        location = parts[2] if len(parts) > 2 else ""
        
        # Load existing appointments
        data = load_appointments()
        
        # Generate ID
        appointment_id = max([apt.get('id', 0) for apt in data['appointments']], default=0) + 1
        
        # Create new reminder
        new_reminder = {
            "id": appointment_id,
            "user_id": update.effective_user.id,
            "username": update.effective_user.username or update.effective_user.first_name or "Usuário",
            "date": date_str,
            "time": time_str,
            "doctor": "",
            "description": description,
            "location": location,
            "type": "reminder",
            "created_at": datetime.now().isoformat()
        }
        
        data['appointments'].append(new_reminder)
        save_appointments(data)
        
        # Format date for display
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        date_display = date_obj.strftime('%d/%m/%Y')
        
        print(f"⏰ Reminder saved: ID {appointment_id}, Date: {date_display} {time_str}, Description: {description}")
        
        try:
            await update.message.reply_text(
                f"⏰ Lembrete adicionado com sucesso!\n"
                f"ID: {appointment_id}\n"
                f"Data: {date_display} às {time_str}\n"
                f"Descrição: {description}\n"
                f"Observação: {location}"
            )
            print(f"✅ Confirmation message sent successfully for reminder ID {appointment_id}")
        except Exception as reply_error:
            print(f"❌ ERROR: Failed to send confirmation message: {reply_error}")
            print(f"   Reminder ID: {appointment_id}, User ID: {update.effective_user.id}")
        
    except ValueError as e:
        current_year = datetime.now().year
        print(f"❌ ValueError in add_reminder: {e}")
        await update.message.reply_text(
            f"❌ Formato de data/hora inválido.\n\n"
            f"Formatos aceitos para data:\n"
            f"• 16/03 (dia/mês - usa ano {current_year})\n"
            f"• 03-16 (mês-dia - usa ano {current_year})\n"
            f"• 2026-03-16 (ano-mês-dia)\n"
            f"• 16/03/2026 (dia/mês/ano)\n\n"
            f"Hora: HH:MM (exemplo: 08:00)\n\n"
            f"Erro: {str(e)}"
        )
    except Exception as e:
        print(f"❌ Exception in add_reminder: {e}")
        await update.message.reply_text(f"❌ Erro ao adicionar lembrete: {str(e)}")

async def add_recurring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adiciona um compromisso recorrente: /addrec DATA HORA | FREQ | MÉDICO | DESCRIÇÃO | LOCAL"""
    print(f"🔁 /addrec command received from user {update.effective_user.id}")

    if not await check_authorization(update, context):
        return
    if not await rate_limit_check(update, context):
        return

    text = update.message.text.replace('/addrec', '').strip()
    if not text:
        await update.message.reply_text(
            "Formato: /addrec DATA HORA | FREQ | TÍTULO | DESCRIÇÃO | LOCAL\n\n"
            "Frequências aceitas: semanal, quinzenal, mensal, anual\n\n"
            "Exemplo: /addrec 15/05 10:00 | mensal | Academia | Treino funcional | Parque"
        )
        return

    parts = [p.strip() for p in text.split('|')]
    if len(parts) < 3:
        await update.message.reply_text(
            "Formato inválido. Use:\n"
            "/addrec DATA HORA | FREQ | TÍTULO | DESCRIÇÃO | LOCAL"
        )
        return

    try:
        datetime_parts = parts[0].split()
        if len(datetime_parts) < 2:
            await update.message.reply_text("Forneça data e hora.")
            return

        date_str = parse_flexible_date(datetime_parts[0])
        time_str = datetime_parts[1]
        datetime.strptime(time_str, '%H:%M')

        freq_input = parts[1].lower().strip()
        frequency = FREQ_ALIASES.get(freq_input)
        if not frequency:
            await update.message.reply_text(
                f"Frequência '{freq_input}' inválida.\n"
                "Use: semanal, quinzenal, mensal, anual"
            )
            return

        doctor = parts[2] if len(parts) > 2 else ""
        description = parts[3] if len(parts) > 3 else "Compromisso recorrente"
        location = parts[4] if len(parts) > 4 else ""

        data = load_appointments()
        appointment_id = max([a.get('id', 0) for a in data['appointments']], default=0) + 1

        new_entry = {
            "id": appointment_id,
            "user_id": update.effective_user.id,
            "username": update.effective_user.username or update.effective_user.first_name or "Usuário",
            "date": date_str,
            "time": time_str,
            "doctor": doctor,
            "description": description,
            "location": location,
            "type": "appointment",
            "recurrence": frequency,
            "created_at": datetime.now().isoformat()
        }

        data['appointments'].append(new_entry)
        save_appointments(data)

        freq_label = FREQ_LABELS[frequency]
        await update.message.reply_text(
            f"🔁 Evento recorrente adicionado!\n"
            f"ID: {appointment_id}\n"
            f"Início: {date_str} às {time_str}\n"
            f"Frequência: {freq_label} (sem data de término)\n"
            + (f"Título: {doctor}\n" if doctor else "")
            + f"Descrição: {description}\n\n"
            + f"Para excluir esta série: /delrec {appointment_id}"
        )
        print(f"✅ Recurring entry saved: ID {appointment_id}, freq={frequency}, start={date_str}")

    except ValueError as e:
        await update.message.reply_text(f"❌ Erro: {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao adicionar recorrente: {e}")


async def delete_recurring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exclui uma regra recorrente inteira por ID: /delrec <id>"""
    if not await check_authorization(update, context):
        return

    user_id = update.effective_user.id
    text = update.message.text.replace('/delrec', '').strip()
    if not text:
        await update.message.reply_text("Use: /delrec <id>\nVeja o ID com /list")
        return

    try:
        appointment_id = int(text)
    except ValueError:
        await update.message.reply_text("ID inválido. Forneça um número.")
        return

    data = load_appointments()
    target = next((a for a in data['appointments'] if a['id'] == appointment_id), None)

    if not target:
        await update.message.reply_text(f"Item com ID {appointment_id} não encontrado.")
        return
    if target.get('user_id') != user_id:
        await update.message.reply_text("❌ Você não pode excluir este item.")
        return
    if not target.get('recurrence'):
        await update.message.reply_text("Este item não é recorrente. Use /delete para excluí-lo.")
        return

    data['appointments'] = [a for a in data['appointments'] if a['id'] != appointment_id]
    save_appointments(data)
    await update.message.reply_text(f"✅ Série recorrente ID {appointment_id} excluída com sucesso!")


async def list_appointments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista todas as consultas e lembretes do usuário"""
    if not await check_authorization(update, context):
        return

    try:
        user_id = update.effective_user.id
        print(f"📋 /list command received from user {user_id}")

        data = load_appointments()
        all_appointments = data.get('appointments', [])
        user_appointments = [apt for apt in all_appointments if apt.get('user_id') == user_id]

        if not user_appointments:
            await update.message.reply_text("Você ainda não tem eventos ou lembretes cadastrados.\n\nUse /add ou /reminder para adicionar!")
            print(f"ℹ️  User {user_id} has no appointments yet")
            return

        now = datetime.now()
        # Show each appointment/reminder as a single entry (no expansion)
        one_time = [apt for apt in user_appointments if not apt.get('recurrence')]
        recurring = [apt for apt in user_appointments if apt.get('recurrence')]

        # Sort one-time entries by date/time; filter out past ones
        future_one_time = sorted(
            [apt for apt in one_time if datetime.strptime(f"{apt['date']} {apt['time']}", '%Y-%m-%d %H:%M') >= now],
            key=lambda a: datetime.strptime(f"{a['date']} {a['time']}", '%Y-%m-%d %H:%M')
        )

        if not future_one_time and not recurring:
            await update.message.reply_text("Sem compromissos futuros.")
            return

        message = "📋 Seus Eventos e Lembretes:\n\n"

        for apt in future_one_time:
            item_type = "📅 Evento" if apt.get('type') == 'appointment' else "⏰ Lembrete"
            message += f"{item_type} - ID: {apt['id']}\n"
            message += f"Data: {apt['date']} às {apt['time']}\n"
            if apt.get('doctor'):
                message += f"Título: {apt['doctor']}\n"
            message += f"Descrição: {apt['description']}\n"
            if apt.get('location'):
                message += f"Local: {apt['location']}\n"
            message += "\n"

        if recurring:
            message += "🔁 Eventos Recorrentes:\n\n"
            for apt in sorted(recurring, key=lambda a: a['id']):
                freq_label = FREQ_LABELS.get(apt['recurrence'], apt['recurrence'])
                message += f"🔁 {freq_label} - ID: {apt['id']}\n"
                message += f"Início: {apt['date']} às {apt['time']}\n"
                if apt.get('doctor'):
                    message += f"Título: {apt['doctor']}\n"
                message += f"Descrição: {apt['description']}\n"
                if apt.get('location'):
                    message += f"Local: {apt['location']}\n"
                message += "\n"

        await update.message.reply_text(message)
        print(f"✅ List sent to user {user_id} ({len(future_one_time)} one-time, {len(recurring)} recurring)")

    except Exception as e:
        print(f"❌ Exception in list_appointments for user {update.effective_user.id}: {e}")
        await update.message.reply_text(f"Erro ao listar eventos: {str(e)}")

async def delete_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exclui uma consulta por ID (apenas do próprio usuário)"""
    if not await check_authorization(update, context):
        return
    
    try:
        user_id = update.effective_user.id
        text = update.message.text.replace('/delete', '').strip()
        
        if not text:
            await update.message.reply_text("Por favor, forneça o ID da consulta: /delete 1")
            return
        
        appointment_id = int(text)
        
        data = load_appointments()
        appointments = data.get('appointments', [])
        
        # Find the appointment
        appointment_to_delete = None
        for apt in appointments:
            if apt['id'] == appointment_id:
                appointment_to_delete = apt
                break
        
        if not appointment_to_delete:
            await update.message.reply_text(f"Item com ID {appointment_id} não encontrado.")
            return
        
        # Check if user owns this appointment
        if appointment_to_delete.get('user_id') != user_id:
            await update.message.reply_text(f"❌ Você não pode excluir este item. Ele pertence a outro usuário.")
            return
        
        # Remove appointment
        data['appointments'] = [apt for apt in appointments if apt['id'] != appointment_id]
        
        save_appointments(data)
        await update.message.reply_text(f"✅ Item {appointment_id} excluído com sucesso!")
        
    except ValueError:
        await update.message.reply_text("ID inválido. Por favor, forneça um número.")
    except Exception as e:
        await update.message.reply_text(f"Erro ao excluir item: {str(e)}")

async def test_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a test notification immediately to verify bot is working"""
    if not await check_authorization(update, context):
        return
    
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "Usuário"
    
    print(f"🧪 /test command received from user {user_id} ({user_name})")
    
    try:
        test_message = f"""
🧪 TESTE DE NOTIFICAÇÃO

Olá {user_name}! 👋

✅ O bot está funcionando corretamente!
✅ Você está recebendo mensagens!

Este é um teste para verificar se:
• O bot está online
• Consegue enviar mensagens para você
• Os lembretes automáticos funcionarão

🔔 Quando você adicionar eventos, receberá lembretes automáticos:
• 24 horas antes
• 2 horas antes

Seu User ID: {user_id}
        """
        
        await update.message.reply_text(test_message)
        print(f"✅ Test notification sent successfully to user {user_id}")
        
    except Exception as e:
        print(f"❌ ERROR: Failed to send test notification to user {user_id}: {e}")
        # Try to send a simpler error message
        try:
            await update.message.reply_text("❌ Erro ao enviar notificação de teste")
        except:
            pass

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa mensagens de voz e cria consultas/lembretes"""
    if not await check_authorization(update, context):
        return
    if not await rate_limit_check(update, context):
        return
    
    # Check if OpenAI is configured
    if not openai_client:
        await update.message.reply_text(
            "❌ Mensagens de voz não estão disponíveis. "
            "O administrador precisa configurar OPENAI_API_KEY."
        )
        return
    
    audio_path = None
    try:
        await update.message.reply_text("🎤 Processando sua mensagem de voz...")
        
        # Download voice message
        voice = update.message.voice
        
        # Check file size (max 10MB)
        MAX_SIZE_MB = 10
        if voice.file_size and voice.file_size > MAX_SIZE_MB * 1024 * 1024:
            await update.message.reply_text(
                f"❌ Arquivo de áudio muito grande. "
                f"Tamanho máximo: {MAX_SIZE_MB}MB"
            )
            return
        
        file = await context.bot.get_file(voice.file_id)
        
        # Sanitize file_id to prevent path traversal
        safe_filename = re.sub(r'[^a-zA-Z0-9_-]', '', voice.file_id[:50])
        if not safe_filename:
            safe_filename = f"voice_{int(datetime.now().timestamp())}"
        
        audio_path = os.path.join(TEMP_DIR, f"{safe_filename}.ogg")
        
        # Verify the path is still within TEMP_DIR
        audio_path_abs = os.path.abspath(audio_path)
        temp_dir_abs = os.path.abspath(TEMP_DIR)
        if not audio_path_abs.startswith(temp_dir_abs):
            raise ValueError("Invalid file path detected")
        
        await file.download_to_drive(audio_path)
        
        # Transcribe with OpenAI Whisper
        with open(audio_path, 'rb') as audio_file:
            transcription = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="pt"
            )
        
        transcribed_text = transcription.text
        await update.message.reply_text(f"📝 Transcrição: {transcribed_text}")
        
        # Parse the transcribed text using OpenAI to extract appointment details
        today = datetime.now()
        current_date = today.strftime("%Y-%m-%d")
        current_year = today.year
        current_month = today.month
        
        system_prompt = f"""Você é um assistente que extrai informações de eventos e lembretes de mensagens de voz.

CONTEXTO TEMPORAL:
- Data atual: {current_date}
- Ano atual: {current_year}
- Mês atual: {current_month}
- Se o usuário não mencionar o ano, assuma o ano atual ({current_year})
- Se o usuário mencionar apenas dia e mês (ex: "dia 15 de março"), use o ano atual
- Se o usuário mencionar "amanhã", "próxima semana", etc., calcule a data baseada em {current_date}

Extraia as seguintes informações:
- data (formato AAAA-MM-DD)
- hora (formato HH:MM, aceite também "14h", "14h30", "2 da tarde")
- tipo (appointment para eventos/compromissos, reminder para lembretes)
- título (título curto do evento, deixe vazio se for lembrete simples)
- descrição (resumo do compromisso)
- local/observação

EXEMPLOS:
- "reunião com o cliente dia 15 de março às 14h" → use ano {current_year}
- "lembrete para ligar para o banco amanhã às 8h" → calcule data de amanhã
- "academia na próxima terça às 10h30" → calcule a próxima terça

EVENTOS RECORRENTES:
Se o usuário mencionar recorrência (toda semana, todo mês, semanalmente, mensalmente, toda segunda-feira, toda quinta-feira, etc.), inclua o campo "recurrence":
- "toda semana" / "semanalmente" / "toda <dia da semana>" → "weekly"
- "quinzenalmente" / "a cada duas semanas" → "biweekly"
- "todo mês" / "mensalmente" / "todo dia X" → "monthly"
- "todo ano" / "anualmente" → "yearly"
Se não houver recorrência, omita o campo "recurrence".

QUANDO HÁ RECORRÊNCIA E DIA DA SEMANA:
- "toda quinta-feira" com data atual {current_date} → calcule a próxima quinta-feira como "date"
- "toda terça às 10h" → próxima terça como "date"

Retorne APENAS um JSON no formato:
{{"date": "AAAA-MM-DD", "time": "HH:MM", "type": "appointment", "doctor": "Título do evento", "description": "texto", "location": "local", "recurrence": "weekly"}}

Se não conseguir extrair a data/hora, use valores vazios."""

        completion = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Hoje é {current_date}. Mensagem do usuário: {transcribed_text}"}
            ],
            response_format={"type": "json_object"}
        )
        
        parsed_data = json.loads(completion.choices[0].message.content)
        
        # Validate required fields
        if not parsed_data.get('date') or not parsed_data.get('time'):
            await update.message.reply_text(
                "❌ Não consegui identificar a data e hora. Por favor, tente novamente mencionando claramente a data e horário.\n\n"
                "Exemplo: 'Consulta com Dr. Silva no dia 15 de março às 14h30'"
            )
            return
        
        # Load existing appointments
        data = load_appointments()
        appointment_id = max([apt.get('id', 0) for apt in data['appointments']], default=0) + 1

        recurrence = parsed_data.get('recurrence', '').lower() or None
        if recurrence and recurrence not in FREQ_LABELS:
            recurrence = None  # ignore unknown values from GPT

        new_entry = {
            "id": appointment_id,
            "user_id": update.effective_user.id,
            "date": parsed_data.get('date', ''),
            "time": parsed_data.get('time', ''),
            "doctor": parsed_data.get('doctor', ''),
            "description": parsed_data.get('description', transcribed_text),
            "location": parsed_data.get('location', ''),
            "type": parsed_data.get('type', 'appointment'),
            "created_at": datetime.now().isoformat()
        }

        if recurrence:
            new_entry['recurrence'] = recurrence
            # No recurrence_end stored → infinite series

        data['appointments'].append(new_entry)
        save_appointments(data)

        # Send confirmation
        item_type = "📅 Evento" if new_entry['type'] == 'appointment' else "⏰ Lembrete"
        confirmation = f"✅ {item_type} adicionado com sucesso!\n\n"
        confirmation += f"ID: {appointment_id}\n"
        confirmation += f"Data: {new_entry['date']} às {new_entry['time']}\n"
        if recurrence:
            confirmation += f"🔁 Recorrência: {FREQ_LABELS[recurrence]} (sem data de término)\n"
            confirmation += f"Para excluir a série: /delrec {appointment_id}\n"
        if new_entry['doctor']:
            confirmation += f"Título: {new_entry['doctor']}\n"
        confirmation += f"Descrição: {new_entry['description']}\n"
        if new_entry['location']:
            confirmation += f"{'Local' if new_entry['type'] == 'appointment' else 'Observação'}: {new_entry['location']}"

        await update.message.reply_text(confirmation)
        
    except Exception as e:
        print(f"Voice processing error: {e}")
        await update.message.reply_text(
            "❌ Erro ao processar mensagem de voz. "
            "Tente novamente ou use comandos de texto."
        )
    finally:
        # Always clean up audio file
        if audio_path and os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except Exception as cleanup_error:
                print(f"Failed to remove audio file {audio_path}: {cleanup_error}")

async def check_and_send_reminders():
    """Verifica e envia lembretes de consultas próximas para cada usuário"""
    global app_instance
    
    if not app_instance:
        return
    
    try:
        data = load_appointments()
        appointments = data.get('appointments', [])
        now = datetime.now()
        
        for apt in appointments:
            try:
                # Skip if no user_id (old data)
                user_id = apt.get('user_id')
                if not user_id:
                    continue
                
                # Parse base appointment datetime
                apt_datetime = datetime.strptime(f"{apt['date']} {apt['time']}", '%Y-%m-%d %H:%M')

                # Skip entries with no future occurrences (non-recurring past dates)
                if not apt.get('recurrence') and apt_datetime <= now:
                    continue
                
                apt_id = apt['id']
                item_type = "📅 Evento" if apt.get('type') == 'appointment' else "⏰ Lembrete"

                # Iterate over all upcoming occurrences of this entry
                window_start = now - timedelta(hours=24, minutes=11)
                window_end = now + timedelta(hours=24, minutes=11)
                for occ_date, occ_time in generate_occurrences(apt, from_dt=window_start, to_dt=window_end):
                    occ_dt = datetime.strptime(f"{occ_date} {occ_time}", '%Y-%m-%d %H:%M')
                    if occ_dt <= now:
                        continue
                    time_until = occ_dt - now

                    # Check for 24-hour reminder
                    if timedelta(hours=23, minutes=50) <= time_until <= timedelta(hours=24, minutes=10):
                        if not was_reminder_sent(apt_id, occ_date, '24h'):
                            message = f"🔔 {item_type} AMANHÃ!\n\n"
                            message += f"Data: {occ_dt.strftime('%d/%m/%Y')} às {occ_time}\n"
                            if apt.get('doctor'):
                                message += f"Título: {apt['doctor']}\n"
                            message += f"Descrição: {apt['description']}\n"
                            if apt.get('location'):
                                message += f"Local: {apt['location']}\n"
                            message += f"\n⏰ Faltam aproximadamente 24 horas!"
                            await app_instance.bot.send_message(chat_id=user_id, text=message)
                            save_sent_reminder_occurrence(apt_id, occ_date, '24h')
                            print(f"Sent 24h reminder for appointment {apt_id} ({occ_date}) to user {user_id}")

                    # Check for 2-hour reminder
                    elif timedelta(hours=1, minutes=50) <= time_until <= timedelta(hours=2, minutes=10):
                        if not was_reminder_sent(apt_id, occ_date, '2h'):
                            message = f"🔔 {item_type} EM 2 HORAS!\n\n"
                            message += f"Data: HOJE às {occ_time}\n"
                            if apt.get('doctor'):
                                message += f"Título: {apt['doctor']}\n"
                            message += f"Descrição: {apt['description']}\n"
                            if apt.get('location'):
                                message += f"Local: {apt['location']}\n"
                            message += f"\n⏰ Faltam aproximadamente 2 horas!"
                            await app_instance.bot.send_message(chat_id=user_id, text=message)
                            save_sent_reminder_occurrence(apt_id, occ_date, '2h')
                            print(f"Sent 2h reminder for appointment {apt_id} ({occ_date}) to user {user_id}")
                        
            except Exception as e:
                print(f"Error processing appointment {apt.get('id')}: {e}")
                continue
                
    except Exception as e:
        print(f"Error in check_and_send_reminders: {e}")

async def post_init(application: Application) -> None:
    """Initialize scheduler after application starts"""
    global app_instance
    app_instance = application
    
    # Setup scheduler for reminder notifications
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_and_send_reminders,
        trigger=IntervalTrigger(minutes=5),  # Check every 5 minutes
        id='reminder_checker',
        name='Check and send appointment reminders',
        replace_existing=True
    )
    scheduler.start()
    
    print("🔔 Automatic reminder system activated!")
    print("📱 Each user will receive reminders for their own appointments")
    print("⏰ Checking for reminders every 5 minutes...")

def main():
    """Inicia o bot"""
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add", add_appointment))
    application.add_handler(CommandHandler("reminder", add_reminder))
    application.add_handler(CommandHandler("list", list_appointments))
    application.add_handler(CommandHandler("delete", delete_appointment))
    application.add_handler(CommandHandler("addrec", add_recurring))
    application.add_handler(CommandHandler("delrec", delete_recurring))
    application.add_handler(CommandHandler("test", test_notification))
    
    # Register voice message handler
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    # Setup post-init callback for scheduler
    application.post_init = post_init
    
    # Start the Bot
    print("🤖 Bot is running...")
    print("🎤 Voice message support enabled!")
    print("\nPress Ctrl+C to stop.\n")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n👋 Bot stopped!")

if __name__ == '__main__':
    main()
