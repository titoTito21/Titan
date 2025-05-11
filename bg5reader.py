import os
import threading
import platform

class BG5Reader:
    def __init__(self):
        self.speech_thread = None
        self.lock = threading.Lock()

    def interrupt_and_speak(self, text):
        with self.lock:
            # If a speech thread is running, we wait briefly for it to finish
            if self.speech_thread and self.speech_thread.is_alive():
                # You can kill or stop speech here if needed, depending on the engine
                self.speech_thread.join(timeout=0.1)
            # Start new speech thread
            self.speech_thread = threading.Thread(target=self._speak, args=(text,))
            self.speech_thread.start()

    def _speak(self, text):
        system = platform.system()
        if system == 'Windows':
            try:
                import win32com.client
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                speaker.Speak(text)
            except ImportError:
                print("win32com.client is not available. Cannot use SAPI voice.")
        elif system == 'Darwin':  # macOS
            os.system(f'say "{text}"')
        else:  # Assume Linux
            os.system(f'spd-say "{text}"')

# Singleton reader instance
bg5reader = BG5Reader()

def speak(text):
    bg5reader.interrupt_and_speak(text)
