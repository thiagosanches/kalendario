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

def was_reminder_sent(appointment_id, reminder_type):
    """Verifica se um lembrete já foi enviado"""
    data = load_sent_reminders()
    reminder_key = f"{appointment_id}_{reminder_type}"
    return reminder_key in data['reminders']

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
Bem-vindo ao Kalendario, {user_name}! 🏥

👤 Seu User ID: {user_id}

✨ Recursos Multi-Usuário:
• Cada usuário tem seus próprios compromissos
• Lembretes são enviados automaticamente apenas para você
• Suas consultas são privadas e independentes

Comandos:
/add - Adicionar uma nova consulta
/reminder - Adicionar um lembrete (medicamento, exame, etc.)
/list - Listar todas as suas consultas e lembretes
/delete - Excluir uma consulta/lembrete por ID
/test - Testar se o bot está enviando mensagens
/help - Mostrar esta mensagem de ajuda

📝 Comandos de Texto:
Para adicionar uma consulta:
/add 15/03 14:30 | Dr. Silva | Consulta Geral | Sala 205
ou
/add 2026-03-15 14:30 | Dr. Silva | Consulta Geral | Sala 205

Para adicionar um lembrete:
/reminder 16/03 08:00 | Tomar medicamento - Losartana 50mg | Em jejum

Formato consulta: /add DATA HORA | MÉDICO | DESCRIÇÃO | LOCAL
Formato lembrete: /reminder DATA HORA | DESCRIÇÃO | OBSERVAÇÃO

💡 DICA: Você não precisa informar o ano! 
   Aceito formatos: 15/03, 03-15, ou 2026-03-15

🎤 Mensagens de Voz:
Você também pode enviar mensagens de voz! Basta falar algo como:
"Consulta com Dr. Silva no dia 15 de março às 14h30 na sala 205"
"Lembrete para tomar remédio amanhã às 8 da manhã"

O bot vai transcrever e adicionar automaticamente!

