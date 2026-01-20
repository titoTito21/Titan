TITAN-NET SERVER
================

Instrukcja uruchomienia:
1. Kliknij dwukrotnie na plik "start_server.bat"
2. Serwer uruchomi się i będzie nasłuchiwał na:
   - WebSocket: ws://localhost:8001
   - HTTP API: http://localhost:8000

WAŻNE: Serwer musi być uruchomiony PRZED uruchomieniem aplikacji TCE Launcher,
aby okno logowania Titan-Net mogło się połączyć.

Aby zatrzymać serwer, naciśnij Ctrl+C w oknie konsoli.

Logi serwera są zapisywane w katalogu "logs/".

---

Narzędzia diagnostyczne:
- check_server.bat - Sprawdza czy serwer jest uruchomiony
- test_client.py - Testuje połączenie klient-serwer

Jeśli masz problem z połączeniem, najpierw uruchom check_server.bat
aby upewnić się że serwer działa na portach 8000 i 8001.
