"""All slash-command handlers."""

from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from date_utils import parse_flexible_date
from middleware import check_authorization, rate_limit_check
from recurrence import FREQ_ALIASES, FREQ_LABELS
from storage import load_appointments, save_appointments


# ---------------------------------------------------------------------------
# /start  /help
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_authorization(update, context):
        return

    user_id   = update.effective_user.id
    user_name = update.effective_user.first_name or "Usuário"
    print(f"🚀 /start command received from user {user_id} ({user_name})")

    await update.message.reply_text(f"""
Bem-vindo ao Kalendario, {user_name}! 📅

👤 Seu User ID: {user_id}

✨ Recursos Multi-Usuário:
• Cada usuário tem seus próprios eventos
• Lembretes são enviados automaticamente apenas para você
• Seus eventos são privados e independentes

Comandos:
/add       — Adicionar um novo evento
/reminder  — Adicionar um lembrete
/addrec    — Adicionar evento recorrente
/list      — Listar todos os seus eventos e lembretes
/delete    — Excluir um evento/lembrete por ID
/delrec    — Excluir uma série recorrente por ID
/test      — Testar se o bot está enviando mensagens
/help      — Mostrar esta mensagem de ajuda

📝 Formato evento:
/add DATA HORA | TÍTULO | DESCRIÇÃO | LOCAL
Exemplo: /add 15/03 14:30 | Reunião de equipe | Sala 205

📝 Formato lembrete:
/reminder DATA HORA | DESCRIÇÃO | OBSERVAÇÃO
Exemplo: /reminder 16/03 08:00 | Tomar medicamento | Em jejum

💡 O ano é opcional — aceito 15/03, 03-15, ou 2026-03-15.

🎤 Mensagens de Voz:
Você também pode enviar mensagens de voz! O bot transcreve e cria o evento automaticamente.

🔔 Lembretes Automáticos:
• 24 horas antes de cada evento
• 2 horas antes de cada evento
""")
    print(f"✅ Welcome message sent successfully to user {user_id}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


# ---------------------------------------------------------------------------
# /add
# ---------------------------------------------------------------------------

async def add_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"📝 /add command received from user {update.effective_user.id}")
    if not await check_authorization(update, context):
        return
    if not await rate_limit_check(update, context):
        return

    text = update.message.text.replace('/add', '').strip()
    if not text:
        year = datetime.now().year
        await update.message.reply_text(
            f"Por favor, forneça os detalhes do evento:\n"
            f"/add 15/03 14:30 | Reunião de equipe | Sala 205\n\n"
            f"💡 Ano atual é {year}, não precisa informar!"
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

    try:
        dt_parts = parts[0].split()
        if len(dt_parts) < 2:
            await update.message.reply_text("Por favor, forneça data e hora.")
            return

        date_str = parse_flexible_date(dt_parts[0])
        time_str = dt_parts[1]
        datetime.strptime(time_str, '%H:%M')

        doctor      = parts[1] if len(parts) > 1 else ""
        description = parts[2] if len(parts) > 2 else "Evento"
        location    = parts[3] if len(parts) > 3 else ""

        data   = load_appointments()
        apt_id = max((a.get('id', 0) for a in data['appointments']), default=0) + 1

        data['appointments'].append({
            "id":          apt_id,
            "user_id":     update.effective_user.id,
            "username":    update.effective_user.username or update.effective_user.first_name or "Usuário",
            "date":        date_str,
            "time":        time_str,
            "doctor":      doctor,
            "description": description,
            "location":    location,
            "type":        "appointment",
            "created_at":  datetime.now().isoformat(),
        })
        save_appointments(data)

        date_display = datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y')
        print(f"✅ Appointment saved: ID {apt_id}, {date_display} {time_str}, title={doctor!r}")
        await update.message.reply_text(
            f"✅ Evento adicionado com sucesso!\n"
            f"ID: {apt_id}\nData: {date_display} às {time_str}\n"
            + (f"Título: {doctor}\n" if doctor else "")
            + f"Descrição: {description}\n"
            + (f"Local: {location}" if location else "")
        )

    except ValueError as exc:
        year = datetime.now().year
        await update.message.reply_text(
            f"❌ Formato de data/hora inválido.\n\n"
            f"Formatos aceitos: 15/03, 03-15, 2026-03-15, 15/03/2026\n"
            f"Hora: HH:MM (ex: 14:30)\n\nErro: {exc}"
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ Erro ao adicionar evento: {exc}")


# ---------------------------------------------------------------------------
# /reminder
# ---------------------------------------------------------------------------

async def add_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"⏰ /reminder command received from user {update.effective_user.id}")
    if not await check_authorization(update, context):
        return
    if not await rate_limit_check(update, context):
        return

    text = update.message.text.replace('/reminder', '').strip()
    if not text:
        year = datetime.now().year
        await update.message.reply_text(
            f"Por favor, forneça os detalhes do lembrete:\n"
            f"/reminder 16/03 08:00 | Tomar medicamento | Em jejum\n\n"
            f"💡 Ano atual é {year}, não precisa informar!"
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

    try:
        dt_parts = parts[0].split()
        if len(dt_parts) < 2:
            await update.message.reply_text("Por favor, forneça data e hora.")
            return

        date_str = parse_flexible_date(dt_parts[0])
        time_str = dt_parts[1]
        datetime.strptime(time_str, '%H:%M')

        description = parts[1] if len(parts) > 1 else "Lembrete"
        location    = parts[2] if len(parts) > 2 else ""

        data   = load_appointments()
        apt_id = max((a.get('id', 0) for a in data['appointments']), default=0) + 1

        data['appointments'].append({
            "id":          apt_id,
            "user_id":     update.effective_user.id,
            "username":    update.effective_user.username or update.effective_user.first_name or "Usuário",
            "date":        date_str,
            "time":        time_str,
            "doctor":      "",
            "description": description,
            "location":    location,
            "type":        "reminder",
            "created_at":  datetime.now().isoformat(),
        })
        save_appointments(data)

        date_display = datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y')
        print(f"⏰ Reminder saved: ID {apt_id}, {date_display} {time_str}, desc={description!r}")
        await update.message.reply_text(
            f"⏰ Lembrete adicionado com sucesso!\n"
            f"ID: {apt_id}\nData: {date_display} às {time_str}\n"
            f"Descrição: {description}\n"
            + (f"Observação: {location}" if location else "")
        )

    except ValueError as exc:
        print(f"❌ ValueError in add_reminder: {exc}")
        await update.message.reply_text(f"❌ Formato de data/hora inválido.\nErro: {exc}")
    except Exception as exc:
        print(f"❌ Exception in add_reminder: {exc}")
        await update.message.reply_text(f"❌ Erro ao adicionar lembrete: {exc}")


# ---------------------------------------------------------------------------
# /addrec
# ---------------------------------------------------------------------------

async def add_recurring(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"🔁 /addrec command received from user {update.effective_user.id}")
    if not await check_authorization(update, context):
        return
    if not await rate_limit_check(update, context):
        return

    text = update.message.text.replace('/addrec', '').strip()
    if not text:
        await update.message.reply_text(
            "Formato: /addrec DATA HORA | FREQ | TÍTULO | DESCRIÇÃO | LOCAL\n\n"
            "Frequências aceitas: diário, semanal, quinzenal, mensal, anual\n\n"
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
        dt_parts = parts[0].split()
        if len(dt_parts) < 2:
            await update.message.reply_text("Forneça data e hora.")
            return

        date_str = parse_flexible_date(dt_parts[0])
        time_str = dt_parts[1]
        datetime.strptime(time_str, '%H:%M')

        frequency = FREQ_ALIASES.get(parts[1].lower().strip())
        if not frequency:
            await update.message.reply_text(
                f"Frequência '{parts[1]}' inválida.\n"
                "Use: diário, semanal, quinzenal, mensal, anual"
            )
            return

        doctor      = parts[2] if len(parts) > 2 else ""
        description = parts[3] if len(parts) > 3 else "Compromisso recorrente"
        location    = parts[4] if len(parts) > 4 else ""

        data   = load_appointments()
        apt_id = max((a.get('id', 0) for a in data['appointments']), default=0) + 1

        data['appointments'].append({
            "id":          apt_id,
            "user_id":     update.effective_user.id,
            "username":    update.effective_user.username or update.effective_user.first_name or "Usuário",
            "date":        date_str,
            "time":        time_str,
            "doctor":      doctor,
            "description": description,
            "location":    location,
            "type":        "appointment",
            "recurrence":  frequency,
            "created_at":  datetime.now().isoformat(),
        })
        save_appointments(data)

        print(f"✅ Recurring entry saved: ID {apt_id}, freq={frequency}, start={date_str}")
        await update.message.reply_text(
            f"🔁 Evento recorrente adicionado!\n"
            f"ID: {apt_id}\nInício: {date_str} às {time_str}\n"
            f"Frequência: {FREQ_LABELS[frequency]} (sem data de término)\n"
            + (f"Título: {doctor}\n" if doctor else "")
            + f"Descrição: {description}\n\n"
            f"Para excluir esta série: /delrec {apt_id}"
        )

    except ValueError as exc:
        await update.message.reply_text(f"❌ Erro: {exc}")
    except Exception as exc:
        await update.message.reply_text(f"❌ Erro ao adicionar recorrente: {exc}")


# ---------------------------------------------------------------------------
# /delrec
# ---------------------------------------------------------------------------

async def delete_recurring(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_authorization(update, context):
        return

    user_id = update.effective_user.id
    text    = update.message.text.replace('/delrec', '').strip()
    if not text:
        await update.message.reply_text("Use: /delrec <id>\nVeja o ID com /list")
        return

    try:
        apt_id = int(text)
    except ValueError:
        await update.message.reply_text("ID inválido. Forneça um número.")
        return

    data   = load_appointments()
    target = next((a for a in data['appointments'] if a['id'] == apt_id), None)

    if not target:
        await update.message.reply_text(f"Item com ID {apt_id} não encontrado.")
        return
    if target.get('user_id') != user_id:
        await update.message.reply_text("❌ Você não pode excluir este item.")
        return
    if not target.get('recurrence'):
        await update.message.reply_text("Este item não é recorrente. Use /delete para excluí-lo.")
        return

    data['appointments'] = [a for a in data['appointments'] if a['id'] != apt_id]
    save_appointments(data)
    await update.message.reply_text(f"✅ Série recorrente ID {apt_id} excluída com sucesso!")


# ---------------------------------------------------------------------------
# /list
# ---------------------------------------------------------------------------

async def list_appointments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_authorization(update, context):
        return

    user_id = update.effective_user.id
    print(f"📋 /list command received from user {user_id}")

    try:
        data        = load_appointments()
        user_apts   = [a for a in data.get('appointments', []) if a.get('user_id') == user_id]

        if not user_apts:
            await update.message.reply_text(
                "Você ainda não tem eventos ou lembretes cadastrados.\n\n"
                "Use /add ou /reminder para adicionar!"
            )
            return

        now       = datetime.now()
        one_time  = [a for a in user_apts if not a.get('recurrence')]
        recurring = [a for a in user_apts if a.get('recurrence')]

        future = sorted(
            [a for a in one_time
             if datetime.strptime(f"{a['date']} {a['time']}", '%Y-%m-%d %H:%M') >= now],
            key=lambda a: datetime.strptime(f"{a['date']} {a['time']}", '%Y-%m-%d %H:%M'),
        )

        if not future and not recurring:
            await update.message.reply_text("Sem compromissos futuros.")
            return

        lines = ["📋 Seus Eventos e Lembretes:\n"]
        for a in future:
            kind = "📅 Evento" if a.get('type') == 'appointment' else "⏰ Lembrete"
            lines.append(f"{kind} - ID: {a['id']}")
            lines.append(f"Data: {a['date']} às {a['time']}")
            if a.get('doctor'):
                lines.append(f"Título: {a['doctor']}")
            lines.append(f"Descrição: {a['description']}")
            if a.get('location'):
                lines.append(f"Local: {a['location']}")
            lines.append("")

        if recurring:
            lines.append("🔁 Eventos Recorrentes:\n")
            for a in sorted(recurring, key=lambda x: x['id']):
                freq = FREQ_LABELS.get(a['recurrence'], a['recurrence'])
                lines.append(f"🔁 {freq} - ID: {a['id']}")
                lines.append(f"Início: {a['date']} às {a['time']}")
                if a.get('doctor'):
                    lines.append(f"Título: {a['doctor']}")
                lines.append(f"Descrição: {a['description']}")
                if a.get('location'):
                    lines.append(f"Local: {a['location']}")
                lines.append("")

        await update.message.reply_text('\n'.join(lines))
        print(f"✅ List sent to user {user_id} ({len(future)} one-time, {len(recurring)} recurring)")

    except Exception as exc:
        print(f"❌ Exception in list_appointments for user {user_id}: {exc}")
        await update.message.reply_text(f"Erro ao listar eventos: {exc}")


# ---------------------------------------------------------------------------
# /delete
# ---------------------------------------------------------------------------

async def delete_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_authorization(update, context):
        return

    try:
        user_id = update.effective_user.id
        text    = update.message.text.replace('/delete', '').strip()
        if not text:
            await update.message.reply_text("Por favor, forneça o ID do evento: /delete 1")
            return

        apt_id = int(text)
        data   = load_appointments()
        target = next((a for a in data['appointments'] if a['id'] == apt_id), None)

        if not target:
            await update.message.reply_text(f"Item com ID {apt_id} não encontrado.")
            return
        if target.get('user_id') != user_id:
            await update.message.reply_text("❌ Você não pode excluir este item. Ele pertence a outro usuário.")
            return

        data['appointments'] = [a for a in data['appointments'] if a['id'] != apt_id]
        save_appointments(data)
        await update.message.reply_text(f"✅ Item {apt_id} excluído com sucesso!")

    except ValueError:
        await update.message.reply_text("ID inválido. Por favor, forneça um número.")
    except Exception as exc:
        await update.message.reply_text(f"Erro ao excluir item: {exc}")


# ---------------------------------------------------------------------------
# /test
# ---------------------------------------------------------------------------

async def test_notification(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_authorization(update, context):
        return

    user_id   = update.effective_user.id
    user_name = update.effective_user.first_name or "Usuário"
    print(f"🧪 /test command received from user {user_id} ({user_name})")

    try:
        await update.message.reply_text(f"""
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
""")
        print(f"✅ Test notification sent successfully to user {user_id}")

    except Exception as exc:
        print(f"❌ ERROR: Failed to send test notification to user {user_id}: {exc}")
        try:
            await update.message.reply_text("❌ Erro ao enviar notificação de teste")
        except Exception:
            pass
