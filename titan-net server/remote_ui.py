"""
Titan-Net Remote UI - screens the SERVER defines and every client renders.

The problem this solves: a new server-side component needs a dialog, but
shipping a dialog used to mean shipping a new Titan build and asking every
user to update. Here the server stores a DECLARATIVE JSON description of the
screen; the desktop client has one generic renderer
(``src/network/remote_ui.py``) that turns it into an accessible, skinned
wxPython dialog. A screen written today opens on a client built months ago.

Nothing here is code the client executes. The definition is data, validated
on the way in (by ``validate_definition``) and again on the way back (by
``coerce_values``), so a malformed or hostile screen cannot do more than an
ordinary dialog.

Flow
----
1. client asks for ``list_remote_screens``   -> menu entries it may see
2. client sends ``open_remote_screen(slug)`` -> full definition (a handler
   may fill in dynamic content: user lists, defaults, current settings)
3. user presses a button -> ``remote_screen_action(slug, action, values)``
4. the registered handler returns a RESULT telling the client what to do
   next: close, show a message, play a sound, or open another screen.

Writing a handler
-----------------
A server component registers a handler and gets full server-side power -
the client only ever sees the result::

    from remote_ui import handler, close, message, screen, error

    @handler('warn_user')
    async def warn_user(ctx):
        if ctx.action == 'open':
            names = [u['username'] for u in ctx.db.get_all_users()]
            return ctx.fill({'user': {'items': names}})
        if ctx.action == 'send':
            if not ctx.values.get('reason'):
                return error({'reason': 'A reason is required'})
            ctx.db.jail_user(...)
            return close(message='Warning sent', sound='warn')
        return close()

Handlers may be plain functions or coroutines. ``ctx.action`` is ``'open'``
when the screen is being opened, otherwise the id of the pressed button.
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger('TitanNetRemoteUI')

# Bumped when the schema gains features. Clients report the highest version
# they understand so the server can degrade gracefully for older builds.
#   1 - form screens (fields + buttons), rendered as a dialog
#   2 - view screens (a navigable list), which is how a whole SERVICE is built
SCHEMA_VERSION = 2

# What a screen IS, not just what it contains:
#   'dialog' - a form: labelled fields and buttons, shown modally
#   'view'   - a service: a list you arrow through, Enter opens an entry,
#              Escape goes back. Views nest, so a service is a tree of them.
SCREEN_KINDS = ('dialog', 'view')

# Every field type the generic client renderer knows about. A definition
# that uses anything else is rejected at save time rather than confusing a
# user with a half-drawn dialog.
FIELD_TYPES = (
    'text',        # single-line entry (password=True hides it)
    'multiline',   # multi-line entry
    'number',      # spin control, honours min / max / step
    'choice',      # drop-down or list of options
    'checkbox',    # boolean
    'radio',       # one of N, rendered as a radio box
    'list',        # read-only list of rows (reports, logs, results)
    'static',      # read-only text shown to the user
    'separator',   # visual/structural break
)

BUTTON_ACTIONS = (
    'submit',   # send the field values to the handler under the button id
    'cancel',   # close without contacting the server
    'open',     # open another screen (``screen`` names the slug)
    'action',   # contact the handler WITHOUT sending field values
)

MAX_FIELDS = 60
MAX_BUTTONS = 10
MAX_ITEMS = 2000
MAX_TEXT = 20000
# A view is a listbox; past a few thousand rows it stops being navigable by
# ear anyway, and the server should be paging instead.
MAX_VIEW_ROWS = 2000
MAX_TABS = 12
MAX_MENUS = 8
MAX_MENU_ITEMS = 30


# ---------------------------------------------------------------------------
# Definition validation
# ---------------------------------------------------------------------------

def _as_items(raw: Any) -> Optional[List[Dict[str, Any]]]:
    """Normalise a choice/radio/list ``items`` value.

    Accepts ``["a", "b"]`` or ``[{"value": 1, "label": "a"}]`` and always
    returns the dict form so the client renderer has one shape to handle.
    """
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) > MAX_ITEMS:
        return None
    items = []
    for entry in raw:
        if isinstance(entry, (str, int, float)):
            items.append({'value': entry, 'label': str(entry)})
        elif isinstance(entry, dict):
            label = entry.get('label', entry.get('value'))
            if label is None:
                return None
            items.append({'value': entry.get('value', label),
                          'label': str(label)[:500]})
        else:
            return None
    return items


def _validate_rows(raw: Any) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """Normalise a view's rows.

    A row is what the user arrows onto and presses Enter on. ``action`` is
    the handler action that firing it sends (default ``'activate'``), and
    ``id`` comes back as ``values['item']`` so the handler knows which row.
    """
    if raw is None:
        return [], ""
    if not isinstance(raw, list):
        return None, "'items' must be a list"
    if len(raw) > MAX_VIEW_ROWS:
        return None, f"Too many rows (max {MAX_VIEW_ROWS})"

    rows = []
    for index, entry in enumerate(raw):
        if isinstance(entry, str):
            rows.append({'id': entry[:120], 'label': entry[:500],
                         'action': 'activate'})
            continue
        if not isinstance(entry, dict):
            return None, f"Row {index} is neither text nor an object"
        label = entry.get('label', entry.get('id'))
        if label is None:
            return None, f"Row {index} has no label"
        row: Dict[str, Any] = {
            'id': str(entry.get('id', label))[:120],
            'label': str(label)[:500],
            'action': str(entry.get('action') or 'activate')[:64],
        }
        # Spoken after the label, for the detail a list row cannot show:
        # "Channel 3" / "playing Chopin, 42 listeners".
        if entry.get('sublabel'):
            row['sublabel'] = str(entry['sublabel'])[:500]
        if entry.get('sound'):
            row['sound'] = str(entry['sound'])[:64]
        if entry.get('data') is not None:
            row['data'] = entry['data']
        rows.append(row)
    return rows, ""


def _validate_tabs(raw: Any) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """Normalise a view's tab bar.

    Rendered exactly like the Feedback Hub's: row 0 of the list is the tab
    bar, Left/Right cycles it, and switching tabs asks the server for that
    tab's rows. Keeping the interaction identical means somebody who can use
    one Titan-Net view can use every service without relearning anything.
    """
    if raw is None:
        return [], ""
    if not isinstance(raw, list):
        return None, "'tabs' must be a list"
    if len(raw) > MAX_TABS:
        return None, f"Too many tabs (max {MAX_TABS})"
    tabs = []
    for index, entry in enumerate(raw):
        if isinstance(entry, str):
            tabs.append({'id': entry[:64], 'label': entry[:120]})
            continue
        if not isinstance(entry, dict):
            return None, f"Tab {index} is neither text nor an object"
        label = entry.get('label', entry.get('id'))
        if label is None:
            return None, f"Tab {index} has no label"
        tabs.append({'id': str(entry.get('id', label))[:64],
                     'label': str(label)[:120]})
    return tabs, ""


def _validate_menus(raw: Any) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """Normalise a view's menu bar (Alt-reachable, like every Titan window)."""
    if raw is None:
        return [], ""
    if not isinstance(raw, list):
        return None, "'menus' must be a list"
    if len(raw) > MAX_MENUS:
        return None, f"Too many menus (max {MAX_MENUS})"

    menus = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            return None, f"Menu {index} is not an object"
        label = str(entry.get('label') or '').strip()
        if not label:
            return None, f"Menu {index} has no label"
        raw_items = entry.get('items') or []
        if not isinstance(raw_items, list):
            return None, f"Menu '{label}' has no item list"
        if len(raw_items) > MAX_MENU_ITEMS:
            return None, f"Menu '{label}' has too many items (max {MAX_MENU_ITEMS})"

        items = []
        for item_index, raw_item in enumerate(raw_items):
            if raw_item in ('-', '---') or raw_item is None:
                items.append({'separator': True})
                continue
            if not isinstance(raw_item, dict):
                return None, f"Menu '{label}' item {item_index} is not an object"
            if raw_item.get('separator'):
                items.append({'separator': True})
                continue
            item_label = str(raw_item.get('label') or '').strip()
            if not item_label:
                return None, f"Menu '{label}' item {item_index} has no label"
            action = str(raw_item.get('action') or 'menu').lower()
            if action not in ('menu', 'open', 'submit', 'close', 'refresh'):
                return None, f"Menu '{label}': unknown action '{action}'"
            item: Dict[str, Any] = {
                'id': str(raw_item.get('id') or item_label)[:64],
                'label': item_label[:120],
                'action': action,
            }
            if action == 'open':
                target = str(raw_item.get('screen') or '').strip().lower()
                if not target:
                    return None, f"Menu '{label}': '{item_label}' opens nothing"
                item['screen'] = target[:64]
            if raw_item.get('confirm'):
                item['confirm'] = str(raw_item['confirm'])[:500]
            if raw_item.get('sound'):
                item['sound'] = str(raw_item['sound'])[:64]
            items.append(item)
        menus.append({'label': label[:60], 'items': items})
    return menus, ""


