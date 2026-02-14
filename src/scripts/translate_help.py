#!/usr/bin/env python3
"""
Script to fix incorrect translations in help.po
Corrects "Klawisz Titan:" to "Pomoc Titana" and other help-related translations
"""

import re

def fix_help_translations(po_file_path):
    """Fix incorrect help translations in Polish .po file"""

    with open(po_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Dictionary of corrections
    # Format: (msgid, incorrect_msgstr, correct_msgstr)
    corrections = [
        # Main title - WRONG: "Klawisz Titan:" → CORRECT: "Pomoc Titana"
        (
            'msgid "Titan Help"',
            'msgstr "Klawisz Titan:"',
            'msgstr "Pomoc Titana"'
        ),
        # Help file not found - was empty
        (
            'msgid "Help file not found."',
            'msgstr ""',
            'msgstr "Nie znaleziono pliku pomocy."'
        ),
        # Error reading help file - WRONG: "Błąd ładowania widżetu" → CORRECT: help file error
        (
            'msgid "Error reading help file: {}"',
            'msgstr "Błąd ładowania widżetu: {}"',
            'msgstr "Błąd odczytu pliku pomocy: {}"'
        ),
        # Unexpected error - WRONG: "Błąd połączenia" → CORRECT: unexpected error
        (
            'msgid "Unexpected error: {}"',
            'msgstr "Błąd połączenia: {}"',
            'msgstr "Nieoczekiwany błąd: {}"'
        ),
        # No help content found - was empty
        (
            'msgid "No help content found."',
            'msgstr ""',
            'msgstr "Nie znaleziono treści pomocy."'
        ),
        # Error parsing help data - WRONG: "Błąd ładowania widżetu" → CORRECT: parsing error
        (
            'msgid "Error parsing help data: {}"',
            'msgstr "Błąd ładowania widżetu: {}"',
            'msgstr "Błąd parsowania danych pomocy: {}"'
        ),
        # No content available - was empty
        (
            'msgid "No content available for this section."',
            'msgstr ""',
            'msgstr "Brak treści dla tej sekcji."'
        ),
    ]

    original_content = content
    fixed_count = 0

    for msgid, old_msgstr, new_msgstr in corrections:
        # Create pattern that matches msgid followed by old msgstr
        # Need to escape special regex characters
        msgid_escaped = re.escape(msgid)
        old_msgstr_escaped = re.escape(old_msgstr)

        pattern = f'{msgid_escaped}\\s+{old_msgstr_escaped}'
        replacement = f'{msgid}\n{new_msgstr}'

        new_content, count = re.subn(pattern, replacement, content, count=1)

        if count > 0:
            content = new_content
            fixed_count += 1
            print(f"[OK] Fixed: {msgid}")
            print(f"  Old: {old_msgstr}")
            print(f"  New: {new_msgstr}")
        else:
            print(f"[SKIP] Not found or already fixed: {msgid}")

    if content != original_content:
        # Write updated content
        with open(po_file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"\n[SUCCESS] Fixed {fixed_count} translations in {po_file_path}")
        return True
    else:
        print(f"\n[INFO] No changes made to {po_file_path}")
        return False

if __name__ == '__main__':
    po_file = 'languages/pl/LC_MESSAGES/help.po'

    print("Fixing incorrect help translations in help.po...")
    print("=" * 60)

    success = fix_help_translations(po_file)

    if success:
        print("\nTranslations fixed successfully!")
        print("\nRun the following command to compile:")
        print("  pybabel compile -d languages -D help")
    else:
        print("\nNo changes were needed.")
