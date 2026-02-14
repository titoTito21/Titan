# -*- coding: utf-8 -*-
import wx
import threading
import time
import platform
import psutil

if platform.system() == "Windows":
    import win32gui
    import win32process
    import win32api
    import win32con

# Import play_sound lazily to avoid initialization order issues
play_sound = None

# Lista procesów systemowych
SYSTEM_PROCESSES = {
    "explorer.exe",
    "taskmgr.exe",
    "cmd.exe",
    "ms-settings.exe",
    "services.exe",
    "svchost.exe",
    "winlogon.exe",
    "lsass.exe",
}


class SystemAudioFeedback(threading.Thread):
    """
    Wątek monitorujący procesy i aktywne okno, bez globalnego hooka klawiatury.

    1) Procesy z oknem:
       - Aplikacja systemowa => sysprocess_open/close
       - Aplikacja użytkownika => uiopen/uiclose
    2) Okna dialogowe/menu:
       - Otwarcie => statusbar.ogg
       - Zamknięcie => applist.ogg
    3) Zwykły skok kursora (zmiana zwykłego okna) => focus.ogg
    """

    def __init__(self):
        super().__init__()
        self.daemon = True
        self._stop_event = threading.Event()

        # Słownik informacji o monitorowanych procesach
        # { pid: {"exe_name": str, "is_system": bool, "had_window": bool } }
        self.process_info = {}
        self.prev_pids = set()

        # Poprzednio aktywne okno
        self.prev_window = None

    def run(self):
        global play_sound

        if platform.system() != "Windows":
            print("SystemAudioFeedback działa tylko na Windows.")
            return

        # Import play_sound here to ensure sound system is initialized first
        try:
            from .sound import play_sound as _play_sound
            play_sound = _play_sound
        except Exception as e:
            print(f"Failed to import play_sound in tsounds: {e}")
            return

        # Inicjalizacja stanu procesów
        self.prev_pids = self._get_current_pids()

        while not self._stop_event.is_set():
            try:
                # 1. Monitoruj procesy
                self._monitor_processes()
                # 2. Monitoruj okna procesów
                self._monitor_windows()
                # 3. Monitoruj aktywne okno (skok kursora, dialogi, itp.)
                self._monitor_active_window()
            except Exception as e:
                print(f"Error in SystemAudioFeedback monitoring loop: {e}")
                # Don't crash the thread, just continue

            time.sleep(0.1)

    def stop(self):
        """Zatrzymuje wątek."""
        self._stop_event.set()

    # --------------------------------------------------------------------------
    #                           MONITOROWANIE PROCESÓW
    # --------------------------------------------------------------------------
    def _monitor_processes(self):
        try:
            current_pids = self._get_current_pids()
            new_pids = current_pids - self.prev_pids
            closed_pids = self.prev_pids - current_pids

            for pid in new_pids:
                self._on_new_process(pid)
            for pid in closed_pids:
                self._on_closed_process(pid)

            self.prev_pids = current_pids
        except Exception as e:
            print(f"Error monitoring processes: {e}")

    def _get_current_pids(self):
        try:
            return {p.pid for p in psutil.process_iter(['pid'])}
        except Exception as e:
            print(f"Error getting process list: {e}")
            return set()

    def _on_new_process(self, pid):
        """Rejestrujemy nowy proces. Nie odtwarzamy jeszcze dźwięku,
        dopóki nie potwierdzimy, że proces ma okno."""
        try:
            proc = psutil.Process(pid)
            exe_name = (proc.name() or "").lower()
            is_sys = exe_name in SYSTEM_PROCESSES
            self.process_info[pid] = {
                "exe_name": exe_name,
                "is_system": is_sys,
                "had_window": False
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # Process already gone or inaccessible
            pass
        except Exception as e:
            print(f"Error monitoring new process {pid}: {e}")

    def _on_closed_process(self, pid):
        """Jeśli proces miał okno, odtwarzamy dźwięk zamknięcia."""
        global play_sound
        try:
            info = self.process_info.pop(pid, None)
            if info and info.get("had_window") and play_sound:
                try:
                    if info.get("is_system"):
                        play_sound("system/sysprocess_close.ogg")
                    else:
                        play_sound("ui/uiclose.ogg")
                except Exception as e:
                    print(f"Error playing sound: {e}")
        except Exception as e:
            print(f"Error handling closed process {pid}: {e}")

    # --------------------------------------------------------------------------
    #                      MONITOROWANIE OKIEN PROCESÓW
    # --------------------------------------------------------------------------
    def _monitor_windows(self):
        """
        Sprawdza, czy procesy z self.process_info mają top-level window.
        Jeśli tak i 'had_window' == False => odtwarzamy open.ogg (systemowe lub użytkownika).
        """
        global play_sound

        def enum_handler(hwnd, _):
            try:
                # Check if window still exists
                if not win32gui.IsWindow(hwnd):
                    return True

                if not win32gui.IsWindowVisible(hwnd):
                    return True  # pomiń ukryte okna

                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid in self.process_info:
                    info = self.process_info[pid]
                    if not info.get("had_window") and play_sound:
                        # Pierwsze okno = odtwarzamy dźwięk otwarcia
                        info["had_window"] = True
                        try:
                            if info.get("is_system"):
                                play_sound("system/sysprocess_open.ogg")
                            else:
                                play_sound("ui/uiopen.ogg")
                        except Exception as e:
                            print(f"Error playing open sound: {e}")
            except Exception as e:
                # Silently handle window enumeration errors
                pass

            return True

        try:
            win32gui.EnumWindows(enum_handler, None)
        except Exception as e:
            print(f"Error enumerating windows: {e}")

    # --------------------------------------------------------------------------
    #              MONITOROWANIE AKTYWNEGO OKNA (dialogi, menu, focus)
    # --------------------------------------------------------------------------
    def _monitor_active_window(self):
        global play_sound

        if not play_sound:
            return

        try:
            current_window = win32gui.GetForegroundWindow()

            # Ignore invalid window handles
            if not current_window or current_window == 0:
                return

            # Ignoruj okna Titan
            if self._is_titan_window(current_window):
                # Aktualizuj prev_window ale nie odtwarzaj dźwięków
                self.prev_window = current_window
                return

            if current_window != self.prev_window:
                # Zamknięcie poprzedniego okna dialog/menu?
                if self.prev_window and play_sound:
                    # Nie odtwarzaj dźwięku zamknięcia jeśli poprzednie okno było Titan
                    if not self._is_titan_window(self.prev_window):
                        try:
                            if self._is_menu(self.prev_window):
                                play_sound("ui/tui_close.ogg")
                            elif self._is_dialog_or_menu(self.prev_window):
                                play_sound("ui/applist.ogg")
                        except Exception:
                            pass  # Window may no longer exist

                # Otwarcie nowego okna
                self.prev_window = current_window
                if play_sound and win32gui.IsWindow(current_window):
                    if self._is_menu(current_window):
                        play_sound("ui/tui_open.ogg")
                    elif self._is_dialog_or_menu(current_window):
                        play_sound("ui/statusbar.ogg")
                    else:
                        # Zwykła zmiana fokusa / skok kursora
                        play_sound("core/FOCUS.ogg")
        except Exception as e:
            # Handle errors getting foreground window
            pass

    def _is_titan_window(self, hwnd) -> bool:
        """Sprawdza czy okno należy do aplikacji Titan"""
        try:
            # Check if window still exists
            if not win32gui.IsWindow(hwnd):
                return False

            # Pobierz tytuł okna
            window_title = win32gui.GetWindowText(hwnd)

            # Sprawdź czy tytuł zawiera "Titan" (główne okno TCE i podokna)
            if "Titan" in window_title:
                return True

            # Sprawdź nazwę procesu
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process = psutil.Process(pid)
                exe_name = process.name().lower()

                # Sprawdź czy to proces Titan (main.py, main.exe, titan.exe, itp.)
                if "titan" in exe_name or exe_name == "main.exe" or exe_name == "python.exe":
                    # Dla python.exe dodatkowo sprawdź tytuł
                    if exe_name == "python.exe" and "Titan" in window_title:
                        return True
                    elif exe_name != "python.exe":
                        return True
            except Exception:
                pass

        except Exception:
            pass

        return False

    def _is_menu(self, hwnd) -> bool:
        """Sprawdza czy okno to menu (kontekstowe, systemowe, etc.)"""
        try:
            # Check if window still exists
            if not win32gui.IsWindow(hwnd):
                return False

            class_name = win32gui.GetClassName(hwnd)

            # #32768 to klasa menu popup Windows
            if class_name == "#32768":
                return True

            # Sprawdź inne klasy menu
            menu_classes = ["menu", "menubar", "popup", "dropdown", "context"]
            if any(mc in class_name.lower() for mc in menu_classes):
                return True

        except Exception:
            pass

        return False

    def _is_dialog_or_menu(self, hwnd) -> bool:
        """Sprawdza czy okno to dialog Windows z przyciskami (np. MessageBox, potwierdzenia)"""
        try:
            # Check if window still exists
            if not win32gui.IsWindow(hwnd):
                return False

            # Sprawdź klasę okna - #32770 to standardowa klasa dialogu Windows
            class_name = win32gui.GetClassName(hwnd)

            # #32770 to główna klasa dialogów Windows
            if class_name == "#32770":
                # Dodatkowo sprawdź czy ma przyciski (child windows typu Button)
                if self._has_buttons(hwnd):
                    return True

            # Sprawdź styl okna - dialog musi mieć WS_DLGFRAME i WS_POPUP
            try:
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            except Exception:
                return False

            # Dialog powinien mieć WS_DLGFRAME lub DS_MODALFRAME
            is_dialog_frame = (style & win32con.WS_DLGFRAME) or ((style & win32con.WS_POPUP) and (ex_style & win32con.WS_EX_DLGMODALFRAME))

            # Jeśli ma styl dialogu, sprawdź czy ma przyciski
            if is_dialog_frame and self._has_buttons(hwnd):
                return True

        except Exception:
            pass

        return False

    def _has_buttons(self, hwnd) -> bool:
        """Sprawdza czy okno ma przyciski (child windows)"""
        try:
            # Check if window still exists
            if not win32gui.IsWindow(hwnd):
                return False

            buttons_found = [False]

            def enum_child_proc(child_hwnd, _):
                try:
                    if not win32gui.IsWindow(child_hwnd):
                        return True
                    child_class = win32gui.GetClassName(child_hwnd)
                    # Sprawdź czy to przycisk
                    if child_class.lower() in ["button", "static", "edit"]:
                        if child_class.lower() == "button":
                            buttons_found[0] = True
                            return False  # Zatrzymaj enumerację
                except Exception:
                    pass
                return True

            win32gui.EnumChildWindows(hwnd, enum_child_proc, None)
            return buttons_found[0]
        except Exception:
            return False

# ------------------------------------------------------------------------------
#    FUNKCJE DLA TITANA
# ------------------------------------------------------------------------------
def initialize(app=None):
    """
    Inicjalizuje wątek monitorujący procesy i aktywne okna (bez globalnego hooka).
    Zwraca wątek, by można go zatrzymać przy zamykaniu Titana.
    """
    feedback = SystemAudioFeedback()
    feedback.start()
    return feedback

def add_menu(menubar):
    pass

# ------------------------------------------------------------------------------
#    TEST LOKALNY
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    if platform.system() != "Windows":
        print("Ten komponent działa tylko na Windows.")
    else:
        app = wx.App(False)
        frame = wx.Frame(None, title="System Audio Feedback", size=(300, 200))
        frame.Show()

        feedback_thread = initialize(app)
        app.MainLoop()

        feedback_thread.stop()