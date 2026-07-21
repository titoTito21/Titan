"""Lightweight, dependency-light web search for the AI creation kit.

Lets the generator optionally pull real, current reference material from the
internet (library APIs, error messages, examples) before producing an add-on.
Uses the DuckDuckGo HTML endpoint via ``requests`` (already a Titan dependency)
so no API key is required. Every function is best-effort: on any failure it
returns an empty result rather than raising, so a search outage never blocks
generation.
"""

import html
import re

_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/120.0 Safari/537.36'),
}

_DDG_HTML = 'https://html.duckduckgo.com/html/'

# DuckDuckGo HTML result anchors and snippets.
_RESULT_A = re.compile(
    r'<a[^>]+class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.S)
_SNIPPET = re.compile(
    r'<a[^>]+class="result__snippet"[^>]*>(?P<snip>.*?)</a>', re.S)


def _strip_html(text):
    text = re.sub(r'<[^>]+>', '', text or '')
    return html.unescape(text).strip()


def _clean_ddg_url(url):
    """DuckDuckGo wraps result links in a redirect (uddg=<encoded>); unwrap it."""
    m = re.search(r'[?&]uddg=([^&]+)', url or '')
    if m:
        from urllib.parse import unquote
        return unquote(m.group(1))
    return url


def search(query, max_results=5, timeout=12):
    """Return up to ``max_results`` results as [{'title', 'url', 'snippet'}].

    Never raises: returns [] if requests is unavailable, the query is empty, or
    anything goes wrong with the network/parse."""
    query = (query or '').strip()
    if not query:
        return []
    try:
        import requests
    except Exception:
        return []
    try:
        resp = requests.post(_DDG_HTML, data={'q': query},
                             headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        body = resp.text
    except Exception as e:
        print(f"[web_search] search failed: {e}")
        return []

    titles = list(_RESULT_A.finditer(body))
    snippets = [_strip_html(m.group('snip')) for m in _SNIPPET.finditer(body)]
    results = []
    for i, m in enumerate(titles):
        if len(results) >= max_results:
            break
        title = _strip_html(m.group('title'))
        url = _clean_ddg_url(m.group('url'))
        if not title or not url:
            continue
        snippet = snippets[i] if i < len(snippets) else ''
        results.append({'title': title, 'url': url, 'snippet': snippet})
    return results


def fetch_page_text(url, timeout=12, max_chars=6000):
    """Fetch a URL and return its de-tagged text (capped). '' on any failure."""
    try:
        import requests
    except Exception:
        return ''
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        body = resp.text
    except Exception as e:
        print(f"[web_search] fetch failed for {url}: {e}")
        return ''
    # Drop scripts/styles, then strip tags and collapse whitespace.
    body = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', body)
    text = re.sub(r'(?s)<[^>]+>', ' ', body)
    text = html.unescape(text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n\s*', '\n\n', text).strip()
    return text[:max_chars]


def format_results_for_prompt(results):
    """Render search results as a compact block for the system prompt. '' if
    there are none."""
    if not results:
        return ''
    lines = ["# Web search results (for reference; verify before relying on them)"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}\n   {r['url']}")
        if r.get('snippet'):
            lines.append(f"   {r['snippet']}")
    return "\n".join(lines)
