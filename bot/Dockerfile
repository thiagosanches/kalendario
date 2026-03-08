# Use Python slim image for ARM architecture (Raspberry Pi)
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot files
COPY bot.py .

# Create temp directory for audio files
RUN mkdir -p temp_audio

# Set environment variables (will be overridden by docker-compose)
ENV TELEGRAM_BOT_TOKEN=""
ENV OPENAI_API_KEY=""

# Run the bot
CMD ["python", "-u", "bot.py"]
