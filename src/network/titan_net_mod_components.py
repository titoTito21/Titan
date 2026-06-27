"""
Titan-Net Moderator Component API (v2).

A plugin surface that lets moderators *program new Titan-Net features* without
touching the core. Components are plain Python files dropped into the
user-data folder:

    %APPDATA%/titosoft/Titan/data/titan_net_mod_components/*.py

Each component file declares a ``COMPONENT`` dict and at least a ``run(api)``
function. It may also declare ``MENU_ITEMS`` (extra actions shown for the
component)::

    COMPONENT = {
        "name": "Hello moderators",
        "description": "Greets the current moderator.",
        "author": "you",
        "version": "1.0",
    }

    MENU_ITEMS = [
        {"label": "Say hello", "callback": "say_hello"},
    ]

    def run(api):
        api.message("Hello, " + (api.client.username or "moderator") + "!")

    def say_hello(api):
        api.announce("Hello from a menu action")

``api`` is a :class:`ModeratorComponentAPI` giving:
  * ``api.client``  — the live ``TitanNetClient`` (full access).
  * ``api.groups`` / ``api.forum`` / ``api.moderation`` / ``api.users`` —
    discoverable namespaces wrapping the client.
  * ``api.storage`` — per-component persistent JSON key/value store.
  * ``api.message`` / ``api.prompt`` / ``api.choose`` / ``api.announce`` —
    accessible UI helpers.

Components run on the UI thread (they may open their own wx dialogs).

NOTE: v2 grants full client access (no permission gate yet — deferred). The
event-bus hooks (on_message, on_forum_post, on_tick, ...) and the AI
generation flow are later phases; see the design memo.
"""
import base64
import json
import os
import importlib.util
import threading
import traceback

import wx

from src.titan_core.sound import play_sound
from src.titan_core.translation import set_language
from src.settings.settings import get_setting

_ = set_language(get_setting('language', 'pl'))


def _apply_skin(window):
    """Apply the active TCE skin to a component window/dialog (best-effort)."""
    try:
        from src.titan_core.skin_manager import apply_skin_to_window
        apply_skin_to_window(window)
    except Exception:
        pass


def get_components_dir():
    """Return (creating if needed) the moderator components folder."""
    try:
        from src.platform_utils import ensure_user_data_subdir
        return ensure_user_data_subdir('data', 'titan_net_mod_components')
    except Exception:
        base = os.path.join(os.path.expanduser('~'), '.titan', 'titan_net_mod_components')
        os.makedirs(base, exist_ok=True)
        return base


_EXAMPLE_COMPONENT = '''"""Example Titan-Net moderator component.

Copy this file, rename it, and edit run() to build your own moderator tool.
"""

COMPONENT = {
    "name": "Example: count my groups",
    "description": "Shows how many groups you can see and how many you moderate.",
    "author": "Titan-Net",
    "version": "1.0",
}

MENU_ITEMS = [
    {"label": "Remember a note", "callback": "remember_note"},
]


def run(api):
    result = api.groups.list()
    if not result.get("success"):
        api.message(result.get("error", "Failed to load groups"))
        return
    groups = result.get("groups", [])
    moderated = [g for g in groups if g.get("my_role") in ("owner", "moderator")]
    api.message(
        "You can see %d groups and moderate %d of them." % (len(groups), len(moderated))
    )


def remember_note(api):
    note = api.prompt("Write a note to store with this component:")
    if note:
        api.storage.set("note", note)
        api.announce("Saved. Stored note: " + api.storage.get("note", ""))
'''


_NEW_TEMPLATE = '''"""My Titan-Net moderator component."""

COMPONENT = {
    "name": "My component",
    "description": "What this component does.",
    "author": "",
    "version": "1.0",
    # Optional audience gates (omit for everyone, everywhere):
    # "moderators_only": True,
    # "allowed_regions": ["PL"],   # regional lock (allow-list)
    # "blocked_regions": ["RU"],
    # "requires_server": True,     # server add-on: only runs where it is active
}

MENU_ITEMS = [
    # {"label": "Do something", "callback": "do_something"},
]


def run(api):
    # Entry point. Use api.groups / api.forum / api.moderation / api.users,
    # api.storage (local) or api.cloud (per-user, server-side), and
    # api.message / api.prompt / api.choose / api.announce for accessible UI.
    # Tip: a component can also be a FOLDER with several files (entry file
    # component.py importing sibling modules).
    api.message("Hello from my component!")


# def do_something(api):
#     api.announce("Did something")
'''


API_REFERENCE_TEXT = """TITAN-NET MODERATOR COMPONENT API
=================================

A component is EITHER a single .py file OR a FOLDER (a package with several
files; its entry file is component.py / __init__.py / main.py and may import
the sibling modules normally). Either way it defines:
  COMPONENT = {"name", "description", "author", "version"}   (required dict)
  run(api)                                                   (required function)
  MENU_ITEMS = [{"label", "callback"}]                       (optional actions)
  named callback functions referenced by MENU_ITEMS          (optional)

COMPONENT may also carry optional AUDIENCE GATES that apply everywhere the
component runs (main view, Alt menu, hooks):
  "moderators_only": True            only moderators/developers see & run it
  "allowed_regions": ["PL", "US"]    regional LOCK: only these regions
  "blocked_regions": ["RU"]          regional block-list
  "requires_server": True            SERVER ADD-ON: needs the server side (e.g.
                                     api.cloud) so it only runs on a Titan-Net
                                     server that has it installed/active. On a
                                     server that does not have it, it does not
                                     run at all. The author can switch on local
                                     testing (Moderator Components window) to
                                     try it first; api.cloud then falls back to
                                     a local store.
Omit them (or leave empty) for "everyone, everywhere" — e.g. a cloud-notes
component for all users.

WHERE A COMPONENT APPEARS
-------------------------
An enabled component contributes to the Titan-Net MAIN VIEW (its name + each
MENU_ITEMS action become list entries) and to the Titan-Net MENU BAR under Alt
(a "Components" menu). This is how a moderator adds a whole new feature for
users without touching the core.

Components run on the UI thread and may open their own wx windows/dialogs
(custom GUI is allowed).

THE api OBJECT
--------------
api.client      Live TitanNetClient. Full access to every client method.

api.groups      list()  get(group_id)  create(name, description, visibility,
                member_limit)  update(group_id, **fields)  delete(group_id)
                join(group_id)  leave(group_id)
                members(group_id, status='active')
                approve_member(group_id, user_id)
                reject_member(group_id, user_id)
                set_moderator(group_id, user_id, make=True)
                forums(group_id)  create_forum(group_id, name, description)
                delete_forum(forum_id)

api.forum       topics(forum_id=None, category=None, limit=50)
                topic(topic_id)  replies(topic_id, limit=100)
                create_topic(title, content, category, forum_id)
                reply(topic_id, content)  delete_topic(topic_id)
                move(topic_id, forum_id)  search(query, category=None)

api.moderation  ban_from_group(group_id, user_id, reason=None)
                unban_from_group(group_id, user_id)
                move_requests()  approve_move(request_id)
                reject_move(request_id)
                jail(user_id, minutes, reason=None)   network-wide timed ban
                release(user_id)                      release a jailed user

api.users       all()

api.storage     get(key, default=None)  set(key, value)  delete(key)  all()
                Persistent JSON per component, LOCAL to this client only.

api.cloud       get(key, default=None)  set(key, value)        per-user
                get_shared(key, default=None)  set_shared(key, value)  global
                SERVER-side storage shared across every user's client (the same
                approved component runs everywhere). Per-user keys are
                namespaced by username — use this for e.g. cloud notes. Note:
                the server does not yet ENFORCE per-user isolation, so treat
                per-user data as private-by-convention, not secret.

UI HELPERS
----------
api.message(text)            Info dialog.
api.confirm(text) -> bool    Yes/No dialog.
api.prompt(text, default)    Text input, returns string or None.
api.choose(text, choices)    Single choice, returns index or None.
api.announce(text)           Speak/notify through Titan-Net.
api.speak(text)              Alias for announce (screen reader / Titan TTS).
api.play_component_sound(name)  Play one of THIS component's own sounds
                             (streamed from the server, then cached). For
                             custom sounds, prefer this over inventing names.
api.tts_message(name)        Speak one of THIS component's own TTS messages
                             (server-streamed).
api.translate(lang, key)     Look up a string in THIS component's own language
                             asset (server-streamed JSON of key->text).
api.play_sound(name)         Play a sound. Either an EXISTING TCE theme sound
                             (e.g. 'titannet/online.ogg', 'core/SELECT.ogg') —
                             never invent theme sound names — OR the
                             component's OWN bundled sound file (absolute path
                             in the component folder; for network extensions
                             these are streamed from the server). Missing
                             sounds degrade silently.

BUFFERS (buffer review system, under the 'Titan-Net' category)
--------------------------------------------------------------
api.buffers.ensure_buffer(buffer_id, name)        Create/ensure a buffer.
api.buffers.push(buffer_id, text, author=None)    Add an entry users can
                                                  review with the buffer keys.

BUILDING YOUR OWN GUI CONTROLS (wxPython)
-----------------------------------------
A component may open its own window/dialog with wx. Use api.window as the
parent and api.apply_skin(dlg) so it matches the TCE theme. Keep it
keyboard-accessible: give every control a visible label, rely on wx default
tab order, and don't trap focus. Minimal accessible dialog:

    import wx

    def run(api):
        dlg = wx.Dialog(api.window, title="My tool", size=(420, 260))
        api.apply_skin(dlg)
        panel = wx.Panel(dlg)
        box = wx.BoxSizer(wx.VERTICAL)

        box.Add(wx.StaticText(panel, label="Your name:"), flag=wx.ALL, border=6)
        name = wx.TextCtrl(panel)                       # edit field
        box.Add(name, flag=wx.EXPAND | wx.ALL, border=6)

        choice = wx.Choice(panel, choices=["One", "Two"])  # combo box
        box.Add(choice, flag=wx.EXPAND | wx.ALL, border=6)

        lst = wx.ListBox(panel, choices=["alpha", "beta"])  # list
        box.Add(lst, proportion=1, flag=wx.EXPAND | wx.ALL, border=6)

        ok = wx.Button(panel, wx.ID_OK, "OK")              # button + event
        ok.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_OK))
        box.Add(ok, flag=wx.ALL, border=6)

        panel.SetSizer(box)
        if dlg.ShowModal() == wx.ID_OK:
            api.announce("Hello " + name.GetValue())   # speak the result
        dlg.Destroy()

Common controls: wx.StaticText (label), wx.TextCtrl (single/TE_MULTILINE),
wx.Button, wx.CheckBox, wx.Choice, wx.ListBox/ListCtrl, wx.SpinCtrl. Bind events
with control.Bind(wx.EVT_BUTTON, handler). For quick prompts you don't need a
full dialog — use api.prompt / api.choose / api.confirm / api.message instead.

SOUNDS & SPEECH (no AI needed)
------------------------------
    api.announce("Saved")                 # speak via screen reader / Titan TTS
    api.speak("Saved")                    # same thing
    api.play_sound("core/SELECT.ogg")     # an EXISTING theme sound (don't invent)
    api.play_component_sound("ding.ogg")  # YOUR own sound, streamed from server
    api.tts_message("welcome")            # YOUR own TTS message, streamed
Never invent theme sound names — ship your own sound as a component asset and
play it with api.play_component_sound. Missing sounds simply do nothing.

COMPOSITION (attach a component to another component)
-----------------------------------------------------
api.components.provide(point, fn)   In on_load(api): plug fn into a host's
                                    extension point (e.g. a 'dice_roll' child
                                    into a game host's 'game.actions' point).
api.components.invoke(point, **kw)  A host runs every provider plugged into
                                    point; returns their results.
api.components.points()             Known extension point names.
api.components.providers(point)     Component keys providing at point.

Define on_load(api) to register providers when your component is enabled.

Most api.* calls return the server's dict, typically {"success": bool, ...}.
Always check result.get("success").

EVENT HOOKS (optional functions; only fire while the component is ENABLED)
-------------------------------------------------------------------------
on_message(api, e)           A chat room message arrived. e has the message.
on_private_message(api, e)   A private message arrived.
on_user_online(api, e)       A user came online. e['username'].
on_user_offline(api, e)      A user went offline.
on_forum_post(api, e)        A forum thread/reply was posted.
on_tick(api, e)              Periodic timer (~every 30s).

Hooks run in the background — prefer api.announce / api.storage over modal
dialogs inside a hook. A hook that raises is caught and never breaks Titan-Net.
"""


