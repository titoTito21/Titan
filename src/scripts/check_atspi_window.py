"""Read the focused window the way Orca would, through AT-SPI.

Uses Titan's own Linux/macOS desktop tools (``src/ai/desktop_tools_posix``),
so what it prints is exactly what the AI agent, a macro or a client sees
on this platform: the window in front, the open windows, and the focused
window's controls with their roles. Run it against a running Titan to see
whether the screen reader has anything to read:

    python3 src/scripts/check_atspi_window.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault('DISPLAY', ':0')

from src.ai import desktop_tools_posix as desktop  # noqa: E402

print("--- list_windows:\n" + desktop.list_windows())
print("--- get_foreground_window:\n" + desktop.get_foreground_window())
print("--- read_focused_window:\n" + desktop.read_focused_window())
