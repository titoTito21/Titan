#!/bin/bash
# Titan-Net Server Startup Script for Linux/Mac

echo "================================================"
echo "Titan-Net Server"
echo "================================================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed"
    echo "Please install Python 3.8 or higher"
    exit 1
fi

# Check Python version
python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "Python version: $python_version"

# Check if dependencies are installed
echo "Checking dependencies..."
if ! python3 -c "import websockets" &> /dev/null; then
    echo "Installing dependencies..."
    pip3 install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to install dependencies"
        exit 1
    fi
fi

# Create necessary directories
mkdir -p database
mkdir -p logs
mkdir -p uploads

echo ""
echo "Starting Titan-Net Server..."
echo ""
echo "WebSocket Server: ws://0.0.0.0:8001"
echo "HTTP API Server: http://0.0.0.0:8000"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

# Start the server
python3 main.py
