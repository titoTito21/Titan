"""Titan-native tools for the AI agent and the voice assistant.

Where :mod:`src.ai.agent_tools` gives the AI generic control of the *computer*
(windows, mouse, keyboard, files), this module gives it control of *Titan
itself*: its settings, its components and their actions, and every kind of
add-on (applications, games, components, launchers, Titan IM modules, gamepad
modes, TTS engines, widgets, statusbar applets, languages).

Both the standalone agent and the assistant get these tools automatically -
:func:`src.ai.agent_tools.get_tools` appends :func:`get_titan_tools`.

Tools follow the same dict shape and risk tiers as ``agent_tools``. Observation
(list/get) is ``auto``; anything that changes state (writing a setting, running
a component action, launching an add-on, toggling a component) is ``confirm`` so
it is gated by the agent confirmation policy.
"""

import json
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, quote, unquote, urlparse
from urllib.request import url2pathname

# --------------------------------------------------------------------------- #
# GUI-thread helper
# --------------------------------------------------------------------------- #
def _run_on_gui(fn, timeout=20):
    """Run ``fn`` on the wx main thread and return (ok, result_or_error).

    Titan's components / windows must be touched on the GUI thread; the agent
    runs on a worker thread, so we marshal across and wait for the result."""
    import wx
    if wx.IsMainThread():
        try:
            return True, fn()
        except Exception as e:
            return False, str(e)
    box = {}
    done = threading.Event()

    def _do():
        try:
            box['result'] = fn()
        except Exception as e:
            box['error'] = str(e)
        finally:
            done.set()

    wx.CallAfter(_do)
    if not done.wait(timeout):
        return False, "timed out waiting for the Titan UI"
    if 'error' in box:
        return False, box['error']
    return True, box.get('result')


def _find_main_frame():
    """The main Titan frame that owns the component manager / invisible UI."""
    try:
        import wx
    except Exception:
        return None
    best = None
    for w in wx.GetTopLevelWindows():
        if getattr(w, 'component_manager', None) is not None:
            return w
        if getattr(w, 'invisible_ui', None) is not None:
            best = best or w
    return best


def _component_manager():
    frame = _find_main_frame()
    return getattr(frame, 'component_manager', None) if frame else None


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
# Substrings that mark a value as sensitive. Deliberately specific so ordinary
# keys like 'assistant_hotkey' (a keyboard shortcut, not a secret) are NOT hidden.
_SECRET_HINTS = ('api_key', 'apikey', '_key', 'token', 'password', 'passwd',
                 'secret', 'credential', 'private_key')


def _is_secret(key):
    k = (key or '').lower()
    return any(h in k for h in _SECRET_HINTS)


def _redact(key, value):
    if _is_secret(key) and value:
        return "(hidden)"
    return value


def titan_list_settings(section=None, **_):
    """List Titan settings. Secret-looking values (keys, tokens, passwords) are
    hidden. Pass ``section`` to list just one section."""
    try:
        from src.settings.settings import load_settings
        data = load_settings()
    except Exception as e:
        return f"Could not read settings: {e}"
    if not data:
        return "No settings are stored yet."
    sections = [section] if section else sorted(data.keys())
    out = []
    for sec in sections:
        values = data.get(sec)
        if values is None:
            out.append(f"[{sec}] (no such section)")
            continue
        out.append(f"[{sec}]")
        for k, v in values.items():
            out.append(f"  {k} = {_redact(k, v)}")
    return "\n".join(out) if out else "No settings found."


def titan_get_setting(key, section="general", **_):
    """Get one Titan setting value from a section (default 'general')."""
    try:
        from src.settings.settings import get_setting
        val = get_setting(key, None, section=section)
    except Exception as e:
        return f"Could not read setting: {e}"
    if val is None:
        return f"Setting {section}.{key} is not set."
    return f"{section}.{key} = {_redact(key, val)}"


def _apply_live_setting(section, key, value):
    """Best-effort: make a just-written setting take effect immediately, mirroring
    what the Settings dialog does on save. Returns a list of what was refreshed.
    Every step is guarded so a failure never breaks the write."""
    notes = []
    s = (section or '').lower()
    k = (key or '').lower()

    # Sound theme / volume.
    if s == 'sound':
        try:
            from src.titan_core import sound
            if k == 'theme':
                sound.set_theme(value)
                notes.append('sound theme')
            elif k in ('theme_volume', 'volume'):
                sound.set_sound_theme_volume(int(float(value)))
                notes.append('sound volume')
        except Exception:
            pass

    # Titan TTS / stereo speech (engine, voice, or the on/off toggle).
    if s in ('invisible_interface', 'stereo_speech') or 'stereo_speech' in k:
        try:
            from src.buffers import tts_buffer
            tts_buffer.refresh()
            notes.append('Titan TTS')
        except Exception:
            pass

    # Assistant / global hotkeys (and any hotkey-shaped key elsewhere).
    if s == 'ai' or 'hotkey' in k:
        try:
            from src.ai.assistant import hotkeys
            hotkeys.register()
            notes.append('hotkeys')
        except Exception:
            pass

    # Settings that gate menu items -> rebuild the main menu bar live.
    if (s == 'general' and k in ('developer_tools', 'visible_categories',
                                 'launcher')) or s == 'ai':
        def _rebuild():
            import wx
            for win in wx.GetTopLevelWindows():
                if hasattr(win, 'rebuild_menu_bar'):
                    try:
                        win.rebuild_menu_bar()
                    except Exception:
                        pass
            return True
        if _run_on_gui(_rebuild)[0]:
            notes.append('menus')

    # Skin -> re-apply to every open window.
    if s == 'interface' and k == 'skin':
        def _skin():
            import wx
            from src.titan_core.skin_manager import apply_skin_to_window
            for win in wx.GetTopLevelWindows():
                try:
                    apply_skin_to_window(win)
                except Exception:
                    pass
            return True
        if _run_on_gui(_skin)[0]:
            notes.append('skin')

    return notes


def titan_set_setting(key, value, section="general", **_):
    """Set one Titan setting value in a section and apply it live where possible."""
    try:
        from src.settings.settings import set_setting
        set_setting(key, value, section=section)
    except Exception as e:
        return f"Could not set setting: {e}"
    applied = _apply_live_setting(section, key, value)
    base = f"Set {section}.{key} = {value}."
    # Language is the one change that genuinely needs a restart to fully apply.
    if section.lower() == 'general' and key.lower() == 'language':
        return base + " Restart Titan for the new language to fully apply."
    if applied:
        return base + " Applied live (" + ", ".join(applied) + ")."
    return (base + " Saved; it will apply the next time Titan reads it "
            "(most settings are read live, a few need a restart).")


# --------------------------------------------------------------------------- #
# Components and their actions
# --------------------------------------------------------------------------- #
def titan_list_components(**_):
    """List installed Titan components (name, enabled state) and the component
    menu actions that can be run with titan_run_component_action."""
    cm = _component_manager()
    if cm is None:
        return "The component manager is not available."
    lines = []
    try:
        comps = cm.get_components()
        if comps:
            lines.append("Components:")
            for c in comps:
                state = "enabled" if c.get('enabled') else "disabled"
                lines.append(f"- {c.get('name')} (folder: {c.get('folder')}, {state})")
    except Exception as e:
        lines.append(f"(could not list components: {e})")
    try:
        actions = list(cm.get_component_menu_functions().keys())
        if actions:
            lines.append("")
            lines.append("Component actions (run by name):")
            for a in actions:
                lines.append(f"- {a}")
    except Exception as e:
        lines.append(f"(could not list component actions: {e})")
    return "\n".join(lines) if lines else "No components are installed."


def titan_run_component_action(action, **_):
    """Run a component menu action by its exact name (see titan_list_components)."""
    cm = _component_manager()
    if cm is None:
        return "The component manager is not available."
    try:
        funcs = cm.get_component_menu_functions()
    except Exception as e:
        return f"Could not read component actions: {e}"
    func = funcs.get(action)
    if func is None:
        # case-insensitive fallback
        for name, f in funcs.items():
            if name.lower() == str(action).lower():
                func, action = f, name
                break
    if func is None:
        avail = ", ".join(funcs.keys()) or "(none)"
        return f"No component action named '{action}'. Available: {avail}"
    ok, err = _run_on_gui(lambda: func(None))
    if ok:
        return f"Ran component action '{action}'."
    return f"Component action '{action}' failed: {err}"


def titan_set_component_enabled(component, enabled=True, **_):
    """Enable or disable a component by its folder name (see titan_list_components).
    Takes effect after Titan reloads components / restarts."""
    cm = _component_manager()
    if cm is None:
        return "The component manager is not available."
    folder = str(component)
    try:
        # Match a friendly name to its folder if needed.
        for c in cm.get_components():
            if c.get('folder') == folder or c.get('name', '').lower() == folder.lower():
                folder = c.get('folder')
                break
    except Exception:
        pass
    want_enabled = str(enabled).lower() in ('true', '1', 'yes', 'enable', 'enabled', 'on')
    try:
        # toggle_component_status flips; only toggle if the desired state differs.
        current_enabled = None
        for c in cm.get_components():
            if c.get('folder') == folder:
                current_enabled = c.get('enabled')
                break
        if current_enabled is None:
            return f"No component with folder '{folder}'."
        if bool(current_enabled) == want_enabled:
            return f"Component '{folder}' is already {'enabled' if want_enabled else 'disabled'}."
        ok, err = _run_on_gui(lambda: cm.toggle_component_status(folder))
        if not ok:
            return f"Could not change component '{folder}': {err}"
        return (f"{'Enabled' if want_enabled else 'Disabled'} component '{folder}'. "
                "Restart Titan (or reload components) for it to take effect.")
    except Exception as e:
        return f"Could not change component '{folder}': {e}"


