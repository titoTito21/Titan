#!/usr/bin/env python
"""
Script to migrate translations from old messages.po to new modular .po files.
"""

import os
import re
from collections import defaultdict

def parse_po_file(filepath):
    """Parse a .po file and return a dictionary of msgid -> (msgstr, location)."""
    translations = {}

    if not os.path.exists(filepath):
        print(f"File {filepath} not found")
        return translations

    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    current_msgid = None
    current_msgstr = None
    current_location = None
    in_msgid = False
    in_msgstr = False

    for line in lines:
        line = line.rstrip('\n')

        # Extract location comment (e.g., #: gui.py:40)
        if line.startswith('#:'):
            current_location = line[2:].strip()

        # Start of msgid
        elif line.startswith('msgid '):
            if current_msgid and current_msgstr:
                translations[current_msgid] = (current_msgstr, current_location)

            current_msgid = line[6:].strip().strip('"')
            current_msgstr = None
            current_location = None
            in_msgid = True
            in_msgstr = False

        # Start of msgstr
        elif line.startswith('msgstr '):
            current_msgstr = line[7:].strip().strip('"')
            in_msgid = False
            in_msgstr = True

        # Continuation of multiline string
        elif line.startswith('"') and (in_msgid or in_msgstr):
            text = line.strip().strip('"')
            if in_msgid:
                current_msgid += text
            elif in_msgstr:
                current_msgstr += text

    # Add last entry
    if current_msgid and current_msgstr:
        translations[current_msgid] = (current_msgstr, current_location)

    return translations

def update_po_file(filepath, old_translations):
    """Update a .po file with translations from old messages.po."""
    if not os.path.exists(filepath):
        print(f"File {filepath} not found")
        return 0

    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    updated_lines = []
    updated_count = 0
    current_msgid = None
    in_msgid = False
    in_msgstr = False
    msgid_lines = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Start of msgid
        if line.startswith('msgid '):
            current_msgid = line[6:].strip().strip('"')
            msgid_lines = [line]
            in_msgid = True
            in_msgstr = False
            i += 1

            # Collect multiline msgid
            while i < len(lines) and lines[i].startswith('"'):
                current_msgid += lines[i].strip().strip('"')
                msgid_lines.append(lines[i])
                i += 1

            # Add msgid lines
            updated_lines.extend(msgid_lines)
            continue

        # Start of msgstr
        elif line.startswith('msgstr '):
            current_msgstr = line[7:].strip().strip('"')
            in_msgid = False
            in_msgstr = True

            # Check if we have a translation for this msgid
            if current_msgid and current_msgid in old_translations:
                translated_text, _ = old_translations[current_msgid]
                if translated_text:  # Only update if translation exists
                    # Replace msgstr with translated text
                    updated_lines.append(f'msgstr "{translated_text}"\n')
                    updated_count += 1

                    # Skip old msgstr continuation lines
                    i += 1
                    while i < len(lines) and lines[i].startswith('"'):
                        i += 1
                    continue

            # No translation found, keep original
            updated_lines.append(line)
            i += 1
            continue

        else:
            updated_lines.append(line)
            i += 1

    # Write updated file
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(updated_lines)

    return updated_count

def main():
    """Main migration process."""
    print("=" * 60)
    print("Translation Migration Script")
    print("=" * 60)

    languages = ['pl', 'en']

    for lang in languages:
        print(f"\nMigrating {lang} translations...")

        old_po_file = f'languages/{lang}/LC_MESSAGES/messages.po'

        # Parse old messages.po
        print(f"  Reading {old_po_file}...")
        old_translations = parse_po_file(old_po_file)
        print(f"  Found {len(old_translations)} translations")

        if not old_translations:
            print(f"  Skipping {lang} - no translations found")
            continue

        # Get list of new .po files
        po_dir = f'languages/{lang}/LC_MESSAGES'
        po_files = [f for f in os.listdir(po_dir) if f.endswith('.po') and f != 'messages.po']

        total_updated = 0
        for po_file in po_files:
            po_path = os.path.join(po_dir, po_file)
            updated = update_po_file(po_path, old_translations)
            if updated > 0:
                print(f"  [OK] {po_file}: {updated} translations migrated")
            total_updated += updated

        print(f"  Total: {total_updated} translations migrated for {lang}")

    print("\n" + "=" * 60)
    print("Migration complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Review the migrated translations in languages/*/LC_MESSAGES/")
    print("2. Compile translations: python extract_translations.py")
    print("3. Test the application")
    print("4. Delete old messages.po/messages.pot files if everything works")

if __name__ == '__main__':
    main()
