import os
import threading
import platform

class BG5Reader:
    def __init__(self):
        self.speech_thread = None
        self.lock = threading.Lock()

    def interrupt_and_speak(self, text):
        with self.lock:
            if self.speech_thread and self.speech_thread.is_alive():
                self.speech_thread.join(timeout=0.1)
            self.speech_thread = threading.Thread(target=self._speak, args=(text,))
            self.speech_thread.start()

    def _speak(self, text):
        if platform.system() == 'Windows':
            import win32com.client
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Speak(text)
        elif platform.system() == 'Darwin':  # macOS
            os.system(f"say {text}")
        else:  # Assume Linux
            os.system(f"spd-say {text}")

bg5reader = BG5Reader()

def speak(text):
    bg5reader.interrupt_and_speak(text)