# --------------------------------------------------------------------------- #
# Add-ons of every kind (discovery + launching)
# --------------------------------------------------------------------------- #
# kind id -> (label, data subdir under data/, is a top-level resource dir?)
_ADDON_KINDS = {
    'app':              ("Applications",      'applications',      False),
    'game':             ("Games",             'games',             False),
    'component':        ("Components",        'components',        False),
    'launcher':         ("Launchers",         'launchers',        False),
    'im_module':        ("Titan IM modules",  'titanIM_modules',   False),
    'gamepad_mode':     ("Gamepad modes",     'gamepad/modes',     False),
    'tts_engine':       ("TTS engines",       'titantts engines',  False),
    'widget':           ("Widgets",           'applets',           False),
    'statusbar_applet': ("Statusbar applets", 'statusbar_applets', False),
    'language':         ("Languages",         'languages',         True),
}


def _discover_kind(subdir, is_resource):
    try:
        from src import platform_utils
        if is_resource:
            entries = platform_utils.discover_resource_entries(subdir)
        else:
            entries = platform_utils.discover_data_entries(subdir)
        return sorted(entries.keys())
    except Exception:
        return []


def titan_list_addons(kind="", **_):
    """List Titan add-ons. With no ``kind``, lists every kind (applications,
    games, components, launchers, Titan IM modules, gamepad modes, TTS engines,
    widgets, statusbar applets, languages). Pass a kind id to list just that one."""
    kind = (kind or '').strip().lower()
    kinds = [kind] if kind in _ADDON_KINDS else list(_ADDON_KINDS.keys())
    if kind and kind not in _ADDON_KINDS:
        return (f"Unknown add-on kind '{kind}'. Known kinds: "
                + ", ".join(_ADDON_KINDS.keys()))
    out = []
    for kid in kinds:
        label, subdir, is_resource = _ADDON_KINDS[kid]
        names = _discover_kind(subdir, is_resource)
        out.append(f"{label} ({kid}): "
                   + (", ".join(names) if names else "(none)"))
    return "\n".join(out)


def _all_launchable():
    """[(kind, name, launch_callable), ...] for apps, games and IM modules."""
    items = []
    try:
        from src.titan_core import app_manager
        for info in app_manager.get_applications():
            name = info.get('name') or info.get('shortname') or ''
            if name:
                items.append(('app', name,
                              lambda i=info: app_manager.open_application(i)))
    except Exception as e:
        print(f"[titan_tools] apps: {e}")
    try:
        from src.titan_core import game_manager
        for info in game_manager.get_games():
            name = info.get('name') or ''
            if name:
                items.append(('game', name,
                              lambda i=info: game_manager.open_game(i)))
    except Exception as e:
        print(f"[titan_tools] games: {e}")
    try:
        from src.network.im_module_manager import im_module_manager
        for info in getattr(im_module_manager, 'modules', []):
            name = info.get('name') or info.get('id') or ''
            mid = info.get('id') or name
            if name:
                items.append(('im_module', name,
                              lambda _id=mid: im_module_manager.open_module(
                                  _id, _find_main_frame())))
    except Exception as e:
        print(f"[titan_tools] im modules: {e}")
    return items


def titan_launch(name, **_):
    """Launch a Titan app, game or IM module by (approximate) name."""
    q = (name or '').strip().lower()
    if not q:
        return "Give the name of an app, game or IM module to launch."
    items = _all_launchable()
    match = None
    for entry in items:                       # exact
        if entry[1].lower() == q:
            match = entry
            break
    if match is None:
        for entry in items:                   # substring
            if q in entry[1].lower() or entry[1].lower() in q:
                match = entry
                break
    if match is None:
        return (f"No Titan app, game or IM module matching '{name}'. "
                "Use titan_list_addons to see what is available.")
    kind, item_name, opener = match
    ok, err = _run_on_gui(opener)
    if ok:
        return f"Launched the {kind.replace('_', ' ')} '{item_name}'."
    return f"Could not launch '{item_name}': {err}"


# --------------------------------------------------------------------------- #
# TTS engines
# --------------------------------------------------------------------------- #
def titan_list_tts_engines(**_):
    """List the Titan TTS engines and which one is currently selected."""
    try:
        from src.tts.engine_registry import get_engine_registry
        reg = get_engine_registry()
        engines = reg.get_all_engines()
    except Exception as e:
        return f"Could not list TTS engines: {e}"
    try:
        from src.settings.settings import get_setting
        active = get_setting('tts_engine', None, section='general') \
            or get_setting('engine', None, section='tts')
    except Exception:
        active = None
    lines = ["TTS engines:"]
    for eng in engines:
        try:
            eid = getattr(eng, 'engine_id', None) or getattr(eng, 'id', None) or str(eng)
            ename = getattr(eng, 'engine_name', None) or getattr(eng, 'name', '') or eid
            avail = getattr(eng, 'is_available', None)
            avail_txt = ''
            if callable(avail):
                try:
                    avail_txt = '' if avail() else ' (unavailable)'
                except Exception:
                    avail_txt = ''
            mark = ' [active]' if active and str(active) == str(eid) else ''
            lines.append(f"- {ename} (id: {eid}){avail_txt}{mark}")
        except Exception:
            continue
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Titan IM: log in, list contacts, send messages
# --------------------------------------------------------------------------- #
# Concrete support for Titan-Net and Telegram (which expose programmatic client
# APIs). Other, pluggable IM modules have no unified send API, so for those the
# tools direct the AI to open the module UI (titan_launch) instead.
def _norm_service(service):
    s = (service or '').strip().lower()
    if s in ('telegram', 'tg', 'telega'):
        return 'telegram'
    if 'whatsapp' in s or s in ('wa', 'whats', 'whatsup'):
        return 'whatsapp'
    if 'messenger' in s or s in ('fb', 'facebook', 'fbmessenger', 'msgr'):
        return 'messenger'
    if ('titan' in s or 'net' in s or s in ('tn', 'im', 'titanim', 'titan im')):
        return 'titan_net'
    return s


def _titan_net_client():
    try:
        from src.network.titan_net import get_active_titan_net_client
        return get_active_titan_net_client()
    except Exception:
        return None


# WhatsApp and Messenger have no client API. Two ways to reach them:
#   1. The browser web app - WhatsApp Web / messenger.com - opened with the OS
#      default browser. This is the DEFAULT and needs no Titan IM setup: the
#      agent finishes the send with its computer-use tools (type / Enter), and
#      WhatsApp Web can even take a pre-filled message via a deep link.
#   2. Titan IM's own embedded WebView window, used only when it is already open
#      and signed in (a convenient shortcut, driven via send_message_to_chat).
def _service_label(svc):
    return 'WhatsApp' if svc == 'whatsapp' else 'Messenger'


def _im_backend(svc):
    """The Titan IM web backend object for ``svc`` without starting an engine.

    ``start=False`` matters: the AI must not silently spin up a WhatsApp or
    Messenger session the user never opened. It only rides along on an engine
    that is already running and signed in.
    """
    if svc == 'whatsapp':
        from src.network.im_web.whatsapp_backend import get_whatsapp_backend
        return get_whatsapp_backend(start=False)
    if svc == 'messenger':
        from src.network.im_web.messenger_backend import get_messenger_backend
        return get_messenger_backend(start=False)
    return None


def _titan_im_window_ready(svc):
    """The running, signed-in backend for ``svc`` (so it can send right away)."""
    try:
        backend = _im_backend(svc)
    except Exception:
        return None
    if backend is None or not backend.running or not backend.logged_in:
        return None
    return backend


def _backend_call(fn, timeout=30.0):
    """Run one asynchronous backend command and wait for its result dict."""
    import threading
    done = threading.Event()
    box = {}

    def _callback(result):
        box.update(result or {})
        done.set()

    fn(_callback)
    if not done.wait(timeout):
        return {'success': False, 'error': 'timed out'}
    return box


def _webview_send(svc, recipient, message):
    """Send through an already-open, signed-in Titan IM client. Returns
    (sent: bool, text).

    The backends accept a conversation name where an id is expected (both page
    agents resolve a display name), so the AI can keep saying "send to Anna".
    """
    label = _service_label(svc)
    backend = _titan_im_window_ready(svc)
    if backend is None:
        return False, ''
    result = _backend_call(
        lambda cb: backend.send_text(recipient, message, callback=cb), timeout=45.0)
    if result.get('success'):
        return True, f"Message sent to {recipient} on {label} (Titan IM)."
    error = result.get('error') or ''
    print(f"[titan_tools] {label} send failed: {error}")
    return False, ''


def _open_uri(uri):
    """Open a URL or app deep-link (e.g. whatsapp://) with the OS default
    handler."""
    import sys
    import subprocess
    try:
        if sys.platform == 'win32':
            os.startfile(uri)  # noqa: intended - default handler
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', uri])
        else:
            subprocess.Popen(['xdg-open', uri])
        return True
    except Exception as e:
        print(f"[titan_tools] could not open '{uri[:40]}...': {e}")
        return False


def _looks_like_phone(recipient):
    """(is_phone, digits) - digits are stripped of spaces/dashes/brackets/plus."""
    r = re.sub(r'[\s\-()]', '', recipient or '')
    if re.fullmatch(r'\+?\d{6,15}', r):
        return True, r.lstrip('+')
    return False, ''


