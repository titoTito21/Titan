"""The ``__actions.json`` manifest: an add-on's declaration of what it can do.

The manifest is **data written by somebody else**, so nothing in here raises and
nothing here is trusted: a malformed file yields the best add-on description
that can be salvaged plus warnings, text fields are length-capped and stripped
of control characters, and an add-on can never name a handler outside its own
directory.

Shape (every field except ``actions`` is optional)::

    {
      "version": 1,
      "id": "tedit",
      "label": "Text Editor",
      "description": "Edit plain text files.",
      "transport": "process",
      "entry": "tedit_actions.py",
      "launch_if_needed": true,
      "actions": [
        {
          "name": "open_file",
          "summary": "Open a text file in the editor.",
          "params": {
            "path": {"type": "string", "description": "File to open.",
                     "required": true}
          },
          "risk": "confirm",
          "mode": "any",
          "promote": true
        }
      ]
    }

An in-process add-on may skip the JSON entirely and define a module-level
``TITAN_ACTIONS`` list instead, with a real callable under ``run`` - see
``registry.actions_from_module``.
"""

import json
import os
import re

MANIFEST_NAMES = ('__actions.json', '__actions.TCE')

RISK_LEVELS = ('auto', 'confirm', 'always_confirm')
MODES = ('any', 'live', 'headless')
TRANSPORTS = ('inproc', 'process')

# Accepted spellings -> JSON-schema type. Anything else becomes a string, which
# is always safe: the handler receives text and the model is told as much.
PARAM_TYPES = {
    'string': 'string', 'str': 'string', 'text': 'string',
    'number': 'number', 'float': 'number',
    'integer': 'integer', 'int': 'integer',
    'boolean': 'boolean', 'bool': 'boolean',
}

MAX_LABEL = 80
MAX_SUMMARY = 500
MAX_DESCRIPTION = 800
MAX_ACTIONS = 64
MAX_PARAMS = 12
MAX_ENUM = 40

_SLUG_RE = re.compile(r'[^a-z0-9_]+')
_CONTROL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def slug(text, fallback=''):
    """A safe identifier: lowercase, ASCII, underscores only."""
    out = _SLUG_RE.sub('_', (text or '').strip().lower()).strip('_')
    return out or fallback


def clean_text(value, limit):
    """Text from a third-party manifest, made safe to put in a prompt: one
    line, no control characters, capped."""
    if not isinstance(value, str):
        return ''
    text = _CONTROL_RE.sub(' ', value).replace('\r', ' ')
    text = ' '.join(text.split())
    if len(text) > limit:
        text = text[:limit].rstrip() + '...'
    return text