def validate_definition(definition: Any) -> Tuple[bool, str, Optional[Dict]]:
    """Check a screen definition and return ``(ok, error, normalised)``.

    Normalising here means the client never has to guess: item lists are
    expanded to ``{value, label}`` dicts, numbers are coerced, and unknown
    keys are dropped instead of being forwarded to every client.
    """
    if isinstance(definition, str):
        try:
            definition = json.loads(definition)
        except Exception as e:
            return False, f"Definition is not valid JSON: {e}", None
    if not isinstance(definition, dict):
        return False, "Definition must be a JSON object", None

    title = str(definition.get('title') or '').strip()
    if not title:
        return False, "Screen needs a title", None

    kind = str(definition.get('kind') or 'dialog').lower()
    if kind not in SCREEN_KINDS:
        return False, f"Unknown screen kind '{kind}'", None

    out: Dict[str, Any] = {
        'schema': SCHEMA_VERSION,
        'kind': kind,
        'title': title[:200],
        'fields': [],
        'buttons': [],
    }
    for key in ('description', 'sound', 'announce'):
        value = definition.get(key)
        if value:
            out[key] = str(value)[:MAX_TEXT]

    if kind == 'view':
        rows, why = _validate_rows(definition.get('items'))
        if rows is None:
            return False, why, None
        out['items'] = rows

        tabs, why = _validate_tabs(definition.get('tabs'))
        if tabs is None:
            return False, why, None
        if tabs:
            out['tabs'] = tabs
            active = str(definition.get('active_tab') or tabs[0]['id'])
            if active not in {tab['id'] for tab in tabs}:
                active = tabs[0]['id']
            out['active_tab'] = active

        menus, why = _validate_menus(definition.get('menus'))
        if menus is None:
            return False, why, None
        if menus:
            out['menus'] = menus
        # Spoken when the view opens and after every refresh - a service uses
        # it for "12 unread", "on air now", and so on.
        if definition.get('status'):
            out['status'] = str(definition['status'])[:MAX_TEXT]
        # What to say when there is nothing in the list, so an empty service
        # explains itself instead of reading as a broken one.
        out['empty'] = str(definition.get('empty') or 'This list is empty')[:500]
        try:
            seconds = int(definition.get('refresh_seconds') or 0)
            if seconds:
                # Never let a service busy-poll somebody's connection.
                out['refresh_seconds'] = max(10, min(3600, seconds))
        except Exception:
            pass

    size = definition.get('size')
    if isinstance(size, (list, tuple)) and len(size) == 2:
        try:
            out['size'] = [max(240, min(1600, int(size[0]))),
                           max(180, min(1200, int(size[1])))]
        except Exception:
            pass

    raw_fields = definition.get('fields') or []
    if not isinstance(raw_fields, list):
        return False, "'fields' must be a list", None
    if len(raw_fields) > MAX_FIELDS:
        return False, f"Too many fields (max {MAX_FIELDS})", None

    seen_ids = set()
    for index, raw in enumerate(raw_fields):
        if not isinstance(raw, dict):
            return False, f"Field {index} is not an object", None
        ftype = str(raw.get('type') or 'text').lower()
        if ftype not in FIELD_TYPES:
            return False, f"Unknown field type '{ftype}'", None

        field: Dict[str, Any] = {'type': ftype}

        if ftype != 'separator':
            fid = str(raw.get('id') or '').strip()
            if ftype not in ('static',) and not fid:
                return False, f"Field {index} ({ftype}) needs an id", None
            if fid:
                if fid in seen_ids:
                    return False, f"Duplicate field id '{fid}'", None
                seen_ids.add(fid)
                field['id'] = fid[:64]
            label = raw.get('label')
            if label is not None:
                field['label'] = str(label)[:500]

        if ftype in ('static',):
            field['text'] = str(raw.get('text') or raw.get('label') or '')[:MAX_TEXT]

        if ftype in ('text', 'multiline'):
            field['default'] = str(raw.get('default') or '')[:MAX_TEXT]
            if raw.get('password'):
                field['password'] = True
            if raw.get('required'):
                field['required'] = True
            if raw.get('readonly'):
                field['readonly'] = True
            try:
                if raw.get('max_length'):
                    field['max_length'] = max(1, min(MAX_TEXT, int(raw['max_length'])))
            except Exception:
                pass
            if raw.get('hint'):
                field['hint'] = str(raw['hint'])[:500]

        if ftype == 'number':
            for key, fallback in (('min', 0), ('max', 1000000), ('default', 0), ('step', 1)):
                try:
                    field[key] = int(raw.get(key, fallback))
                except Exception:
                    field[key] = fallback
            if field['min'] > field['max']:
                return False, f"Field '{field.get('id')}' has min above max", None
            field['default'] = max(field['min'], min(field['max'], field['default']))

        if ftype in ('choice', 'radio', 'list'):
            items = _as_items(raw.get('items'))
            if items is None:
                return False, f"Field '{field.get('id')}' has invalid items", None
            field['items'] = items
            if raw.get('default') is not None:
                field['default'] = raw['default']
            if ftype == 'choice' and raw.get('style') in ('combo', 'list'):
                field['style'] = raw['style']
            if ftype == 'list' and raw.get('columns'):
                field['columns'] = [str(c)[:60] for c in raw['columns'][:8]]
            if raw.get('required'):
                field['required'] = True

        if ftype == 'checkbox':
            field['default'] = bool(raw.get('default'))

        out['fields'].append(field)

    raw_buttons = definition.get('buttons') or []
    if not isinstance(raw_buttons, list):
        return False, "'buttons' must be a list", None
    if len(raw_buttons) > MAX_BUTTONS:
        return False, f"Too many buttons (max {MAX_BUTTONS})", None

    for index, raw in enumerate(raw_buttons):
        if not isinstance(raw, dict):
            return False, f"Button {index} is not an object", None
        action = str(raw.get('action') or 'submit').lower()
        if action not in BUTTON_ACTIONS:
            return False, f"Unknown button action '{action}'", None
        bid = str(raw.get('id') or action).strip()[:64]
        label = str(raw.get('label') or bid).strip()[:120]
        button: Dict[str, Any] = {'id': bid, 'label': label, 'action': action}
        if action == 'open':
            target = str(raw.get('screen') or '').strip().lower()
            if not target:
                return False, f"Button '{bid}' opens nothing", None
            button['screen'] = target[:64]
        if raw.get('default'):
            button['default'] = True
        if raw.get('sound'):
            button['sound'] = str(raw['sound'])[:64]
        if raw.get('confirm'):
            button['confirm'] = str(raw['confirm'])[:500]
        out['buttons'].append(button)

    if not out['buttons'] and kind == 'dialog':
        # A form must be closable without the user guessing at Escape. A view
        # always has Escape (it means "back"), so it needs no button bar.
        out['buttons'] = [{'id': 'close', 'label': 'Close', 'action': 'cancel'}]

    return True, "", out