🔔 Lembretes Automáticos:
Você receberá notificações automáticas:
• 24 horas antes de cada compromisso
• 2 horas antes de cada compromisso
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
                f"Por favor, forneça os detalhes da consulta:\n"
                f"/add 15/03 14:30 | Dr. Silva | Consulta Geral | Sala 205\n\n"
                f"💡 Ano atual é {current_year}, não precisa informar!"
            )
            return
        
        parts = [p.strip() for p in text.split('|')]
        
        if len(parts) < 2:
            await update.message.reply_text(
                "Formato inválido. Use:\n"
                "/add DATA HORA | MÉDICO | DESCRIÇÃO | LOCAL\n\n"
                "Exemplo: /add 15/03 14:30 | Dr. Silva | Consulta | Sala 205"
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
        
        doctor = parts[1] if len(parts) > 1 else "Médico Desconhecido"
        description = parts[2] if len(parts) > 2 else "Consulta"
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
        
        print(f"✅ Appointment saved: ID {appointment_id}, Date: {date_display} {time_str}, Doctor: {doctor}")
        
        try:
            await update.message.reply_text(
                f"✅ Consulta adicionada com sucesso!\n"
                f"ID: {appointment_id}\n"
                f"Data: {date_display} às {time_str}\n"
                f"Médico: {doctor}\n"
                f"Descrição: {description}\n"
                f"Local: {location}"
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
        await update.message.reply_text(f"❌ Erro ao adicionar consulta: {str(e)}")

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

async def list_appointments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista todas as consultas e lembretes do usuário"""
    if not await check_authorization(update, context):
        return
    
    try:
        user_id = update.effective_user.id
        print(f"📋 /list command received from user {user_id}")
        
        data = load_appointments()
        all_appointments = data.get('appointments', [])
        
        # Filter appointments for this user
        appointments = [apt for apt in all_appointments if apt.get('user_id') == user_id]
        
        if not appointments:
            await update.message.reply_text("Você ainda não tem consultas ou lembretes cadastrados.\n\nUse /add ou /reminder para adicionar!")
            print(f"ℹ️  User {user_id} has no appointments yet")
            return
        
        # Sort by date and time
        appointments.sort(key=lambda x: (x['date'], x['time']))
        
        message = "📋 Suas Consultas e Lembretes:\n\n"
        for apt in appointments:
            item_type = "🏥 Consulta" if apt.get('type') == 'appointment' else "⏰ Lembrete"
            message += f"{item_type} - ID: {apt['id']}\n"
            message += f"Data: {apt['date']} às {apt['time']}\n"
            if apt.get('doctor'):
                message += f"Médico: {apt['doctor']}\n"
            message += f"Descrição: {apt['description']}\n"
            if apt.get('location'):
                message += f"{'Local' if apt.get('type') == 'appointment' else 'Observação'}: {apt['location']}\n"
            message += "\n"
        
        await update.message.reply_text(message)
        print(f"✅ List sent to user {user_id} ({len(appointments)} items)")
        
    except Exception as e:
        print(f"❌ Exception in list_appointments for user {update.effective_user.id}: {e}")
        await update.message.reply_text(f"Erro ao listar consultas: {str(e)}")

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

🔔 Quando você adicionar consultas, receberá lembretes automáticos:
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
        
        system_prompt = f"""Você é um assistente que extrai informações de consultas médicas e lembretes de mensagens de voz.

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
- tipo (appointment para consultas médicas, reminder para lembretes como medicação, exames, etc.)
- médico (nome do médico se for consulta, deixe vazio se for lembrete)
- descrição (resumo do compromisso)
- local/observação

EXEMPLOS:
- "consulta com Dr. Silva dia 15 de março às 14h" → use ano {current_year}
- "lembrete para tomar remédio amanhã às 8h" → calcule data de amanhã
- "dentista na próxima terça às 10h30" → calcule a próxima terça

Retorne APENAS um JSON no formato:
{{"date": "AAAA-MM-DD", "time": "HH:MM", "type": "appointment", "doctor": "Dr. Nome", "description": "texto", "location": "local"}}

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
        
        # Create new entry
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
        
        data['appointments'].append(new_entry)
        save_appointments(data)
        
        # Send confirmation
        item_type = "🏥 Consulta" if new_entry['type'] == 'appointment' else "⏰ Lembrete"
        confirmation = f"✅ {item_type} adicionado com sucesso!\n\n"
        confirmation += f"ID: {appointment_id}\n"
        confirmation += f"Data: {new_entry['date']} às {new_entry['time']}\n"
        if new_entry['doctor']:
            confirmation += f"Médico: {new_entry['doctor']}\n"
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
                
                # Parse appointment datetime
                apt_datetime = datetime.strptime(f"{apt['date']} {apt['time']}", '%Y-%m-%d %H:%M')
                
                # Skip past appointments
                if apt_datetime <= now:
                    continue
                
                time_until = apt_datetime - now
                apt_id = apt['id']
                item_type = "🏥 Consulta" if apt.get('type') == 'appointment' else "⏰ Lembrete"
                
                # Check for 24-hour reminder
                if timedelta(hours=23, minutes=50) <= time_until <= timedelta(hours=24, minutes=10):
                    if not was_reminder_sent(apt_id, '24h'):
                        message = f"🔔 {item_type} AMANHÃ!\n\n"
                        message += f"Data: {apt_datetime.strftime('%d/%m/%Y')} às {apt['time']}\n"
                        if apt.get('doctor'):
                            message += f"Médico: {apt['doctor']}\n"
                        message += f"Descrição: {apt['description']}\n"
                        if apt.get('location'):
                            message += f"{'Local' if apt.get('type') == 'appointment' else 'Observação'}: {apt['location']}\n"
                        message += f"\n⏰ Faltam aproximadamente 24 horas!"
                        
                        await app_instance.bot.send_message(chat_id=user_id, text=message)
                        save_sent_reminder(apt_id, '24h')
                        print(f"Sent 24h reminder for appointment {apt_id} to user {user_id}")
                
                # Check for 2-hour reminder
                elif timedelta(hours=1, minutes=50) <= time_until <= timedelta(hours=2, minutes=10):
                    if not was_reminder_sent(apt_id, '2h'):
                        message = f"🔔 {item_type} EM 2 HORAS!\n\n"
                        message += f"Data: HOJE às {apt['time']}\n"
                        if apt.get('doctor'):
                            message += f"Médico: {apt['doctor']}\n"
                        message += f"Descrição: {apt['description']}\n"
                        if apt.get('location'):
                            message += f"{'Local' if apt.get('type') == 'appointment' else 'Observação'}: {apt['location']}\n"
                        message += f"\n⏰ Faltam aproximadamente 2 horas!"
                        
                        await app_instance.bot.send_message(chat_id=user_id, text=message)
                        save_sent_reminder(apt_id, '2h')
                        print(f"Sent 2h reminder for appointment {apt_id} to user {user_id}")
                        
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