class ActionSpec:
    """One callable function an add-on offers."""

    def __init__(self, name, summary='', params=None, risk='auto', mode='any',
                 promote=False, handler='', addon=None, timeout=0,
                 launch=None, needs_ai=False):
        self.name = name
        # Is this action *done by a model*? Such an action cannot work with
        # Titan's AI features switched off, and the honest answer then is to say
        # so rather than to fail somewhere inside a provider - see
        # dispatch.run(). Declared per action, because an add-on may have one
        # AI-backed action among a dozen ordinary ones.
        self.needs_ai = bool(needs_ai)
        self.summary = summary
        self.params = params or {}          # ordered: name -> descriptor dict
        self.risk = risk if risk in RISK_LEVELS else 'auto'
        self.mode = mode if mode in MODES else 'any'
        self.promote = bool(promote)
        # Seconds a headless run may take. Zero means the default; an action
        # that genuinely takes longer (generating speech, converting a file)
        # says so rather than being killed halfway.
        self.timeout = max(0, min(int(timeout or 0), 600))
        # May Titan start the add-on to deliver THIS action? None inherits the
        # add-on's setting. It belongs per action: "open this file" should
        # start the editor, "what have you got open" plainly should not - and
        # one flag for the whole add-on cannot say both.
        self.launch = launch
        self.handler = handler or name      # attribute/function to call
        self.addon = addon                  # AddonActions, set by the parser
        self.run = None                     # a direct callable (Python-declared)

    # ------------------------------------------------------------------ names
    @property
    def qualified(self):
        """'tedit.open_file' - how a user or the generic dispatcher names it."""
        addon_id = self.addon.addon_id if self.addon else 'addon'
        return f"{addon_id}.{self.name}"

    @property
    def tool_name(self):
        """The agent tool name. Providers only accept [A-Za-z0-9_-]{1,64}."""
        addon_id = self.addon.addon_id if self.addon else 'addon'
        name = f"{addon_id}_{self.name}"
        return name[:64]

    # ----------------------------------------------------------------- schema
    def json_schema(self):
        props = {}
        required = []
        for pname, p in self.params.items():
            prop = {'type': p.get('type', 'string')}
            if p.get('description'):
                prop['description'] = p['description']
            if p.get('enum'):
                prop['enum'] = p['enum']
            props[pname] = prop
            if p.get('required'):
                required.append(pname)
        return {'type': 'object', 'properties': props, 'required': required}

    def describe(self):
        """One line for titan_list_actions."""
        args = ", ".join(
            f"{n}{'' if p.get('required') else '?'}:{p.get('type', 'string')}"
            for n, p in self.params.items())
        risk = '' if self.risk == 'auto' else f" [{self.risk}]"
        # Whether an action needs the AI is part of what it is: a macro author
        # choosing between two ways of doing something should be able to see
        # which one still works with the AI switched off.
        needs = " [needs AI]" if self.needs_ai else ''
        return f"{self.qualified}({args}){risk}{needs} - {self.summary}"

    def coerce(self, args):
        """Bring model-supplied arguments to the declared types. Models happily
        send "true" for a boolean and "3" for a number; the handler should not
        have to care."""
        out = {}
        for key, value in (args or {}).items():
            spec = self.params.get(key)
            if spec is None:
                out[key] = value
                continue
            want = spec.get('type', 'string')
            try:
                if want == 'boolean' and not isinstance(value, bool):
                    out[key] = str(value).strip().lower() in (
                        '1', 'true', 'yes', 'on', 'tak')
                elif want == 'integer' and not isinstance(value, bool):
                    out[key] = int(float(value))
                elif want == 'number' and not isinstance(value, bool):
                    out[key] = float(value)
                elif want == 'string' and not isinstance(value, str):
                    out[key] = '' if value is None else str(value)
                else:
                    out[key] = value
            except (TypeError, ValueError):
                out[key] = value
        return out

    def missing_required(self, args):
        return [n for n, p in self.params.items()
                if p.get('required') and not str(args.get(n, '')).strip()]


class AddonActions:
    """Everything one add-on declares."""

    def __init__(self, kind, addon_id, name, path, label='', description='',
                 transport='inproc', entry='', launch_if_needed=True):
        self.kind = kind
        self.addon_id = addon_id      # stable id used in tool names
        self.name = name              # the on-disk folder name
        self.path = path
        self.label = label or name
        self.description = description
        self.transport = transport
        self.entry = entry
        self.launch_if_needed = launch_if_needed
        self.actions = []
        self.warnings = []
        self.source = 'json'          # 'json' | 'python' | 'bus' | 'builtin'
        self.builtin = False          # one of Titan's own subsystems
        self.running = False
        self.pid = 0

    def get(self, action_name):
        wanted = slug(action_name)
        for action in self.actions:
            if action.name == wanted:
                return action
        return None

    def entry_path(self):
        """Absolute path of the handler module, or '' when none is declared.

        The entry is resolved *inside* the add-on directory - a manifest cannot
        point Titan at a file elsewhere on the disk."""
        if not self.entry:
            return ''
        candidate = os.path.normpath(os.path.join(self.path, self.entry))
        root = os.path.normpath(self.path)
        if os.path.commonpath([root, candidate]) != root:
            return ''
        return candidate if os.path.isfile(candidate) else ''


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _parse_params(raw, warn):
    """``params`` is a mapping so the declaration order is the prompt order.
    A bare list of names is accepted too, because people write that."""
    params = {}
    if isinstance(raw, list):
        raw = {str(item): {} for item in raw if isinstance(item, (str, int))}
    if not isinstance(raw, dict):
        if raw:
            warn("params must be an object; ignored")
        return params
    for key, value in raw.items():
        if len(params) >= MAX_PARAMS:
            warn(f"more than {MAX_PARAMS} parameters; the rest were dropped")
            break
        pname = slug(key)
        if not pname:
            continue
        if isinstance(value, str):           # "path": "File to open."
            value = {'description': value}
        if not isinstance(value, dict):
            value = {}
        ptype = PARAM_TYPES.get(str(value.get('type', 'string')).lower(), 'string')
        entry = {'type': ptype,
                 'description': clean_text(value.get('description', ''), MAX_SUMMARY),
                 'required': bool(value.get('required'))}
        enum = value.get('enum')
        if isinstance(enum, list) and enum:
            entry['enum'] = [clean_text(str(v), 60) for v in enum[:MAX_ENUM]]
        params[pname] = entry
    return params


