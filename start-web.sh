#!/bin/bash

# Simple start script for the web server
echo "Starting Doctor Appointment Calendar..."
echo "Opening on http://localhost:8000/web"
echo "Press Ctrl+C to stop"
echo ""

# Try to start with Python from the project root
if command -v python3 &> /dev/null; then
    python3 -m http.server 8000
elif command -v python &> /dev/null; then
    python -m http.server 8000
else
    echo "Python not found. Please install Python or use another web server."
    exit 1
fi
