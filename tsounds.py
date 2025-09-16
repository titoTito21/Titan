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
from sound import play_sound

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
        if platform.system() != "Windows":
            print("SystemAudioFeedback działa tylko na Windows.")
            return

        # Inicjalizacja stanu procesów
        self.prev_pids = self._get_current_pids()

        while not self._stop_event.is_set():
            # 1. Monitoruj procesy
            self._monitor_processes()
            # 2. Monitoruj okna procesów
            self._monitor_windows()
            # 3. Monitoruj aktywne okno (skok kursora, dialogi, itp.)
            self._monitor_active_window()

            time.sleep(0.1)

    def stop(self):
        """Zatrzymuje wątek."""
        self._stop_event.set()

    # --------------------------------------------------------------------------
    #                           MONITOROWANIE PROCESÓW
    # --------------------------------------------------------------------------
    def _monitor_processes(self):
        current_pids = self._get_current_pids()
        new_pids = current_pids - self.prev_pids
        closed_pids = self.prev_pids - current_pids

        for pid in new_pids:
            self._on_new_process(pid)
        for pid in closed_pids:
            self._on_closed_process(pid)

        self.prev_pids = current_pids

    def _get_current_pids(self):
        return {p.pid for p in psutil.process_iter(['pid'])}

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
        except psutil.NoSuchProcess:
            pass

    def _on_closed_process(self, pid):
        """Jeśli proces miał okno, odtwarzamy dźwięk zamknięcia."""
        info = self.process_info.pop(pid, None)
        if info and info["had_window"]:
            if info["is_system"]:
                play_sound("sysprocess_close.ogg")
            else:
                play_sound("uiclose.ogg")

    # --------------------------------------------------------------------------
    #                      MONITOROWANIE OKIEN PROCESÓW
    # --------------------------------------------------------------------------
    def _monitor_windows(self):
        """
        Sprawdza, czy procesy z self.process_info mają top-level window.
        Jeśli tak i 'had_window' == False => odtwarzamy open.ogg (systemowe lub użytkownika).
        """
        def enum_handler(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True  # pomiń ukryte okna

            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in self.process_info:
                info = self.process_info[pid]
                if not info["had_window"]:
                    # Pierwsze okno = odtwarzamy dźwięk otwarcia
                    info["had_window"] = True
                    if info["is_system"]:
                        play_sound("sysprocess_open.ogg")
                    else:
                        play_sound("uiopen.ogg")

            return True

        win32gui.EnumWindows(enum_handler, None)

    # --------------------------------------------------------------------------
    #              MONITOROWANIE AKTYWNEGO OKNA (dialogi, menu, focus)
    # --------------------------------------------------------------------------
    def _monitor_active_window(self):
        current_window = win32gui.GetForegroundWindow()
        if current_window != self.prev_window:
            # Zamknięcie poprzedniego okna dialog/menu?
            if self.prev_window:
                old_title = win32gui.GetWindowText(self.prev_window)
                if self._is_dialog_or_menu(old_title):
                    play_sound("applist.ogg")

            # Otwarcie nowego okna
            self.prev_window = current_window
            new_title = win32gui.GetWindowText(current_window)
            if self._is_dialog_or_menu(new_title):
                play_sound("statusbar.ogg")
            else:
                # Zwykła zmiana fokusa / skok kursora
                play_sound("focus.ogg")

    def _is_dialog_or_menu(self, title: str) -> bool:
        t = title.lower()
        return any(word in t for word in ["dialog", "menu", "settings", "popup"])

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