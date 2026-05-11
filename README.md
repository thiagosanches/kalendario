# Kalendario

A complete **multi-user** system for managing doctor appointments with a Telegram bot for adding appointments and a static web application for displaying them on phones.

![alt text](image.png)

## 🌟 Key Features

✨ **Multi-User Support** - Each Telegram user has their own private appointments  
🔒 **User Whitelist** - Optional access control to restrict who can use the bot  
🔔 **Automatic Reminders** - Get notified 24h and 2h before each appointment  
🎤 **Voice Messages** - Add appointments by speaking (powered by OpenAI Whisper)  
� **Recurring Events** - Schedule weekly, biweekly, monthly, or yearly series  
📱 **Telegram Bot** - Manage appointments from anywhere  
🖥️ **Web Dashboard** - Beautiful calendar view optimized for tablets  
🔄 **Auto-Sync** - Bot and web share the same data instantly  

## Project Structure

```
kalendario/
├── bot/                      # Telegram bot
│   ├── bot.py               # Bot implementation
│   ├── test_recurring.py    # Unit tests (45 tests)
│   └── requirements.txt     # Python dependencies
├── web/                      # Web application
│   ├── index.html           # Main HTML
│   ├── app.js               # JavaScript logic
│   └── styles.css           # Styling
└── data/                     # JSON data storage
    └── appointments.json    # Appointments database
```

## Features

### Web Application
- 📅 Interactive calendar view with appointment indicators
- 🔁 Recurring events expanded and shown in all views
- 📋 Upcoming appointments list with details (6-month window)
- ⏰ Today's reminders section
- 📱 Responsive design optimized for tablets
- 🔄 Auto-refresh every 2 minutes with cache-busting
- 🎨 Color-coded by type: appointments (green), reminders (pink/red), recurring (amber/purple)

### Telegram Bot
- ➕ Add appointments and reminders via text commands
- 🔁 Add recurring appointments via `/addrec` or voice message
- 🎤 Add appointments via voice messages (OpenAI Whisper)
- 📝 Flexible date input (accepts dates without year)
- 📋 List your own appointments (filtered by user, recurring expanded)
- ❌ Delete appointments by ID; `/delrec` removes an entire recurring series
- 🔔 **Automatic reminder notifications** (24h and 2h before each occurrence)
- 👥 **Multi-user support** - each user has private appointments
- 🔒 **Optional whitelist** - restrict access to specific users
- 💾 Persistent JSON storage

## Setup Instructions

### 1. Telegram Bot Setup

1. Create a new bot with BotFather on Telegram:
   - Open Telegram and search for @BotFather
   - Send `/newbot` and follow the instructions
   - Save the bot token you receive

2. Install Python dependencies:
```bash
cd bot
pip install -r requirements.txt
```

3. Set your bot token:
```bash
export TELEGRAM_BOT_TOKEN="your_token_here"
```

4. Run the bot:
```bash
python bot.py
```

### 2. Web Application Setup

Start a local web server in the `web` directory:

```bash
# Python
cd web && python -m http.server 8000

# Node.js
cd web && npx http-server -p 8000
```

Open your browser or tablet to `http://localhost:8000`.  
On the same network, replace `localhost` with your machine's IP address.

### 3. Running with Docker

```bash
docker-compose up
```

### 4. Running Tests

```bash
cd bot
python3 -m pytest test_recurring.py -v
```

## Using the Telegram Bot

### Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/add DATE TIME \| DOCTOR \| DESCRIPTION \| LOCATION` | Add a one-time appointment |
| `/addrec DATE TIME \| FREQ \| DOCTOR \| DESCRIPTION \| LOCATION` | Add a recurring appointment |
| `/list` | List your upcoming appointments |
| `/delete ID` | Delete a one-time appointment |
| `/delrec ID` | Delete an entire recurring series |

**Frequency values for `/addrec`:** `semanal`, `quinzenal`, `mensal`, `anual`  
(also accepted in English: `weekly`, `biweekly`, `monthly`, `yearly`)

### Example Usage

```
# One-time appointment
/add 2026-06-10 09:00 | Dr. Sarah Johnson | Annual Physical | Room 101

# Weekly recurring appointment
/addrec 2026-06-01 08:00 | semanal | Dr. Chen | Fisioterapia | Clínica Norte

# List all (recurring series are expanded to show upcoming occurrences)
/list

# Remove the recurring series with ID 3
/delrec 3
```

**Voice messages** are also supported — just send a voice note describing the appointment (including frequency words like "toda semana" or "todo mês" for recurring events).

## JSON Data Format

Appointments are stored in `data/appointments.json`:

```json
{
  "appointments": [
    {
      "id": 1,
      "date": "2026-06-10",
      "time": "09:00",
      "doctor": "Dr. Sarah Johnson",
      "description": "Annual Physical Checkup",
      "location": "Room 101",
      "type": "appointment",
      "created_at": "2026-05-11T10:00:00"
    },
    {
      "id": 2,
      "date": "2026-06-01",
      "time": "08:00",
      "doctor": "Dr. Chen",
      "description": "Fisioterapia",
      "location": "Clínica Norte",
      "recurrence": "weekly",
      "type": "appointment",
      "created_at": "2026-05-11T10:05:00"
    }
  ]
}
```

Recurring entries store a single rule (one JSON object per series). The bot and web frontend both expand the rule into concrete occurrences on the fly. Reminders are tracked per-occurrence so no occurrence is notified twice.

## License

MIT License - Feel free to use and modify this project for your needs!
