"""Voice message handler: Whisper transcription + GPT-4o-mini intent parsing."""

import json
import re
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from config import TEMP_DIR, openai_client
from middleware import check_authorization, rate_limit_check
from recurrence import FREQ_LABELS
from storage import load_appointments, save_appointments

_WEEKDAY_PT = [
    'segunda-feira', 'terça-feira', 'quarta-feira',
    'quinta-feira',  'sexta-feira', 'sábado',       'domingo',
]


def _build_system_prompt(current_date: str, current_weekday: str, current_year: int, current_month: int) -> str:
    return f"""Você é um assistente que extrai informações de eventos e lembretes de mensagens de voz.

CONTEXTO TEMPORAL:
- Data atual: {current_date} ({current_weekday})
- Ano atual: {current_year}
- Mês atual: {current_month}
- Se o usuário não mencionar o ano, assuma o ano atual ({current_year})
- Se o usuário mencionar apenas dia e mês (ex: "dia 15 de março"), use o ano atual
- Se o usuário mencionar "amanhã", "próxima semana", etc., calcule a data baseada em {current_date}

Extraia as seguintes informações:
- data (formato AAAA-MM-DD)
- hora (formato HH:MM, aceite também "14h", "14h30", "2 da tarde", "três e meia da tarde" = 15:30)
- tipo (appointment para eventos/compromissos, reminder para lembretes)
- doctor: título curto do evento — SEMPRE preencha com o assunto principal (ex: "Reunião com Donald Trump", "Academia", "Consulta médica"). NUNCA deixe vazio se houver um assunto na mensagem.
- description: descrição completa do compromisso com todos os detalhes relevantes mencionados. Se não houver detalhes extras além do título, repita o título aqui.
- local/observação

EXEMPLOS:
- "reunião com o cliente dia 15 de março às 14h" → doctor: "Reunião com o cliente", description: "Reunião com o cliente", use ano {current_year}
- "reunião semanal com Donald Trump às três e meia da tarde, começando na quinta-feira" → doctor: "Reunião com Donald Trump", description: "Reunião semanal com Donald Trump", time: "15:30", próxima quinta como date, recurrence: "weekly"
- "reunião com o Menine, todos os dias, por uma semana, às 13h30" → doctor: "Reunião com o Menine", recurrence: "daily", recurrence_end: 6 dias após date (uma semana = 7 ocorrências, end = start + 6 dias)
- "lembrete para ligar para o banco amanhã às 8h" → doctor: "Ligar para o banco", description: "Ligar para o banco", calcule data de amanhã
- "academia na próxima terça às 10h30" → doctor: "Academia", description: "Academia", calcule a próxima terça

EVENTOS RECORRENTES:
Se o usuário mencionar recorrência, inclua o campo "recurrence":
- "todo dia" / "todos os dias" / "diariamente" → "daily"
- "toda semana" / "semanalmente" / "toda <dia da semana>" → "weekly"
- "quinzenalmente" / "a cada duas semanas" → "biweekly"
- "todo mês" / "mensalmente" / "todo dia X" → "monthly"
- "todo ano" / "anualmente" → "yearly"
Se não houver recorrência, omita o campo "recurrence".

DATA DE TÉRMINO DA RECORRÊNCIA:
REGRA CRÍTICA: só inclua "recurrence_end" se o usuário mencionar EXPLICITAMENTE uma duração ou data de fim. Se não mencionou, NUNCA inclua "recurrence_end".
- "por uma semana" → recurrence_end = date + 6 dias
- "por 10 dias" → recurrence_end = date + 9 dias
- "por um mês" → recurrence_end = date + 29 dias
- "até dia 30 de maio" → recurrence_end = "2026-05-30"
- "por 3 semanas" → recurrence_end = date + 20 dias
- "todo dia" / "todos os dias" SEM duração → NÃO inclua "recurrence_end"
- "toda semana" SEM duração → NÃO inclua "recurrence_end"
Se não houver data de término explícita na fala, OMITA "recurrence_end" completamente.

QUANDO HÁ RECORRÊNCIA E DIA DA SEMANA:
- "toda quinta-feira" com data atual {current_date} → calcule a próxima quinta-feira como "date"
- "toda terça às 10h" → próxima terça como "date"

Retorne APENAS um JSON no formato:
{{"date": "AAAA-MM-DD", "time": "HH:MM", "type": "appointment", "doctor": "Título do evento", "description": "texto", "location": "local", "recurrence": "daily", "recurrence_end": "AAAA-MM-DD"}}

Se não conseguir extrair a data/hora, use valores vazios."""


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Transcribe a voice note and create an appointment/reminder from it."""
    if not await check_authorization(update, context):
        return
    if not await rate_limit_check(update, context):
        return

    if not openai_client:
        await update.message.reply_text(
            "❌ Mensagens de voz não estão disponíveis. "
            "O administrador precisa configurar OPENAI_API_KEY."
        )
        return

    audio_path: Path | None = None
    try:
        await update.message.reply_text("🎤 Processando sua mensagem de voz...")

        voice = update.message.voice
        if voice.file_size and voice.file_size > 10 * 1024 * 1024:
            await update.message.reply_text("❌ Arquivo de áudio muito grande. Máximo: 10 MB.")
            return

        # Sanitise file_id to prevent path traversal
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '', voice.file_id[:50]) \
                    or f"voice_{int(datetime.now().timestamp())}"
        audio_path = TEMP_DIR / f"{safe_name}.ogg"
        if not str(audio_path.resolve()).startswith(str(TEMP_DIR.resolve())):
            raise ValueError("Invalid file path detected")

        tg_file = await context.bot.get_file(voice.file_id)
        await tg_file.download_to_drive(str(audio_path))

        # --- Whisper transcription ---
        with audio_path.open('rb') as af:
            transcription = openai_client.audio.transcriptions.create(
                model="whisper-1", file=af, language="pt"
            )
        transcribed_text = transcription.text
        await update.message.reply_text(f"📝 Transcrição: {transcribed_text}")

        # --- GPT intent parsing ---
        today           = datetime.now()
        current_date    = today.strftime("%Y-%m-%d")
        current_weekday = _WEEKDAY_PT[today.weekday()]

        completion = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _build_system_prompt(
                    current_date, current_weekday, today.year, today.month
                )},
                {"role": "user", "content": (
                    f"Hoje é {current_date} ({current_weekday}). "
                    f"Mensagem do usuário: {transcribed_text}"
                )},
            ],
            response_format={"type": "json_object"},
        )
        parsed = json.loads(completion.choices[0].message.content)

        if not parsed.get('date') or not parsed.get('time'):
            await update.message.reply_text(
                "❌ Não consegui identificar a data e hora.\n\n"
                "Exemplo: 'Reunião com João no dia 15 de março às 14h30'"
            )
            return

        # --- Persist ---
        data   = load_appointments()
        apt_id = max((a.get('id', 0) for a in data['appointments']), default=0) + 1

        recurrence = (parsed.get('recurrence') or '').lower() or None
        if recurrence and recurrence not in FREQ_LABELS:
            recurrence = None

        new_entry: dict = {
            "id":          apt_id,
            "user_id":     update.effective_user.id,
            "date":        parsed.get('date', ''),
            "time":        parsed.get('time', ''),
            "doctor":      parsed.get('doctor', ''),
            "description": parsed.get('description', transcribed_text),
            "location":    parsed.get('location', ''),
            "type":        parsed.get('type', 'appointment'),
            "created_at":  datetime.now().isoformat(),
        }
        if recurrence:
            new_entry['recurrence'] = recurrence
            rec_end = (parsed.get('recurrence_end') or '').strip() or None
            if rec_end:
                new_entry['recurrence_end'] = rec_end

        data['appointments'].append(new_entry)
        save_appointments(data)

        # --- Confirmation ---
        kind  = "📅 Evento" if new_entry['type'] == 'appointment' else "⏰ Lembrete"
        lines = [f"✅ {kind} adicionado com sucesso!\n",
                 f"ID: {apt_id}",
                 f"Data: {new_entry['date']} às {new_entry['time']}"]
        if recurrence:
            end_label = (f" até {new_entry['recurrence_end']}"
                         if new_entry.get('recurrence_end') else " (sem data de término)")
            lines.append(f"🔁 Recorrência: {FREQ_LABELS[recurrence]}{end_label}")
            lines.append(f"Para excluir a série: /delrec {apt_id}")
        if new_entry['doctor']:
            lines.append(f"Título: {new_entry['doctor']}")
        lines.append(f"Descrição: {new_entry['description']}")
        if new_entry['location']:
            label = 'Local' if new_entry['type'] == 'appointment' else 'Observação'
            lines.append(f"{label}: {new_entry['location']}")

        await update.message.reply_text('\n'.join(lines))

    except Exception as exc:
        print(f"Voice processing error: {exc}")
        await update.message.reply_text(
            "❌ Erro ao processar mensagem de voz. "
            "Tente novamente ou use comandos de texto."
        )
    finally:
        if audio_path and audio_path.exists():
            try:
                audio_path.unlink()
            except Exception as exc:
                print(f"Failed to remove audio file {audio_path}: {exc}")