_GUI_EXAMPLE_COMPONENT = '''"""Example moderator component WITH its own GUI, sound and speech.

A template for authors who do not use AI: shows how to build accessible wx
controls, speak with TTS, and play a sound.
"""
import wx

COMPONENT = {
    "name": "Example: GUI, sound and speech",
    "description": "A small accessible dialog that greets you, speaks and beeps.",
    "author": "Titan-Net",
    "version": "1.0",
}


def run(api):
    dlg = wx.Dialog(api.window, title="Greeter", size=(420, 220))
    api.apply_skin(dlg)                      # match the TCE theme
    panel = wx.Panel(dlg)
    box = wx.BoxSizer(wx.VERTICAL)

    box.Add(wx.StaticText(panel, label="Your name:"), flag=wx.ALL, border=8)
    name = wx.TextCtrl(panel)
    box.Add(name, flag=wx.EXPAND | wx.ALL, border=8)

    greet = wx.Button(panel, label="Greet me")
    box.Add(greet, flag=wx.ALL, border=8)

    def on_greet(evt):
        who = name.GetValue().strip() or "moderator"
        api.play_sound("core/SELECT.ogg")    # an existing theme sound
        api.announce("Hello " + who)         # speak via TTS / screen reader

    greet.Bind(wx.EVT_BUTTON, on_greet)
    panel.SetSizer(box)
    name.SetFocus()
    dlg.ShowModal()
    dlg.Destroy()
'''


_NOTES_EXAMPLE_COMPONENT = '''"""Example: cloud notes for EVERYONE.

A moderator builds this once and submits it to the network; after approval it
runs in every user's client and each user gets their own notes that follow them
across devices (stored server-side via api.cloud, namespaced per user).

This component is a SERVER ADD-ON: it stores data on the server (api.cloud), so
it only runs once approved and active on the Titan-Net server you connect to
("requires_server"). On a server that does not have it, it simply does not run.
Its author can still switch on local testing in the Moderator Components window
to try it first (api.cloud then falls back to a local store).

It is for everyone (no moderators_only / region lock). To make a
moderators-only or region-locked feature, add to COMPONENT, e.g.:
    "moderators_only": True,
    "allowed_regions": ["PL"],
"""

COMPONENT = {
    "name": "Cloud notes",
    "description": "Personal notes saved in the cloud, available to every user.",
    "author": "Titan-Net",
    "version": "1.0",
    # Needs the server side (api.cloud) -> only runs where it is active.
    "requires_server": True,
}

MENU_ITEMS = [
    {"label": "Add a note", "callback": "add_note"},
]


def _load(api):
    notes = api.cloud.get("notes", [])
    return notes if isinstance(notes, list) else []


def run(api):
    notes = _load(api)
    if not notes:
        api.message("You have no notes yet. Use 'Add a note'.")
        return
    api.message("\\n".join("- " + str(n) for n in notes), caption="Your notes")


def add_note(api):
    text = api.prompt("Write your note:")
    if not text:
        return
    notes = _load(api)
    notes.append(text)
    result = api.cloud.set("notes", notes)
    if result.get("success"):
        api.announce("Note saved to the cloud")
    else:
        api.message(result.get("error", "Could not save the note"))
'''


def _seed_example(components_dir):
    """Drop a README + example component the first time the folder is empty."""
    try:
        readme = os.path.join(components_dir, 'README.txt')
        if not os.path.exists(readme):
            with open(readme, 'w', encoding='utf-8') as f:
                f.write(
                    "Titan-Net moderator components\n"
                    "==============================\n\n"
                    "Drop *.py files OR folders here. Each component must "
                    "define a COMPONENT dict (name, description, author, "
                    "version) and a run(api) function. A FOLDER component has "
                    "several files; its entry file is component.py / "
                    "__init__.py / main.py and may import the sibling modules. "
                    "Optionally MENU_ITEMS (extra actions) and named callbacks.\n\n"
                    "COMPONENT optional gates: moderators_only=True, "
                    "allowed_regions=[...], blocked_regions=[...], "
                    "requires_server=True (server add-on: only runs where it "
                    "is active on the server; the author can switch on local "
                    "testing in the Moderator Components window).\n\n"
                    "api.client      - live TitanNetClient (full access)\n"
                    "api.groups      - list/get/create/join/leave/members/...\n"
                    "api.forum       - topics/replies/create/move/search\n"
                    "api.moderation  - ban/unban/move-requests approve/reject\n"
                    "api.users       - all()\n"
                    "api.storage     - persistent JSON per component (LOCAL)\n"
                    "api.cloud       - server-side storage (per-user + shared)\n"
                    "api.message/prompt/choose/announce - accessible UI\n"
                    "api.play_sound / api.play_component_sound / api.tts_message\n"
                    "api.apply_skin(window) - theme your own wx dialogs\n\n"
                    "Enabled components also appear in the Titan-Net main view "
                    "and the Alt menu (Components).\n\n"
                    "Examples: example_component.py (basic), "
                    "gui_example_component.py (own GUI + sound + speech), "
                    "cloud_notes_component.py (cloud storage for everyone).\n"
                    "Full reference with a GUI-building walkthrough: the "
                    "Documentation button in the Moderator Components window.\n"
                )
        example = os.path.join(components_dir, 'example_component.py')
        if not os.path.exists(example):
            with open(example, 'w', encoding='utf-8') as f:
                f.write(_EXAMPLE_COMPONENT)
        gui_example = os.path.join(components_dir, 'gui_example_component.py')
        if not os.path.exists(gui_example):
            with open(gui_example, 'w', encoding='utf-8') as f:
                f.write(_GUI_EXAMPLE_COMPONENT)
        notes_example = os.path.join(components_dir, 'cloud_notes_component.py')
        if not os.path.exists(notes_example):
            with open(notes_example, 'w', encoding='utf-8') as f:
                f.write(_NOTES_EXAMPLE_COMPONENT)
    except Exception as e:
        print(f"[mod-components] could not seed example: {e}")


# ----------------------------------------------------------------------------
# Per-component persistent storage
# ----------------------------------------------------------------------------