def _parse_action(raw, addon, warn):
    if not isinstance(raw, dict):
        warn("an action entry is not an object; ignored")
        return None
    name = slug(raw.get('name', ''))
    if not name:
        warn("an action has no usable 'name'; ignored")
        return None
    summary = clean_text(raw.get('summary') or raw.get('description', ''),
                         MAX_SUMMARY)
    if not summary:
        summary = f"Run '{name}' in {addon.label}."
    risk = str(raw.get('risk', 'auto')).strip().lower()
    if risk not in RISK_LEVELS:
        if risk:
            warn(f"action '{name}': unknown risk '{risk}', using 'auto'")
        risk = 'auto'
    mode = str(raw.get('mode', 'any')).strip().lower()
    if mode not in MODES:
        if mode:
            warn(f"action '{name}': unknown mode '{mode}', using 'any'")
        mode = 'any'
    handler = raw.get('handler', '')
    handler = handler if isinstance(handler, str) and handler.isidentifier() else name
    try:
        timeout = int(raw.get('timeout') or 0)
    except (TypeError, ValueError):
        timeout = 0
    launch = raw.get('launch_if_needed')
    return ActionSpec(
        name=name, summary=summary,
        params=_parse_params(raw.get('params'), warn),
        risk=risk, mode=mode, promote=bool(raw.get('promote')),
        handler=handler, addon=addon, timeout=timeout,
        launch=None if launch is None else bool(launch),
        needs_ai=bool(raw.get('needs_ai')))


def parse_manifest(data, kind, name, path, default_transport='inproc',
                   fallback_label=''):
    """Turn parsed JSON into an AddonActions. Never raises."""
    addon = AddonActions(kind=kind, addon_id=slug(name, 'addon'), name=name,
                         path=path, label=fallback_label or name,
                         transport=default_transport)
    warnings = addon.warnings

    def warn(message):
        if len(warnings) < 12:
            warnings.append(message)

    if not isinstance(data, dict):
        warn("the manifest is not a JSON object")
        return addon

    addon.addon_id = slug(data.get('id', ''), addon.addon_id)
    addon.label = clean_text(data.get('label', ''), MAX_LABEL) or addon.label
    addon.description = clean_text(data.get('description', ''), MAX_DESCRIPTION)

    transport = str(data.get('transport', '')).strip().lower()
    if transport in TRANSPORTS:
        addon.transport = transport
    elif transport:
        warn(f"unknown transport '{transport}', using '{default_transport}'")

    entry = data.get('entry', '')
    if isinstance(entry, str):
        addon.entry = entry.strip()
    if 'launch_if_needed' in data:
        addon.launch_if_needed = bool(data.get('launch_if_needed'))

    raw_actions = data.get('actions')
    if not isinstance(raw_actions, list):
        warn("'actions' is missing or is not a list")
        raw_actions = []
    seen = set()
    for raw in raw_actions:
        if len(addon.actions) >= MAX_ACTIONS:
            warn(f"more than {MAX_ACTIONS} actions; the rest were dropped")
            break
        action = _parse_action(raw, addon, warn)
        if action is None:
            continue
        if action.name in seen:
            warn(f"duplicate action '{action.name}'; the later one was dropped")
            continue
        seen.add(action.name)
        addon.actions.append(action)
    return addon


def manifest_path(addon_dir):
    for filename in MANIFEST_NAMES:
        candidate = os.path.join(addon_dir, filename)
        if os.path.isfile(candidate):
            return candidate
    return ''


def read_manifest(addon_dir, kind, name, default_transport='inproc',
                  fallback_label=''):
    """Read and parse an add-on's manifest. Returns None when it has none."""
    path = manifest_path(addon_dir)
    if not path:
        return None
    try:
        with open(path, 'r', encoding='utf-8-sig') as handle:
            data = json.load(handle)
    except Exception as e:
        addon = AddonActions(kind=kind, addon_id=slug(name, 'addon'), name=name,
                             path=addon_dir, label=fallback_label or name,
                             transport=default_transport)
        addon.warnings.append(f"could not read {os.path.basename(path)}: {e}")
        return addon
    return parse_manifest(data, kind, name, addon_dir,
                          default_transport=default_transport,
                          fallback_label=fallback_label)
