#!/usr/bin/env python
"""
Add Titan-Net translations to gui.po
"""

import re

# Titan-Net specific translations for gui.py
GUI_TITANNET_TRANSLATIONS = {
    "Titan-Net": "Titan-Net",
    "Logged in to Titan-Net as {username}": "Zalogowano do Titan-Net jako {username}",
    "Cannot launch Titan-Net.\\nError: {error}": "Nie można uruchomić Titan-Net.\\nBłąd: {error}",
    "Titan-Net Error": "Błąd Titan-Net",
    "Not connected to Titan-Net": "Nie połączono z Titan-Net",
    "Opening Titan-Net": "Otwieranie Titan-Net",
}

def translate_po_file(input_file, translations):
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
            if current_msgid in translations:
                translation = translations[current_msgid]
                output_lines.append(f'msgstr "{translation}"\n')
                translated_count += 1
                print(f"  Translated: {current_msgid[:60]}...")
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

    print(f"\\nTranslated {translated_count} strings in gui.po")

if __name__ == "__main__":
    gui_po_file = "languages/pl/LC_MESSAGES/gui.po"

    translate_po_file(gui_po_file, GUI_TITANNET_TRANSLATIONS)

    print("\\nDone! Now run: pybabel compile -d languages -D gui")
