"""Extra tools that give the voice assistant its everyday abilities on top of
the computer-use agent: web search, weather, music playback and launching Titan
(TCE) apps and games by name in natural language.

Tools use the same dict shape as :mod:`src.ai.agent_tools` so they can be handed
straight to :func:`src.ai.ai_agent.run_agent`. The assistant's full toolset is
:func:`get_assistant_tools` = the computer-use tools + these.
"""

from src.ai.agent_tools import _tool, get_tools as _get_computer_tools


# --------------------------------------------------------------------------- #
# Web search (risk: auto)
# --------------------------------------------------------------------------- #
def web_search_tool(query, **_):
    """Search the web and return the top results as text."""
    try:
        from src.ai import web_search
        results = web_search.search(query, max_results=5)
        if not results:
            return "No web results found."
        return web_search.format_results_for_prompt(results)
    except Exception as e:
        return f"Web search failed: {e}"


# --------------------------------------------------------------------------- #
# Online definitions / meanings (risk: auto) - via Wikipedia, no API key
# --------------------------------------------------------------------------- #
def _wiki_summary(term, lang):
    import requests
    from urllib.parse import quote
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(term)}"
    resp = requests.get(url, headers={'User-Agent': 'Titan/1.0'}, timeout=12)
    if resp.status_code != 200:
        return None
    data = resp.json()
    if data.get('type') == 'disambiguation':
        return None
    extract = (data.get('extract') or '').strip()
    if not extract:
        return None
    return f"{data.get('title') or term}: {extract}"


def get_definition(term, **_):
    """Look up the definition / meaning of a word, term or topic online
    (Wikipedia), in the user's language with an English fallback."""
    term = (term or '').strip()
    if not term:
        return "Give a word or term to define."
    try:
        from src.settings.settings import get_setting
        lang = (get_setting('language', 'pl') or 'pl').split('_')[0]
    except Exception:
        lang = 'pl'
    langs = [lang] + (['en'] if lang != 'en' else [])
    for lg in langs:
        try:
            result = _wiki_summary(term, lg)
        except Exception:
            result = None
        if result:
            return result
    try:
        return "No direct definition found. Web results:\n" + web_search_tool(term)
    except Exception:
        return f"Could not find a definition for '{term}'."


