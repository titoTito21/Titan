# -*- coding: utf-8 -*-
"""Rich mail bodies, turned into something a screen reader can walk through.

Mail is the one part of Titan-Net where the content is written by *other*
people's programs: a phone client sends HTML, a developer sends Markdown, a
mailing list sends both. The Mail client must never show tag soup and must never
throw the markup away either - so a body is parsed here into a flat list of
``Block`` objects (a heading, a list item, a quote, a code line, a table row),
which is exactly the shape Titan's list-based interaction wants: one block per
row, navigated with the arrows, read on demand.

Nothing here renders HTML as HTML. There is no browser engine, no external
dependency and no network access: an inline image is a row that says it is an
image, a link is a row plus an entry in the message's Links tab. That is the
same trade the rest of Titan makes - the content becomes *readable*, not
*displayed*.

The module is deliberately usable on its own (no wx), so the same rendering
serves the reader window, the compose preview and anything else that later
wants to speak a message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
from typing import Dict, List, Optional, Sequence, Tuple

from src.settings.settings import get_setting
from src.titan_core.translation import set_language

_ = set_language(get_setting('language', 'pl'))


# --------------------------------------------------------------------------- #
# Block kinds. A block is one navigable row in the reader.
# --------------------------------------------------------------------------- #
KIND_PARAGRAPH = 'paragraph'
KIND_HEADING = 'heading'
KIND_LIST = 'list_item'
KIND_QUOTE = 'quote'
KIND_CODE = 'code'
KIND_TABLE = 'table_row'
KIND_RULE = 'rule'
KIND_IMAGE = 'image'

FORMAT_PLAIN = 'plain'
FORMAT_MARKDOWN = 'markdown'
FORMAT_HTML = 'html'

CONTENT_TYPES = {
    FORMAT_PLAIN: 'text/plain',
    FORMAT_MARKDOWN: 'text/markdown',
    FORMAT_HTML: 'text/html',
}


def format_label(fmt: str) -> str:
    """The name of a body format, as the user hears it."""
    return {
        FORMAT_PLAIN: _("Plain text"),
        FORMAT_MARKDOWN: _("Markdown"),
        FORMAT_HTML: _("HTML"),
    }.get(fmt, fmt)


@dataclass
class Block:
    """One navigable piece of a message body."""

    kind: str = KIND_PARAGRAPH
    text: str = ''
    level: int = 0
    links: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def url(self) -> str:
        """The first link this block carries, if any."""
        return self.links[0][1] if self.links else ''

    def speak(self) -> str:
        """The row text: the block, plus what *kind* of block it is.

        The kind is spoken rather than shown as punctuation - "Heading level 2"
        is understandable, a row of hash marks is not.
        """
        text = self.text
        if self.kind == KIND_HEADING:
            return _("Heading level {level}: {text}").format(
                level=self.level or 1, text=text)
        if self.kind == KIND_LIST:
            return _("List item: {text}").format(text=text)
        if self.kind == KIND_QUOTE:
            return _("Quote: {text}").format(text=text)
        if self.kind == KIND_CODE:
            return _("Code: {text}").format(text=text)
        if self.kind == KIND_TABLE:
            return _("Table row: {text}").format(text=text)
        if self.kind == KIND_RULE:
            return _("Separator")
        if self.kind == KIND_IMAGE:
            return _("Image: {text}").format(text=text or _("no description"))
        if self.links and self.links[0][0] == text:
            return _("Link: {text}").format(text=text)
        return text

    def plain(self) -> str:
        """The block as plain text - what a reply quotes and Copy copies."""
        if self.kind == KIND_HEADING:
            return self.text
        if self.kind == KIND_LIST:
            return f"- {self.text}"
        if self.kind == KIND_QUOTE:
            return f"{'>' * max(1, self.level)} {self.text}"
        if self.kind == KIND_RULE:
            return '---'
        if self.kind == KIND_IMAGE:
            return f"[{_('Image')}: {self.text}]" if self.text else f"[{_('Image')}]"
        return self.text


@dataclass
class RenderedMail:
    """A parsed body: the rows, plus everything the reader's other tabs show."""

    fmt: str = FORMAT_PLAIN
    blocks: List[Block] = field(default_factory=list)
    links: List[Tuple[str, str]] = field(default_factory=list)
    images: List[Tuple[str, str]] = field(default_factory=list)

    def text(self) -> str:
        return '\n'.join(block.plain() for block in self.blocks).strip()

    def speech(self) -> str:
        return '\n'.join(block.speak() for block in self.blocks).strip()