def _uri_scheme_registered(scheme):
    """True if a URL-protocol ``scheme`` (e.g. 'whatsapp') is registered on this
    Windows machine - i.e. a desktop app is installed to handle it."""
    if os.name != 'nt':
        return False
    try:
        import winreg
    except Exception:
        return False
    for root, path in ((winreg.HKEY_CLASSES_ROOT, scheme),
                       (winreg.HKEY_CURRENT_USER, r'Software\Classes\%s' % scheme)):
        try:
            with winreg.OpenKey(root, path):
                return True
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return False


def _desktop_app_send(svc, recipient, message):
    """Send via an installed desktop app's deep link, but only when we can target
    the exact chat (WhatsApp by phone, Messenger by handle). Returns text on
    success, or None to fall through to the browser."""
    if os.name != 'nt':
        return None
    label = _service_label(svc)
    if svc == 'whatsapp':
        is_phone, digits = _looks_like_phone(recipient)
        if is_phone and _uri_scheme_registered('whatsapp'):
            if _open_uri(f"whatsapp://send?phone={digits}&text={quote(message)}"):
                return (f"Opened the {label} desktop app on that chat with the "
                        f"message ready. Press Enter to send it.")
    elif svc == 'messenger':
        handle = (recipient or '').strip().lstrip('@')
        if re.fullmatch(r'[A-Za-z0-9.]+', handle):
            for scheme in ('fb-messenger', 'messenger'):
                if _uri_scheme_registered(scheme):
                    if _open_uri(f"{scheme}://user/{handle}"):
                        return (f"Opened the {label} desktop app on '{recipient}'. "
                                f"Type this and press Enter: {message}")
    return None


def _web_send(svc, recipient, message):
    """Open the browser web app at the right chat and hand off to the agent's
    computer-use tools to finish typing/sending."""
    label = _service_label(svc)
    if svc == 'whatsapp':
        is_phone, digits = _looks_like_phone(recipient)
        if is_phone:
            url = (f"https://web.whatsapp.com/send?phone={digits}"
                   f"&text={quote(message)}")
            if not _open_uri(url):
                return "Could not open WhatsApp Web."
            return ("Opened WhatsApp Web on that chat with the message already "
                    "typed in. When the conversation has finished loading, press "
                    "Enter to send it.")
        if not _open_uri("https://web.whatsapp.com/"):
            return "Could not open WhatsApp Web."
        return (f"Opened WhatsApp Web in the browser. Find and open the chat with "
                f"'{recipient}', click the message box, type this and press Enter: "
                f"{message}")
    # Messenger has no text-prefill URL scheme.
    handle = (recipient or '').strip().lstrip('@')
    if re.fullmatch(r'[A-Za-z0-9.]+', handle):
        url = f"https://www.messenger.com/t/{handle}"
    else:
        url = "https://www.messenger.com/"
    if not _open_uri(url):
        return "Could not open Messenger in the browser."
    return (f"Opened Messenger in the browser. Open the chat with '{recipient}', "
            f"click the message box, type this and press Enter: {message}")


def _send_web_im(svc, recipient, message):
    """Send to WhatsApp / Messenger, trying in order: an already-open, signed-in
    Titan IM window; the installed desktop system app (deep link to the exact
    chat); then the browser web app."""
    sent, text = _webview_send(svc, recipient, message)
    if sent:
        return text
    text = _desktop_app_send(svc, recipient, message)
    if text:
        return text
    return _web_send(svc, recipient, message)


def titan_im_login(service, username, password="", **_):
    """Log in to a Titan IM service. ``service`` is 'titan_net' or 'telegram'
    (for Telegram, ``username`` is the phone number)."""
    svc = _norm_service(service)
    if svc == 'titan_net':
        client = _titan_net_client()
        if client is None:
            return "Titan-Net is not initialised in this session."
        try:
            res = client.login(username, password)
        except Exception as e:
            return f"Titan-Net login failed: {e}"
        if isinstance(res, dict):
            if res.get('success'):
                return f"Logged in to Titan-Net as {username}."
            return f"Titan-Net login failed: {res.get('message', 'unknown error')}"
        return "Titan-Net login attempted."
    if svc == 'telegram':
        try:
            from src.network import telegram_client as tg
            res = tg.login(username, password or None)
        except Exception as e:
            return f"Telegram login failed: {e}"
        return f"Telegram login result: {res}"
    if svc in ('whatsapp', 'messenger'):
        label = _service_label(svc)
        # Prefer Titan's own accessible client: it signs in without a QR code
        # (WhatsApp pairing code) or in a normal dialog (Messenger), and once it
        # is up the AI can send and read through the backend directly.
        opened = False
        try:
            if svc == 'whatsapp':
                from src.network.whatsapp_titan_gui import show_whatsapp_client as _show
            else:
                from src.network.messenger_titan_gui import show_messenger_client as _show
            ok, res = _run_on_gui(lambda: bool(_show(None)))
            opened = bool(ok and res)
        except Exception as e:
            print(f"[titan_tools] could not open the {label} client: {e}")
        if opened:
            return (f"Opened the Titan {label} client. Sign in there (Titan asks "
                    f"for what it needs - no QR code); after that I can list "
                    f"conversations and send messages directly.")

        url = ('https://web.whatsapp.com/' if svc == 'whatsapp'
               else 'https://www.messenger.com/')
        _open_uri(url)
        return (f"The Titan {label} client could not be opened, so I opened "
                f"{label} in the browser instead. Sign in there and I will send "
                f"through the browser or the desktop app.")
    return (f"Don't know how to log in to '{service}'. Known services: "
            "titan_net, telegram, whatsapp, messenger.")


def _titan_net_resolve_recipient(client, recipient):
    """Resolve a Titan-Net username (or numeric id) to a user id."""
    r = str(recipient).strip()
    if r.isdigit():
        return int(r)
    for getter in ('get_online_users', 'get_all_users'):
        fn = getattr(client, getter, None)
        if not callable(fn):
            continue
        try:
            res = fn()
        except Exception:
            continue
        users = res.get('users') if isinstance(res, dict) else res
        for u in (users or []):
            try:
                if str(u.get('username', '')).lower() == r.lower():
                    return u.get('id')
            except Exception:
                continue
    return None


def titan_send_message(service, recipient, message, **_):
    """Send a private message to someone on a Titan IM service. ``service`` is
    'titan_net' or 'telegram'; ``recipient`` is a username (or phone/id)."""
    if not str(recipient).strip() or not str(message).strip():
        return "Need both a recipient and a message."
    svc = _norm_service(service)
    if svc == 'titan_net':
        client = _titan_net_client()
        if client is None:
            return "Titan-Net is not initialised in this session."
        if not getattr(client, 'is_connected', False):
            return ("Not logged in to Titan-Net. Use titan_im_login first.")
        rid = _titan_net_resolve_recipient(client, recipient)
        if rid is None:
            return (f"Could not find Titan-Net user '{recipient}' (they may be "
                    "offline). Use titan_list_im_contacts to see who is online.")
        try:
            res = client.send_private_message(rid, message)
        except Exception as e:
            return f"Could not send the message: {e}"
        ok = res.get('success') if isinstance(res, dict) else bool(res)
        if ok:
            return f"Message sent to {recipient} on Titan-Net."
        return (f"Send failed: "
                f"{res.get('message') if isinstance(res, dict) else res}")
    if svc == 'telegram':
        try:
            from src.network import telegram_client as tg
            res = tg.send_message(recipient, message)
        except Exception as e:
            return f"Could not send the Telegram message: {e}"
        if isinstance(res, dict) and res.get('success') is False:
            return f"Telegram send failed: {res.get('message', res)}"
        return f"Message sent to {recipient} on Telegram."
    if svc in ('whatsapp', 'messenger'):
        return _send_web_im(svc, str(recipient).strip(), message)
    return (f"Sending to '{service}' programmatically is not supported. Open the "
            "module with titan_launch and use it directly.")


def titan_list_im_contacts(service, **_):
    """List contacts / online users of a Titan IM service so a recipient can be
    chosen. ``service`` is 'titan_net' or 'telegram'."""
    svc = _norm_service(service)
    if svc == 'titan_net':
        client = _titan_net_client()
        if client is None:
            return "Titan-Net is not initialised in this session."
        try:
            res = client.get_online_users()
        except Exception as e:
            return f"Could not list Titan-Net users: {e}"
        users = res.get('users', []) if isinstance(res, dict) else []
        names = [u.get('username') for u in users if u.get('username')]
        return ("Online Titan-Net users: "
                + (", ".join(sorted(names)) if names else "(none online)"))
    if svc == 'telegram':
        try:
            from src.network import telegram_client as tg
            res = tg.get_contacts()
        except Exception as e:
            return f"Could not list Telegram contacts: {e}"
        return f"Telegram contacts: {str(res)[:2000]}"
    if svc in ('whatsapp', 'messenger'):
        label = 'WhatsApp' if svc == 'whatsapp' else 'Messenger'
        backend = _titan_im_window_ready(svc)
        if backend is None:
            return (f"{label} is not open (or not signed in). Open it first "
                    f"(titan_im_login with service '{svc}') and sign in.")
        result = _backend_call(lambda cb: backend.list_chats(callback=cb), timeout=45.0)
        if not result.get('success'):
            return f"Could not list {label} chats: {result.get('error') or ''}"
        chats = result.get('chats') or []
        lines = []
        for chat in chats[:60]:
            entry = chat.name
            if chat.unread:
                entry += f" ({chat.unread} unread)"
            if chat.last_message:
                entry += f": {chat.last_message}"
            lines.append(entry)
        return f"{label} chats: " + ("; ".join(lines) if lines else "(none)")
    return "Known services: titan_net, telegram, whatsapp, messenger."


