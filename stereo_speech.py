import win32com.client
import math
import threading
import time
import tempfile
import os
import io
import accessible_output3.outputs.auto
from settings import get_setting

try:
    from pydub import AudioSegment
    from pydub.playback import play
    PYDUB_AVAILABLE = True
except ImportError:
    print("Warning: pydub not available, stereo effects will be limited")
    PYDUB_AVAILABLE = False

class StereoSpeech:
    """
    Klasa do stereo pozycjonowania mowy SAPI5 z kontrolą wysokości głosu.
    
    Pozwala na pozycjonowanie głosu w przestrzeni stereo używając pydub do przetwarzania audio.
    Używa dedykowanego kanału pygame dla TTS, nie blokując dźwięków UI.
    """
    
    def __init__(self):
        self.sapi = None
        self.current_voice = None
        self.default_rate = 0
        self.default_volume = 100
        self.default_pitch = 0
        self.is_speaking = False
        self.speech_lock = threading.Lock()
        self.current_tts_channel = None  # Aktualny kanał TTS
        
        # Fallback dla przypadków gdy SAPI5 nie jest dostępne
        self.fallback_speaker = accessible_output3.outputs.auto.Auto()
        
        try:
            self._init_sapi()
        except Exception as e:
            print(f"Błąd inicjalizacji SAPI5: {e}")
            self.sapi = None
    
    def __del__(self):
        """Cleanup COM objects on destruction safely."""
        try:
            # Stop any ongoing speech first
            if hasattr(self, 'is_speaking') and self.is_speaking:
                self.stop()
            
            # Clean up COM objects safely
            if hasattr(self, 'sapi') and self.sapi is not None:
                try:
                    # Reset audio output to default before cleanup
                    if hasattr(self.sapi, 'AudioOutputStream'):
                        self.sapi.AudioOutputStream = None
                except (AttributeError, OSError):
                    pass
                
                # Release COM object
                try:
                    del self.sapi
                except (AttributeError, OSError):
                    pass
                finally:
                    self.sapi = None
            
            # Don't call CoUninitialize in destructor - can cause crashes
            # COM will cleanup automatically when process ends
        except Exception:
            pass  # Prevent any exceptions during cleanup
    
    def _init_sapi(self):
        """Inicjalizuje SAPI5 voice object safely."""
        try:
            import pythoncom
            
            # Initialize COM with apartment threading
            try:
                pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            except pythoncom.com_error as e:
                # COM might already be initialized
                if e.hresult != -2147417850:  # RPC_E_CHANGED_MODE
                    raise
            
            # Create SAPI voice object
            self.sapi = win32com.client.Dispatch("SAPI.SpVoice")
            if self.sapi:
                # Save default settings safely
                try:
                    self.default_rate = self.sapi.Rate
                    self.default_volume = self.sapi.Volume
                    self.current_voice = self.sapi.Voice
                except (AttributeError, OSError) as e:
                    print(f"Warning: Could not read SAPI default settings: {e}")
                    self.default_rate = 0
                    self.default_volume = 100
                    
        except Exception as e:
            print(f"Błąd inicjalizacji SAPI5: {e}")
            self.sapi = None
            # Don't call CoUninitialize on errors - can cause crashes
    
    def is_stereo_enabled(self):
        """Sprawdza czy stereo speech jest włączone w ustawieniach."""
        return get_setting('stereo_speech', 'False', 'invisible_interface').lower() in ['true', '1']
    
    
    def _generate_tts_to_file(self, text, pitch_offset=0):
        """
        Generuje TTS do pliku tymczasowego używając SAPI5.
        Thread-safe version with proper COM handling.
        
        Args:
            text (str): Tekst do wypowiedzenia
            pitch_offset (int): Przesunięcie wysokości głosu -10 do +10
            
        Returns:
            str: Ścieżka do pliku tymczasowego lub None w przypadku błędu
        """
        if not self.sapi:
            return None
            
        try:
            # Inicjalizuj COM dla tego wątku z retry logic
            import pythoncom
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
                try:
                    # Use apartment threading to avoid COM issues
                    pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
                    break
                except pythoncom.com_error as e:
                    # Handle already initialized COM
                    if e.hresult == -2147417850:  # RPC_E_CHANGED_MODE
                        break  # COM already initialized with different threading model
                    retry_count += 1
                    if retry_count >= max_retries:
                        print(f"Failed to initialize COM after {max_retries} retries: {e}")
                        return None
                    time.sleep(0.05)
                except Exception as e:
                    retry_count += 1
                    if retry_count >= max_retries:
                        print(f"Failed to initialize COM after {max_retries} retries: {e}")
                        return None
                    time.sleep(0.05)
            # Utwórz plik tymczasowy z pełną ścieżką
            temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            temp_path = os.path.abspath(temp_file.name)
            temp_file.close()
            
            # Przygotuj tekst z kontrolą wysokości głosu używając SSML
            if pitch_offset != 0:
                # SAPI5 obsługuje SSML markup dla kontroli głosu
                pitch_value = max(-10, min(10, pitch_offset))
                # Użyj prosty SSML dla kontroli pitch
                ssml_text = f'<pitch absmiddle="{pitch_value}">{text}</pitch>'
            else:
                ssml_text = text
            
            # Utwórz nowy SpFileStream object
            file_stream = win32com.client.Dispatch("SAPI.SpFileStream")
            
            # Ustaw format audio (16-bit, 22kHz, mono - stabilny format)
            # 22 = SAFT22kHz16BitMono
            try:
                file_stream.Format.Type = 22
            except:
                pass  # Jeśli nie można ustawić formatu, użyj domyślnego
            
            # Otwórz plik do zapisu (3 = SSFMCreateForWrite)
            file_stream.Open(temp_path, 3)
            
            # Zapisz oryginalny output stream
            original_output = self.sapi.AudioOutputStream
            
            # Ustaw output na plik
            self.sapi.AudioOutputStream = file_stream
            
            # Wypowiedz tekst safely
            try:
                self.sapi.Speak(ssml_text, 0)  # 0 = synchronous
                
                # Poczekaj aż skończy z timeout
                if not self.sapi.WaitUntilDone(10000):  # Max 10 sekund
                    print("Warning: SAPI TTS timeout")
                    
            except Exception as e:
                print(f"Error during SAPI speak: {e}")
            finally:
                # Always clean up properly
                try:
                    file_stream.Close()
                except Exception as e:
                    print(f"Error closing file stream: {e}")
                try:
                    self.sapi.AudioOutputStream = original_output
                except Exception as e:
                    print(f"Error restoring audio output: {e}")
            
            # Sprawdź czy plik został utworzony i ma zawartość
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 100:  # Minimum 100 bajtów
                print(f"TTS plik utworzony: {temp_path}, rozmiar: {os.path.getsize(temp_path)} bajtów")
                return temp_path
            else:
                print(f"Plik TTS nie został utworzony prawidłowo: {temp_path}")
                return None
            
        except Exception as e:
            print(f"Błąd podczas generowania TTS do pliku: {e}")
            import traceback
            traceback.print_exc()
            # Usuń plik tymczasowy w przypadku błędu
            if 'temp_path' in locals() and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
            return None

    def speak(self, text, position=0.0, pitch_offset=0, use_fallback=True):
        """
        Wypowiada tekst z pozycjonowaniem stereo i kontrolą wysokości.
        
        Args:
            text (str): Tekst do wypowiedzenia
            position (float): Pozycja stereo od -1.0 (lewo) do 1.0 (prawo)
            pitch_offset (int): Przesunięcie wysokości głosu -10 do +10
            use_fallback (bool): Czy użyć fallback jeśli SAPI5 nie działa
        """
        if not text:
            return
        
        # Add timeout protection for the lock to prevent hangs
        lock_acquired = False
        try:
            # Try to acquire lock with timeout
            lock_acquired = self.speech_lock.acquire(timeout=2.0)
            if not lock_acquired:
                print("Warning: Could not acquire speech lock, using fallback")
                if use_fallback:
                    self.fallback_speaker.speak(text)
                return
            
            # Zatrzymaj poprzednią mowę przed rozpoczęciem nowej
            self.stop()
            
            self.is_speaking = True
            
            try:
                # Sprawdź czy stereo speech jest włączone
                if not self.is_stereo_enabled():
                    # Jeśli stereo jest wyłączone, użyj standardowego TTS
                    if use_fallback:
                        self.fallback_speaker.speak(text)
                    return
                
                if not self.sapi or not PYDUB_AVAILABLE:
                    # Brak SAPI5 lub pydub, użyj fallback
                    if use_fallback:
                        self.fallback_speaker.speak(text)
                    return
                
                # Generuj TTS do pliku tymczasowego z kontrolą wysokości
                temp_file = self._generate_tts_to_file(text, pitch_offset)
                if not temp_file:
                    # Błąd generowania, użyj fallback
                    if use_fallback:
                        self.fallback_speaker.speak(text)
                    return
                
                try:
                    # Wczytaj audio z pliku
                    audio = AudioSegment.from_wav(temp_file)
                    
                    # Zastosuj pozycjonowanie stereo używając pydub
                    if position != 0.0:
                        # Pozycja od -1.0 (lewo) do 1.0 (prawo)
                        # pydub.pan() przyjmuje wartości od -1.0 do 1.0
                        panned_audio = audio.pan(position)
                    else:
                        panned_audio = audio
                    
                    # Zapisz przetworzone audio do nowego pliku tymczasowego
                    processed_temp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                    processed_path = processed_temp.name
                    processed_temp.close()
                    
                    # Eksportuj przetworzone audio
                    panned_audio.export(processed_path, format="wav")
                    
                    # Użyj drugi kanał pygame dla TTS (responsywny)
                    import pygame
                    
                    # Sprawdź czy główny mixer jest zainicjalizowany
                    if not pygame.mixer.get_init():
                        pygame.mixer.pre_init(frequency=22050, size=-16, channels=2, buffer=1024)
                        pygame.mixer.init()
                    
                    # Znajdź wolny kanał dla TTS (nie channel 0 używany przez UI)
                    tts_channel = None
                    for channel_id in range(1, pygame.mixer.get_num_channels()):  # Pomiń kanał 0
                        channel = pygame.mixer.Channel(channel_id)
                        if not channel.get_busy():
                            tts_channel = channel
                            break
                    
                    if not tts_channel:
                        # Jeśli wszystkie kanały zajęte, zwiększ liczbę kanałów
                        pygame.mixer.set_num_channels(pygame.mixer.get_num_channels() + 1)
                        tts_channel = pygame.mixer.Channel(pygame.mixer.get_num_channels() - 1)
                    
                    # Odtwórz TTS w dedykowanym kanale
                    sound = pygame.mixer.Sound(processed_path)
                    tts_channel.play(sound)
                    
                    # Zapamiętaj aktualny kanał TTS
                    self.current_tts_channel = tts_channel
                    
                    # Poczekaj na zakończenie TTS (responsywnie)
                    while tts_channel.get_busy():
                        time.sleep(0.05)  # Krótkie sprawdzanie co 50ms
                    
                    # Wyczyść kanał po zakończeniu
                    self.current_tts_channel = None
                    
                    # Usuń przetworzone pliki
                    try:
                        os.unlink(processed_path)
                    except:
                        pass
                    
                finally:
                    # Usuń plik tymczasowy
                    try:
                        os.unlink(temp_file)
                    except:
                        pass
                
            except Exception as e:
                print(f"Błąd podczas mówienia stereo: {e}")
                # Fallback do standardowego TTS
                if use_fallback:
                    self.fallback_speaker.speak(text)
            finally:
                self.is_speaking = False
        finally:
            # Always release the lock if it was acquired
            if lock_acquired:
                self.speech_lock.release()
    
    def speak_async(self, text, position=0.0, pitch_offset=0, use_fallback=True):
        """
        Wypowiada tekst asynchronicznie z pozycjonowaniem stereo.
        
        Args:
            text (str): Tekst do wypowiedzenia
            position (float): Pozycja stereo od -1.0 (lewo) do 1.0 (prawo)
            pitch_offset (int): Przesunięcie wysokości głosu -10 do +10
            use_fallback (bool): Czy użyć fallback jeśli SAPI5 nie działa
        """
        def speak_thread():
            # Wywołaj synchroniczną metodę speak w osobnym wątku
            self.speak(text, position, pitch_offset, use_fallback)
        
        thread = threading.Thread(target=speak_thread)
        thread.daemon = True
        thread.start()
    
    def stop(self):
        """Zatrzymuje aktualną mowę TTS bezpiecznie."""
        try:
            # Set flag to stop speech
            self.is_speaking = False
            
            # Stop current TTS channel (not entire mixer!)
            if hasattr(self, 'current_tts_channel') and self.current_tts_channel:
                try:
                    if self.current_tts_channel.get_busy():
                        self.current_tts_channel.stop()
                except (AttributeError, Exception) as e:
                    print(f"Error stopping TTS channel: {e}")
                finally:
                    self.current_tts_channel = None
            
            # Stop SAPI if it's speaking
            if hasattr(self, 'sapi') and self.sapi:
                try:
                    # SAPI doesn't have a direct stop method, but we can speak empty text
                    self.sapi.Speak("", 1)  # 1 = asynchronous, empty string stops current speech
                except (AttributeError, OSError) as e:
                    print(f"Error stopping SAPI speech: {e}")
                
        except Exception as e:
            print(f"Błąd podczas zatrzymywania mowy TTS: {e}")
    
    def set_rate(self, rate):
        """
        Ustawia szybkość mówienia.
        
        Args:
            rate (int): Szybkość od -10 do +10
        """
        try:
            if self.sapi:
                self.sapi.Rate = max(-10, min(10, rate))
        except Exception as e:
            print(f"Błąd ustawiania szybkości mowy: {e}")
    
    def set_volume(self, volume):
        """
        Ustawia głośność mowy.
        
        Args:
            volume (int): Głośność od 0 do 100
        """
        try:
            if self.sapi:
                self.sapi.Volume = max(0, min(100, volume))
                self.default_volume = self.sapi.Volume
        except Exception as e:
            print(f"Błąd ustawiania głośności mowy: {e}")
    
    def get_available_voices(self):
        """
        Zwraca listę dostępnych głosów SAPI5.
        
        Returns:
            list: Lista nazw dostępnych głosów
        """
        try:
            if not self.sapi:
                return []
            
            voices = []
            voice_tokens = self.sapi.GetVoices()
            
            for i in range(voice_tokens.Count):
                voice = voice_tokens.Item(i)
                voices.append(voice.GetDescription())
            
            return voices
        except Exception as e:
            print(f"Błąd pobierania listy głosów: {e}")
            return []
    
    def set_voice(self, voice_index):
        """
        Ustawia głos SAPI5.
        
        Args:
            voice_index (int): Indeks głosu z listy dostępnych głosów
        """
        try:
            if not self.sapi:
                return
            
            voice_tokens = self.sapi.GetVoices()
            if 0 <= voice_index < voice_tokens.Count:
                self.sapi.Voice = voice_tokens.Item(voice_index)
                self.current_voice = self.sapi.Voice
        except Exception as e:
            print(f"Błąd ustawiania głosu: {e}")