# --------------------------------------------------------------------------- #
# Format detection
# --------------------------------------------------------------------------- #
_HTML_HINTS = re.compile(
    r'<\s*(?:html|body|div|p|br|table|tr|td|ul|ol|li|h[1-6]|blockquote|span|a\s|img\s)',
    re.IGNORECASE)
_HTML_DOCTYPE = re.compile(r'<!doctype\s+html', re.IGNORECASE)

_MD_STRONG = (
    re.compile(r'^\s{0,3}#{1,6}\s+\S', re.MULTILINE),      # heading
    re.compile(r'^\s*(?:```|~~~)', re.MULTILINE),           # fenced code
    re.compile(r'!?\[[^\]]*\]\([^)\s]+\)'),                 # link / image
    re.compile(r'^\s*\|.+\|\s*$', re.MULTILINE),            # table row
)
_MD_WEAK = (
    re.compile(r'^\s*[-*+]\s+\S', re.MULTILINE),            # bullet list
    re.compile(r'^\s*\d+[.)]\s+\S', re.MULTILINE),          # numbered list
    re.compile(r'\*\*[^*\n]+\*\*'),                         # bold
    re.compile(r'`[^`\n]+`'),                               # inline code
)

BARE_URL = re.compile(r'(?:https?://|www\.)[^\s<>"\')\]]+', re.IGNORECASE)


def absolute_url(url: str) -> str:
    """A URL that a browser (or an <a href>) can actually follow.

    Bodies are full of bare ``www.`` addresses; without a scheme they would be
    opened as a file path and written into outgoing HTML as a relative link.
    """
    url = (url or '').strip()
    if not url:
        return ''
    if url.lower().startswith('www.'):
        return f"http://{url}"
    if '@' in url and '://' not in url and not url.lower().startswith('mailto:'):
        return f"mailto:{url}"
    return url


def looks_like_html(source: str) -> bool:
    if not source:
        return False
    return bool(_HTML_DOCTYPE.search(source) or _HTML_HINTS.search(source))


def looks_like_markdown(source: str) -> bool:
    """Markdown needs real evidence.

    Ordinary mail is full of dashes and asterisks, so a single weak signal is
    not enough: either one unmistakable construct, or two weak ones.
    """
    if not source:
        return False
    if any(pattern.search(source) for pattern in _MD_STRONG):
        return True
    return sum(1 for pattern in _MD_WEAK if pattern.search(source)) >= 2


def detect_format(body: str, content_type: str = '', body_html: str = '') -> str:
    """What a stored body actually is.

    ``content_type`` is what the sender declared (a newer server keeps it);
    when it is missing - every message stored before this existed, and every
    message from a client that does not say - the body is sniffed instead.
    """
    declared = (content_type or '').lower()
    if body_html:
        return FORMAT_HTML
    if 'html' in declared:
        return FORMAT_HTML
    if 'markdown' in declared:
        return FORMAT_MARKDOWN
    if declared.startswith('text/plain'):
        # Trust an explicit text/plain, unless the body is plainly HTML that
        # some client mislabelled.
        return FORMAT_HTML if looks_like_html(body) else FORMAT_PLAIN
    if looks_like_html(body):
        return FORMAT_HTML
    if looks_like_markdown(body):
        return FORMAT_MARKDOWN
    return FORMAT_PLAIN


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
_SKIP_TAGS = {'script', 'style', 'head', 'title', 'meta', 'link', 'noscript'}
_FLUSH_TAGS = {'p', 'div', 'section', 'article', 'header', 'footer', 'main',
               'form', 'table', 'tbody', 'thead', 'tfoot', 'figure', 'figcaption',
               'dl', 'dt', 'dd', 'center', 'body'}
_HEADINGS = {f'h{level}': level for level in range(1, 7)}


