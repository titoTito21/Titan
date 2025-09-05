#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Titan IM Messenger Client
Standalone launcher for the messenger client similar to Telegram/TCE
"""

import sys
import os

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import and run messenger GUI
from messenger_gui import run_messenger_gui

if __name__ == '__main__':
    print("Launching Titan IM Messenger Client...")
    print("Interface similar to Telegram with chat list and messaging functionality")
    run_messenger_gui()