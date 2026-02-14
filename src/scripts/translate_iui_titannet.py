#!/usr/bin/env python
"""
Add/Fix Titan-Net translations in invisibleui.po
"""

import re

# Titan-Net specific translations for invisibleui.py
IUI_TITANNET_TRANSLATIONS = {
    "Titan-Net": "Titan-Net",
    "Cannot open Titan-Net - application not ready": "Nie można otworzyć Titan-Net - aplikacja nie jest gotowa",
    "Titan-Net client not available": "Klient Titan-Net niedostępny",
    "Titan-Net, application": "Titan-Net, aplikacja",
    "Not connected to Titan-Net server": "Nie połączono z serwerem Titan-Net",
    "Error opening Titan-Net": "Błąd otwierania Titan-Net",
    "Titan-Net not available": "Titan-Net niedostępny",
    "Opening forum": "Otwieranie forum",
    "Opening Titan-Net": "Otwieranie Titan-Net",
    "Login cancelled": "Anulowano logowanie",
    "Offline mode selected": "Wybrano tryb offline",
}

def fix_translations(input_file, translations):
    """Fix/add translations in a .po file."""
    print(f"Reading {input_file}...")

    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    fixed_count = 0
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

        # Check for msgstr (empty or not)
        if line.startswith('msgstr ') and in_msgid and current_msgid:
            # Check if we have a translation to fix/add
            if current_msgid in translations:
                translation = translations[current_msgid]
                output_lines.append(f'msgstr "{translation}"\n')
                fixed_count += 1
                print(f"  Fixed/Added: {current_msgid[:60]}...")
            else:
                output_lines.append(line)

            in_msgid = False
            current_msgid = None
            i += 1
            continue

        # Default: just copy the line
        output_lines.append(line)
        i += 1

    # Write output
    print(f"\\nWriting to {input_file}...")
    with open(input_file, 'w', encoding='utf-8') as f:
        f.writelines(output_lines)

    print(f"\\nFixed/Added {fixed_count} strings in invisibleui.po")

if __name__ == "__main__":
    iui_po_file = "languages/pl/LC_MESSAGES/invisibleui.po"

    fix_translations(iui_po_file, IUI_TITANNET_TRANSLATIONS)

    print("\\nDone! Now run: pybabel compile -d languages -D invisibleui")
