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
# Play music (risk: confirm) - hands off to Titan's media player (tMedia)
# --------------------------------------------------------------------------- #
def play_music(query="", **_):
    """Play music. Opens Titan's media player (tMedia); ``query`` is passed along
    when the player is available, otherwise falls back to a web music search."""
    try:
        from src.titan_core import app_manager
        for info in app_manager.get_applications():
            name = (info.get('name') or '') + ' ' + (info.get('shortname') or '')
            if 'tmedia' in name.lower() or 'media' in name.lower():
                app_manager.open_application(info)
                extra = f" (search: {query})" if query else ''
                return f"Opening the Titan media player{extra}."
    except Exception as e:
        print(f"[assistant_tools] media launch failed: {e}")
    # Fallback: open a web music search with the default handler.
    try:
        import os
        from urllib.parse import quote
        q = quote(query or 'music')
        os.startfile(f"https://www.youtube.com/results?search_query={q}")  # noqa
        return f"Opening a web music search for '{query or 'music'}'."
    except Exception as e:
        return f"Could not play music: {e}"


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
        _tool('list_tce_items',
              "List the Titan apps and games that can be launched by name.",
              list_tce_items),
        _tool('launch_tce_item',
              "Launch a Titan app or game by name.", launch_tce_item,
              risk='confirm',
              properties={'name': dict(S, description="App or game name.")},
              required=['name']),
        _tool('play_music',
              "Play music by opening the Titan media player (or a web search).",
              play_music, risk='confirm',
              properties={'query': dict(S, description="Artist, track or query (optional).")}),
    ]


def get_assistant_tools():
    """Full assistant toolset: computer-use agent tools + the assistant tools."""
    return list(_get_computer_tools()) + get_assistant_only_tools()