class ComponentStorage:
    """A tiny JSON key/value store scoped to one component (by file name).

    Persisted to ``<components_dir>/_state/<component>.json``.
    """

    def __init__(self, components_dir, component_key):
        self._dir = os.path.join(components_dir, '_state')
        self._path = os.path.join(self._dir, component_key + '.json')
        self._data = {}
        try:
            if os.path.exists(self._path):
                with open(self._path, 'r', encoding='utf-8') as f:
                    self._data = json.load(f)
        except Exception:
            self._data = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self._save()

    def delete(self, key):
        self._data.pop(key, None)
        self._save()

    def all(self):
        return dict(self._data)

    def _save(self):
        try:
            os.makedirs(self._dir, exist_ok=True)
            with open(self._path, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[mod-components] storage save failed: {e}")


# ----------------------------------------------------------------------------
# API namespaces (thin wrappers over TitanNetClient)
# ----------------------------------------------------------------------------

class _Namespace:
    def __init__(self, client):
        self._client = client

    def _call(self, name, *args, **kwargs):
        fn = getattr(self._client, name, None)
        if not callable(fn):
            return {"success": False, "error": f"Client has no method '{name}'"}
        return fn(*args, **kwargs)


class _GroupsAPI(_Namespace):
    def list(self): return self._call('list_groups')
    def get(self, group_id): return self._call('get_group', group_id)
    def create(self, name, description=None, visibility='public', member_limit=None):
        return self._call('create_group', name, description, visibility, member_limit)
    def update(self, group_id, **fields): return self._call('update_group', group_id, **fields)
    def delete(self, group_id): return self._call('delete_group', group_id)
    def join(self, group_id): return self._call('join_group', group_id)
    def leave(self, group_id): return self._call('leave_group', group_id)
    def members(self, group_id, status='active'): return self._call('get_group_members', group_id, status)
    def approve_member(self, group_id, user_id): return self._call('approve_group_member', group_id, user_id)
    def reject_member(self, group_id, user_id): return self._call('reject_group_member', group_id, user_id)
    def set_moderator(self, group_id, user_id, make=True): return self._call('set_group_moderator', group_id, user_id, make)
    def forums(self, group_id): return self._call('list_group_forums', group_id)
    def create_forum(self, group_id, name, description=None): return self._call('create_group_forum', group_id, name, description)
    def delete_forum(self, forum_id): return self._call('delete_group_forum', forum_id)


class _ForumAPI(_Namespace):
    def topics(self, forum_id=None, category=None, limit=50): return self._call('get_forum_topics', category, limit, forum_id)
    def topic(self, topic_id): return self._call('get_forum_topic', topic_id)
    def replies(self, topic_id, limit=100): return self._call('get_forum_replies', topic_id, limit)
    def create_topic(self, title, content, category='general', forum_id=None):
        return self._call('create_forum_topic', title, content, category, forum_id)
    def reply(self, topic_id, content): return self._call('add_forum_reply', topic_id, content)
    def delete_topic(self, topic_id): return self._call('delete_forum_topic', topic_id)
    def move(self, topic_id, forum_id): return self._call('move_topic_to_forum', topic_id, forum_id)
    def search(self, query, category=None): return self._call('search_forum', query, category)


class _ModerationAPI(_Namespace):
    def ban_from_group(self, group_id, user_id, reason=None): return self._call('ban_from_group', group_id, user_id, reason)
    def unban_from_group(self, group_id, user_id): return self._call('unban_from_group', group_id, user_id)
    def move_requests(self): return self._call('list_move_requests')
    def approve_move(self, request_id): return self._call('approve_move_request', request_id)
    def reject_move(self, request_id): return self._call('reject_move_request', request_id)
    # Server-enforced, network-wide timed jail (e.g. "virtual jail").
    def jail(self, user_id, minutes, reason=None): return self._call('jail_user', user_id, minutes, reason)
    def release(self, user_id): return self._call('release_user', user_id)


class _UsersAPI(_Namespace):
    def all(self): return self._call('get_all_users')


# Inter-component composition registry. A HOST component declares extension
# points and invokes them; CHILD components plug in providers (e.g. a
# "dice roll" child plugs into a "game" host). Cleared and rebuilt whenever the
# runtime reloads, so providers are registered from components' on_load(api).
_EXTENSION_POINTS = {}


def _clear_extension_points():
    _EXTENSION_POINTS.clear()


class _ComponentsAPI:
    """Lets a component attach to / be attached by other components."""

    def __init__(self, component_key):
        self._key = component_key

    def provide(self, point_name, fn):
        """Register a callable into another component's extension point. Call
        this from your component's on_load(api)."""
        if callable(fn):
            _EXTENSION_POINTS.setdefault(point_name, []).append((self._key, fn))

    def invoke(self, point_name, **payload):
        """Call every provider registered at point_name; return their results.
        A host (e.g. a game) calls this to run plugged-in children (e.g. dice
        roll). Each provider receives the payload dict."""
        results = []
        for key, fn in list(_EXTENSION_POINTS.get(point_name, [])):
            try:
                results.append({'component': key, 'result': fn(payload)})
            except Exception as e:
                print(f"[mod-components] extension point {point_name} provider {key} error: {e}")
        return results

    def points(self):
        return list(_EXTENSION_POINTS.keys())

    def providers(self, point_name):
        return [k for k, _ in _EXTENSION_POINTS.get(point_name, [])]


class _CloudStorage:
    """Per-component storage that lives on the SERVER (shared across every
    user's client), backed by the extension data KV.

    ``get``/``set`` are scoped to the CURRENT user (keys namespaced by username)
    so a component like cloud notes gives each user their own data. The
    ``*_shared`` variants are visible to everyone (e.g. a global announcement
    board). Distribution is the same as a network extension: an approved
    component's storage is reachable from any client.

    LOCAL FALLBACK: the server only accepts data for an ACTIVE network
    extension. A component the author is still developing locally (or one used
    while offline) is not active server-side, so the server replies "active
    extension not found". Rather than failing, this store then transparently
    persists to a LOCAL JSON file, so cloud-backed components (e.g. cloud notes)
    work end-to-end while testing locally and switch to the real server store
    once the component is approved and active. The local copy is per-user and
    per-component, mirroring the server's namespacing.

    NOTE: the server authenticates the request but does not yet ENFORCE
    per-user isolation, so treat namespaced data as private-by-convention, not
    secret. Returns plain dicts ({'success': ...})."""

    def __init__(self, client, slug, components_dir=None):
        self._client = client
        self._slug = slug
        # A local store used whenever the server has no active extension for
        # this slug (local testing / offline). Keyed by '_cloud_<slug>'.
        self._local = None
        if components_dir:
            try:
                self._local = ComponentStorage(components_dir, '_cloud_' + slug)
            except Exception:
                self._local = None

    def _user_key(self, key):
        uname = getattr(self._client, 'username', '') or '?'
        return f"u:{uname}:{key}"

    def _get(self, full_key, default):
        r = self._client.extension_data_get(self._slug, full_key)
        if isinstance(r, dict) and r.get('success'):
            val = r.get('value')
            return default if val is None else val
        # Server has no active extension for this slug -> local fallback.
        if self._local is not None:
            return self._local.get(full_key, default)
        return default

    def _set(self, full_key, value):
        r = self._client.extension_data_set(self._slug, full_key, value)
        if isinstance(r, dict) and r.get('success'):
            return r
        # Not active server-side -> persist locally so the component still works.
        if self._local is not None:
            self._local.set(full_key, value)
            return {'success': True, 'local': True}
        return r if isinstance(r, dict) else {'success': False, 'error': 'cloud unavailable'}

    def get(self, key, default=None):
        return self._get(self._user_key(key), default)

    def set(self, key, value):
        return self._set(self._user_key(key), value)

    def get_shared(self, key, default=None):
        return self._get(f"g:{key}", default)

    def set_shared(self, key, value):
        return self._set(f"g:{key}", value)


class ModeratorComponentAPI:
    """Surface handed to a component's ``run(api)`` / menu callbacks."""

    def __init__(self, titan_client, parent_window, components_dir, component_key):
        self.client = titan_client
        self.window = parent_window
        self.component_key = component_key
        self.component_dir = components_dir
        self.groups = _GroupsAPI(titan_client)
        self.forum = _ForumAPI(titan_client)
        self.moderation = _ModerationAPI(titan_client)
        self.users = _UsersAPI(titan_client)
        self.components = _ComponentsAPI(component_key)
        self.storage = ComponentStorage(components_dir, component_key)
        self._buffers = None
        self._cloud = None

    @property
    def buffers(self):
        """Push entries into the buffer system under the 'Titan-Net' category.
        Lazily bound. Use api.buffers.ensure_buffer(buffer_id, name) then
        api.buffers.push(buffer_id, text, author=...)."""
        if self._buffers is None:
            try:
                from src.buffers import buffer_bus
                self._buffers = buffer_bus.make_module_api('titannet', 'Titan-Net')
            except Exception:
                self._buffers = None
        return self._buffers

    @property
    def cloud(self):
        """Server-side storage shared across all clients (the same approved
        component runs everywhere). api.cloud.get/set are per-user; api.cloud
        .get_shared/set_shared are global. Backs features like cloud notes."""
        if self._cloud is None:
            self._cloud = _CloudStorage(self.client, self._slug(), self.component_dir)
        return self._cloud

    # --- accessible UI helpers ---
    def message(self, text, caption=None):
        wx.MessageBox(str(text), caption or _("Component"), wx.OK | wx.ICON_INFORMATION, self.window)

    def confirm(self, text, caption=None):
        return wx.MessageBox(str(text), caption or _("Component"),
                             wx.YES_NO | wx.ICON_QUESTION, self.window) == wx.YES

    def prompt(self, text, caption=None, default=""):
        dlg = wx.TextEntryDialog(self.window, str(text), caption or _("Component"), default)
        value = dlg.GetValue() if dlg.ShowModal() == wx.ID_OK else None
        dlg.Destroy()
        return value

    def choose(self, text, choices, caption=None):
        dlg = wx.SingleChoiceDialog(self.window, str(text), caption or _("Component"), list(choices))
        value = dlg.GetSelection() if dlg.ShowModal() == wx.ID_OK else None
        dlg.Destroy()
        return value

    def announce(self, text):
        try:
            from src.network.titan_net_gui import speak_notification
            speak_notification(str(text), 'info')
        except Exception:
            pass

    # alias — speak some text through Titan-Net (screen reader / Titan TTS).
    def speak(self, text):
        self.announce(text)

    def apply_skin(self, window):
        """Apply the active TCE skin to a component's own window/dialog so it
        matches the rest of the environment."""
        _apply_skin(window)

    def play_sound(self, name):
        """Play a sound by theme-relative path (e.g. 'titannet/online.ogg') or
        an absolute path to a file inside the component's folder."""
        try:
            if os.path.isabs(str(name)) and os.path.exists(str(name)):
                from src.titan_core.sound import play_sound_file
                play_sound_file(str(name))
            else:
                play_sound(str(name))
        except Exception as e:
            print(f"[mod-components] play_sound failed: {e}")

    # --- the component's OWN assets, streamed from the server ---
    def _slug(self):
        k = self.component_key
        return k[4:] if k.startswith('ext_') else k

    def _asset_cache_path(self, kind, name):
        d = os.path.join(self.component_dir, '_assets', self._slug(), kind)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, name)

    def play_component_sound(self, name):
        """Play one of THIS component's own sounds (streamed from the server
        for network extensions, then cached locally). Falls back silently."""
        try:
            cached = self._asset_cache_path('sound', name)
            if not os.path.exists(cached):
                resp = self.client.get_extension_asset(self._slug(), 'sound', name)
                if not resp.get('success'):
                    return
                content = resp.get('asset', {}).get('content', '')
                with open(cached, 'wb') as f:
                    f.write(base64.b64decode(content))
            from src.titan_core.sound import play_sound_file
            play_sound_file(cached)
        except Exception as e:
            print(f"[mod-components] play_component_sound failed: {e}")

    def tts_message(self, name):
        """Speak one of THIS component's own TTS messages (server-streamed)."""
        try:
            resp = self.client.get_extension_asset(self._slug(), 'tts', name)
            if resp.get('success'):
                self.announce(resp.get('asset', {}).get('content', ''))
        except Exception as e:
            print(f"[mod-components] tts_message failed: {e}")

    def translate(self, lang_name, key, default=None):
        """Look up a string in one of THIS component's own language assets
        (a JSON object of key->text, server-streamed)."""
        try:
            resp = self.client.get_extension_asset(self._slug(), 'lang', lang_name)
            if resp.get('success'):
                data = json.loads(resp.get('asset', {}).get('content', '{}'))
                return data.get(key, default if default is not None else key)
        except Exception as e:
            print(f"[mod-components] translate failed: {e}")
        return default if default is not None else key


# ----------------------------------------------------------------------------
# Discovery + enable/disable state
# ----------------------------------------------------------------------------

def _enabled_path(components_dir):
    return os.path.join(components_dir, '_enabled.json')


