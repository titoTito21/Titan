# -*- coding: utf-8 -*-
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sound import play_sound
import time

print("=== QUICK SOUND TEST ===")

sounds = [
    ('titannet/welcome to IM.ogg', 'Welcome'),
    ('titannet/message_send.ogg', 'Send message'),
    ('titannet/new_message.ogg', 'New message'),
    ('titannet/typing.ogg', 'Typing'),
    ('titannet/bye.ogg', 'Goodbye')
]

for sound_file, desc in sounds:
    print(f"\nTesting: {desc} ({sound_file})")
    try:
        play_sound(sound_file)
        print("  OK - Sound played")
        time.sleep(1)
    except Exception as e:
        print(f"  ERROR: {e}")

print("\nDone! If sounds played, the audio system works.")
print("Problem might be in Messenger WebView JavaScript detection.")