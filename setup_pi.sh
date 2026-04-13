#!/bin/bash
# setup_pi.sh
# Automates dependency installation for Smart Pantry Kitchen Hub on Raspberry Pi OS.

set -e

echo "🥦 Starting Smart Pantry Hub Setup..."

# 1. Update system
echo "Updating system packages..."
sudo apt-get update

# 2. Install system dependencies for Kivy and Sense HAT
echo "Installing system dependencies..."
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    python3-dev \
    libsdl2-dev \
    libsdl2-image-dev \
    libsdl2-mixer-dev \
    libsdl2-ttf-dev \
    pkg-config \
    libgl1-mesa-dev \
    libgles2-mesa-dev \
    libmtdev-dev \
    xclip \
    xsel \
    libjpeg-dev \
    sense-hat \
    evtest

# 3. Create Virtual Environment
echo "Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 4. Install Python requirements
echo "Installing Python packages..."
pip install --upgrade pip
pip install -r hub/requirements.txt

# 5. Setup Environment
if [ ! -f .env ]; then
    echo "Creating .env from example..."
    cp .env.example .env
    echo "⚠️  IMPORTANT: Please edit .env and add your Firebase credentials!"
fi

echo "✅ Setup complete! To run the hub:"
echo "   source venv/bin/activate"
echo "   python -m hub.main"