# --------------------------------------------------------------------------- #
# Media library (tMedia): find a title in the user's catalogs and play it
# --------------------------------------------------------------------------- #
# tMedia (the "multimedia" app) ships a "Media Library" built from the catalogs
# listed in its data/urls.tmedia file: HTTP directory listings and local folders
# (including a Google Drive for Desktop mount). These tools let the AI search
# those catalogs by title (e.g. "swiat wedlug kiepskich odc 6") and hand the
# matching file straight to tMedia to play - the same file the user would reach
# by browsing the tree manually.
# Full media set (audio + video) - kept for reference / any playback checks.
_MEDIA_EXTS = ('.mp3', '.wav', '.ogg', '.wma', '.flac', '.aac', '.mp4', '.avi',
               '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4a')
# The library index only stores AUDIO (plus .mp4, which is very often an
# audio-only recording - podcasts, lectures, audiobooks). tMedia is used almost
# exclusively to listen, and the catalogs - especially the Google Drive
# "tyflodysk" - hold huge numbers of large pure-video files (.mkv/.avi/...) that
# only bloat the index and slow the crawl/save/search without ever being wanted.
# Restricting the index this way makes building and searching it much faster.
_AUDIO_EXTS = ('.mp3', '.wav', '.ogg', '.wma', '.flac', '.aac', '.m4a', '.mp4',
               '.m4b', '.opus', '.aiff', '.aif', '.ape', '.oga', '.mka')
_GOOGLE_DRIVE_MARKER = 'googledrive://'


# Letters that NFKD does NOT decompose into base + combining mark and so must be
# folded by hand (most importantly Polish l-with-stroke).
_LETTER_FOLD = {'ł': 'l', 'Ł': 'L', 'ø': 'o', 'Ø': 'O', 'đ': 'd', 'Đ': 'D'}


def _strip_accents(s):
    s = ''.join(_LETTER_FOLD.get(c, c) for c in (s or ''))
    return ''.join(c for c in unicodedata.normalize('NFKD', s)
                   if not unicodedata.combining(c))


def _norm_text(s):
    return _strip_accents((s or '').lower())


def _detect_google_drive_path():
    """Drive letter Google Drive for Desktop is mounted on (Windows only)."""
    try:
        import platform
        if platform.system() != 'Windows':
            return None
        import win32api
    except Exception:
        return None
    try:
        drives = win32api.GetLogicalDriveStrings().split('\x00')
    except Exception:
        return None
    for drive in drives:
        if not drive:
            continue
        try:
            volume_name = win32api.GetVolumeInformation(drive)[0]
        except Exception:
            continue
        if 'google drive' in volume_name.strip().lower():
            return drive
    return None


def _tmedia_app_info():
    try:
        from src.titan_core import app_manager
        for info in (app_manager.get_applications()
                     + app_manager.get_hidden_applications()):
            if info.get('shortname') == 'media':
                return info
    except Exception as e:
        print(f"[titan_tools] could not locate tMedia: {e}")
    return None


def _tmedia_catalogs():
    """[(name, root_url_or_file_uri)] for every Media Library catalog."""
    info = _tmedia_app_info()
    if not info:
        return []
    urls_file = os.path.join(info['path'], 'data', 'urls.tmedia')
    catalogs = []
    try:
        with open(urls_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or '=' not in line:
                    continue
                name, url = line.split('=', 1)
                url = url.strip()
                if url.lower() == _GOOGLE_DRIVE_MARKER:
                    drive = _detect_google_drive_path()
                    if not drive:
                        continue
                    url = Path(drive).as_uri()
                catalogs.append((name.strip(), url))
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[titan_tools] could not read media catalogs: {e}")
    return catalogs


def _query_tokens(query):
    return [t for t in re.split(r'\s+', _norm_text(query)) if t]


def _matches_tokens(text, tokens):
    """True when every query token appears in ``text``. Numeric tokens must match
    on a digit boundary so 'odc 6' does not match 'odc 60'."""
    t = _norm_text(text)
    for tok in tokens:
        if tok.isdigit():
            if not re.search(r'(?<!\d)' + re.escape(tok) + r'(?!\d)', t):
                return False
        elif tok not in t:
            return False
    return True


def _file_uri_to_path(uri):
    return url2pathname(urlparse(uri).path)


# --------------------------------------------------------------------------- #
# Persistent media index
# --------------------------------------------------------------------------- #
# The media library - especially the Google Drive "tyflodysk" - is huge, deep
# and cloud-backed: listing a single folder can stall for many seconds and a
# full walk has thousands of directories, so crawling live on every query is
# hopeless (measured: ~160 dirs in 100s, thousands still queued). Instead we
# build a flat index of every media file ONCE in a background thread, persist it
# to disk, and search that index instantly; it is refreshed in the background
# when it goes stale. Partial progress is flushed during the build so results
# appear before the crawl finishes.
_INDEX_LOCK = threading.Lock()
_INDEX_BUILDING = {'flag': False, 'count': 0, 'started': 0.0, 'finished': 0.0}
_INDEX_CACHE = {'mtime': None, 'items': None, 'ts': 0.0}
_INDEX_TTL = 24 * 3600        # refresh in the background at most once a day
_INDEX_MAX_SECONDS = 4 * 3600  # generous cap on a single build (huge cloud drives);
#                               partial progress is flushed and persisted anyway

# Directory names never worth indexing (junk / backups / cloud internals).
_SKIP_DIR_NAMES = {
    '.shortcut-targets-by-id', '$recycle.bin', '.encrypted', '.trash',
    '.tmp.drivedownload', 'system volume information', 'found.000',
    'inne komputery', 'other computers',
}


def _media_index_path():
    """The media index lives in the user's Titan data: Titan/ai/media_index.TCI."""
    try:
        from src.platform_utils import get_user_data_dir
        base = os.path.join(get_user_data_dir(), 'ai')
    except Exception:
        base = os.path.join(_appsettings_dir(), 'ai')
    return os.path.join(base, 'media_index.TCI')


def _save_media_index(items, complete):
    try:
        path = _media_index_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'ts': time.time(), 'complete': complete, 'items': items}, f)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[titan_tools] could not save media index: {e}")


def _load_media_index():
    """(items, ts) from the on-disk index, memoized by file mtime so repeated
    searches don't re-parse the JSON."""
    path = _media_index_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return [], 0.0
    if _INDEX_CACHE['mtime'] == mtime and _INDEX_CACHE['items'] is not None:
        return _INDEX_CACHE['items'], _INDEX_CACHE['ts']
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return [], 0.0
    items = data.get('items', []) or []
    _INDEX_CACHE.update(mtime=mtime, items=items, ts=data.get('ts', 0.0))
    return items, _INDEX_CACHE['ts']


def _short_path(path, parts=2):
    """Last ``parts`` components of a path/URL, for a compact 'catalog/catalog'
    progress line."""
    p = unquote(path or '').replace('\\', '/').rstrip('/')
    segs = [s for s in p.split('/') if s and '://' not in s and ':' != s[-1:]]
    return '/'.join(segs[-parts:]) if segs else p


# Both crawlers are directory-latency bound (a cloud folder or an HTTP listing
# can stall for seconds), so they walk the tree with a POOL of worker threads
# fanning out over sub-directories instead of one dir at a time. This is what
# turns a multi-hour serial walk of a big library into minutes. ``out`` is a
# shared list guarded by ``out_lock``; a background flusher in _build_media_index
# persists partial progress so results are searchable while the crawl runs.
# A cloud drive (Google Drive for Desktop) is almost pure per-folder LATENCY:
# each os.scandir round-trips to the Drive filesystem driver, so wall-clock time
# is (folders x latency) / threads. The only way to turn a multi-hour serial
# walk into minutes is to fan out very wide - dozens to a couple hundred threads
# - since they spend nearly all their time waiting on I/O, not on the CPU.
_LOCAL_CRAWL_WORKERS = 96     # cloud/network folders: latency-bound, fan out wide
_HTTP_CRAWL_WORKERS = 32
_WORKERS_MIN, _WORKERS_MAX = 8, 512


def _media_index_workers(default):
    """Thread count for a crawl, overridable via the ``media_index_workers``
    setting (ai section) for users on especially large/slow libraries. Clamped
    to a sane range; falls back to ``default`` when unset/invalid."""
    try:
        from src.settings.settings import get_setting
        raw = get_setting('media_index_workers', 0, section='ai')
        n = int(raw)
    except Exception:
        n = 0
    if n <= 0:
        n = default
    return max(_WORKERS_MIN, min(_WORKERS_MAX, n))


