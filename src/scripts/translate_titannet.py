#!/usr/bin/env python
"""
Automatic translation script for Titan-Net Polish translations.
Translates all empty msgstr entries in titannet.po
"""

import re

# Dictionary of English -> Polish translations for Titan-Net
TRANSLATIONS = {
    # General Titan-Net
    "Titan-Net": "Titan-Net",
    "Titan IM": "Titan IM",
    "Login": "Zaloguj",
    "Logout": "Wyloguj",
    "Register": "Zarejestruj",
    "Username": "Nazwa użytkownika",
    "Password": "Hasło",
    "Username:": "Nazwa użytkownika:",
    "Password:": "Hasło:",
    "First Name:": "Imię:",
    "Last Name:": "Nazwisko:",
    "Full Name": "Pełna nazwa",
    "optional": "opcjonalne",
    "Cancel": "Anuluj",
    "Refresh": "Odśwież",
    "Send": "Wyślij",
    "Select": "Wybierz",
    "Back": "Wstecz",
    "Error": "Błąd",
    "Success": "Sukces",

    # Login/Registration
    "Titan-Net Login": "Logowanie Titan-Net",
    "Create Account": "Utwórz konto",
    "Create Titan-Net Account": "Utwórz konto Titan-Net",
    "Continue in Offline Mode": "Kontynuuj w trybie offline",
    "I don't use Titan-Net": "Nie używam Titan-Net",
    "Account created. You can now login.": "Konto utworzone. Możesz się teraz zalogować.",
    "Please enter username and password": "Wprowadź nazwę użytkownika i hasło",
    "Connecting to Titan-Net...": "Łączenie z Titan-Net...",
    "Login successful": "Logowanie pomyślne",
    "Login failed": "Logowanie nieudane",
    "Logged in as: {username}": "Zalogowano jako: {username}",
    "Logged in as: {username} (#{titan_number})": "Zalogowano jako: {username} (#{titan_number})",
    "Continuing in offline mode": "Kontynuacja w trybie offline",
    "Username and password are required": "Nazwa użytkownika i hasło są wymagane",
    "Creating account...": "Tworzenie konta...",
    "Account created successfully. Your Titan number is {titan_number}": "Konto utworzone pomyślnie. Twój numer Titan to {titan_number}",
    "Registration failed": "Rejestracja nieudana",
    "Registration error: {error}": "Błąd rejestracji: {error}",
    "Login error: {error}": "Błąd logowania: {error}",
    "Not logged in": "Nie zalogowano",
    "Logout successful": "Wylogowano pomyślnie",
    "Logout error: {error}": "Błąd wylogowania: {error}",
    "Cannot connect to Titan-Net server": "Nie można połączyć się z serwerem Titan-Net",
    "No response from server": "Brak odpowiedzi z serwera",
    "Checking Titan-Net connection...": "Sprawdzanie połączenia Titan-Net...",
    "Titan-Net server is not available. Would you like to continue in offline mode?": "Serwer Titan-Net jest niedostępny. Czy chcesz kontynuować w trybie offline?",
    "Titan-Net server is not available.\\nYou can continue in offline mode without messaging features.": "Serwer Titan-Net jest niedostępny.\\nMożesz kontynuować w trybie offline bez funkcji komunikatora.",
    "Server Not Available": "Serwer niedostępny",
    "Server connected": "Serwer połączony",
    "Not connected to Titan-Net": "Nie połączono z Titan-Net",
    "Disconnect": "Rozłącz",

    # Messages
    "Message sent": "Wiadomość wysłana",
    "Error sending message: {error}": "Błąd wysyłania wiadomości: {error}",
    "Private Messages": "Wiadomości prywatne",
    "Private Messages:": "Wiadomości prywatne:",
    "Send message to:": "Wyślij wiadomość do:",
    "Send Message": "Wyślij wiadomość",
    "Messages retrieved": "Wiadomości pobrane",
    "Error getting messages: {error}": "Błąd pobierania wiadomości: {error}",
    "Loading messages...": "Ładowanie wiadomości...",
    "Messages loaded": "Wiadomości załadowane",
    "Please select a user": "Wybierz użytkownika",
    "Please select a user first": "Najpierw wybierz użytkownika",
    "New message from {user}": "Nowa wiadomość od {user}",

    # Rooms
    "Chat Rooms": "Pokoje czatu",
    "Available Rooms:": "Dostępne pokoje:",
    "Room Chat:": "Czat pokoju:",
    "Create Room": "Utwórz pokój",
    "Join Room": "Dołącz do pokoju",
    "Leave Room": "Opuść pokój",
    "Enter room name:": "Wprowadź nazwę pokoju:",
    "Room created": "Pokój utworzony",
    "Room created successfully": "Pokój utworzony pomyślnie",
    "Failed to create room": "Nie udało się utworzyć pokoju",
    "Error creating room: {error}": "Błąd tworzenia pokoju: {error}",
    "Joined room: {name}": "Dołączono do pokoju: {name}",
    "Joined room successfully": "Pomyślnie dołączono do pokoju",
    "Failed to join room": "Nie udało się dołączyć do pokoju",
    "Error joining room: {error}": "Błąd dołączania do pokoju: {error}",
    "Left room": "Opuszczono pokój",
    "Error leaving room: {error}": "Błąd opuszczania pokoju: {error}",
    "Room deleted": "Pokój usunięty",
    "Failed to delete room": "Nie udało się usunąć pokoju",
    "Error deleting room: {error}": "Błąd usuwania pokoju: {error}",
    "Rooms retrieved": "Pokoje pobrane",
    "Error getting rooms: {error}": "Błąd pobierania pokoi: {error}",
    "Please select a room": "Wybierz pokój",
    "joined the room": "dołączył do pokoju",
    "left the room": "opuścił pokój",
    "Name": "Nazwa",
    "Type": "Typ",
    "Members": "Członkowie",

    # Users
    "Online Users": "Użytkownicy online",
    "Online Users:": "Użytkownicy online:",
    "Titan Number": "Numer Titan",
    "Users retrieved": "Użytkownicy pobrani",
    "Error getting users: {error}": "Błąd pobierania użytkowników: {error}",
    "Welcome user {username}, Titan ID: {titan_number}": "Witaj użytkowniku {username}, ID Titan: {titan_number}",

    # Forum - General
    "Forum": "Forum",
    "Titan-Net Forum": "Forum Titan-Net",
    "Titan-Net Forum - Discuss topics with the community": "Forum Titan-Net - Dyskutuj z społecznością",
    "Recent Topics:": "Ostatnie tematy:",
    "Open Full Forum": "Otwórz pełne forum",
    "New Topic": "Nowy temat",
    "Search Forum": "Szukaj na forum",
    "Browse Topics": "Przeglądaj tematy",
    "Create Topic": "Utwórz temat",
    "My Topics": "Moje tematy",

    # Forum - Topic
    "Forum Topic": "Temat forum",
    "Topic": "Temat",
    "Topic Content:": "Treść tematu:",
    "Title": "Tytuł",
    "Title:": "Tytuł:",
    "Content": "Treść",
    "Content:": "Treść:",
    "Category": "Kategoria",
    "Category:": "Kategoria:",
    "Author": "Autor",
    "Posted": "Opublikowano",
    "Views": "Wyświetlenia",
    "Last Update": "Ostatnia aktualizacja",
    "All": "Wszystkie",
    "General": "Ogólne",
    "Help": "Pomoc",
    "Announcements": "Ogłoszenia",
    "Discussion": "Dyskusja",
    "No topics found": "Nie znaleziono tematów",
    "Failed to load topics": "Nie udało się załadować tematów",
    "Failed to load topic": "Nie udało się załadować tematu",
    "Loading forum topics": "Ładowanie tematów forum",
    "Loading topic": "Ładowanie tematu",
    "Forum topics. Use A and D to navigate, Enter to view": "Tematy forum. Użyj A i D do nawigacji, Enter aby wyświetlić",
    "Topic created successfully": "Temat utworzony pomyślnie",
    "Failed to create topic": "Nie udało się utworzyć tematu",
    "Creating topic": "Tworzenie tematu",
    "Create forum topic": "Utwórz temat forum",
    "Enter topic title": "Wprowadź tytuł tematu",
    "Enter topic content": "Wprowadź treść tematu",
    "Title and content are required": "Tytuł i treść są wymagane",
    "New Forum Topic": "Nowy temat forum",

    # Forum - Replies
    "Replies": "Odpowiedzi",
    "Replies:": "Odpowiedzi:",
    "Reply": "Odpowiedź",
    "Reply:": "Odpowiedź:",
    "Your Reply:": "Twoja odpowiedź:",
    "Send Reply": "Wyślij odpowiedź",
    "Add Reply": "Dodaj odpowiedź",
    "View Replies": "Zobacz odpowiedzi",
    "No replies yet": "Brak odpowiedzi",
    "No replies yet. Be the first to reply!": "Brak odpowiedzi. Bądź pierwszym!",
    "replies": "odpowiedzi",
    "Reply added successfully": "Odpowiedź dodana pomyślnie",
    "Reply sent successfully": "Odpowiedź wysłana pomyślnie",
    "Failed to send reply": "Nie udało się wysłać odpowiedzi",
    "Please enter reply content": "Wprowadź treść odpowiedzi",
    "Loading replies": "Ładowanie odpowiedzi",
    "Failed to load replies": "Nie udało się załadować odpowiedzi",
    "Replies. Use A and D to navigate": "Odpowiedzi. Użyj A i D do nawigacji",
    "Add reply": "Dodaj odpowiedź",
    "Enter your reply": "Wprowadź swoją odpowiedź",

    # App Repository - General
    "App Repository": "Repozytorium aplikacji",
    "Titan-Net App Repository - Browse and share applications": "Repozytorium aplikacji Titan-Net - Przeglądaj i dziel się aplikacjami",
    "Available Applications:": "Dostępne aplikacje:",
    "Application": "Aplikacja",
    "Application Name:": "Nazwa aplikacji:",
    "Description": "Opis",
    "Description:": "Opis:",
    "Version": "Wersja",
    "Version:": "Wersja:",
    "Status": "Status",
    "Status:": "Status:",
    "Approved": "Zatwierdzone",
    "Pending": "Oczekujące",
    "Pending approval": "Oczekuje zatwierdzenia",
    "Downloads": "Pobrano",
    "Uploaded": "Przesłano",

    # App Repository - Download
    "Download & Install": "Pobierz i zainstaluj",
    "Download": "Pobierz",
    "Download and install {app}?": "Pobrać i zainstalować {app}?",
    "Confirm Download": "Potwierdź pobieranie",
    "Downloading...": "Pobieranie...",
    "Download complete": "Pobieranie zakończone",
    "Download failed": "Pobieranie nie powiodło się",
    "Failed to load app details": "Nie udało się załadować szczegółów aplikacji",
    "Application downloaded successfully to:\\n{path}": "Aplikacja pobrana pomyślnie do:\\n{path}",
    "Failed to save file: {error}": "Nie udało się zapisać pliku: {error}",
    "Save application as": "Zapisz aplikację jako",

    # App Repository - Upload
    "Upload App": "Prześlij aplikację",
    "Upload Application": "Prześlij aplikację",
    "Upload": "Prześlij",
    "Confirm Upload": "Potwierdź przesyłanie",
    "Uploading...": "Przesyłanie...",
    "Upload complete": "Przesyłanie zakończone",
    "Upload failed": "Przesyłanie nie powiodło się",
    "Application uploaded successfully.\\nIt will be available after admin approval.": "Aplikacja przesłana pomyślnie.\\nBędzie dostępna po zatwierdzeniu przez administratora.",
    "Name, category, and file are required": "Nazwa, kategoria i plik są wymagane",
    "File is too large. Maximum size is 100 MB": "Plik jest za duży. Maksymalny rozmiar to 100 MB",
    "Upload application?\\n\\nName: {name}\\nSize: {size:.2f} MB": "Przesłać aplikację?\\n\\nNazwa: {name}\\nRozmiar: {size:.2f} MB",
    "No file selected": "Nie wybrano pliku",
    "Select File": "Wybierz plik",
    "Select application file": "Wybierz plik aplikacji",

    # Klango Mode
    "Titan-Net client not available": "Klient Titan-Net niedostępny",
    "Error opening Titan-Net": "Błąd otwierania Titan-Net",
    "Titan-Net server is not available": "Serwer Titan-Net jest niedostępny",
    "Server available": "Serwer dostępny",
    "Checking server...": "Sprawdzanie serwera...",
    "Enter username": "Wprowadź nazwę użytkownika",
    "Enter password": "Wprowadź hasło",
    "Logging in...": "Logowanie...",
    "Logged in as {username}": "Zalogowano jako {username}",
    "Error during login": "Błąd podczas logowania",
    "Create new Titan-Net account": "Utwórz nowe konto Titan-Net",
    "Your Titan number is {number}": "Twój numer Titan to {number}",
    "Logged out from Titan-Net": "Wylogowano z Titan-Net",
    "Error loading forum": "Błąd ładowania forum",
    "Error loading topics": "Błąd ładowania tematów",
    "Error viewing topic": "Błąd wyświetlania tematu",
    "Error viewing replies": "Błąd wyświetlania odpowiedzi",
    "Error loading replies": "Błąd ładowania odpowiedzi",
    "Login required for forum": "Wymagane logowanie do forum",
    "Cancelled": "Anulowano",

    # Common UI elements
    "OK": "OK",
    "Yes": "Tak",
    "No": "Nie",
    "Close": "Zamknij",
    "Save": "Zapisz",
    "Delete": "Usuń",
    "Edit": "Edytuj",
    "Search": "Szukaj",
    "Filter": "Filtruj",
    "Sort": "Sortuj",
    "Loading": "Ładowanie",
    "Loading...": "Ładowanie...",
    "Please wait...": "Proszę czekać...",
    "Information": "Informacja",
    "Warning": "Ostrzeżenie",
    "Confirmation": "Potwierdzenie",
}