class _HtmlToBlocks(HTMLParser):
    """HTML into blocks, tolerating anything (mail HTML is rarely well-formed)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: List[Block] = []
        self.links: List[Tuple[str, str]] = []
        self.images: List[Tuple[str, str]] = []
        self._buffer: List[str] = []
        self._buffer_links: List[Tuple[str, str]] = []
        self._skip = 0
        self._quote = 0
        self._pre = 0
        self._lists: List[List] = []
        self._anchors: List[Tuple[str, int]] = []
        self._pending = (KIND_PARAGRAPH, 0)

    # -- helpers ------------------------------------------------------------
    def _current_text(self) -> str:
        return ''.join(self._buffer)

    def _default_pending(self) -> Tuple[str, int]:
        if self._quote:
            return (KIND_QUOTE, self._quote)
        if self._pre:
            return (KIND_CODE, 0)
        return (KIND_PARAGRAPH, 0)

    def _flush(self) -> None:
        text = self._current_text()
        if self._pre:
            text = text.strip('\n').rstrip()
        else:
            text = re.sub(r'\s+', ' ', text).strip()
        kind, level = self._pending
        links = list(self._buffer_links)
        self._buffer = []
        self._buffer_links = []
        self._pending = self._default_pending()
        if not text:
            return
        if self._pre and kind == KIND_CODE:
            # A <pre> block keeps its own line structure - one row per line, so
            # the arrows still move through code a line at a time.
            for line in text.split('\n'):
                self.blocks.append(Block(KIND_CODE, line.rstrip(), 0, []))
            return
        self.blocks.append(Block(kind, text, level, links))

    def _emit(self, block: Block) -> None:
        self._flush()
        self.blocks.append(block)

    # -- parser callbacks ---------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        values = {name.lower(): (value or '') for name, value in attrs}

        if tag == 'br':
            self._flush()
            return
        if tag == 'hr':
            self._emit(Block(KIND_RULE, ''))
            return
        if tag == 'img':
            alt = (values.get('alt') or values.get('title') or '').strip()
            src = values.get('src', '').strip()
            if src or alt:
                self.images.append((alt, src))
            self._buffer.append(
                f" [{_('Image')}: {alt}] " if alt else f" [{_('Image')}] ")
            return
        if tag == 'a':
            href = values.get('href', '').strip()
            self._anchors.append((href, len(self._current_text())))
            return
        if tag in _HEADINGS:
            self._flush()
            self._pending = (KIND_HEADING, _HEADINGS[tag])
            return
        if tag in ('ul', 'ol'):
            self._flush()
            self._lists.append([tag, 0])
            return
        if tag == 'li':
            self._flush()
            depth = max(1, len(self._lists))
            self._pending = (KIND_LIST, depth)
            if self._lists and self._lists[-1][0] == 'ol':
                self._lists[-1][1] += 1
                self._buffer.append(f"{self._lists[-1][1]}. ")
            return
        if tag == 'blockquote':
            self._flush()
            self._quote += 1
            self._pending = self._default_pending()
            return
        if tag in ('pre', 'code') and tag == 'pre':
            self._flush()
            self._pre += 1
            self._pending = self._default_pending()
            return
        if tag == 'tr':
            self._flush()
            self._pending = (KIND_TABLE, 0)
            return
        if tag in ('td', 'th'):
            if self._current_text().strip():
                self._buffer.append(' | ')
            return
        if tag in _FLUSH_TAGS:
            self._flush()

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == 'a':
            if self._anchors:
                href, start = self._anchors.pop()
                label = self._current_text()[start:].strip()
                label = re.sub(r'\s+', ' ', label)
                if href and not href.lower().startswith(('javascript:', '#')):
                    entry = (label or href, href)
                    self._buffer_links.append(entry)
                    self.links.append(entry)
                    if not label:
                        self._buffer.append(href)
            return
        if tag in ('ul', 'ol'):
            self._flush()
            if self._lists:
                self._lists.pop()
            return
        if tag == 'blockquote':
            self._flush()
            self._quote = max(0, self._quote - 1)
            self._pending = self._default_pending()
            return
        if tag == 'pre':
            self._flush()
            self._pre = max(0, self._pre - 1)
            self._pending = self._default_pending()
            return
        if tag in _HEADINGS or tag in ('li', 'tr') or tag in _FLUSH_TAGS:
            self._flush()

    def handle_data(self, data):
        if self._skip:
            return
        self._buffer.append(data)

    def finish(self) -> None:
        self._flush()


def html_to_blocks(source: str) -> Tuple[List[Block], List[Tuple[str, str]],
                                         List[Tuple[str, str]]]:
    """Parse HTML into (blocks, links, images). Never raises."""
    parser = _HtmlToBlocks()
    try:
        parser.feed(source or '')
        parser.close()
    except Exception as exc:  # malformed HTML must still produce something
        print(f"[Mail] HTML parse stopped early: {exc}")
    try:
        parser.finish()
    except Exception:
        pass
    if not parser.blocks:
        # Nothing survived (a body that is one giant unclosed tag, say): fall
        # back to the tags-stripped text rather than showing an empty message.
        stripped = re.sub(r'(?s)<[^>]*>', ' ', source or '')
        stripped = re.sub(r'\s+', ' ', stripped).strip()
        if stripped:
            return [Block(KIND_PARAGRAPH, stripped)], [], []
    return parser.blocks, parser.links, parser.images


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
_MD_LINK = re.compile(r'(!?)\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)')
_MD_AUTOLINK = re.compile(r'<((?:https?://|mailto:)[^>\s]+)>', re.IGNORECASE)
_MD_EMPHASIS = (
    (re.compile(r'\*\*\*(.+?)\*\*\*', re.DOTALL), r'\1'),
    (re.compile(r'\*\*(.+?)\*\*', re.DOTALL), r'\1'),
    (re.compile(r'(?<!\w)_{2}(.+?)_{2}(?!\w)', re.DOTALL), r'\1'),
    (re.compile(r'(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)', re.DOTALL), r'\1'),
    (re.compile(r'(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)'), r'\1'),
    (re.compile(r'~~(.+?)~~', re.DOTALL), r'\1'),
    (re.compile(r'`([^`]+)`'), r'\1'),
)


def strip_emphasis(text: str) -> str:
    """Drop the markers that only exist to make text bold/italic on screen."""
    for pattern, replacement in _MD_EMPHASIS:
        text = pattern.sub(replacement, text)
    return text


def _inline(text: str, links: List[Tuple[str, str]],
            images: List[Tuple[str, str]]) -> Tuple[str, List[Tuple[str, str]]]:
    """Resolve inline Markdown: links, images, emphasis, bare URLs."""
    local: List[Tuple[str, str]] = []

    def _replace(match):
        bang, label, url = match.group(1), match.group(2).strip(), match.group(3).strip()
        if bang:
            images.append((label, url))
            return f"[{_('Image')}: {label}]" if label else f"[{_('Image')}]"
        entry = (label or url, url)
        local.append(entry)
        return label or url

    text = _MD_LINK.sub(_replace, text)

    def _autolink(match):
        url = match.group(1)
        local.append((url, url))
        return url

    text = _MD_AUTOLINK.sub(_autolink, text)
    text = strip_emphasis(text)

    known = {url for _label, url in local}
    for url in BARE_URL.findall(text):
        url = url.rstrip('.,;:!?')
        if url not in known:
            known.add(url)
            local.append((url, url))

    links.extend(local)
    return text.strip(), local


def markdown_to_blocks(source: str) -> Tuple[List[Block], List[Tuple[str, str]],
                                             List[Tuple[str, str]]]:
    """Parse Markdown into (blocks, links, images). Never raises."""
    blocks: List[Block] = []
    links: List[Tuple[str, str]] = []
    images: List[Tuple[str, str]] = []
    lines = (source or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    paragraph: List[str] = []

    def flush_paragraph():
        if not paragraph:
            return
        joined = ' '.join(part.strip() for part in paragraph).strip()
        paragraph.clear()
        if joined:
            text, local = _inline(joined, links, images)
            if text:
                blocks.append(Block(KIND_PARAGRAPH, text, 0, local))

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        fence = stripped[:3]
        if fence in ('```', '~~~'):
            flush_paragraph()
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(fence):
                blocks.append(Block(KIND_CODE, lines[index].rstrip()))
                index += 1
            index += 1
            continue

        if not stripped:
            flush_paragraph()
            index += 1
            continue

        heading = re.match(r'^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$', line)
        if heading:
            flush_paragraph()
            text, local = _inline(heading.group(2), links, images)
            blocks.append(Block(KIND_HEADING, text, len(heading.group(1)), local))
            index += 1
            continue

        if re.match(r'^\s{0,3}([-*_])(?:\s*\1){2,}\s*$', line):
            flush_paragraph()
            blocks.append(Block(KIND_RULE, ''))
            index += 1
            continue

        if stripped.startswith('>'):
            flush_paragraph()
            depth = 0
            rest = stripped
            while rest.startswith('>'):
                depth += 1
                rest = rest[1:].lstrip()
            text, local = _inline(rest, links, images)
            blocks.append(Block(KIND_QUOTE, text, depth, local))
            index += 1
            continue

        bullet = re.match(r'^(\s*)[-*+]\s+(.*)$', line)
        if bullet:
            flush_paragraph()
            text, local = _inline(bullet.group(2), links, images)
            depth = 1 + len(bullet.group(1)) // 2
            blocks.append(Block(KIND_LIST, text, depth, local))
            index += 1
            continue

        numbered = re.match(r'^(\s*)(\d+)[.)]\s+(.*)$', line)
        if numbered:
            flush_paragraph()
            text, local = _inline(numbered.group(3), links, images)
            depth = 1 + len(numbered.group(1)) // 2
            blocks.append(Block(KIND_LIST, f"{numbered.group(2)}. {text}", depth, local))
            index += 1
            continue

        if stripped.startswith('|') and stripped.endswith('|') and len(stripped) > 2:
            cells = [cell.strip() for cell in stripped.strip('|').split('|')]
            if cells and all(re.match(r'^:?-{2,}:?$', cell) for cell in cells if cell):
                index += 1  # the |---|---| separator row carries no content
                continue
            flush_paragraph()
            text, local = _inline(' | '.join(cells), links, images)
            blocks.append(Block(KIND_TABLE, text, 0, local))
            index += 1
            continue

        if index + 1 < len(lines) and re.match(r'^\s{0,3}(=+|-+)\s*$', lines[index + 1]):
            flush_paragraph()
            level = 1 if lines[index + 1].strip().startswith('=') else 2
            text, local = _inline(stripped, links, images)
            blocks.append(Block(KIND_HEADING, text, level, local))
            index += 2
            continue

        paragraph.append(line)
        index += 1

    flush_paragraph()
    return blocks, links, images


# --------------------------------------------------------------------------- #
# Plain text
# --------------------------------------------------------------------------- #
def plain_to_blocks(source: str) -> Tuple[List[Block], List[Tuple[str, str]],
                                          List[Tuple[str, str]]]:
    """Plain text: one row per line, with quoted lines recognised as quotes.

    Lines are kept as they arrived rather than re-wrapped into paragraphs -
    mail is hard-wrapped, and a signature or a table only survives line by line.
    """
    blocks: List[Block] = []
    links: List[Tuple[str, str]] = []
    blank = False
    for raw in (source or '').replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        line = raw.rstrip()
        if not line.strip():
            blank = True
            continue
        if blank and blocks:
            blank = False
        stripped = line.strip()
        local: List[Tuple[str, str]] = []
        for url in BARE_URL.findall(stripped):
            url = url.rstrip('.,;:!?')
            entry = (url, url)
            local.append(entry)
            links.append(entry)
        if stripped.startswith('>'):
            depth = 0
            rest = stripped
            while rest.startswith('>'):
                depth += 1
                rest = rest[1:].lstrip()
            blocks.append(Block(KIND_QUOTE, rest, depth, local))
        else:
            blocks.append(Block(KIND_PARAGRAPH, stripped, 0, local))
    return blocks, links, []


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #
def render(body: str, content_type: str = '', body_html: str = '',
           fmt: str = '') -> RenderedMail:
    """Parse a stored body into rows the reader can navigate.

    ``fmt`` forces a format (the compose preview does this); otherwise it is
    detected from the declared content type, falling back to sniffing.
    """
    fmt = fmt or detect_format(body, content_type, body_html)
    source = body_html if (fmt == FORMAT_HTML and body_html) else (body or '')
    try:
        if fmt == FORMAT_HTML:
            blocks, links, images = html_to_blocks(source)
        elif fmt == FORMAT_MARKDOWN:
            blocks, links, images = markdown_to_blocks(source)
        else:
            blocks, links, images = plain_to_blocks(source)
    except Exception as exc:
        print(f"[Mail] rendering failed ({fmt}): {exc}")
        blocks, links, images = plain_to_blocks(source)
        fmt = FORMAT_PLAIN

    # Deduplicate links while keeping the order they appear in.
    seen = set()
    unique_links = []
    for label, url in links:
        if url and url not in seen:
            seen.add(url)
            unique_links.append((label, url))
    return RenderedMail(fmt=fmt, blocks=blocks, links=unique_links, images=images)


def to_plain_text(body: str, content_type: str = '', body_html: str = '') -> str:
    """A body reduced to readable plain text (used when quoting a reply)."""
    return render(body, content_type, body_html).text()


def quote_body(body: str, content_type: str = '', body_html: str = '',
               author: str = '') -> str:
    """The quoted block a reply starts with."""
    text = to_plain_text(body, content_type, body_html)
    quoted = '\n'.join(f"> {line}" for line in text.split('\n'))
    header = _("{author} wrote:").format(author=author) if author else ''
    return f"\n\n{header}\n{quoted}\n" if header else f"\n\n{quoted}\n"


# --------------------------------------------------------------------------- #
# Outgoing: a composed body turned into the HTML alternative that leaves Titan
# --------------------------------------------------------------------------- #
def _wrap_html(inner: str) -> str:
    return ('<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>'
            f'{inner}</body></html>')


def blocks_to_html(blocks: Sequence[Block]) -> str:
    """Render blocks back to simple, valid HTML (no styling, no scripts)."""
    parts: List[str] = []
    open_list: Optional[str] = None
    open_quote = False

    def close_list():
        nonlocal open_list
        if open_list:
            parts.append(f'</{open_list}>')
            open_list = None

    def close_quote():
        nonlocal open_quote
        if open_quote:
            parts.append('</blockquote>')
            open_quote = False

    def linked(block: Block) -> str:
        text = escape(block.text)
        for label, url in block.links:
            if not label:
                continue
            anchor = f'<a href="{escape(absolute_url(url), quote=True)}">{escape(label)}</a>'
            text = text.replace(escape(label), anchor, 1)
        return text

    for index, block in enumerate(blocks):
        if block.kind != KIND_LIST:
            close_list()
        if block.kind != KIND_QUOTE:
            close_quote()

        if block.kind == KIND_HEADING:
            level = min(6, max(1, block.level or 1))
            parts.append(f'<h{level}>{linked(block)}</h{level}>')
        elif block.kind == KIND_LIST:
            ordered = bool(re.match(r'^\d+\.\s', block.text))
            wanted = 'ol' if ordered else 'ul'
            if open_list != wanted:
                close_list()
                parts.append(f'<{wanted}>')
                open_list = wanted
            text = re.sub(r'^\d+\.\s+', '', block.text) if ordered else block.text
            parts.append(f'<li>{linked(Block(block.kind, text, block.level, block.links))}</li>')
        elif block.kind == KIND_QUOTE:
            if not open_quote:
                parts.append('<blockquote>')
                open_quote = True
            parts.append(f'<p>{linked(block)}</p>')
        elif block.kind == KIND_CODE:
            # Consecutive code rows are one <pre> again: they were split into
            # rows only so the arrows can walk through the listing.
            if index and blocks[index - 1].kind == KIND_CODE and parts:
                parts[-1] = parts[-1][:-len('</code></pre>')] + \
                    f'\n{escape(block.text)}</code></pre>'
            else:
                parts.append(f'<pre><code>{escape(block.text)}</code></pre>')
        elif block.kind == KIND_TABLE:
            cells = ''.join(f'<td>{escape(cell.strip())}</td>'
                            for cell in block.text.split('|'))
            parts.append(f'<table><tr>{cells}</tr></table>')
        elif block.kind == KIND_RULE:
            parts.append('<hr>')
        else:
            parts.append(f'<p>{linked(block)}</p>')

    close_list()
    close_quote()
    return _wrap_html(''.join(parts))


def plain_to_html(source: str) -> str:
    """Plain text as HTML, preserving the line breaks the author typed."""
    body = escape(source or '').replace('\n', '<br>')
    return _wrap_html(f'<p>{body}</p>')


def markdown_to_html(source: str) -> str:
    blocks, _links, _images = markdown_to_blocks(source)
    return blocks_to_html(blocks)


def build_outgoing(body: str, fmt: str) -> Dict[str, str]:
    """What the client sends for a composed message.

    Always includes a readable plain-text ``body``: an old server, an old
    client, and every mail program that refuses HTML all fall back to it. The
    HTML alternative is sent alongside so a normal mail client shows the
    formatting the author intended.
    """
    fmt = fmt if fmt in CONTENT_TYPES else FORMAT_PLAIN
    if fmt == FORMAT_HTML:
        rendered = render(body, fmt=FORMAT_HTML)
        return {'body': rendered.text(), 'body_html': body,
                'content_type': CONTENT_TYPES[FORMAT_HTML]}
    if fmt == FORMAT_MARKDOWN:
        return {'body': body, 'body_html': markdown_to_html(body),
                'content_type': CONTENT_TYPES[FORMAT_MARKDOWN]}
    return {'body': body, 'body_html': '', 'content_type': CONTENT_TYPES[FORMAT_PLAIN]}