def _run_bfs_workers(worker, seed, n):
    """Run ``n`` daemon threads over a shared work queue seeded with ``seed``.
    ``worker`` receives (queue, pending, plock) and must, for each item it takes,
    push discovered children onto the queue (bumping ``pending`` by the number
    pushed) and decrement ``pending`` by one when done. Workers exit once the
    queue drains AND ``pending`` reaches zero."""
    import queue as _q
    q = _q.Queue()
    q.put(seed)
    pending = [1]
    plock = threading.Lock()

    def _loop():
        while True:
            try:
                item = q.get(timeout=0.2)
            except _q.Empty:
                with plock:
                    if pending[0] == 0:
                        return
                continue
            try:
                worker(item, q, pending, plock)
            except Exception as e:
                # A crash on one item must not kill the worker (which would risk
                # the queue never draining); worker() already balanced ``pending``.
                print(f"[titan_tools] crawl worker error: {e}")

    threads = [threading.Thread(target=_loop, daemon=True) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def _crawl_local_into(root_uri, out, out_lock, deadline, progress=None):
    try:
        root = _file_uri_to_path(root_uri)
    except Exception:
        return
    report = [0.0]

    def worker(d, q, pending, plock):
        try:
            if time.time() > deadline:
                return
            now = time.time()
            if progress and now - report[0] > 0.3:
                report[0] = now
                progress(len(out), _short_path(d))
            try:
                entries = list(os.scandir(d))
            except Exception:
                return
            found, subdirs = [], []
            for e in entries:
                try:
                    isdir = e.is_dir()
                except OSError:
                    isdir = False
                if isdir:
                    if e.name.lower() in _SKIP_DIR_NAMES or e.name.startswith('.'):
                        continue
                    # Skip reparse points / symlinks (Google Drive "shortcuts"):
                    # following them re-crawls the SAME content under another path,
                    # wasting most of the time on a big Drive and risking cycles.
                    try:
                        if e.is_symlink():
                            continue
                    except OSError:
                        pass
                    subdirs.append(e.path)
                elif e.name.lower().endswith(_AUDIO_EXTS):
                    try:
                        display = os.path.relpath(e.path, root)
                    except Exception:
                        display = e.name
                    found.append({'name': e.name, 'display': display,
                                  'url': Path(e.path).as_uri()})
            if found:
                with out_lock:
                    out.extend(found)
            with plock:
                pending[0] += len(subdirs)
            for s in subdirs:
                q.put(s)
        finally:
            with plock:
                pending[0] -= 1

    _run_bfs_workers(worker, root, _media_index_workers(_LOCAL_CRAWL_WORKERS))


def _crawl_http_into(base_url, out, out_lock, deadline, progress=None, max_dirs=4000):
    import html as _html
    import requests
    seen = {base_url}
    seen_lock = threading.Lock()
    counters = {'dirs': 0}
    report = [0.0]

    def worker(url, q, pending, plock):
        try:
            if time.time() > deadline:
                return
            with plock:
                if counters['dirs'] >= max_dirs:
                    return
                counters['dirs'] += 1
            now = time.time()
            if progress and now - report[0] > 0.3:
                report[0] = now
                progress(len(out), _short_path(url))
            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code != 200:
                    return
            except Exception:
                return
            found, newdirs = [], []
            for line in resp.text.splitlines():
                if 'href="' not in line:
                    continue
                start = line.find('href="') + len('href="')
                end = line.find('"', start)
                if end <= start:
                    continue
                link = _html.unescape(line[start:end])
                if not link or link.startswith(('?', '/', '..')) or '://' in link:
                    continue
                full = urljoin(url, quote(link, safe='%/'))
                name = unquote(link).strip('/')
                if link.endswith('/'):
                    with seen_lock:
                        if full in seen:
                            continue
                        seen.add(full)
                    newdirs.append(full)
                elif link.lower().endswith(_AUDIO_EXTS):
                    display = (unquote(full[len(base_url):])
                               if full.startswith(base_url) else name)
                    found.append({'name': name, 'display': display or name,
                                  'url': full})
            if found:
                with out_lock:
                    out.extend(found)
            with plock:
                pending[0] += len(newdirs)
            for nd in newdirs:
                q.put(nd)
        finally:
            with plock:
                pending[0] -= 1

    _run_bfs_workers(worker, base_url, _media_index_workers(_HTTP_CRAWL_WORKERS))


def _build_media_index(progress=None):
    with _INDEX_LOCK:
        if _INDEX_BUILDING['flag']:
            return
        _INDEX_BUILDING.update(flag=True, count=0, started=time.time(), finished=0.0)
    out = []
    out_lock = threading.Lock()
    deadline = time.time() + _INDEX_MAX_SECONDS

    # Persist partial progress from ONE background thread while every catalog is
    # crawled in parallel below, so a long build stays searchable as it grows and
    # the crawlers never contend on the disk save.
    stop_flush = threading.Event()

    def _flusher():
        while not stop_flush.wait(5.0):
            with out_lock:
                snapshot = list(out)
            _save_media_index(snapshot, False)
            _INDEX_BUILDING['count'] = len(snapshot)

    flusher = threading.Thread(target=_flusher, daemon=True)
    flusher.start()
    try:
        catalogs = _tmedia_catalogs()

        def _crawl_one(catalog):
            name, root = catalog
            if time.time() > deadline:
                return
            if progress:
                progress(len(out), name)
            if root.startswith('file://'):
                _crawl_local_into(root, out, out_lock, deadline, progress)
            elif root.startswith('http'):
                _crawl_http_into(root, out, out_lock, deadline, progress)

        # Crawl catalogs concurrently too; each one already fans out internally.
        if catalogs:
            with ThreadPoolExecutor(max_workers=min(4, len(catalogs))) as ex:
                for fut in [ex.submit(_crawl_one, c) for c in catalogs]:
                    try:
                        fut.result()
                    except Exception as e:
                        print(f"[titan_tools] media crawl failed: {e}")
    finally:
        stop_flush.set()
        flusher.join(timeout=2)
        with out_lock:
            final = list(out)
        _save_media_index(final, True)
        with _INDEX_LOCK:
            _INDEX_BUILDING.update(flag=False, count=len(final), finished=time.time())
        if progress:
            progress(len(final), '', True)


def _make_index_progress_dialog():
    """Create (on the GUI thread) a small progress window shown during the FIRST
    media index build. Returns an object with a thread-safe
    ``report(count, note, done=False)`` method, or None if there is no GUI."""
    def _create():
        import wx
        if not wx.GetApp():
            return None
        try:
            from src.titan_core.translation import set_language
            from src.settings.settings import get_setting
            _ = set_language(get_setting('language', 'pl'))
        except Exception:
            _ = lambda s: s
        # Bare _() calls so pybabel (keyword '_') extracts these into the 'ai'
        # domain; formatting is applied after translation.
        strings = {
            'title': _("Indexing media library"),
            'wait': _("Indexing media library, please wait..."),
            'hide': _("Hide"),
            'progress': _("Indexing media library... {n} files"),
            'done': _("Media library indexed: {n} files."),
            'folder': _("Folder: {name}"),
        }

        class _IndexProgress(wx.Frame):
            def __init__(self):
                super().__init__(None, title=strings['title'],
                                 style=wx.CAPTION | wx.STAY_ON_TOP | wx.CLOSE_BOX)
                self.s = strings
                panel = wx.Panel(self)
                v = wx.BoxSizer(wx.VERTICAL)
                self.label = wx.StaticText(panel, label=strings['wait'])
                v.Add(self.label, 0, wx.ALL, 12)
                self.folder = wx.StaticText(panel, label="")
                v.Add(self.folder, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
                self.gauge = wx.Gauge(panel, range=100, size=(340, 18))
                v.Add(self.gauge, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 12)
                self.hide_btn = wx.Button(panel, wx.ID_ANY, strings['hide'])
                self.hide_btn.Bind(wx.EVT_BUTTON, lambda e: self.Hide())
                v.Add(self.hide_btn, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
                panel.SetSizerAndFit(v)
                self.Fit()
                try:
                    from src.titan_core.skin_manager import apply_skin_to_window
                    apply_skin_to_window(self)
                except Exception:
                    pass
                self.CentreOnScreen()
                self.gauge.Pulse()
                self.Show()

            def update(self, count, note, done):
                if done:
                    self.label.SetLabel(self.s['done'].format(n=count))
                    self.folder.SetLabel("")
                    self.gauge.SetRange(100)
                    self.gauge.SetValue(100)
                    wx.CallLater(1800, self.Close)
                    return
                self.label.SetLabel(self.s['progress'].format(n=count))
                if note:
                    self.folder.SetLabel(self.s['folder'].format(name=note))
                self.gauge.Pulse()
                self.Layout()

        return _IndexProgress()

    ok, frame = _run_on_gui(_create)
    if not ok or frame is None:
        return None

    class _Reporter:
        def report(self, count, note='', done=False):
            import wx
            try:
                wx.CallAfter(frame.update, count, note, done)
            except Exception:
                pass
    return _Reporter()


def _ensure_index_building(gui=False):
    """Start a background index build if one isn't already running. When ``gui``
    is set and a GUI is available, show a progress window (used for the very
    first build). Returns True if it kicked off a new build."""
    with _INDEX_LOCK:
        if _INDEX_BUILDING['flag']:
            return False
    progress = None
    if gui:
        reporter = _make_index_progress_dialog()
        if reporter is not None:
            progress = reporter.report
    threading.Thread(target=_build_media_index,
                     kwargs={'progress': progress}, daemon=True).start()
    return True


def _index_status_note():
    """Short note about index state, for empty-result messages."""
    with _INDEX_LOCK:
        building = _INDEX_BUILDING['flag']
        count = _INDEX_BUILDING['count']
    if building:
        return (f" (The media library index is still being built - {count} files "
                f"so far. Ask again in a moment.)")
    items, _ts = _load_media_index()
    if not items:
        return (" (The media library index is empty; I've started building it in "
                "the background - ask again shortly.)")
    return ""


def _search_media_catalogs(query, limit=15):
    tokens = _query_tokens(query)
    if not tokens:
        return []
    items, ts = _load_media_index()
    # Kick off a background (re)build when the index is missing or a day old.
    # First-ever build shows a progress window; a stale refresh is silent.
    if not items:
        _ensure_index_building(gui=True)
    elif time.time() - ts > _INDEX_TTL:
        _ensure_index_building(gui=False)
    results = []
    for it in items:
        text = it.get('display') or it.get('name', '')
        if _matches_tokens(text, tokens):
            results.append((it.get('name', ''), it.get('url', '')))
            if len(results) >= limit:
                break
    return results


def _open_in_tmedia(initial=None):
    """Launch tMedia (optionally with a startup file/URL/query). Returns True on
    success."""
    info = _tmedia_app_info()
    if not info:
        return False
    try:
        from src.titan_core import app_manager
        app_manager.open_application(info, file_path=initial)
        return True
    except Exception as e:
        print(f"[titan_tools] tMedia launch failed: {e}")
        return False


def titan_list_media_catalogs(**_):
    """List the user's configured Media Library catalogs (tMedia)."""
    catalogs = _tmedia_catalogs()
    if not catalogs:
        return ("No media library catalogs are configured (tMedia's "
                "data/urls.tmedia is empty or the app is missing).")
    return "Media library catalogs:\n" + "\n".join(
        f"- {name}" for name, _url in catalogs)


def titan_search_media(query, **_):
    """Search the user's Media Library (tMedia catalogs) for media files (tracks,
    episodes, audiobooks...) whose name/path matches ``query`` and return the
    matches WITH their playable location, so a specific one can then be played
    with titan_play_media(url=...)."""
    q = (query or '').strip()
    if not q:
        return "Give something to search for (a title, series, artist, book...)."
    try:
        results = _search_media_catalogs(q, limit=15)
    except Exception as e:
        return f"Media search failed: {e}"
    if not results:
        return (f"Found nothing matching '{q}' in the media library."
                + _index_status_note())
    lines = []
    for i, (name, url) in enumerate(results, 1):
        lines.append(f"{i}. {name}\n   url: {url}")
    return (f"Media matching '{q}' (play one with titan_play_media using its "
            f"url):\n" + "\n".join(lines))


def titan_reindex_media(**_):
    """Rebuild the media library index now (in the background). Use this if the
    library changed or a search says the index is missing/stale."""
    started = _ensure_index_building(gui=True)
    if started:
        return ("Rebuilding the media library index in the background. Large "
                "libraries (e.g. a Google Drive) can take a while; searches work "
                "against whatever has been indexed so far.")
    with _INDEX_LOCK:
        count = _INDEX_BUILDING['count']
    return f"The media library index is already being built ({count} files so far)."


def titan_play_media(query="", url="", position="", **_):
    """Directly play something from the user's Media Library in tMedia. Give a
    direct ``url``/file to play that exact item (e.g. a url from
    titan_search_media), OR a ``query`` (a title/series/episode/book to find in
    the catalogs, e.g. 'swiat wedlug kiepskich odc 6') - the best match is played
    straight away. If the query is ambiguous, search first and play by url.

    ``position`` starts it somewhere other than the beginning/resume point:
    '50%', '49 minutes', '1:23:45'."""
    target = (url or '').strip()
    title = None
    extra = ''
    if not target:
        q = (query or '').strip()
        if not q:
            return "Give a query or a url to play."
        try:
            results = _search_media_catalogs(q, limit=8)
        except Exception as e:
            return f"Media search failed: {e}"
        if not results:
            return (f"Found nothing matching '{q}' in the media library."
                    + _index_status_note()
                    + " To play it from YouTube instead, use play_music.")
        title, target = results[0]
        if len(results) > 1:
            others = "; ".join(n for n, _u in results[1:5])
            extra = (f" ({len(results)} matches - playing the first; others: "
                     f"{others}. Use titan_search_media to pick a specific one.)")
    argument = target
    spec = _sanitize_arg(position)
    if spec:
        argument = f"position:{spec}|{target}"
    if not _open_in_tmedia(argument):
        return "Could not find the Titan media player (tMedia)."
    where = f" from {spec}" if spec else ""
    return (f"Playing '{title or target}'{where} in the Titan media player "
            f"(tMedia)." + extra)


def _sanitize_arg(text):
    """tMedia's startup argument is inlined into generated code as r'...', so a
    quote/backslash would break it. Country/station names never need those."""
    return (text or '').replace("'", ' ').replace('"', ' ').replace('\\', ' ').strip()


# --------------------------------------------------------------------------- #
# Audiobooks and bookmarks (tMedia)
# --------------------------------------------------------------------------- #
# tMedia plays a whole FOLDER as one audiobook and remembers where the user
# stopped - the resume point automatically, plus any number of named bookmarks -
# in a JSON file next to its own settings
# (%APPDATA%/Titosoft/Titan/appsettings/media_bookmarks.json). Reading that file
# is what lets the assistant answer "what was I listening to?" and "wroc do
# zakladki" without the app being open; playback itself is always handed to
# tMedia through its startup argument:
#   audiobook:<folder>            play a folder as one book (from its resume point)
#   position:<where>|<target>     start that target at a position instead
#                                 ("50%", "49 min", "1:23:45", "track 4 12:30")
_MEDIA_BOOKMARKS_FILE = 'media_bookmarks.json'


def media_bookmarks_path():
    """Full path of tMedia's bookmarks file (the same one the app writes)."""
    return os.path.join(_appsettings_dir(), _MEDIA_BOOKMARKS_FILE)


def _load_media_bookmarks():
    """[entry, ...] most recently played first; [] when nothing is saved."""
    try:
        with open(media_bookmarks_path(), 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[titan_tools] could not read media bookmarks: {e}")
        return []
    items = data.get('items') if isinstance(data, dict) else None
    if not isinstance(items, dict):
        return []
    entries = [e for e in items.values() if isinstance(e, dict)]
    entries.sort(key=lambda e: e.get('updated', 0), reverse=True)
    return entries


def _format_ms(ms):
    total = int(max(0, ms or 0)) // 1000
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return '%d:%02d:%02d' % (hours, minutes, seconds)
    return '%d:%02d' % (minutes, seconds)


def _place_text(entry, place):
    """A resume point / bookmark as text, including the track when the item is
    an audiobook (a position alone means nothing across 40 files)."""
    text = _format_ms(place.get('position', 0))
    if entry.get('kind') != 'audiobook':
        return text
    track = int(place.get('track', 0) or 0) + 1
    total = len(entry.get('tracks') or [])
    where = f"track {track} of {total}" if total else f"track {track}"
    if place.get('track_title'):
        where += f" ({place['track_title']})"
    return f"{where}, {text}"


def _place_spec(entry, place):
    """The startup position spec for a saved place - tMedia parses
    'track 4 1:23:45' as well as a bare time."""
    time_text = _format_ms(place.get('position', 0))
    if entry.get('kind') == 'audiobook':
        return f"track {int(place.get('track', 0) or 0) + 1} {time_text}"
    return time_text


def _folder_url(url):
    """The folder a media URL lives in (an audiobook is its folder)."""
    u = (url or '').strip()
    if not u:
        return ''
    if '://' in u and not u.lower().startswith('file://'):
        return u.rsplit('/', 1)[0] + '/'
    path = _file_uri_to_path(u) if u.lower().startswith('file://') else u
    parent = os.path.dirname(path.rstrip('\\/'))
    if not parent:
        return ''
    try:
        return Path(parent).as_uri()
    except Exception:
        return parent


def _search_media_folders(query, limit=8):
    """[(name, folder_url, file_count)] for folders whose PATH matches the
    query - i.e. audiobooks, which are folders of many files rather than one
    file with the book's name."""
    tokens = _query_tokens(query)
    if not tokens:
        return []
    items, _ts = _load_media_index()
    if not items:
        _ensure_index_building(gui=True)
        return []
    folders = {}
    for it in items:
        folder = _folder_url(it.get('url', ''))
        if not folder:
            continue
        if folder not in folders:
            if not _matches_tokens(unquote(folder), tokens):
                folders[folder] = None      # remembered as "does not match"
                continue
            folders[folder] = 0
        if folders[folder] is None:
            continue
        folders[folder] += 1
    matches = [(f, c) for f, c in folders.items() if c]
    matches.sort(key=lambda fc: fc[1], reverse=True)
    results = []
    for folder, count in matches[:limit]:
        name = unquote(folder.rstrip('/\\')).replace('\\', '/').rsplit('/', 1)[-1]
        results.append((name, folder, count))
    return results


def _to_folder_arg(folder):
    """A folder as something tMedia's startup argument can carry."""
    if '://' in folder:
        return folder
    try:
        return Path(folder).as_uri()
    except Exception:
        return folder


def titan_list_media_bookmarks(**_):
    """List what the user can resume in tMedia: every film, recording and
    audiobook with a saved position, plus their named bookmarks."""
    entries = _load_media_bookmarks()
    if not entries:
        return ("Nothing is saved yet - tMedia stores a resume point once "
                "something long has been played, and bookmarks when the user "
                "presses Ctrl+B.")
    lines = []
    for entry in entries[:25]:
        title = entry.get('title') or entry.get('url') or '?'
        head = f"- {title}"
        if entry.get('kind') == 'audiobook':
            head += f" (audiobook, {len(entry.get('tracks') or [])} tracks)"
        resume = entry.get('resume')
        if resume and resume.get('position'):
            head += f" - stopped at {_place_text(entry, resume)}"
        lines.append(head)
        for bookmark in entry.get('bookmarks') or []:
            lines.append(f"    bookmark '{bookmark.get('name', '')}' at "
                         f"{_place_text(entry, bookmark)}")
    return ("Saved positions and bookmarks in tMedia (resume one with "
            "titan_resume_media):\n" + "\n".join(lines))


def titan_play_audiobook(query="", path="", position="", **_):
    """Play a whole FOLDER as one audiobook in tMedia: every file in it, in
    order, continuing from where the user stopped last time.

    ``query`` finds the book's folder in the media library; ``path`` names it
    directly; ``position`` optionally starts somewhere specific instead of at
    the saved place ('50%', '49 minutes', '1:23:45', 'track 4 12:30')."""
    folder = (path or '').strip()
    name = None
    if not folder:
        q = (query or '').strip()
        if not q:
            return "Give the audiobook's name (query) or its folder (path)."
        try:
            results = _search_media_folders(q, limit=8)
        except Exception as e:
            return f"Audiobook search failed: {e}"
        if not results:
            return (f"Found no folder matching '{q}' in the media library."
                    + _index_status_note()
                    + " If it is a single file rather than a folder of files, "
                      "use titan_play_media.")
        name, folder, count = results[0]
        extra = ''
        if len(results) > 1:
            others = "; ".join(f"{n} ({c} files)" for n, _f, c in results[1:4])
            extra = f" (other matches: {others})"
        argument = f"audiobook:{_to_folder_arg(folder)}"
        spec = _sanitize_arg(position)
        if spec:
            argument = f"position:{spec}|{argument}"
        if not _open_in_tmedia(argument):
            return "Could not find the Titan media player (tMedia)."
        where = f" from {spec}" if spec else " from where it was left"
        return (f"Playing the audiobook '{name}' ({count} files){where} in "
                f"tMedia.{extra}")

    argument = f"audiobook:{_to_folder_arg(folder)}"
    spec = _sanitize_arg(position)
    if spec:
        argument = f"position:{spec}|{argument}"
    if not _open_in_tmedia(argument):
        return "Could not find the Titan media player (tMedia)."
    where = f" from {spec}" if spec else " from where it was left"
    return f"Playing the audiobook in '{folder}'{where} in tMedia."


def titan_resume_media(query="", bookmark="", **_):
    """Carry on with something the user was listening to or watching: pick the
    saved item matching ``query`` (or the most recent one) and play it from its
    saved position, or from one of its named bookmarks (``bookmark``)."""
    entries = _load_media_bookmarks()
    if not entries:
        return ("Nothing is saved to resume yet (tMedia saves a position once "
                "something long has been played).")
    entry = entries[0]
    q = (query or '').strip()
    if q:
        tokens = _query_tokens(q)
        matches = [e for e in entries
                   if _matches_tokens(f"{e.get('title', '')} {unquote(e.get('url', ''))}",
                                      tokens)]
        if not matches:
            titles = "; ".join(e.get('title', '?') for e in entries[:6])
            return f"Nothing saved matches '{q}'. Saved items: {titles}."
        entry = matches[0]

    url = entry.get('url') or ''
    if not url:
        return "That saved item has no location any more."
    argument = f"audiobook:{url}" if entry.get('kind') == 'audiobook' else url

    place, place_name = entry.get('resume'), 'the saved position'
    wanted = (bookmark or '').strip()
    if wanted:
        tokens = _query_tokens(wanted)
        found = [b for b in entry.get('bookmarks') or []
                 if _matches_tokens(b.get('name', ''), tokens)]
        if not found:
            names = "; ".join(b.get('name', '') for b in entry.get('bookmarks') or [])
            return (f"'{entry.get('title', '')}' has no bookmark matching "
                    f"'{wanted}'." + (f" Its bookmarks: {names}." if names else ""))
        place, place_name = found[0], f"bookmark '{found[0].get('name', '')}'"
    if place and place.get('position'):
        argument = f"position:{_place_spec(entry, place)}|{argument}"

    if not _open_in_tmedia(argument):
        return "Could not find the Titan media player (tMedia)."
    where = _place_text(entry, place) if place else 'the beginning'
    return (f"Resuming '{entry.get('title') or url}' in tMedia from "
            f"{place_name} ({where}).")


def titan_play_radio(country="", station="", **_):
    """Play internet radio in tMedia for a given country, AUTOMATICALLY selecting
    that country (no manual picker). ``country`` is the country in ENGLISH or its
    ISO code (e.g. 'Poland' or 'PL') - required to auto-select. ``station`` is an
    optional station name to search for and auto-play; without it the country's
    station list is shown."""
    c = _sanitize_arg(country)
    if not c:
        return ("Say which country's radio to open (in English or as an ISO "
                "code, e.g. 'Poland' or 'PL') so I can auto-select it.")
    s = _sanitize_arg(station)
    initial = f"radio:{c}:{s}"
    if not _open_in_tmedia(initial):
        return "Could not find the Titan media player (tMedia)."
    if s:
        return (f"Opening {country} radio in tMedia and playing a station "
                f"matching '{station}'.")
    return f"Opening {country} radio stations in tMedia."


# --------------------------------------------------------------------------- #
# Reminders (tReminder / "Titan Organizer")
# --------------------------------------------------------------------------- #
# tReminder stores its reminders as a JSON list in
# %APPDATA%/Titosoft/Titan/appsettings/calendar.tcal - each entry is
# {name, description, date 'YYYY-MM-DD', time 'HH:MM', priority 0/1/2,
# repeat 0..3, done}. We append straight to that file (the same source of truth
# the app reads on startup), so a reminder can be created whether or not the app
# is running.
_REMINDER_PRIORITY = {'low': 0, 'niski': 0, 'medium': 1, 'sredni': 1,
                      'średni': 1, 'normal': 1, 'high': 2, 'wysoki': 2}
# repeat index -> meaning: 0="2x every 3 min", 1="4x every min", 2="every 15
# min", 3="once".
_REMINDER_REPEAT = {'once': 3, 'raz': 3, 'tylko raz': 3, '15': 2,
                    'every15': 2, 'co15': 2}


def _appsettings_dir():
    """Titan's per-user app settings directory - where the bundled apps keep
    their own data (tReminder's calendar, tMedia's config and bookmarks)."""
    import platform
    plat = platform.system()
    if plat == 'Windows':
        base = os.getenv('APPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'Titosoft', 'Titan', 'appsettings')
    if plat == 'Darwin':
        return os.path.join(os.path.expanduser('~'), 'Library',
                            'Application Support', 'Titosoft', 'Titan', 'appsettings')
    return os.path.join(os.path.expanduser('~'), '.config', 'Titosoft', 'Titan',
                        'appsettings')


def reminder_file_path():
    """Full path of tReminder's calendar file (the shared source of truth for
    reminders, read by the app and by the automatic announcer)."""
    return os.path.join(_appsettings_dir(), 'calendar.tcal')


def _parse_reminder_datetime(date_str, time_str):
    """Return (date 'YYYY-MM-DD', time 'HH:MM') from flexible input, defaulting
    to today / the next hour. Accepts today/tomorrow, YYYY-MM-DD, DD.MM.YYYY,
    DD/MM/YYYY; time HH:MM (or HH.MM)."""
    import datetime
    now = datetime.datetime.now()
    d = (date_str or '').strip().lower()
    if d in ('', 'today', 'dzis', 'dziś', 'dzisiaj'):
        date = now.date()
    elif d in ('tomorrow', 'jutro'):
        date = now.date() + datetime.timedelta(days=1)
    else:
        date = None
        for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y', '%d-%m-%Y'):
            try:
                date = datetime.datetime.strptime(d, fmt).date()
                break
            except ValueError:
                continue
        if date is None:
            date = now.date()
    t = (time_str or '').strip().replace('.', ':')
    tm = None
    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            tm = datetime.datetime.strptime(t, fmt).time()
            break
        except ValueError:
            continue
    if tm is None:
        tm = (now + datetime.timedelta(hours=1)).time().replace(second=0, microsecond=0)
    return date.isoformat(), tm.strftime('%H:%M')


def titan_create_reminder(name, description="", date="", time="", priority="medium",
                          repeat="once", **_):
    """Create a reminder in tReminder (Titan Organizer). It is saved to the app's
    calendar file so it appears/alerts in tReminder (open the app to be alerted).
    ``date`` accepts today/tomorrow or YYYY-MM-DD (etc.); ``time`` is HH:MM;
    ``priority`` is low/medium/high; ``repeat`` is 'once' by default."""
    import json
    name = (name or '').strip()
    if not name:
        return "A reminder needs a name/title."
    date_iso, time_hm = _parse_reminder_datetime(date, time)
    prio = _REMINDER_PRIORITY.get((priority or '').strip().lower(), 1)
    rep = _REMINDER_REPEAT.get((repeat or '').strip().lower(), 3)
    entry = {'name': name, 'description': (description or name).strip(),
             'date': date_iso, 'time': time_hm, 'priority': prio,
             'repeat': rep, 'done': False}
    try:
        os.makedirs(_appsettings_dir(), exist_ok=True)
        path = reminder_file_path()
        data = []
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    data = []
            except (ValueError, OSError):
                data = []
        data.append(entry)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    except Exception as e:
        return f"Could not save the reminder: {e}"
    return (f"Reminder '{name}' saved for {date_iso} at {time_hm} in Titan "
            f"Organizer (tReminder). Titan announces it when it is due, even if "
            f"tReminder is closed.")


# --------------------------------------------------------------------------- #
# Open Titan's own windows
# --------------------------------------------------------------------------- #
def titan_speak(text, interrupt=False, **_):
    """Say something out loud through Titan's own speech.

    Windowless by definition: Titan's TTS engines are loaded in Titan's own
    process, so this reads text to the user without opening anything. It is
    what an add-on should use to have something read out - a note, a result, a
    warning - instead of shipping a voice of its own.
    """
    message = str(text or '').strip()
    if not message:
        return "There is nothing to say."
    stop_first = str(interrupt).strip().lower() in ('1', 'true', 'yes', 'on')
    try:
        from src.ai.ai_speech import speak
        speak(message, interrupt=stop_first)
    except Exception as e:
        return f"Could not speak: {e}"
    return f"Said: {message[:200]}" + ('...' if len(message) > 200 else '')


def titan_open_settings(**_):
    """Open Titan's Settings window."""
    def _open():
        from src.ui.settingsgui import SettingsFrame
        try:
            from src.titan_core.translation import set_language
            from src.settings.settings import get_setting
            _t = set_language(get_setting('language', 'pl'))
            title = _t("Settings")
        except Exception:
            title = "Settings"
        frame = SettingsFrame(None, title=title)
        frame.Show()
        frame.Raise()
        return True
    ok, err = _run_on_gui(_open)
    return "Opened the Settings window." if ok else f"Could not open Settings: {err}"


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def get_titan_tools():
    """Tools that expose Titan itself (settings, components, add-ons)."""
    from src.ai.agent_tools import _tool
    S = {'type': 'string'}
    B = {'type': 'boolean'}
    return [
        # Settings
        _tool('titan_list_settings',
              "List Titan's settings (secret values are hidden). Optional "
              "'section' lists just one section.", titan_list_settings,
              properties={'section': dict(S, description="Section name (optional).")}),
        _tool('titan_get_setting', "Get one Titan setting value.", titan_get_setting,
              properties={'key': dict(S, description="Setting key."),
                          'section': dict(S, description="Section (default 'general').")},
              required=['key']),
        _tool('titan_set_setting',
              "Change one Titan setting. Some settings need a restart to apply.",
              titan_set_setting, risk='confirm',
              properties={'key': dict(S, description="Setting key."),
                          'value': dict(S, description="New value."),
                          'section': dict(S, description="Section (default 'general').")},
              required=['key', 'value']),
        # Components
        _tool('titan_list_components',
              "List installed Titan components and their runnable menu actions.",
              titan_list_components),
        _tool('titan_run_component_action',
              "Run a component's menu action by name.", titan_run_component_action,
              risk='confirm',
              properties={'action': dict(S, description="Exact action name.")},
              required=['action']),
        _tool('titan_set_component_enabled',
              "Enable or disable a component by folder name (needs a reload/restart).",
              titan_set_component_enabled, risk='confirm',
              properties={'component': dict(S, description="Component folder or name."),
                          'enabled': dict(B, description="True to enable, False to disable.")},
              required=['component']),
        # Add-ons (all kinds)
        _tool('titan_list_addons',
              "List Titan add-ons of every kind (apps, games, components, "
              "launchers, Titan IM modules, gamepad modes, TTS engines, widgets, "
              "statusbar applets, languages). Optional 'kind' filters to one.",
              titan_list_addons,
              properties={'kind': dict(S, description="Add-on kind id (optional).")}),
        _tool('titan_launch',
              "Launch a Titan app, game or IM module by name.", titan_launch,
              risk='confirm',
              properties={'name': dict(S, description="App, game or IM module name.")},
              required=['name']),
        _tool('titan_list_tts_engines',
              "List Titan TTS engines and the active one.", titan_list_tts_engines),
        # Media library (tMedia): find a title and play it
        _tool('titan_list_media_catalogs',
              "List the user's configured Media Library catalogs (tMedia).",
              titan_list_media_catalogs),
        _tool('titan_search_media',
              "Search the user's Media Library (tMedia catalogs: online folders "
              "and local/Google Drive files) for media matching a title, series, "
              "artist or track. Uses a background-built index (fast).",
              titan_search_media,
              properties={'query': dict(S, description="Title/series/artist/track to find.")},
              required=['query']),
        _tool('titan_reindex_media',
              "Rebuild the media library index in the background (use if the "
              "library changed or a search reports the index is missing/stale).",
              titan_reindex_media),
        _tool('titan_play_media',
              "Play something from the user's Media Library in tMedia. Give a "
              "'query' to find and play a title/episode/audiobook (e.g. 'swiat "
              "wedlug kiepskich odc 6') or a direct 'url'/file - it plays right "
              "away. Use this for the user's own media; use titan_play_audiobook "
              "for a whole folder/book, titan_play_radio for internet radio and "
              "play_music for YouTube/Spotify.", titan_play_media,
              risk='confirm',
              properties={'query': dict(S, description="Title/series/episode/book to find and play."),
                          'url': dict(S, description="Direct media URL or file path (optional)."),
                          'position': dict(S, description="Start here instead of the beginning: '50%', '49 minutes', '1:23:45' (optional).")}),
        _tool('titan_play_audiobook',
              "Play a whole FOLDER as one audiobook in tMedia (all its files "
              "in order, continuing from where the user stopped). 'query' finds "
              "the book's folder in the media library, 'path' names it directly, "
              "'position' optionally starts somewhere specific ('50%', '49 "
              "minutes', '1:23:45', 'track 4 12:30').",
              titan_play_audiobook, risk='confirm',
              properties={'query': dict(S, description="Audiobook/folder name to find."),
                          'path': dict(S, description="Folder path or URL (optional)."),
                          'position': dict(S, description="Where to start (optional).")}),
        _tool('titan_list_media_bookmarks',
              "List what can be resumed in tMedia: films, recordings and "
              "audiobooks with a saved position, plus their named bookmarks.",
              titan_list_media_bookmarks),
        _tool('titan_resume_media',
              "Carry on with something the user was listening to or watching: "
              "plays the saved item matching 'query' (or the most recent one) "
              "from its saved position, or from one of its named bookmarks.",
              titan_resume_media, risk='confirm',
              properties={'query': dict(S, description="Which saved item (optional - default the most recent)."),
                          'bookmark': dict(S, description="Named bookmark to jump to (optional).")}),
        _tool('titan_play_radio',
              "Play internet radio in tMedia for a country, auto-selecting that "
              "country (no manual picker). 'country' is the country in English or "
              "its ISO code (e.g. 'Poland' or 'PL'); 'station' optionally names a "
              "station to find and auto-play.", titan_play_radio, risk='confirm',
              properties={'country': dict(S, description="Country in English or ISO code (e.g. Poland, PL)."),
                          'station': dict(S, description="Station name to search for (optional).")},
              required=['country']),
        # Reminders (tReminder / Titan Organizer)
        _tool('titan_create_reminder',
              "Create a reminder in tReminder (Titan Organizer). Saves it so it "
              "alerts when tReminder is running. date: today/tomorrow or "
              "YYYY-MM-DD; time: HH:MM; priority: low/medium/high.",
              titan_create_reminder, risk='confirm',
              properties={'name': dict(S, description="Reminder title."),
                          'description': dict(S, description="Text spoken/shown when it fires (optional)."),
                          'date': dict(S, description="today/tomorrow or a date like 2026-07-25."),
                          'time': dict(S, description="Time of day HH:MM (24h)."),
                          'priority': dict(S, description="low, medium or high (optional)."),
                          'repeat': dict(S, description="'once' (default) or 'every15'.")},
              required=['name']),
        # Titan IM (log in, list contacts, send messages)
        _tool('titan_im_login',
              "Log in to / open an IM service: 'titan_net', 'telegram' (username "
              "is the phone number), 'whatsapp' or 'messenger' (these open the web "
              "app in the browser to sign in; the desktop app can be used too).",
              titan_im_login,
              risk='confirm', always_confirm=True,
              properties={'service': dict(S, description="titan_net, telegram, whatsapp or messenger."),
                          'username': dict(S, description="Username (or phone for Telegram)."),
                          'password': dict(S, description="Password (optional for Telegram).")},
              required=['service', 'username']),
        _tool('titan_list_im_contacts',
              "List online users / contacts / chats of an IM service so you can "
              "pick a recipient.", titan_list_im_contacts,
              properties={'service': dict(S, description="titan_net, telegram, whatsapp or messenger.")},
              required=['service']),
        _tool('titan_send_message',
              "Send a private message to someone on an IM service: Titan-Net, "
              "Telegram, WhatsApp or Messenger. WhatsApp/Messenger go through the "
              "desktop app or the browser web app (no Titan IM needed): give a "
              "phone number for WhatsApp to pre-fill the chat, otherwise the "
              "recipient is the contact/chat name and you finish by typing and "
              "pressing Enter. The result tells you what to do next.",
              titan_send_message,
              risk='confirm', always_confirm=True,
              properties={'service': dict(S, description="titan_net, telegram, whatsapp or messenger."),
                          'recipient': dict(S, description="Username / phone / chat name."),
                          'message': dict(S, description="Message text to send.")},
              required=['service', 'recipient', 'message']),
        # Speech, without opening anything
        _tool('titan_speak',
              "Read text out loud through Titan's own speech. Needs no window "
              "and no add-on: use it to have something read to the user - a "
              "note, an answer, a warning.", titan_speak,
              properties={'text': dict(S, description="What to say."),
                          'interrupt': dict(B, description="Stop whatever is "
                                            "being said first (default no).")},
              required=['text']),
        # Titan windows
        _tool('titan_open_settings', "Open Titan's Settings window.",
              titan_open_settings, risk='confirm'),
    ]