def coerce_values(definition: Dict[str, Any], values: Any,
                  strict: bool = True) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Validate what a client sent back against the screen's own fields.

    The client validates too, for a fast, spoken error - but this is the
    copy that decides. Returns ``(clean_values, errors)`` where ``errors``
    maps a field id to a message the client shows next to that field.

    ``strict`` is False for anything that is not an explicit submit - firing
    a row in a service view, pressing Refresh, switching a tab. Those still
    get typed, range-checked values, but a half-filled form must not stop
    the user from navigating; bad fields are simply left out.
    """
    clean: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    if not isinstance(values, dict):
        values = {}

    # A view has rows rather than fields, and firing a row sends its id as
    # 'item'. Only ids the view actually listed are accepted, so a client
    # cannot fire a row the server never offered it.
    if definition.get('kind') == 'view' and 'item' in values:
        known = {str(row.get('id')) for row in definition.get('items', [])}
        candidate = str(values.get('item'))
        if candidate in known:
            clean['item'] = candidate
        else:
            errors['item'] = "That entry is no longer in the list"

    for field in definition.get('fields', []):
        ftype = field.get('type')
        fid = field.get('id')
        if not fid or ftype in ('static', 'separator'):
            continue
        raw = values.get(fid)

        if ftype in ('text', 'multiline'):
            text = '' if raw is None else str(raw)
            limit = int(field.get('max_length') or MAX_TEXT)
            if len(text) > limit:
                errors[fid] = f"Maximum {limit} characters"
                continue
            if field.get('required') and not text.strip():
                errors[fid] = "This field is required"
                continue
            clean[fid] = text

        elif ftype == 'number':
            try:
                number = int(raw)
            except Exception:
                errors[fid] = "Enter a number"
                continue
            if number < field.get('min', 0) or number > field.get('max', 0):
                errors[fid] = f"Value must be between {field.get('min')} and {field.get('max')}"
                continue
            clean[fid] = number

        elif ftype == 'checkbox':
            clean[fid] = bool(raw)

        elif ftype in ('choice', 'radio', 'list'):
            allowed = [item.get('value') for item in field.get('items', [])]
            if raw is None or raw == '':
                if field.get('required'):
                    errors[fid] = "Choose an option"
                    continue
                clean[fid] = None
            elif raw in allowed:
                clean[fid] = raw
            else:
                # Clients send the label when a list was rebuilt locally.
                match = next((item.get('value') for item in field.get('items', [])
                              if str(item.get('label')) == str(raw)), None)
                if match is None:
                    errors[fid] = "Unknown option"
                    continue
                clean[fid] = match

    if not strict:
        # Navigating a service must never be blocked by an unfinished form:
        # keep only the row-level error, which really does mean "that entry
        # is gone" rather than "you have not typed enough yet".
        errors = {fid: why for fid, why in errors.items() if fid == 'item'}
    return clean, errors


# ---------------------------------------------------------------------------
# Results a handler can return
# ---------------------------------------------------------------------------

def close(message: Optional[str] = None, sound: Optional[str] = None,
          announce: Optional[str] = None) -> Dict[str, Any]:
    """Close the screen, optionally with a final message / sound."""
    result: Dict[str, Any] = {'close': True}
    if message:
        result['message'] = str(message)
    if announce:
        result['announce'] = str(announce)
    if sound:
        result['sound'] = str(sound)
    return result


def message(text: str, sound: Optional[str] = None) -> Dict[str, Any]:
    """Show a message and leave the screen open."""
    result: Dict[str, Any] = {'message': str(text)}
    if sound:
        result['sound'] = str(sound)
    return result


def announce(text: str, sound: Optional[str] = None) -> Dict[str, Any]:
    """Speak text without a dialog (screen stays open)."""
    result: Dict[str, Any] = {'announce': str(text)}
    if sound:
        result['sound'] = str(sound)
    return result


def error(field_errors: Dict[str, str], text: Optional[str] = None) -> Dict[str, Any]:
    """Reject a submit: the client focuses and speaks the first bad field."""
    result: Dict[str, Any] = {'errors': {str(k): str(v) for k, v in field_errors.items()}}
    if text:
        result['message'] = str(text)
    return result


def sound(name: str) -> Dict[str, Any]:
    """Play one of the server's registered sounds on this client."""
    return {'sound': str(name)}