# --------------------------------------------------------------------------- #
# Weather (risk: auto) - via wttr.in, no API key required
# --------------------------------------------------------------------------- #
def get_weather(location="", **_):
    """Return the current weather for ``location`` (city name). If empty, uses
    the caller's approximate location (wttr.in geolocates by IP)."""
    try:
        import requests
        loc = (location or '').strip()
        url = f"https://wttr.in/{loc}?format=j1"
        resp = requests.get(url, headers={'User-Agent': 'curl/8'}, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        cur = (data.get('current_condition') or [{}])[0]
        area = (data.get('nearest_area') or [{}])[0]
        place = ''
        try:
            place = area.get('areaName', [{}])[0].get('value', '') or loc
        except Exception:
            place = loc
        desc = ''
        try:
            desc = cur.get('weatherDesc', [{}])[0].get('value', '')
        except Exception:
            pass
        temp = cur.get('temp_C', '?')
        feels = cur.get('FeelsLikeC', '?')
        humidity = cur.get('humidity', '?')
        wind = cur.get('windspeedKmph', '?')
        return (f"Weather in {place or 'your area'}: {desc}, {temp} degrees C "
                f"(feels like {feels}), humidity {humidity}%, wind {wind} km/h.")
    except Exception as e:
        return f"Could not get the weather: {e}"


# --------------------------------------------------------------------------- #
# Launch Titan (TCE) apps and games by name (risk: confirm)
# --------------------------------------------------------------------------- #
def _all_tce_items():
    """Return [(kind, name, info, opener), ...] for every launchable app/game."""
    items = []
    try:
        from src.titan_core import app_manager
        for info in app_manager.get_applications():
            name = info.get('name') or info.get('shortname') or ''
            if name:
                items.append(('app', name, info, app_manager.open_application))
    except Exception as e:
        print(f"[assistant_tools] could not list applications: {e}")
    try:
        from src.titan_core import game_manager
        for info in game_manager.get_games():
            name = info.get('name') or ''
            if name:
                items.append(('game', name, info, game_manager.open_game))
    except Exception as e:
        print(f"[assistant_tools] could not list games: {e}")
    return items


def list_tce_items(**_):
    """List the Titan apps and games that can be launched by name."""
    items = _all_tce_items()
    if not items:
        return "No Titan apps or games are available."
    apps = [n for k, n, _i, _o in items if k == 'app']
    games = [n for k, n, _i, _o in items if k == 'game']
    out = []
    if apps:
        out.append("Apps: " + ", ".join(sorted(apps)))
    if games:
        out.append("Games: " + ", ".join(sorted(games)))
    return "\n".join(out)


def _find_item(name):
    """Best-effort match of a spoken name to an app/game (exact, then substring)."""
    q = (name or '').strip().lower()
    if not q:
        return None
    items = _all_tce_items()
    for entry in items:  # exact
        if entry[1].lower() == q:
            return entry
    for entry in items:  # substring
        if q in entry[1].lower() or entry[1].lower() in q:
            return entry
    return None


def launch_tce_item(name, **_):
    """Launch a Titan app or game by (approximate) name."""
    entry = _find_item(name)
    if not entry:
        return (f"No Titan app or game matching '{name}'. Use list_tce_items to "
                f"see what is available.")
    kind, item_name, info, opener = entry
    try:
        opener(info)
        return f"Launching the {kind} '{item_name}'."
    except Exception as e:
        return f"Could not launch '{item_name}': {e}"


# --------------------------------------------------------------------------- #
# Play music (risk: confirm) - Titan's media player (tMedia), YouTube Music,
# Spotify, or web radio.
# --------------------------------------------------------------------------- #
def _open_url(url):
    """Open a URL (or app URI) with the OS default handler, cross-platform."""
    import sys
    import subprocess
    if sys.platform == 'win32':
        import os
        os.startfile(url)  # noqa: intended - default handler
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', url])
    else:
        subprocess.Popen(['xdg-open', url])


def _open_tmedia(initial=None):
    """Open Titan's own media player (tMedia), optionally with a startup argument
    (``ytsearch:<query>`` makes tMedia search YouTube and auto-play the first
    result). Returns True if tMedia was found and launched."""
    try:
        from src.titan_core import app_manager
        for info in app_manager.get_applications():
            name = (info.get('name') or '') + ' ' + (info.get('shortname') or '')
            if ('tmedia' in name.lower() or 'media' in name.lower()
                    or info.get('shortname') == 'media'):
                app_manager.open_application(info, file_path=initial)
                return True
    except Exception as e:
        print(f"[assistant_tools] tMedia launch failed: {e}")
    return False


def _sanitize_for_arg(text):
    """Titan passes an app's startup argument by inlining it into generated code
    as r'...'; a quote or backslash in it would break that. Music/YouTube search
    is fuzzy, so we can safely drop those characters."""
    return (text or '').replace("'", ' ').replace('"', ' ').replace('\\', ' ').strip()


# Accepted 'source' values (normalised) -> canonical.
_MUSIC_SOURCES = {
    'tmedia': 'tmedia', 'titan': 'tmedia', 'media': 'tmedia', 'local': 'tmedia',
    'youtube': 'youtube', 'yt': 'youtube', 'youtube_music': 'youtube',
    'youtubemusic': 'youtube', 'ytmusic': 'youtube', 'music': 'youtube',
    'spotify': 'spotify',
    'radio': 'radio', 'tunein': 'radio',
}


def play_music(query="", source="", **_):
    """Play music. ``source`` chooses where: 'tmedia' (Titan's own player, the
    default; it also has YouTube search and internet radio built in),
    'youtube' (YouTube Music), 'spotify', or 'radio' (internet radio). ``query``
    is the artist / track / station / genre to look for."""
    from urllib.parse import quote
    q = (query or '').strip()
    enc = quote(q) if q else ''
    src = _MUSIC_SOURCES.get((source or '').strip().lower().replace(' ', '_'),
                             '' if not source else 'youtube')

    # Default OR a YouTube request: play inside Titan's own player (tMedia),
    # which has local files, YouTube search and radio built in. With a query it
    # searches YouTube and auto-plays the first match - keeping playback inside
    # Titan. Only when tMedia is NOT installed do we fall back to the web player.
    if src in ('', 'tmedia', 'youtube'):
        initial = f"ytsearch:{_sanitize_for_arg(q)}" if q else None
        if _open_tmedia(initial):
            if q:
                return f"Playing '{q}' in the Titan media player (tMedia)."
            return "Opening the Titan media player (tMedia)."
        src = 'youtube'  # tMedia not installed -> fall back to the web

    if src == 'youtube':
        url = (f"https://music.youtube.com/search?q={enc}" if q
               else "https://music.youtube.com/")
        try:
            _open_url(url)
            return f"Playing '{q or 'music'}' on YouTube Music."
        except Exception as e:
            return f"Could not open YouTube Music: {e}"

    if src == 'spotify':
        # Prefer the desktop app via its URI scheme, fall back to the web player.
        try:
            _open_url(f"spotify:search:{enc}" if q else "spotify:")
            return f"Opening Spotify for '{q or 'music'}'."
        except Exception:
            try:
                _open_url(f"https://open.spotify.com/search/{enc}" if q
                          else "https://open.spotify.com/")
                return f"Opening Spotify for '{q or 'music'}'."
            except Exception as e:
                return f"Could not open Spotify: {e}"

    if src == 'radio':
        url = (f"https://tunein.com/search/?query={enc}" if q
               else "https://tunein.com/")
        try:
            _open_url(url)
            return f"Opening internet radio{(' for ' + q) if q else ''}."
        except Exception as e:
            return f"Could not open radio: {e}"

    return f"Unknown music source '{source}'. Try tmedia, youtube, spotify or radio."


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def get_assistant_only_tools():
    """The assistant-specific tools (excludes the shared computer-use tools)."""
    S = {'type': 'string'}
    return [
        _tool('web_search', "Search the web and return top results as text.",
              web_search_tool, properties={'query': dict(S, description="Search query.")},
              required=['query']),
        _tool('get_weather',
              "Get the current weather for a city (or the local area if omitted).",
              get_weather,
              properties={'location': dict(S, description="City name (optional).")}),
        _tool('get_definition',
              "Look up the definition or meaning of a word, term or topic online.",
              get_definition,
              properties={'term': dict(S, description="Word or term to define.")},
              required=['term']),
        _tool('list_tce_items',
              "List the Titan apps and games that can be launched by name.",
              list_tce_items),
        _tool('launch_tce_item',
              "Launch a Titan app or game by name.", launch_tce_item,
              risk='confirm',
              properties={'name': dict(S, description="App or game name.")},
              required=['name']),
        _tool('play_music',
              "Play music. YouTube and the user's own files play INSIDE Titan's "
              "media player (tMedia, which has YouTube search built in); only if "
              "tMedia is not installed does YouTube open in the web browser.",
              play_music, risk='confirm',
              properties={'query': dict(S, description="Artist, track, station or genre (optional)."),
                          'source': dict(S, description="tmedia (default), youtube, spotify or radio.")}),
    ]


# --------------------------------------------------------------------------- #
# Interactive follow-up question (risk: auto) - lets the assistant PLAN by
# gathering missing details from the user before it acts.
# --------------------------------------------------------------------------- #
def make_ask_user_tool(ask_fn):
    """Build an ``ask_user`` tool bound to ``ask_fn(question) -> answer|None``.

    ``ask_fn`` is supplied by the caller so the SAME tool works by voice (speak
    the question, record and transcribe the spoken answer) or by text (a dialog).
    It may raise :class:`~src.ai.ai_agent.AgentCancelled` to abort the turn."""

    def ask_user(question, **_):
        q = (question or '').strip()
        if not q:
            return "No question was provided to ask."
        try:
            answer = ask_fn(q)
        except BaseException as e:
            # Let cancellation abort the whole run; report anything else.
            from src.ai.ai_agent import AgentCancelled
            if isinstance(e, AgentCancelled):
                raise
            return f"Could not get an answer from the user: {e}"
        answer = (answer or '').strip() if isinstance(answer, str) else answer
        if not answer:
            return ("The user did not answer. Ask again more simply, or proceed "
                    "with a sensible default and tell them what you assumed.")
        return f"The user answered: {answer}"

    S = {'type': 'string'}
    return _tool(
        'ask_user',
        "Ask the user a follow-up question OUT LOUD and get their spoken answer. "
        "Use this to collect the details you still need for a complex request - "
        "for example the date and time of a reminder, who to message and what to "
        "say, or the values for a form - BEFORE you carry the action out. Ask "
        "ONE short, clear question at a time and call this again for the next "
        "missing detail; keep asking until you have everything, then act.",
        ask_user,
        properties={'question': dict(S, description="The question to ask the user.")},
        required=['question'])


def get_assistant_tools(ask_user=None):
    """Full assistant toolset: computer-use agent tools + the assistant tools.

    ``ask_user`` (a callable ``question -> answer``) enables the interactive
    follow-up-question tool, so the assistant can gather missing details before
    acting; omit it to leave that ability out."""
    tools = list(_get_computer_tools()) + get_assistant_only_tools()
    if ask_user is not None:
        tools.append(make_ask_user_tool(ask_user))
    return tools