def translate_po_file(input_file, output_file):
    """Translate empty msgstr entries in a .po file."""
    print(f"Reading {input_file}...")

    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    translated_count = 0
    in_msgid = False
    current_msgid = None
    output_lines = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Check for msgid
        if line.startswith('msgid '):
            match = re.match(r'msgid "(.*)"', line)
            if match:
                current_msgid = match.group(1)
                in_msgid = True
            output_lines.append(line)
            i += 1
            continue

        # Check for empty msgstr
        if line.startswith('msgstr ""') and in_msgid and current_msgid:
            # Check if we have a translation
            if current_msgid in TRANSLATIONS:
                translation = TRANSLATIONS[current_msgid]
                output_lines.append(f'msgstr "{translation}"\n')
                translated_count += 1
                print(f"  Translated: {current_msgid[:50]}...")
            else:
                output_lines.append(line)
                print(f"  [MISSING] No translation for: {current_msgid}")

            in_msgid = False
            current_msgid = None
            i += 1
            continue

        # Default: just copy the line
        output_lines.append(line)
        i += 1

    # Write output
    print(f"\\nWriting to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(output_lines)

    print(f"\\nTranslated {translated_count} strings")
    print(f"Output written to: {output_file}")

if __name__ == "__main__":
    input_file = "languages/pl/LC_MESSAGES/titannet.po"
    output_file = "languages/pl/LC_MESSAGES/titannet.po"

    translate_po_file(input_file, output_file)

    print("\\nDone! Now run: pybabel compile -d languages -D titannet")