def update(values: Dict[str, Any], items: Optional[Dict[str, List]] = None,
           text: Optional[str] = None) -> Dict[str, Any]:
    """Update the OPEN screen in place: new field values and/or list items."""
    result: Dict[str, Any] = {'values': values or {}}
    if items:
        result['items'] = {k: (_as_items(v) or []) for k, v in items.items()}
    if text:
        result['message'] = str(text)
    return result


def goto(definition: Dict[str, Any]) -> Dict[str, Any]:
    """Open another screen, built here and now rather than stored in the DB.

    This is how a service drills down: the list handler builds the next list
    (or form) on the spot and returns it. Clients push it onto their back
    stack, so Escape returns to where the user came from.
    """
    ok, why, normalised = validate_definition(definition)
    if not ok:
        logger.error(f"[REMOTE-UI] handler produced an invalid screen: {why}")
        return {'message': 'The server sent a screen this client cannot show'}
    return {'screen': normalised}


def view(title: str, items: Optional[List] = None, status: Optional[str] = None,
         empty: Optional[str] = None, buttons: Optional[List[Dict]] = None,
         description: Optional[str] = None, sound: Optional[str] = None,
         refresh_seconds: Optional[int] = None,
         tabs: Optional[List] = None, active_tab: Optional[str] = None,
         menus: Optional[List[Dict]] = None,
         fields: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """Build a SERVICE view: a list the user arrows through.

    The building block for anything that is more than one form - a radio
    service, a news feed, a shop, a file browser. Rows carry an ``action``;
    firing one calls the handler again with ``values['item']`` set to that
    row's id, and the handler answers with the next view, a form, or just a
    message. Nesting views is what turns a handler into a whole service::

        return view("Radio Titan",
                    [{'id': ch['id'], 'label': ch['name'],
                      'sublabel': f"{ch['listeners']} listening",
                      'action': 'open_channel'} for ch in channels],
                    status=f"{len(channels)} channels on air")
    """
    definition: Dict[str, Any] = {'kind': 'view', 'title': title,
                                  'items': items or []}
    if status:
        definition['status'] = status
    if empty:
        definition['empty'] = empty
    if buttons:
        definition['buttons'] = buttons
    if description:
        definition['description'] = description
    if sound:
        definition['sound'] = sound
    if refresh_seconds:
        definition['refresh_seconds'] = refresh_seconds
    if tabs:
        definition['tabs'] = tabs
    if active_tab:
        definition['active_tab'] = active_tab
    if menus:
        definition['menus'] = menus
    if fields:
        definition['fields'] = fields
    return goto(definition)


def back(message_text: Optional[str] = None,
         sound_name: Optional[str] = None) -> Dict[str, Any]:
    """Go one step back up the service, refreshing whatever we return to."""
    result: Dict[str, Any] = {'back': True}
    if message_text:
        result['message'] = str(message_text)
    if sound_name:
        result['sound'] = str(sound_name)
    return result


def refresh(items: Optional[List] = None, status: Optional[str] = None,
            message_text: Optional[str] = None,
            sound_name: Optional[str] = None) -> Dict[str, Any]:
    """Update the OPEN view in place, keeping the user where they are.

    Use this rather than ``view()`` when a list just changed - replacing the
    screen would throw away the cursor position, which for somebody using a
    screen reader means losing their place entirely.
    """
    result: Dict[str, Any] = {'refresh': True}
    if items is not None:
        rows, why = _validate_rows(items)
        if rows is None:
            logger.error(f"[REMOTE-UI] refresh produced invalid rows: {why}")
            return {'message': 'The server sent a list this client cannot show'}
        result['items'] = rows
    if status is not None:
        result['status'] = str(status)[:MAX_TEXT]
    if message_text:
        result['message'] = str(message_text)
    if sound_name:
        result['sound'] = str(sound_name)
    return result


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

HANDLERS: Dict[str, Callable] = {}


def handler(name: str) -> Callable:
    """Register a server-side handler under ``name``.

    A screen row's ``handler`` column points at one of these. Handlers live
    on the server, so they can touch the database, moderate, send mail -
    anything - while the client stays a dumb, safe renderer.
    """
    def _wrap(fn: Callable) -> Callable:
        HANDLERS[name] = fn
        logger.info(f"[REMOTE-UI] handler registered: {name}")
        return fn
    return _wrap


class ScreenContext:
    """What a handler is given for one open/submit."""

    def __init__(self, server, db, user: Dict[str, Any], screen: Dict[str, Any],
                 definition: Dict[str, Any], action: str, values: Dict[str, Any]):
        self.server = server
        self.db = db
        self.user = user
        self.user_id = user.get('id')
        self.username = user.get('username')
        self.screen = screen
        self.slug = screen.get('slug')
        self.definition = definition
        self.action = action
        self.values = values

    @property
    def is_moderator(self) -> bool:
        return bool(self.db.is_moderator(self.user_id))

    @property
    def item(self) -> Optional[str]:
        """Which row the user fired, on a view screen (None on a form)."""
        value = self.values.get('item')
        return None if value is None else str(value)

    @property
    def row(self) -> Optional[Dict[str, Any]]:
        """The full row the user fired, including any ``data`` you attached."""
        wanted = self.item
        if wanted is None:
            return None
        for row in self.definition.get('items', []):
            if str(row.get('id')) == wanted:
                return row
        return None

    def fill(self, per_field: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Open-time convenience: inject items/defaults into the definition.

        ``ctx.fill({'user': {'items': [...], 'default': 'ala'}})`` returns the
        screen with that field's options already populated, so the client
        shows a live list without knowing where it came from.
        """
        for field in self.definition.get('fields', []):
            patch = per_field.get(field.get('id'))
            if not patch:
                continue
            if 'items' in patch:
                field['items'] = _as_items(patch['items']) or []
            if 'default' in patch:
                field['default'] = patch['default']
            if 'text' in patch:
                field['text'] = str(patch['text'])[:MAX_TEXT]
            if 'label' in patch:
                field['label'] = str(patch['label'])[:500]
        return {'screen': self.definition}

    def rows(self, items: List, status: Optional[str] = None) -> Dict[str, Any]:
        """Open-time convenience for a VIEW: fill the stored screen's list.

        Lets a service keep its title, buttons and wording in the stored JSON
        while the actual rows are computed fresh every time it opens::

            @handler('radio')
            def radio(ctx):
                if ctx.action == 'open':
                    return ctx.rows(load_channels(), status='On air now')
        """
        normalised, why = _validate_rows(items)
        if normalised is None:
            logger.error(f"[REMOTE-UI] {self.slug}: invalid rows: {why}")
            return {'message': 'The server sent a list this client cannot show'}
        self.definition['kind'] = 'view'
        self.definition['items'] = normalised
        if status is not None:
            self.definition['status'] = str(status)[:MAX_TEXT]
        return {'screen': self.definition}

    async def play_sound(self, name: str, target: Optional[Dict] = None):
        """Play a server sound - by default at the user who is looking."""
        if self.server is None:
            return
        await self.server.push_server_sound(
            name, target or {'type': 'user', 'user_id': self.user_id})


async def run_handler(name: str, ctx: ScreenContext) -> Dict[str, Any]:
    """Invoke a handler, tolerating sync and async implementations."""
    fn = HANDLERS.get(name)
    if fn is None:
        if name and name != 'store':
            logger.warning(f"[REMOTE-UI] no handler named '{name}', using 'store'")
        fn = HANDLERS['store']
    result = fn(ctx)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, dict):
        return close()
    return result


# ---------------------------------------------------------------------------
# Built-in handlers
# ---------------------------------------------------------------------------

@handler('store')
def _store(ctx: ScreenContext) -> Dict[str, Any]:
    """Default handler: hand back the screen on open, record what comes back.

    Enough on its own for surveys, request forms and report screens - the
    submissions are readable through ``list_remote_submissions`` and the
    ``/api/remote-screens/<slug>/submissions`` endpoint.
    """
    if ctx.action == 'open':
        return {'screen': ctx.definition}
    # Navigation the client performs on its own (F5, tab cycling, firing a
    # row on a plain list) is not an answer to a form - recording it would
    # fill the submissions log with noise.
    if ctx.action in ('refresh', 'tab', 'activate'):
        return {'screen': ctx.definition}
    try:
        ctx.db.run_write(ctx.db.record_remote_submission, ctx.slug, ctx.user_id,
                         ctx.action, json.dumps(ctx.values, ensure_ascii=False)).result(timeout=10)
    except Exception as e:
        logger.error(f"[REMOTE-UI] could not store submission for {ctx.slug}: {e}")
        return message("The server could not save your answer. Please try again.")
    return close(message="Sent. Thank you.")


@handler('readonly')
def _readonly(ctx: ScreenContext) -> Dict[str, Any]:
    """A screen that only displays things; any button just closes it."""
    if ctx.action == 'open':
        return {'screen': ctx.definition}
    return close()
