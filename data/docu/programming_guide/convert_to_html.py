#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Konwerter dokumentacji Markdown na HTML
Konwertuje wszystkie przewodniki programistyczne TCE Launcher na strony HTML z nawigacją.
"""

import os
import re
from pathlib import Path

# Sprawdź czy markdown2 jest dostępny, jeśli nie użyj prostej konwersji
try:
    import markdown2
    HAS_MARKDOWN2 = True
except ImportError:
    HAS_MARKDOWN2 = False
    print("Uwaga: markdown2 nie jest zainstalowane, używam prostej konwersji")
    print("Zainstaluj markdown2 dla lepszych wyników: pip install markdown2")


def simple_markdown_to_html(md_text):
    """Prosta konwersja Markdown na HTML bez zewnętrznych bibliotek."""
    import html as html_module

    # Najpierw przetwarzamy bloki kodu i zamieniamy je na placeholdery
    # żeby inne konwersje nie zepsuły kodu
    code_blocks = {}

    def extract_code_blocks(text):
        """Wyodrębnij bloki kodu i zamień na placeholdery."""
        pattern = r'```(\w*)\n(.*?)\n```'

        def replace_code_block(match):
            lang = match.group(1)
            code = match.group(2)
            # Escape HTML w kodzie
            code_escaped = html_module.escape(code)
            lang_class = f' class="language-{lang}"' if lang else ''
            code_html = f'<pre><code{lang_class}>{code_escaped}</code></pre>'

            # Utwórz unikalny placeholder
            placeholder = f'___CODE_BLOCK_{len(code_blocks)}___'
            code_blocks[placeholder] = code_html
            return placeholder

        return re.sub(pattern, replace_code_block, text, flags=re.DOTALL)

    html = extract_code_blocks(md_text)

    # Nagłówki
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', html, flags=re.MULTILINE)

    # Inline code (przed pogrubieniem, żeby uniknąć konfliktów)
    def replace_inline_code(match):
        code_text = match.group(1)
        # Escape HTML w inline kodzie
        code_escaped = html_module.escape(code_text)
        return f'<code>{code_escaped}</code>'

    html = re.sub(r'`(.+?)`', replace_inline_code, html)

    # Pogrubienie i kursywa
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)

    # Listy
    html = re.sub(r'^\- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    html = re.sub(r'^\d+\. (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)

    # Linki
    html = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', html)

    # Tabele - prosta obsługa
    lines = html.split('\n')
    in_table = False
    new_lines = []

    for line in lines:
        if '|' in line and not in_table:
            in_table = True
            new_lines.append('<table class="doc-table">')
            # Nagłówek tabeli
            headers = [h.strip() for h in line.split('|') if h.strip()]
            new_lines.append('<thead><tr>')
            for h in headers:
                new_lines.append(f'<th>{h}</th>')
            new_lines.append('</tr></thead><tbody>')
        elif '|' in line and in_table:
            # Pomiń linię separatora
            if '---' in line:
                continue
            # Wiersz tabeli
            cells = [c.strip() for c in line.split('|') if c.strip()]
            new_lines.append('<tr>')
            for c in cells:
                new_lines.append(f'<td>{c}</td>')
            new_lines.append('</tr>')
        elif in_table and '|' not in line:
            in_table = False
            new_lines.append('</tbody></table>')
            new_lines.append(line)
        else:
            new_lines.append(line)

    if in_table:
        new_lines.append('</tbody></table>')

    html = '\n'.join(new_lines)

    # Paragrafy
    paragraphs = html.split('\n\n')
    html_paragraphs = []
    for p in paragraphs:
        p = p.strip()
        # Sprawdź czy to nie jest placeholder bloków kodu lub tag HTML
        if p and not any(p.startswith(tag) for tag in ['<h', '<pre', '<ul', '<ol', '<table', '<li', '___CODE_BLOCK_']):
            if not p.endswith('>'):
                p = f'<p>{p}</p>'
        html_paragraphs.append(p)

    html = '\n\n'.join(html_paragraphs)

    # Przywróć bloki kodu z placeholderów
    for placeholder, code_html in code_blocks.items():
        html = html.replace(placeholder, code_html)

    return html


def markdown_to_html(md_text):
    """Konwertuj Markdown na HTML używając markdown2 lub prostej konwersji."""
    if HAS_MARKDOWN2:
        return markdown2.markdown(md_text, extras=['tables', 'fenced-code-blocks', 'header-ids'])
    else:
        return simple_markdown_to_html(md_text)


def extract_title(md_text):
    """Wyodrębnij tytuł z pierwszego nagłówka # ."""
    match = re.search(r'^# (.+)$', md_text, re.MULTILINE)
    return match.group(1) if match else "TCE Launcher - Przewodnik programisty"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - TCE Launcher Programming Guide</title>
    <style>
        :root {{
            --primary-color: #2563eb;
            --secondary-color: #1e40af;
            --bg-color: #ffffff;
            --text-color: #1f2937;
            --code-bg: #f3f4f6;
            --sidebar-bg: #f9fafb;
            --border-color: #e5e7eb;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: var(--text-color);
            background: var(--bg-color);
        }}

        .container {{
            display: flex;
            min-height: 100vh;
        }}

        .sidebar {{
            width: 280px;
            background: var(--sidebar-bg);
            border-right: 1px solid var(--border-color);
            padding: 2rem 1.5rem;
            position: fixed;
            height: 100vh;
            overflow-y: auto;
        }}

        .sidebar h2 {{
            color: var(--primary-color);
            margin-bottom: 1.5rem;
            font-size: 1.25rem;
        }}

        .sidebar nav ul {{
            list-style: none;
        }}

        .sidebar nav li {{
            margin-bottom: 0.5rem;
        }}

        .sidebar nav a {{
            color: var(--text-color);
            text-decoration: none;
            display: block;
            padding: 0.5rem 0.75rem;
            border-radius: 0.375rem;
            transition: background-color 0.2s;
        }}

        .sidebar nav a:hover {{
            background-color: var(--code-bg);
        }}

        .sidebar nav a.active {{
            background-color: var(--primary-color);
            color: white;
        }}

        .content {{
            flex: 1;
            margin-left: 280px;
            padding: 2rem 3rem;
            max-width: 1200px;
        }}

        .content h1 {{
            color: var(--primary-color);
            margin-bottom: 1.5rem;
            padding-bottom: 0.75rem;
            border-bottom: 2px solid var(--border-color);
            font-size: 2.5rem;
        }}

        .content h2 {{
            color: var(--secondary-color);
            margin-top: 2.5rem;
            margin-bottom: 1rem;
            font-size: 2rem;
        }}

        .content h3 {{
            color: var(--text-color);
            margin-top: 2rem;
            margin-bottom: 0.75rem;
            font-size: 1.5rem;
        }}

        .content h4 {{
            color: var(--text-color);
            margin-top: 1.5rem;
            margin-bottom: 0.5rem;
            font-size: 1.25rem;
        }}

        .content p {{
            margin-bottom: 1rem;
        }}

        .content ul, .content ol {{
            margin-bottom: 1rem;
            margin-left: 2rem;
        }}

        .content li {{
            margin-bottom: 0.5rem;
        }}

        .content code {{
            background: var(--code-bg);
            padding: 0.2rem 0.4rem;
            border-radius: 0.25rem;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 0.9em;
        }}

        .content pre {{
            background: var(--code-bg);
            padding: 1.5rem;
            border-radius: 0.5rem;
            overflow-x: auto;
            margin-bottom: 1rem;
            border: 1px solid var(--border-color);
        }}

        .content pre code {{
            background: none;
            padding: 0;
            font-size: 0.875rem;
        }}

        .doc-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 1.5rem 0;
            background: white;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }}

        .doc-table th {{
            background: var(--primary-color);
            color: white;
            padding: 0.75rem;
            text-align: left;
            font-weight: 600;
        }}

        .doc-table td {{
            padding: 0.75rem;
            border-bottom: 1px solid var(--border-color);
        }}

        .doc-table tr:hover {{
            background: var(--code-bg);
        }}

        .content a {{
            color: var(--primary-color);
            text-decoration: none;
        }}

        .content a:hover {{
            text-decoration: underline;
        }}

        .content blockquote {{
            border-left: 4px solid var(--primary-color);
            padding-left: 1rem;
            margin: 1rem 0;
            color: #6b7280;
            font-style: italic;
        }}

        .header-banner {{
            background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%);
            color: white;
            padding: 1rem 3rem;
            margin: -2rem -3rem 2rem -3rem;
        }}

        .header-banner h1 {{
            color: white;
            border: none;
            padding: 0;
            margin: 0;
        }}

        .back-to-top {{
            position: fixed;
            bottom: 2rem;
            right: 2rem;
            background: var(--primary-color);
            color: white;
            width: 50px;
            height: 50px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            text-decoration: none;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            transition: transform 0.2s;
        }}

        .back-to-top:hover {{
            transform: translateY(-2px);
        }}

        @media (max-width: 768px) {{
            .sidebar {{
                display: none;
            }}

            .content {{
                margin-left: 0;
                padding: 1.5rem;
            }}

            .header-banner {{
                margin: -1.5rem -1.5rem 1.5rem -1.5rem;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <aside class="sidebar">
            <h2>TCE Launcher<br>Programming Guide</h2>
            <nav>
                <ul>
                    {navigation}
                </ul>
            </nav>
        </aside>

        <main class="content">
            <div class="header-banner">
                <h1>{title}</h1>
            </div>
            {content}
            <a href="#" class="back-to-top" title="Powrót na górę">↑</a>
        </main>
    </div>
</body>
</html>
"""


def generate_navigation(files, current_file, language='pl'):
    """Generuj HTML nawigacji z listy plików."""
    nav_items = []

    guides_pl = {
        'component_creation_guide_pl.md': 'Tworzenie komponentów',
        'widget_creation_guide_pl.md': 'Tworzenie widgetów',
        'statusbar_applet_guide_pl.md': 'Aplety paska statusu',
        'titanim_module_guide_pl.md': 'Moduły Titan IM',
        'app_creation_guide_pl.md': 'Tworzenie aplikacji',
        'game_creation_guide_pl.md': 'Tworzenie gier',
    }

    guides_en = {
        'component_creation_guide_en.md': 'Creating Components',
        'widget_creation_guide_en.md': 'Creating Widgets',
        'statusbar_applet_guide_en.md': 'Statusbar Applets',
        'titanim_module_guide_en.md': 'Titan IM Modules',
        'app_creation_guide_en.md': 'Creating Applications',
        'game_creation_guide_en.md': 'Creating Games',
    }

    guides = guides_pl if language == 'pl' else guides_en

    # Dodaj link do wersji językowej
    other_lang = 'en' if language == 'pl' else 'pl'
    other_lang_name = 'English' if language == 'pl' else 'Polski'
    other_index = f'index_{other_lang}.html'
    nav_items.append(f'<li style="border-top: 1px solid var(--border-color); padding-top: 0.5rem; margin-top: 0.5rem;"><a href="{other_index}">{other_lang_name} version</a></li>')

    for md_file, title in guides.items():
        if md_file in files:
            html_file = md_file.replace('.md', '.html')
            active_class = ' class="active"' if md_file == current_file else ''
            nav_items.append(f'<li><a href="{html_file}"{active_class}>{title}</a></li>')

    return '\n'.join(nav_items)


def convert_file(md_path, output_dir, all_files):
    """Konwertuj pojedynczy plik Markdown na HTML."""
    print(f"Konwersja: {md_path.name}")

    # Wykryj język z nazwy pliku
    language = 'en' if '_en.md' in md_path.name else 'pl'

    # Wczytaj Markdown
    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()

    # Konwertuj na HTML
    title = extract_title(md_content)
    html_content = markdown_to_html(md_content)

    # Filtruj pliki tego samego języka dla nawigacji
    same_lang_files = [f.name for f in all_files if (f'_{language}.md' in f.name)]
    navigation = generate_navigation(same_lang_files, md_path.name, language)

    # Wygeneruj kompletny HTML
    full_html = HTML_TEMPLATE.format(
        title=title,
        content=html_content,
        navigation=navigation
    )

    # Zapisz HTML
    html_path = output_dir / md_path.name.replace('.md', '.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(full_html)

    print(f"  -> Utworzono: {html_path.name}")


def create_index_page(output_dir, all_files, language='pl'):
    """Utwórz stronę index.html z linkami do wszystkich przewodników."""
    index_name = 'index.html' if language == 'pl' else 'index_en.html'
    print(f"Tworzenie {index_name}...")

    guides_pl = {
        'component_creation_guide_pl.md': ('Tworzenie komponentów', 'Dowiedz się jak tworzyć własne komponenty TCE'),
        'widget_creation_guide_pl.md': ('Tworzenie widgetów', 'Twórz interaktywne widgety dla niewidzialnego interfejsu'),
        'statusbar_applet_guide_pl.md': ('Aplety paska statusu', 'Dodaj dynamiczne informacje do paska statusu'),
        'titanim_module_guide_pl.md': ('Moduły Titan IM', 'Rozszerz Titan IM o własne komunikatory'),
        'app_creation_guide_pl.md': ('Tworzenie aplikacji', 'Twórz aplikacje dla TCE Launcher'),
        'game_creation_guide_pl.md': ('Tworzenie gier', 'Dodaj własne gry do TCE Launcher'),
    }

    guides_en = {
        'component_creation_guide_en.md': ('Creating Components', 'Learn how to create custom TCE components'),
        'widget_creation_guide_en.md': ('Creating Widgets', 'Build interactive widgets for invisible interface'),
        'statusbar_applet_guide_en.md': ('Statusbar Applets', 'Add dynamic information to status bar'),
        'titanim_module_guide_en.md': ('Titan IM Modules', 'Extend Titan IM with custom communicators'),
        'app_creation_guide_en.md': ('Creating Applications', 'Create applications for TCE Launcher'),
        'game_creation_guide_en.md': ('Creating Games', 'Add custom games to TCE Launcher'),
    }

    guides = guides_pl if language == 'pl' else guides_en
    hero_title = "TCE Launcher" if language == 'pl' else "TCE Launcher"
    hero_subtitle = "Przewodnik programisty - Dokumentacja API i przykłady" if language == 'pl' else "Programming Guide - API Documentation and Examples"
    other_lang_link = '<a href="index_en.html" style="color: white; opacity: 0.8;">English version</a>' if language == 'pl' else '<a href="index.html" style="color: white; opacity: 0.8;">Wersja polska</a>'

    cards_html = []
    for md_file, (title, desc) in guides.items():
        if md_file in [f.name for f in all_files]:
            html_file = md_file.replace('.md', '.html')
            cards_html.append(f'''
            <div class="guide-card">
                <h3><a href="{html_file}">{title}</a></h3>
                <p>{desc}</p>
            </div>
            ''')

    other_index_file = 'index_en.html' if language == 'pl' else 'index.html'
    lang_switcher_text = 'English' if language == 'pl' else 'Polski'

    index_html = f'''<!DOCTYPE html>
<html lang="{language}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{hero_title} - {hero_subtitle.split(' - ')[0]}</title>
    <style>
        {HTML_TEMPLATE.split('<style>')[1].split('</style>')[0]}

        .lang-switcher {{
            position: fixed;
            top: 1.5rem;
            right: 1.5rem;
            z-index: 1000;
        }}

        .lang-switcher a {{
            background: white;
            color: #2563eb;
            padding: 0.75rem 1.5rem;
            border-radius: 2rem;
            text-decoration: none;
            font-weight: 600;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            transition: transform 0.2s, box-shadow 0.2s;
            display: inline-block;
        }}

        .lang-switcher a:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.15);
        }}

        .hero {{
            background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%);
            color: white;
            padding: 4rem 2rem;
            text-align: center;
        }}

        .hero h1 {{
            font-size: 3rem;
            margin-bottom: 1rem;
        }}

        .hero p {{
            font-size: 1.25rem;
            opacity: 0.9;
        }}

        .guides-container {{
            max-width: 1200px;
            margin: 3rem auto;
            padding: 0 2rem;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 2rem;
        }}

        .guide-card {{
            background: white;
            border: 1px solid #e5e7eb;
            border-radius: 0.5rem;
            padding: 1.5rem;
            transition: transform 0.2s, box-shadow 0.2s;
        }}

        .guide-card:hover {{
            transform: translateY(-4px);
            box-shadow: 0 10px 20px rgba(0, 0, 0, 0.1);
        }}

        .guide-card h3 {{
            color: #2563eb;
            margin-bottom: 0.5rem;
        }}

        .guide-card a {{
            text-decoration: none;
            color: inherit;
        }}

        .guide-card p {{
            color: #6b7280;
        }}

        @media (max-width: 768px) {{
            .lang-switcher {{
                position: static;
                text-align: center;
                margin-bottom: 1rem;
            }}
        }}
    </style>
</head>
<body>
    <div class="lang-switcher">
        <a href="{other_index_file}">{lang_switcher_text}</a>
    </div>

    <div class="hero">
        <h1>{hero_title}</h1>
        <p>{hero_subtitle}</p>
    </div>

    <div class="guides-container">
        {''.join(cards_html)}
    </div>
</body>
</html>
'''

    index_path = output_dir / index_name
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(index_html)

    print(f"  -> Utworzono: {index_path.name}")


def main():
    """Główna funkcja konwertera."""
    script_dir = Path(__file__).parent
    output_dir = script_dir / 'html'

    # Utwórz katalog wyjściowy
    output_dir.mkdir(exist_ok=True)

    # Znajdź wszystkie pliki Markdown (PL i EN)
    md_files_pl = list(script_dir.glob('*_pl.md'))
    md_files_en = list(script_dir.glob('*_en.md'))
    all_md_files = md_files_pl + md_files_en

    if not all_md_files:
        print("Nie znaleziono plików Markdown do konwersji.")
        return

    print(f"Znaleziono {len(all_md_files)} plików do konwersji ({len(md_files_pl)} PL, {len(md_files_en)} EN).\n")

    # Konwertuj każdy plik
    for md_file in all_md_files:
        try:
            convert_file(md_file, output_dir, all_md_files)
        except Exception as e:
            print(f"  X Blad: {e}")

    # Utwórz strony index (PL i EN)
    try:
        if md_files_pl:
            create_index_page(output_dir, md_files_pl, 'pl')
        if md_files_en:
            create_index_page(output_dir, md_files_en, 'en')
    except Exception as e:
        print(f"  X Blad tworzenia index: {e}")

    print(f"\nKonwersja zakończona! Pliki HTML znajdują się w: {output_dir}")
    print(f"Otwórz index.html (PL) lub index_en.html (EN) w przeglądarce aby przeglądać dokumentację.")


if __name__ == '__main__':
    main()