# Globalna instancja dla łatwego użycia
_stereo_speech_instance = None

def get_stereo_speech():
    """Zwraca globalną instancję StereoSpeech bezpiecznie."""
    global _stereo_speech_instance
    try:
        if _stereo_speech_instance is None:
            _stereo_speech_instance = StereoSpeech()
        return _stereo_speech_instance
    except Exception as e:
        print(f"Error getting stereo speech instance: {e}")
        return None

def speak_stereo(text, position=0.0, pitch_offset=0, async_mode=False):
    """
    Funkcja pomocnicza do szybkiego użycia stereo speech.
    
    Args:
        text (str): Tekst do wypowiedzenia
        position (float): Pozycja stereo od -1.0 (lewo) do 1.0 (prawo)
        pitch_offset (int): Przesunięcie wysokości głosu -10 do +10
        async_mode (bool): Czy mówić asynchronicznie
    """
    stereo_speech = get_stereo_speech()
    
    if async_mode:
        stereo_speech.speak_async(text, position, pitch_offset)
    else:
        stereo_speech.speak(text, position, pitch_offset)

def stop_stereo_speech():
    """Zatrzymuje aktualną stereo mowę."""
    stereo_speech = get_stereo_speech()
    stereo_speech.stop()


# Przykłady użycia
if __name__ == "__main__":
    # Test stereo speech
    stereo = StereoSpeech()
    
    print("Test stereo speech:")
    print("Lewy kanał...")
    stereo.speak("To jest test lewego kanału", position=-1.0, pitch_offset=-3)
    
    time.sleep(1)
    
    print("Środek...")
    stereo.speak("To jest test środka", position=0.0, pitch_offset=0)
    
    time.sleep(1)
    
    print("Prawy kanał...")
    stereo.speak("To jest test prawego kanału", position=1.0, pitch_offset=3)
    
    print("Test zakończony.")