def load_enabled_state(components_dir):
    try:
        path = _enabled_path(components_dir)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_enabled_state(components_dir, state):
    try:
        with open(_enabled_path(components_dir), 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[mod-components] enabled-state save failed: {e}")


def _local_test_path(components_dir):
    return os.path.join(components_dir, '_local_test.json')


def load_local_test_state(components_dir):
    """Keys of components the AUTHOR has switched on for LOCAL testing. A
    server add-on component (requires_server) normally only surfaces once it is
    active on the connected server; listing it here lets its author run it in
    their own client first to see how it really behaves in Titan-Net."""
    try:
        path = _local_test_path(components_dir)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
    except Exception:
        pass
    return set()


def save_local_test_state(components_dir, keys):
    try:
        with open(_local_test_path(components_dir), 'w', encoding='utf-8') as f:
            json.dump(sorted(keys), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[mod-components] local-test-state save failed: {e}")


def _unpack_extension_bundle(b64_zip, dest_dir):
    """Replace ``dest_dir`` with the contents of a base64-encoded zip bundle.
    Zip-slip safe: entries that escape dest_dir are skipped."""
    import io
    import shutil
    import zipfile
    if os.path.isdir(dest_dir):
        shutil.rmtree(dest_dir, ignore_errors=True)
    os.makedirs(dest_dir, exist_ok=True)
    raw = base64.b64decode(b64_zip)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        dest_abs = os.path.abspath(dest_dir)
        for member in zf.namelist():
            target = os.path.abspath(os.path.join(dest_dir, member))
            if not (target == dest_abs or target.startswith(dest_abs + os.sep)):
                print(f"[mod-components] skipped unsafe zip entry: {member}")
                continue
            if member.endswith('/'):
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(member) as src, open(target, 'wb') as out:
                out.write(src.read())


def sync_active_extensions(titan_client, components_dir=None):
    """Download every ACTIVE approved extension into the components folder so
    the runtime loads them like local components — THIS is how Titan-Net runs a
    component on every user's client: each client pulls the approved code from
    the server, caches it locally, and the runtime executes it.

    A 'single' extension is written as ``ext_<slug>.py``; a 'folder' extension
    has its base64 zip unpacked into ``ext_<slug>/``. Each is refreshed only
    when the server hash differs from the cached one. Returns the number of
    extensions written/updated."""
    if components_dir is None:
        components_dir = get_components_dir()
    written = 0
    try:
        listing = titan_client.list_extensions(status='active')
        if not listing.get('success'):
            return 0
        # Record which extensions this server actually has active, so the
        # runtime can gate server add-on components (requires_server): a
        # component the connected server does not have simply does not run.
        active_slugs = {ext.get('slug') for ext in listing.get('extensions', []) if ext.get('slug')}
        if _RUNTIME is not None:
            _RUNTIME.active_slugs = active_slugs
        hashes_path = os.path.join(components_dir, '_ext_hashes.json')
        try:
            with open(hashes_path, 'r', encoding='utf-8') as f:
                known = json.load(f)
        except Exception:
            known = {}
        for ext in listing.get('extensions', []):
            slug = ext.get('slug')
            if not slug:
                continue
            detail = titan_client.get_extension_client(slug)
            if not detail.get('success'):
                continue
            body = detail.get('extension', {})
            code_hash = body.get('code_hash') or ''
            kind = body.get('kind') or 'single'
            file_target = os.path.join(components_dir, f'ext_{slug}.py')
            dir_target = os.path.join(components_dir, f'ext_{slug}')
            already = (
                known.get(slug) == code_hash
                and (os.path.exists(dir_target) if kind == 'folder' else os.path.exists(file_target))
            )
            if already:
                continue
            try:
                if kind == 'folder' and body.get('bundle'):
                    # Drop any stale single-file form, then unpack the bundle.
                    if os.path.exists(file_target):
                        os.remove(file_target)
                    _unpack_extension_bundle(body['bundle'], dir_target)
                else:
                    code = body.get('client_code') or ''
                    with open(file_target, 'w', encoding='utf-8') as f:
                        f.write(code)
                known[slug] = code_hash
                written += 1
            except Exception as e:
                print(f"[mod-components] could not write extension {slug}: {e}")
        try:
            with open(hashes_path, 'w', encoding='utf-8') as f:
                json.dump(known, f)
        except Exception:
            pass
    except Exception as e:
        print(f"[mod-components] sync_active_extensions failed: {e}")
    return written


# ----------------------------------------------------------------------------
# Audience gating — moderators-only flag and regional lock
# ----------------------------------------------------------------------------

def _current_region():
    """Best-effort 2-letter region code for the current user (upper-case).

    An explicit ``region`` setting wins; otherwise the system locale's country
    (``pl_PL`` -> ``PL``); otherwise the UI language (``pl`` -> ``PL``)."""
    try:
        r = (get_setting('region', '') or '').strip().upper()
        if r:
            return r
    except Exception:
        pass
    try:
        import locale
        loc = locale.getlocale()[0] or (locale.getdefaultlocale() or [''])[0] or ''
        if '_' in loc:
            return loc.split('_')[1].upper()
    except Exception:
        pass
    try:
        return (get_setting('language', 'pl') or 'pl').upper()
    except Exception:
        return ''


def _user_is_moderator(titan_client):
    role = getattr(titan_client, 'user_role', 'user') if titan_client is not None else 'user'
    return role in ('moderator', 'developer')


def _component_server_slug(component):
    """The network slug a component maps to: a synced extension keeps its slug
    after the ``ext_`` prefix; a local file uses its key with dashes (matching
    how Submit-to-Network derives the slug)."""
    key = component.get('key', '')
    if key.startswith('ext_'):
        return key[4:]
    return key.replace('_', '-')


def is_component_accessible(component, titan_client=None, region=None,
                            active_slugs=None):
    """Whether a component should be visible/run for THIS user, honouring its
    manifest audience gates::

        COMPONENT = {..., "moderators_only": True,
                     "allowed_regions": ["PL", "US"],   # allow-list (lock)
                     "blocked_regions": ["RU"],          # block-list
                     "requires_server": True}            # server add-on

    Missing/empty gates mean "everyone, everywhere".

    ``requires_server`` marks a SERVER ADD-ON: the component depends on the
    server side (e.g. api.cloud) and must NOT run on a Titan-Net server that
    does not have it installed/active. ``active_slugs`` is the set of slugs the
    connected server currently has active; when the component's slug is not in
    it the component is inaccessible. (The author can still test it via the
    local-test override — handled by the runtime, not here.) When
    ``active_slugs`` is unknown (None) a server add-on is treated as not
    accessible, so it never runs against a server that has not confirmed it."""
    if component.get('moderators_only') and not _user_is_moderator(titan_client):
        return False
    if region is None:
        region = _current_region()
    allowed = [str(a).upper() for a in (component.get('allowed_regions') or [])]
    blocked = [str(b).upper() for b in (component.get('blocked_regions') or [])]
    if allowed and region not in allowed:
        return False
    if blocked and region in blocked:
        return False
    if component.get('requires_server'):
        slugs = active_slugs if active_slugs is not None else set()
        if _component_server_slug(component) not in slugs:
            return False
    return True


# A folder component is a directory holding several files; its entry point is
# the first of these that exists (it defines COMPONENT + run and may import the
# sibling modules).
_COMPONENT_ENTRY_NAMES = ('component.py', '__init__.py', 'main.py')


def _component_entry_file(folder):
    for cand in _COMPONENT_ENTRY_NAMES:
        p = os.path.join(folder, cand)
        if os.path.exists(p):
            return p
    return None


def _load_component_module(path, key):
    """Load a component from either a single ``.py`` file or a FOLDER (package).

    For a folder, the entry file (``component.py`` / ``__init__.py`` / ``main.py``)
    is executed as a package so its sibling modules import normally (``from . import
    x`` and plain ``import x`` both work). Returns the loaded module or None."""
    import sys
    mod_name = 'titan_mod_component_' + key
    if os.path.isdir(path):
        entry = _component_entry_file(path)
        if entry is None:
            return None
        spec = importlib.util.spec_from_file_location(
            mod_name, entry, submodule_search_locations=[path])
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module  # let submodules resolve the package
        added = path not in sys.path
        if added:
            sys.path.insert(0, path)
        try:
            spec.loader.exec_module(module)
        finally:
            if added:
                try:
                    sys.path.remove(path)
                except ValueError:
                    pass
        return module
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def discover_components(components_dir):
    """Load every valid component. A component is either a single ``.py`` file
    or a FOLDER (package) with an entry file and any number of sibling modules.
    Returns a list of dicts with keys: key, name, description, author, version,
    run, menu_items (list of {label, callback_fn}), module, path, entry,
    is_package, enabled, moderators_only, allowed_regions, blocked_regions."""
    components = []
    if not os.path.isdir(components_dir):
        return components
    enabled_state = load_enabled_state(components_dir)
    for name in sorted(os.listdir(components_dir)):
        if name.startswith('_'):
            continue  # _state, _assets, _enabled.json, _ext_hashes.json, ...
        full = os.path.join(components_dir, name)
        is_package = os.path.isdir(full)
        if is_package:
            if _component_entry_file(full) is None:
                continue
            key = name
            path = full
            entry = _component_entry_file(full)
        else:
            if not name.endswith('.py'):
                continue
            key = name[:-3]
            path = full
            entry = full
        try:
            module = _load_component_module(path, key)
            if module is None:
                continue
            meta = getattr(module, 'COMPONENT', None)
            run = getattr(module, 'run', None)
            if not isinstance(meta, dict) or not callable(run):
                continue
            menu_items = []
            for item in (getattr(module, 'MENU_ITEMS', None) or []):
                cb = getattr(module, item.get('callback', ''), None)
                if item.get('label') and callable(cb):
                    menu_items.append({'label': item['label'], 'callback': cb})
            components.append({
                'key': key,
                'name': meta.get('name', name),
                'description': meta.get('description', ''),
                'author': meta.get('author', ''),
                'version': meta.get('version', ''),
                'run': run,
                'menu_items': menu_items,
                'module': module,
                'path': path,
                'entry': entry,
                'is_package': is_package,
                'enabled': enabled_state.get(key, True),
                'moderators_only': bool(meta.get('moderators_only', False)),
                'allowed_regions': meta.get('allowed_regions') or meta.get('regions') or [],
                'blocked_regions': meta.get('blocked_regions') or [],
                'requires_server': bool(meta.get('requires_server', False)),
            })
        except Exception as e:
            print(f"[mod-components] failed to load {name}: {e}")
            traceback.print_exc()
    return components


# ----------------------------------------------------------------------------
# Event bus / runtime — dispatches Titan-Net events to enabled components.
# ----------------------------------------------------------------------------

# event name -> component hook function name
_HOOKS = {
    'message': 'on_message',
    'private_message': 'on_private_message',
    'user_online': 'on_user_online',
    'user_offline': 'on_user_offline',
    'forum_post': 'on_forum_post',
    'tick': 'on_tick',
}


class ComponentRuntime:
    """Loads ENABLED components and dispatches Titan-Net events to their hook
    functions. A buggy hook is caught so it can never break the host app."""

    def __init__(self, titan_client, window):
        self.titan_client = titan_client
        self.window = window
        self.components_dir = get_components_dir()
        self.components = []
        # Slugs the connected server currently has active (filled by
        # sync_active_extensions); gates server add-on components.
        self.active_slugs = set()
        self.reload()

    def reload(self):
        try:
            # Author's local-test overrides: keys allowed to run locally even
            # when they are server add-ons not (yet) active on this server, so
            # the author can see how the component really behaves in Titan-Net.
            local_test = load_local_test_state(self.components_dir)
            # Only ENABLED components that this user is allowed to see/run
            # (moderators-only flag + regional lock + server add-on presence)
            # feed hooks and the menu.
            self.components = [
                c for c in discover_components(self.components_dir)
                if c['enabled'] and (
                    is_component_accessible(c, self.titan_client,
                                            active_slugs=self.active_slugs)
                    or c['key'] in local_test)
            ]
        except Exception as e:
            print(f"[mod-components] runtime reload failed: {e}")
            self.components = []
        # Rebuild the composition registry: clear, then let each enabled
        # component register its providers via on_load(api).
        _clear_extension_points()
        for component in self.components:
            on_load = getattr(component['module'], 'on_load', None)
            if callable(on_load):
                try:
                    on_load(self._api_for(component))
                except Exception as e:
                    print(f"[mod-components] {component['key']}.on_load error: {e}")

    def shutdown(self):
        """Tear the runtime down on logout: call each loaded component's
        on_unload(api) (best effort), drop the composition registry and forget
        the loaded components so no hook/tick can touch a dead client and hang
        the UI. Never raises."""
        for component in self.components:
            on_unload = getattr(component['module'], 'on_unload', None)
            if callable(on_unload):
                try:
                    on_unload(self._api_for(component))
                except Exception as e:
                    print(f"[mod-components] {component['key']}.on_unload error: {e}")
        self.components = []
        _clear_extension_points()

    def _api_for(self, component):
        return ModeratorComponentAPI(self.titan_client, self.window, self.components_dir, component['key'])

    def dispatch(self, event, **payload):
        hook_name = _HOOKS.get(event)
        if not hook_name:
            return
        for component in self.components:
            fn = getattr(component['module'], hook_name, None)
            if not callable(fn):
                continue
            try:
                fn(self._api_for(component), payload)
            except Exception as e:
                print(f"[mod-components] {component['key']}.{hook_name} error: {e}")
                traceback.print_exc()


_RUNTIME = None


def get_runtime(titan_client=None, window=None):
    """Return the process-wide ComponentRuntime singleton, creating it on the
    first call (which must supply titan_client + window)."""
    global _RUNTIME
    if _RUNTIME is None and titan_client is not None:
        _RUNTIME = ComponentRuntime(titan_client, window)
    return _RUNTIME


def dispatch_event(event, **payload):
    """Convenience: dispatch to the runtime if it exists (no-op otherwise)."""
    rt = _RUNTIME
    if rt is not None:
        rt.dispatch(event, **payload)


def shutdown_runtime():
    """Tear down and forget the process-wide runtime (called on Titan-Net
    logout). Unloads components cleanly so nothing keeps firing against a
    disconnected client. Safe to call when no runtime exists."""
    global _RUNTIME
    rt = _RUNTIME
    _RUNTIME = None
    if rt is not None:
        try:
            rt.shutdown()
        except Exception as e:
            print(f"[mod-components] runtime shutdown error: {e}")


def get_menu_contributions():
    """Contributions from every ENABLED component, so the host can surface them
    in the Titan-Net main view AND the menu bar (Alt menu).

    Returns a list of dicts grouped per component::

        {'component': <display name>,
         'actions': [(label, run_callable_no_args), ...]}

    Each ``run_callable`` takes no arguments and runs the component action with
    a fresh API parented to the runtime's window; a failing action is caught so
    it never breaks Titan-Net. Returns ``[]`` if the runtime isn't up yet."""
    rt = _RUNTIME
    if rt is None:
        return []

    def _make(comp, fn):
        def _run():
            api = rt._api_for(comp)
            try:
                fn(api)
            except Exception as e:
                print(f"[mod-components] menu action error: {e}")
                traceback.print_exc()
        return _run

    contributions = []
    for component in rt.components:
        actions = [(_("Run"), _make(component, component['run']))]
        for mi in component.get('menu_items', []):
            actions.append((mi['label'], _make(component, mi['callback'])))
        contributions.append({'component': component['name'], 'actions': actions})
    return contributions


class ComponentDocsDialog(wx.Dialog):
    """Read-only API reference for component authors (no-AI path)."""

    def __init__(self, parent):
        super().__init__(parent, title=_("Component API Documentation"), size=(640, 600))
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        doc = wx.TextCtrl(panel, value=API_REFERENCE_TEXT,
                          style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        try:
            doc.SetFont(wx.Font(wx.FontInfo(10).Family(wx.FONTFAMILY_TELETYPE)))
        except Exception:
            pass
        vbox.Add(doc, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)
        close_btn = wx.Button(panel, wx.ID_CANCEL, _("Close"))
        vbox.Add(close_btn, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)
        panel.SetSizer(vbox)
        _apply_skin(self)
        self.Centre()


def build_system_prompt():
    """Build the AI system prompt FROM the real API reference so the model
    cannot invent methods that would destabilise Titan-Net. API_REFERENCE_TEXT
    mirrors the actual ``api.*`` surface — keep them in sync."""
    return (
        "You generate ONE Titan-Net moderator component as a single, valid "
        "Python file. Output ONLY the Python code — no explanations, no "
        "markdown fences.\n\n"
        "Hard rules (violating these breaks Titan-Net):\n"
        "- Use ONLY the documented api.* methods below. Never invent methods, "
        "attributes or endpoints. If something is not documented, do not use it.\n"
        "- Every api.* call returns a dict; always check result.get('success').\n"
        "- Never run raw server code, touch the filesystem outside api.storage, "
        "or open network connections yourself.\n"
        "- Confirm destructive actions with api.confirm() before doing them.\n"
        "- Do NOT invent sound names. Use only well-known TCE theme sounds "
        "(e.g. 'core/SELECT.ogg') with api.play_sound, or a sound file the "
        "component itself ships (streamed from the server for network "
        "extensions). Missing sounds simply do nothing.\n"
        "- User-facing text in English; keep any GUI keyboard-accessible.\n"
        "- The file MUST define COMPONENT (dict: name, description, author, "
        "version) and run(api). MENU_ITEMS and on_* hooks are optional.\n"
        "- COMPONENT may include optional audience gates: moderators_only "
        "(bool), allowed_regions (list of region codes, a lock) and "
        "blocked_regions (list). Use them only if the user asks to restrict the "
        "audience; otherwise omit them so everyone can use it.\n"
        "- For data that must follow the user across devices use api.cloud "
        "(per-user) or api.cloud.*_shared (global); api.storage is local only. "
        "If you use api.cloud, set COMPONENT['requires_server'] = True so the "
        "component is treated as a server add-on (it only runs where it is "
        "active on the server). Plain local components must NOT set it.\n"
        "- The file MUST compile.\n\n"
        "API REFERENCE (the only surface you may use):\n"
        + API_REFERENCE_TEXT
        + "\n\nFORMAT EXAMPLE (structure to follow):\n" + _NEW_TEMPLATE
    )


# AI providers the component creator accepts (id, display label). Mirrors the
# interactive-games BYOK provider list so a moderator can reuse the same key.
PROVIDERS = (
    ('anthropic', 'Anthropic Claude'),
    ('gemini', 'Google Gemini'),
    ('openai', 'OpenAI'),
)

# Fallback model per provider, used only when the latest model cannot be
# resolved from the provider (offline, old SDK, etc.). The user can also force
# one with a '<provider>_model' setting.
_DEFAULT_MODELS = {
    'anthropic': 'claude-opus-4-8',
    'gemini': 'gemini-2.0-flash',
    'openai': 'gpt-4o',
}

# Resolved newest-model cache (per provider) so we hit the listing API once.
_MODEL_CACHE = {}


def provider_label(provider_id):
    for pid, label in PROVIDERS:
        if pid == provider_id:
            return label
    return provider_id or '?'


def _gemini_version_key(name):
    """Sort key for a gemini model name so newer versions rank higher
    (e.g. 'gemini-2.5-flash' > 'gemini-2.0-flash' > 'gemini-1.5-pro')."""
    import re
    m = re.search(r'gemini-(\d+)(?:\.(\d+))?', name)
    major = int(m.group(1)) if m else 0
    minor = int(m.group(2)) if (m and m.group(2)) else 0
    # Prefer non-preview/-exp stable names slightly when versions tie.
    stable = 0 if any(t in name for t in ('preview', 'exp', 'latest')) else 1
    return (major, minor, stable)


def resolve_latest_model(provider, api_key):
    """Query the provider for its newest suitable model so the AI creator always
    uses the latest available model without hard-coding versions. Cached per
    provider for the session; falls back to ``_DEFAULT_MODELS`` on any error.

    - anthropic: ``client.models.list()`` (newest first) -> newest Claude,
      preferring an Opus model.
    - openai: ``client.models.list()`` -> newest chat-capable ``gpt-*`` by
      creation time (skips non-chat audio/image/embedding/realtime variants).
    - gemini: ``genai.list_models()`` -> highest gemini version that supports
      generateContent.
    """
    if provider in _MODEL_CACHE:
        return _MODEL_CACHE[provider]
    model = None
    try:
        if provider == 'anthropic':
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            data = getattr(client.models.list(limit=100), 'data', []) or []
            ids = [str(getattr(m, 'id', '')) for m in data]
            ids = [i for i in ids if i.startswith('claude')]
            opus = [i for i in ids if 'opus' in i]
            model = (opus or ids or [None])[0]
        elif provider == 'openai':
            import openai
            client = openai.OpenAI(api_key=api_key)
            data = list(client.models.list().data)
            skip = ('audio', 'realtime', 'image', 'tts', 'transcribe',
                    'embedding', 'instruct', 'moderation', 'search')
            cand = [m for m in data
                    if str(m.id).startswith('gpt-')
                    and not any(s in str(m.id) for s in skip)]
            cand.sort(key=lambda m: getattr(m, 'created', 0), reverse=True)
            model = str(cand[0].id) if cand else None
        elif provider == 'gemini':
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            names = []
            for m in genai.list_models():
                methods = getattr(m, 'supported_generation_methods', []) or []
                nm = getattr(m, 'name', '') or ''
                short = nm.split('/')[-1]
                if 'generateContent' in methods and short.startswith('gemini') \
                        and not any(t in short for t in ('vision', 'embedding', 'aqa')):
                    names.append(short)
            if names:
                names.sort(key=_gemini_version_key, reverse=True)
                model = names[0]
    except Exception as e:
        print(f"[mod-components] could not resolve latest model for {provider}: {e}")
    if not model:
        model = _DEFAULT_MODELS.get(provider, _DEFAULT_MODELS['anthropic'])
    _MODEL_CACHE[provider] = model
    return model


def generate_component_code(conversation, api_key, provider='anthropic', model=None):
    """Call the model to generate component code. Returns code (str).

    ``conversation`` is either a single description string (one-shot) or a list
    of ``{"role": "user"|"assistant", "content": str}`` messages for multi-turn
    refinement. ``provider`` is one of 'anthropic', 'gemini' or 'openai'; the
    user supplies the matching API key. When ``model`` is omitted the newest
    suitable model is resolved automatically from the provider (see
    resolve_latest_model), so the creator always uses the latest available
    model. Raises on failure (missing SDK, bad key, network)."""
    system = build_system_prompt()
    if isinstance(conversation, str):
        messages = [{"role": "user", "content": conversation}]
    else:
        messages = list(conversation)
    # Model precedence: explicit arg > user '<provider>_model' override >
    # auto-resolved newest model from the provider > hard-coded fallback.
    if not model:
        try:
            model = (get_setting(provider + '_model', '') or '').strip() or None
        except Exception:
            model = None
    if not model:
        model = resolve_latest_model(provider, api_key)

    if provider == 'anthropic':
        import anthropic  # may raise ImportError -> surfaced to caller
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=4000,
            system=system,
            messages=messages,
        )
        text = ''.join(getattr(b, 'text', '') for b in msg.content if getattr(b, 'type', '') == 'text')
    elif provider == 'gemini':
        import google.generativeai as genai  # may raise ImportError
        genai.configure(api_key=api_key)
        gmodel = genai.GenerativeModel(model, system_instruction=system)
        # Gemini uses 'user'/'model' roles; map the assistant turns across.
        contents = [
            {'role': 'model' if m['role'] == 'assistant' else 'user',
             'parts': [m['content']]}
            for m in messages
        ]
        resp = gmodel.generate_content(contents)
        text = getattr(resp, 'text', '') or ''
    elif provider == 'openai':
        import openai  # may raise ImportError
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            max_tokens=4000,
            messages=[{"role": "system", "content": system}] + messages,
        )
        text = resp.choices[0].message.content or ''
    else:
        raise RuntimeError(f"Unsupported provider: {provider}")
    # Strip markdown fences if the model added them despite instructions.
    text = text.strip()
    if text.startswith('```'):
        lines = text.split('\n')
        if lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith('```'):
            lines = lines[:-1]
        text = '\n'.join(lines)
    return text.strip() + '\n'


class ComponentAIWizardDialog(wx.Dialog):
    """Textual AI creator: the moderator precisely describes the add-on they
    want; the model returns component code, shown in the editor for review."""

    # Legacy single-key setting (Anthropic only). Kept for back-compat; new
    # keys are stored per provider via _key_setting().
    AI_KEY_SETTING = 'titannet_component_ai_key'

    @staticmethod
    def _key_setting(provider):
        return 'titannet_component_ai_key_' + provider

    def __init__(self, parent, components_dir):
        super().__init__(parent, title=_("Create Component with AI"), size=(720, 560))
        self.components_dir = components_dir
        self.generated_code = None
        self.InitUI()
        _apply_skin(self)
        self.Centre()
        play_sound('ui/dialog.ogg')

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(panel, label=_(
            "Describe precisely the Titan-Net add-on you want, then Generate. "
            "After the first result you can keep refining in the same box."
        )), flag=wx.ALL, border=10)

        # AI provider — accepts Anthropic, Google Gemini or OpenAI keys.
        prov_box = wx.BoxSizer(wx.HORIZONTAL)
        prov_box.Add(wx.StaticText(panel, label=_("AI provider:")),
                     flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)
        self.provider_choice = wx.Choice(panel, choices=[label for _id, label in PROVIDERS])
        self.provider_choice.SetSelection(0)
        prov_box.Add(self.provider_choice, flag=wx.ALIGN_CENTER_VERTICAL)
        vbox.Add(prov_box, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        # Conversation transcript (read-only) so the multi-turn refinement is
        # visible to screen-reader users.
        vbox.Add(wx.StaticText(panel, label=_("Conversation:")), flag=wx.LEFT, border=10)
        self.transcript = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        self.transcript.SetMinSize((-1, 160))
        vbox.Add(self.transcript, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        self.desc_label = wx.StaticText(panel, label=_("Your request:"))
        vbox.Add(self.desc_label, flag=wx.LEFT, border=10)
        self.desc = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_WORDWRAP)
        self.desc.SetMinSize((-1, 120))
        vbox.Add(self.desc, proportion=1, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        self.status = wx.StaticText(panel, label="")
        vbox.Add(self.status, flag=wx.ALL, border=10)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self.gen_btn = wx.Button(panel, label=_("Generate"))
        self.gen_btn.Bind(wx.EVT_BUTTON, self.OnGenerate)
        btn_box.Add(self.gen_btn, flag=wx.RIGHT, border=5)
        self.editor_btn = wx.Button(panel, label=_("Open in Editor"))
        self.editor_btn.Bind(wx.EVT_BUTTON, self.OnOpenEditor)
        self.editor_btn.Enable(False)
        btn_box.Add(self.editor_btn, flag=wx.RIGHT, border=5)
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Close"))
        btn_box.Add(cancel_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)

        panel.SetSizer(vbox)
        # Multi-turn conversation history (list of {role, content}).
        self.messages = []

    def _current_provider(self):
        idx = self.provider_choice.GetSelection()
        return PROVIDERS[idx][0] if idx >= 0 else 'anthropic'

    def _get_key(self, provider):
        setting = self._key_setting(provider)
        try:
            key = get_setting(setting, '')
            # Back-compat: fall back to the old single-key setting for Anthropic.
            if not key and provider == 'anthropic':
                key = get_setting(self.AI_KEY_SETTING, '')
        except Exception:
            key = ''
        if key:
            return key
        dlg = wx.TextEntryDialog(self, _(
            "Enter your {provider} API key. It is stored locally for future use."
        ).format(provider=provider_label(provider)), _("AI API key"))
        key = dlg.GetValue().strip() if dlg.ShowModal() == wx.ID_OK else ''
        dlg.Destroy()
        if key:
            try:
                from src.settings.settings import set_setting
                set_setting(setting, key)
            except Exception:
                pass
        return key

    def OnGenerate(self, event):
        text = self.desc.GetValue().strip()
        if not text:
            wx.MessageBox(_("Please type a request"), _("Error"), wx.OK | wx.ICON_WARNING, self)
            return
        provider = self._current_provider()
        key = self._get_key(provider)
        if not key:
            return
        play_sound('core/SELECT.ogg')
        # Append the user's turn. If we already have generated code, include it
        # as the assistant's prior turn so the model refines rather than starts
        # over (multi-turn).
        if self.generated_code and (not self.messages or self.messages[-1]['role'] != 'user'):
            self.messages.append({"role": "assistant", "content": self.generated_code})
        self.messages.append({"role": "user", "content": text})
        self._append_transcript(_("You"), text)
        self.desc.SetValue("")
        self.gen_btn.Enable(False)
        self.status.SetLabel(_("Generating… this can take a moment."))

        convo = list(self.messages)

        def _work():
            try:
                code = generate_component_code(convo, key, provider=provider)
                wx.CallAfter(self._on_generated, code, None)
            except Exception as e:
                wx.CallAfter(self._on_generated, None, str(e))

        threading.Thread(target=_work, daemon=True).start()

    def _append_transcript(self, who, text):
        self.transcript.AppendText(f"{who}: {text}\n\n")

    def _on_generated(self, code, error):
        self.gen_btn.Enable(True)
        if error:
            self.status.SetLabel("")
            play_sound('core/error.ogg')
            wx.MessageBox(_("AI generation failed: {error}").format(error=error),
                          _("Error"), wx.OK | wx.ICON_ERROR, self)
            return
        self.generated_code = code
        self.editor_btn.Enable(True)
        self._append_transcript(_("AI"), _("(updated the component code — {n} lines)").format(
            n=len(code.splitlines())))
        self.status.SetLabel(_("Generated. Refine further, or Open in Editor to review and save."))
        play_sound('titannet/new_feedpost.ogg')
        self.desc_label.SetLabel(_("Refine (what should change?):"))

    def OnOpenEditor(self, event):
        if not self.generated_code:
            return
        play_sound('core/SELECT.ogg')
        editor = ComponentEditorDialog(self, self.components_dir)
        editor.code.SetValue(self.generated_code)
        result = editor.ShowModal()
        editor.Destroy()
        if result == wx.ID_OK:
            self.EndModal(wx.ID_OK)


class ComponentEditorDialog(wx.Dialog):
    """In-app code editor for writing/editing a component without AI.

    Accessible: a plain multiline text control (works with screen readers) plus
    a Documentation button that opens the API reference.
    """

    def __init__(self, parent, components_dir, path=None):
        title = _("Edit Component") if path else _("New Component")
        super().__init__(parent, title=title, size=(820, 640))
        self.components_dir = components_dir
        self.path = path
        self.InitUI()
        _apply_skin(self)
        self.Centre()
        play_sound('ui/dialog.ogg')

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        name_box = wx.BoxSizer(wx.HORIZONTAL)
        name_box.Add(wx.StaticText(panel, label=_("File name (.py):")), flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)
        default_name = os.path.basename(self.path) if self.path else "my_component.py"
        self.name_input = wx.TextCtrl(panel, value=default_name)
        if self.path:
            self.name_input.Enable(False)
        name_box.Add(self.name_input, proportion=1)
        docs_btn = wx.Button(panel, label=_("Documentation"))
        docs_btn.Bind(wx.EVT_BUTTON, self.OnDocs)
        name_box.Add(docs_btn, flag=wx.LEFT, border=5)
        vbox.Add(name_box, flag=wx.EXPAND | wx.ALL, border=10)

        initial = _NEW_TEMPLATE
        if self.path and os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    initial = f.read()
            except Exception:
                pass
        self.code = wx.TextCtrl(panel, value=initial,
                                style=wx.TE_MULTILINE | wx.TE_DONTWRAP | wx.HSCROLL)
        try:
            self.code.SetFont(wx.Font(wx.FontInfo(10).Family(wx.FONTFAMILY_TELETYPE)))
        except Exception:
            pass
        vbox.Add(self.code, proportion=1, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(panel, wx.ID_OK, _("Save"))
        save_btn.Bind(wx.EVT_BUTTON, self.OnSave)
        btn_box.Add(save_btn, flag=wx.RIGHT, border=5)
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        btn_box.Add(cancel_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)

        panel.SetSizer(vbox)

    def OnDocs(self, event):
        dlg = ComponentDocsDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def OnSave(self, event):
        name = self.name_input.GetValue().strip()
        if not name:
            wx.MessageBox(_("File name is required"), _("Error"), wx.OK | wx.ICON_WARNING, self)
            return
        if not name.endswith('.py'):
            name += '.py'
        if name.startswith('_'):
            wx.MessageBox(_("File name cannot start with an underscore"), _("Error"), wx.OK | wx.ICON_WARNING, self)
            return
        target = self.path or os.path.join(self.components_dir, name)
        code = self.code.GetValue()
        # Validate syntax before saving so the author gets immediate feedback.
        try:
            compile(code, target, 'exec')
        except SyntaxError as e:
            wx.MessageBox(_("Syntax error on line {line}: {msg}").format(line=e.lineno, msg=e.msg),
                          _("Error"), wx.OK | wx.ICON_ERROR, self)
            return
        try:
            with open(target, 'w', encoding='utf-8') as f:
                f.write(code)
        except Exception as e:
            wx.MessageBox(_("Could not save: {error}").format(error=str(e)), _("Error"), wx.OK | wx.ICON_ERROR, self)
            return
        play_sound('titannet/new_feedpost.ogg')
        self.EndModal(wx.ID_OK)


class ExtensionReviewDialog(wx.Dialog):
    """Two-person approval: review PENDING network extensions and approve or
    reject them. The server refuses if you try to approve your own."""

    def __init__(self, parent, titan_client):
        super().__init__(parent, title=_("Review Network Extensions"), size=(720, 480))
        self.titan_client = titan_client
        self.pending = []
        self.InitUI()
        _apply_skin(self)
        self.Centre()
        play_sound('ui/dialog.ogg')
        wx.CallAfter(self.reload)

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.status = wx.StaticText(panel, label="")
        vbox.Add(self.status, flag=wx.ALL, border=8)
        self.list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.AppendColumn(_("Extension"), width=240)
        self.list.AppendColumn(_("Author"), width=160)
        self.list.AppendColumn(_("Version"), width=80)
        vbox.Add(self.list, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)
        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (
            (_("View Code"), self.OnViewCode),
            (_("Run (preview)"), self.OnRunPreview),
            (_("Approve"), lambda e: self._review(True)),
            (_("Reject"), lambda e: self._review(False)),
            (_("Refresh"), lambda e: self.reload()),
        ):
            b = wx.Button(panel, label=label)
            b.Bind(wx.EVT_BUTTON, handler)
            btn_box.Add(b, flag=wx.RIGHT, border=5)
        close_btn = wx.Button(panel, wx.ID_CANCEL, _("Close"))
        btn_box.Add(close_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.ALL, border=8)
        panel.SetSizer(vbox)

    def reload(self):
        def _load():
            result = self.titan_client.list_extensions(status='pending')
            wx.CallAfter(self._display, result)
        threading.Thread(target=_load, daemon=True).start()

    def _display(self, result):
        self.list.DeleteAllItems()
        if not result.get('success'):
            self.status.SetLabel(result.get('error', _("Failed to load")))
            return
        self.pending = result.get('extensions', [])
        for e in self.pending:
            idx = self.list.InsertItem(self.list.GetItemCount(), e.get('name', ''))
            self.list.SetItem(idx, 1, e.get('author_username', ''))
            self.list.SetItem(idx, 2, str(e.get('version', '')))
        self.status.SetLabel("" if self.pending else _("No pending extensions."))

    def _selected(self):
        sel = self.list.GetFirstSelected()
        if sel == -1 or sel >= len(self.pending):
            return None
        return self.pending[sel]

    def OnRunPreview(self, event):
        """Run the selected PENDING extension locally, exactly as if it were
        installed in this reviewer's own Titan-Net, so they can judge its effect
        on the GUI/menu before approving. Nothing is enabled network-wide."""
        ext = self._selected()
        if not ext:
            return
        play_sound('core/SELECT.ogg')

        def _load():
            detail = self.titan_client.get_extension(ext['id'])
            wx.CallAfter(self._run_preview, detail)
        threading.Thread(target=_load, daemon=True).start()

    def _run_preview(self, detail):
        if not detail.get('success'):
            wx.MessageBox(detail.get('error', _("Failed to load")), _("Error"), wx.OK | wx.ICON_ERROR, self)
            return
        ext = detail.get('extension', {})
        slug = ext.get('slug') or 'preview'
        key = 'ext_' + slug
        try:
            components_dir = get_components_dir()
            preview_root = os.path.join(components_dir, '_preview')
            os.makedirs(preview_root, exist_ok=True)
            if ext.get('kind') == 'folder' and ext.get('bundle'):
                dest = os.path.join(preview_root, key)
                _unpack_extension_bundle(ext['bundle'], dest)
                module = _load_component_module(dest, key)
            else:
                dest = os.path.join(preview_root, key + '.py')
                with open(dest, 'w', encoding='utf-8') as f:
                    f.write(ext.get('client_code', ''))
                module = _load_component_module(dest, key)
            run = getattr(module, 'run', None)
            meta = getattr(module, 'COMPONENT', None)
            if not isinstance(meta, dict) or not callable(run):
                wx.MessageBox(_("This extension has no runnable component."),
                              _("Run (preview)"), wx.OK | wx.ICON_WARNING, self)
                return
            # Build the same API a real install would get, parented here.
            api = ModeratorComponentAPI(self.titan_client, self, components_dir, key)
            # Offer run() plus any MENU_ITEMS, so the reviewer can try each
            # action the component would add to the Titan-Net menu.
            actions = [(_("Run"), run)]
            for item in (getattr(module, 'MENU_ITEMS', None) or []):
                cb = getattr(module, item.get('callback', ''), None)
                if item.get('label') and callable(cb):
                    actions.append((item['label'], cb))
            if len(actions) == 1:
                fn = run
            else:
                dlg = wx.SingleChoiceDialog(
                    self, _("Choose what to run (as it would appear in the menu):"),
                    _("Run (preview)"), [lbl for lbl, _fn in actions])
                if dlg.ShowModal() != wx.ID_OK:
                    dlg.Destroy()
                    return
                fn = actions[dlg.GetSelection()][1]
                dlg.Destroy()
            fn(api)
        except Exception as e:
            play_sound('core/error.ogg')
            wx.MessageBox(_("Preview failed: {error}").format(error=str(e)),
                          _("Error"), wx.OK | wx.ICON_ERROR, self)
            traceback.print_exc()

    def OnViewCode(self, event):
        ext = self._selected()
        if not ext:
            return
        def _load():
            detail = self.titan_client.get_extension(ext['id'])
            wx.CallAfter(self._show_code, detail)
        threading.Thread(target=_load, daemon=True).start()

    def _bundle_to_text(self, ext):
        """Render a folder extension's bundle as readable text (file list +
        each file's contents) so a reviewer can actually review it."""
        try:
            import io
            import zipfile
            raw = base64.b64decode(ext.get('bundle') or '')
            parts = [_("Folder extension. Entry: {entry}").format(entry=ext.get('entry') or '?'), ""]
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()
                parts.append(_("Files: {files}").format(files=", ".join(names)))
                parts.append("")
                for name in names:
                    if name.endswith('/'):
                        continue
                    parts.append("=" * 60)
                    parts.append(name)
                    parts.append("=" * 60)
                    try:
                        parts.append(zf.read(name).decode('utf-8', 'replace'))
                    except Exception:
                        parts.append(_("(binary file, not shown)"))
                    parts.append("")
            return "\n".join(parts)
        except Exception as e:
            return _("Could not read bundle: {error}").format(error=str(e))

    def _show_code(self, detail):
        if not detail.get('success'):
            wx.MessageBox(detail.get('error', _("Failed to load")), _("Error"), wx.OK | wx.ICON_ERROR, self)
            return
        ext = detail.get('extension', {})
        if ext.get('kind') == 'folder' and ext.get('bundle'):
            code = self._bundle_to_text(ext)
        else:
            code = ext.get('client_code', '')
        dlg = wx.Dialog(self, title=_("Extension Code"), size=(720, 560))
        p = wx.Panel(dlg)
        s = wx.BoxSizer(wx.VERTICAL)
        tc = wx.TextCtrl(p, value=code, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        try:
            tc.SetFont(wx.Font(wx.FontInfo(10).Family(wx.FONTFAMILY_TELETYPE)))
        except Exception:
            pass
        s.Add(tc, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)
        s.Add(wx.Button(p, wx.ID_CANCEL, _("Close")), flag=wx.ALIGN_RIGHT | wx.ALL, border=8)
        p.SetSizer(s)
        _apply_skin(dlg)
        dlg.ShowModal()
        dlg.Destroy()

    def _review(self, approve):
        ext = self._selected()
        if not ext:
            return
        play_sound('core/SELECT.ogg')
        def _do():
            if approve:
                result = self.titan_client.approve_extension(ext['id'])
            else:
                result = self.titan_client.reject_extension(ext['id'])
            wx.CallAfter(self._on_reviewed, result)
        threading.Thread(target=_do, daemon=True).start()

    def _on_reviewed(self, result):
        if result.get('success'):
            play_sound('core/SELECT.ogg')
            self.reload()
        else:
            play_sound('core/error.ogg')
            wx.MessageBox(result.get('error', _("Operation failed")), _("Error"), wx.OK | wx.ICON_ERROR, self)


class ModeratorComponentsWindow(wx.Frame):
    """Lists moderator components and runs them / their menu actions."""

    def __init__(self, parent, titan_client):
        super().__init__(parent, title=_("Titan-Net Moderator Components"), size=(760, 540))
        self.titan_client = titan_client
        self.components_dir = get_components_dir()
        _seed_example(self.components_dir)
        self.components = []
        self.InitUI()
        _apply_skin(self)
        self.Centre()
        play_sound('ui/uiopen.ogg')
        try:
            from src.ui.window_switcher import register_window
            register_window("Titan-Net Moderator Components", window=self, category='messenger')
        except Exception:
            pass
        # Escape and Alt+F4 must close the window (they did not before).
        self.Bind(wx.EVT_CHAR_HOOK, self.OnKeyDown)
        self.Bind(wx.EVT_CLOSE, self.OnClose)
        wx.CallAfter(self.reload)

    def OnKeyDown(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
            return
        event.Skip()

    def OnClose(self, event):
        try:
            from src.ui.window_switcher import unregister_window
            unregister_window("Titan-Net Moderator Components")
        except Exception:
            pass
        self.Destroy()

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(panel, label=_("Titan-Net Moderator Components"))
        font = title.GetFont(); font.PointSize += 4; font = font.Bold()
        title.SetFont(font)
        vbox.Add(title, flag=wx.ALL | wx.ALIGN_CENTER, border=10)

        vbox.Add(wx.StaticText(panel, label=_(
            "Program your own moderator tools. Components live in your user data folder."
        )), flag=wx.LEFT | wx.RIGHT, border=10)

        self.list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.AppendColumn(_("Component"), width=220)
        self.list.AppendColumn(_("Enabled"), width=80)
        self.list.AppendColumn(_("Description"), width=380)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnRun)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda e: self._rebuild_actions())
        vbox.Add(self.list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        # Static controls.
        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        run_btn = wx.Button(panel, label=_("Run"))
        run_btn.Bind(wx.EVT_BUTTON, self.OnRun)
        btn_box.Add(run_btn, flag=wx.RIGHT, border=5)
        self.toggle_btn = wx.Button(panel, label=_("Enable/Disable"))
        self.toggle_btn.Bind(wx.EVT_BUTTON, self.OnToggleEnabled)
        btn_box.Add(self.toggle_btn, flag=wx.RIGHT, border=5)
        self.local_test_btn = wx.Button(panel, label=_("Test Locally"))
        self.local_test_btn.Bind(wx.EVT_BUTTON, self.OnToggleLocalTest)
        btn_box.Add(self.local_test_btn, flag=wx.RIGHT, border=5)
        new_btn = wx.Button(panel, label=_("New Component"))
        new_btn.Bind(wx.EVT_BUTTON, self.OnNewComponent)
        btn_box.Add(new_btn, flag=wx.RIGHT, border=5)
        ai_btn = wx.Button(panel, label=_("Create with AI"))
        ai_btn.Bind(wx.EVT_BUTTON, self.OnCreateWithAI)
        btn_box.Add(ai_btn, flag=wx.RIGHT, border=5)
        edit_btn = wx.Button(panel, label=_("Edit Code"))
        edit_btn.Bind(wx.EVT_BUTTON, self.OnEditComponent)
        btn_box.Add(edit_btn, flag=wx.RIGHT, border=5)
        docs_btn = wx.Button(panel, label=_("Documentation"))
        docs_btn.Bind(wx.EVT_BUTTON, self.OnDocs)
        btn_box.Add(docs_btn, flag=wx.RIGHT, border=5)
        reload_btn = wx.Button(panel, label=_("Reload"))
        reload_btn.Bind(wx.EVT_BUTTON, lambda e: self.reload())
        btn_box.Add(reload_btn, flag=wx.RIGHT, border=5)
        open_btn = wx.Button(panel, label=_("Open Components Folder"))
        open_btn.Bind(wx.EVT_BUTTON, self.OnOpenFolder)
        btn_box.Add(open_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.ALL, border=5)

        # Network extension pipeline (submit for two-person approval / review).
        net_box = wx.BoxSizer(wx.HORIZONTAL)
        submit_btn = wx.Button(panel, label=_("Submit to Network"))
        submit_btn.Bind(wx.EVT_BUTTON, self.OnSubmitToNetwork)
        net_box.Add(submit_btn, flag=wx.RIGHT, border=5)
        review_btn = wx.Button(panel, label=_("Review Network Extensions"))
        review_btn.Bind(wx.EVT_BUTTON, self.OnReviewExtensions)
        net_box.Add(review_btn)
        vbox.Add(net_box, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)

        # Dynamic per-component actions (from MENU_ITEMS).
        self.actions_label = wx.StaticText(panel, label=_("Component actions:"))
        vbox.Add(self.actions_label, flag=wx.LEFT | wx.TOP, border=10)
        self.actions_panel = wx.Panel(panel)
        self.actions_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.actions_panel.SetSizer(self.actions_sizer)
        vbox.Add(self.actions_panel, flag=wx.EXPAND | wx.ALL, border=5)

        panel.SetSizer(vbox)
        self._panel = panel

    def reload(self):
        self.components = discover_components(self.components_dir)
        local_test = load_local_test_state(self.components_dir)
        self.list.DeleteAllItems()
        for c in self.components:
            idx = self.list.InsertItem(self.list.GetItemCount(), c['name'])
            self.list.SetItem(idx, 1, _("Yes") if c['enabled'] else _("No"))
            desc = c['description']
            # Flag server add-ons so the author knows they only run where active
            # on the server (or under a local-test override).
            if c.get('requires_server'):
                tag = _("[local test]") if c['key'] in local_test else _("[server add-on]")
                desc = (tag + " " + desc).strip()
            self.list.SetItem(idx, 2, desc)
        if self.list.GetItemCount() > 0:
            self.list.Select(0)
        self._rebuild_actions()
        # Keep the live event-bus in sync with on-disk + enabled changes.
        rt = get_runtime()
        if rt is not None:
            rt.reload()

    def _selected(self):
        sel = self.list.GetFirstSelected()
        if sel == -1 or sel >= len(self.components):
            return None
        return self.components[sel]

    def _make_api(self, component):
        return ModeratorComponentAPI(self.titan_client, self, self.components_dir, component['key'])

    def _run_callable(self, component, fn):
        play_sound('core/SELECT.ogg')
        api = self._make_api(component)
        try:
            fn(api)
        except Exception as e:
            play_sound('core/error.ogg')
            wx.MessageBox(_("Component error: {error}").format(error=str(e)),
                          _("Error"), wx.OK | wx.ICON_ERROR, self)
            traceback.print_exc()

    def OnRun(self, event):
        component = self._selected()
        if component:
            self._run_callable(component, component['run'])

    def OnToggleEnabled(self, event):
        component = self._selected()
        if not component:
            return
        state = load_enabled_state(self.components_dir)
        state[component['key']] = not component['enabled']
        save_enabled_state(self.components_dir, state)
        play_sound('core/SELECT.ogg')
        self.reload()

    def OnToggleLocalTest(self, event):
        """Switch a SERVER ADD-ON component on/off for LOCAL testing in this
        client only. Lets its author see how it really behaves in Titan-Net
        before it is approved and active on the server; api.cloud falls back to
        a local store while testing. No effect on plain (non-server) components,
        which already run locally."""
        component = self._selected()
        if not component:
            return
        if not component.get('requires_server'):
            wx.MessageBox(
                _("This component is not a server add-on; it already runs "
                  "locally."),
                _("Test Locally"), wx.OK | wx.ICON_INFORMATION, self)
            return
        keys = load_local_test_state(self.components_dir)
        if component['key'] in keys:
            keys.discard(component['key'])
            msg = _("Local testing turned off for '{name}'.")
        else:
            keys.add(component['key'])
            msg = _("Local testing turned on for '{name}'. It now runs in your "
                    "client as it would on the server.")
        save_local_test_state(self.components_dir, keys)
        play_sound('core/SELECT.ogg')
        self.reload()
        # Keep the live runtime in sync and announce the change.
        rt = get_runtime()
        if rt is not None:
            rt.reload()
        try:
            from src.network.titan_net_gui import speak_notification
            speak_notification(msg.format(name=component['name']), 'info')
        except Exception:
            pass

    def _rebuild_actions(self):
        # Clear existing dynamic buttons.
        self.actions_sizer.Clear(delete_windows=True)
        component = self._selected()
        if component:
            for item in component['menu_items']:
                btn = wx.Button(self.actions_panel, label=item['label'])
                cb = item['callback']
                btn.Bind(wx.EVT_BUTTON, lambda e, c=component, f=cb: self._run_callable(c, f))
                self.actions_sizer.Add(btn, flag=wx.RIGHT, border=5)
        self.actions_panel.Layout()
        # Re-layout the whole frame so freshly added action buttons are sized
        # and clickable without needing a manual resize.
        if getattr(self, '_panel', None):
            self._panel.Layout()

    def OnNewComponent(self, event):
        play_sound('core/SELECT.ogg')
        dlg = ComponentEditorDialog(self, self.components_dir)
        if dlg.ShowModal() == wx.ID_OK:
            self.reload()
        dlg.Destroy()

    def OnCreateWithAI(self, event):
        play_sound('core/SELECT.ogg')
        dlg = ComponentAIWizardDialog(self, self.components_dir)
        if dlg.ShowModal() == wx.ID_OK:
            self.reload()
        dlg.Destroy()

    def OnEditComponent(self, event):
        play_sound('core/SELECT.ogg')
        component = self._selected()
        if not component:
            return
        dlg = ComponentEditorDialog(self, self.components_dir, path=component['path'])
        if dlg.ShowModal() == wx.ID_OK:
            self.reload()
        dlg.Destroy()

    def OnDocs(self, event):
        play_sound('core/SELECT.ogg')
        dlg = ComponentDocsDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def OnSubmitToNetwork(self, event):
        """Submit the selected local component for two-person approval so it can
        affect the whole Titan-Net once approved. Single-file components are sent
        as code; folder components are zipped and sent as a bundle. The manifest
        audience gates (moderators_only / regions) travel with the submission."""
        play_sound('core/SELECT.ogg')
        component = self._selected()
        if not component:
            return

        kind = 'folder' if component.get('is_package') else 'single'
        code = ''
        bundle = None
        entry = None
        try:
            if kind == 'folder':
                import base64 as _b64
                import io
                import zipfile
                folder = component['path']
                entry = os.path.basename(component.get('entry') or 'component.py')
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for root, _dirs, files in os.walk(folder):
                        # Skip caches/state so bundles stay clean and small.
                        if '__pycache__' in root or os.sep + '_' in (root + os.sep):
                            continue
                        for fn in files:
                            if fn.endswith('.pyc'):
                                continue
                            full = os.path.join(root, fn)
                            arc = os.path.relpath(full, folder)
                            zf.write(full, arc)
                bundle = _b64.b64encode(buf.getvalue()).decode('ascii')
            else:
                with open(component['path'], 'r', encoding='utf-8') as f:
                    code = f.read()
        except Exception as e:
            wx.MessageBox(_("Could not read component: {error}").format(error=str(e)),
                          _("Error"), wx.OK | wx.ICON_ERROR, self)
            return

        slug = component['key'].replace('_', '-')
        confirm = wx.MessageBox(
            _("Submit '{name}' to the network? Another moderator/admin must "
              "approve it before it affects all of Titan-Net.").format(name=component['name']),
            _("Submit to Network"), wx.YES_NO | wx.ICON_QUESTION, self)
        if confirm != wx.YES:
            return

        def _submit():
            result = self.titan_client.submit_extension(
                slug, component['name'], code, component.get('description'),
                component.get('version', '1.0'), kind=kind, bundle=bundle, entry=entry,
                moderators_only=component.get('moderators_only', False),
                allowed_regions=component.get('allowed_regions') or [],
                blocked_regions=component.get('blocked_regions') or [])
            wx.CallAfter(self._on_submitted, result)
        threading.Thread(target=_submit, daemon=True).start()

    def _on_submitted(self, result):
        if result.get('success'):
            play_sound('titannet/new_feedpost.ogg')
            wx.MessageBox(_("Submitted for approval."), _("Submit to Network"),
                          wx.OK | wx.ICON_INFORMATION, self)
        else:
            play_sound('core/error.ogg')
            wx.MessageBox(result.get('error', _("Submit failed")), _("Error"),
                          wx.OK | wx.ICON_ERROR, self)

    def OnReviewExtensions(self, event):
        play_sound('core/SELECT.ogg')
        dlg = ExtensionReviewDialog(self, self.titan_client)
        dlg.ShowModal()
        dlg.Destroy()

    def OnOpenFolder(self, event):
        play_sound('core/SELECT.ogg')
        try:
            import subprocess
            import sys
            if sys.platform == 'win32':
                os.startfile(self.components_dir)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', self.components_dir])
            else:
                subprocess.Popen(['xdg-open', self.components_dir])
        except Exception as e:
            print(f"[mod-components] open folder failed: {e}")
