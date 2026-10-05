# -*- coding: utf-8 -*-
"""NVDA's `config`: ``config.conf["section"]["key"]``, as nested sections
that make themselves when first asked for, saved as JSON in the add-ons'
own configuration folder. An add-on's `confspec` registration fills in
its defaults."""

import json
import os
import re
import threading

from . import extensionPoints

_LOCK = threading.RLock()


_KINDS = re.compile(r'^\s*(\w+)\s*\((.*)\)\s*$', re.S)
_DEFAULT = re.compile(r'default\s*=\s*("[^"]*"|\'[^\']*\'|list\([^)]*\)'
                      r'|[^,)]+)')


def _typed(spec):
    """The default a configobj spec line gives, as its own type -
    ``integer(default=130,min=50,max=400)`` is 130, ``boolean(default=
    false)`` is False, ``string(default=None)`` is None."""
    found = _KINDS.match(str(spec or ''))
    if not found:
        return None
    kind, args = found.group(1), found.group(2)
    default = _DEFAULT.search(args)
    if not default:
        return None
    raw = default.group(1).strip()
    if raw.startswith(('"', "'")):
        raw = raw[1:-1]
    elif raw == 'None':
        return None
    if raw.startswith('list('):
        return [item.strip().strip('"\'') for item in
                raw[5:-1].split(',') if item.strip()]
    try:
        if kind == 'boolean':
            return raw.lower() in ('true', '1', 'yes', 'on')
        if kind == 'integer':
            return int(raw)
        if kind == 'float':
            return float(raw)
    except ValueError:
        return raw
    return raw


def _convert(spec, value):
    """A stored text, as the type its spec line names."""
    found = _KINDS.match(str(spec or ''))
    kind = found.group(1) if found else 'string'
    text = str(value)
    try:
        if kind == 'boolean':
            return text.strip().lower() in ('true', '1', 'yes', 'on')
        if kind == 'integer':
            return int(text)
        if kind == 'float':
            return float(text)
    except ValueError:
        return _typed(spec)
    if text == 'None' and 'default=None' in str(spec):
        return None
    return text


class _Spec(dict):
    """A section's spec. ``update`` and assignment MERGE, recursively, as
    configobj does - an add-on registers its spec in pieces."""

    def __setitem__(self, key, value):
        if _is_section(value):
            existing = dict.get(self, key)
            target = existing if isinstance(existing, _Spec) else _Spec()
            for name, item in value.items():
                target[name] = item
            dict.__setitem__(self, key, target)
        else:
            dict.__setitem__(self, key, value)

    def update(self, other=(), **kwargs):
        items = other.items() if hasattr(other, 'items') else other
        for key, value in items:
            self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    def child(self, key):
        found = dict.get(self, key)
        if isinstance(found, _Spec):
            return found
        many = dict.get(self, '__many__')
        if isinstance(many, _Spec):
            return many
        return None


def _is_section(value):
    return isinstance(value, dict) or hasattr(value, 'sections')


class Section(dict):
    """A configuration section, NVDA's way: what is not SET is answered
    from the spec (its default, typed), sub-sections are made from the
    spec - or from its ``__many__`` template - when first asked for, and
    ``isSet`` says what really is set."""

    def __init__(self, *args, spec=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.spec = spec if isinstance(spec, _Spec) else _Spec()

    def __getitem__(self, key):
        if dict.__contains__(self, key):
            value = dict.__getitem__(self, key)
            line = dict.get(self.spec, key)
            if isinstance(value, str) and isinstance(line, str):
                # nvda.ini keeps text; the spec says what it IS - which is
                # what NVDA's validator does on loading.
                return _convert(line, value)
            return value
        if key in self.spec and not isinstance(
                dict.__getitem__(self.spec, key), _Spec):
            return _typed(dict.__getitem__(self.spec, key))
        child = self.spec.child(key)
        if child is not None or key not in self.spec:
            if child is None and not self._open():
                raise KeyError(key)
            made = Section(spec=child)
            dict.__setitem__(self, key, made)
            return made
        return _typed(dict.__getitem__(self.spec, key))

    def _open(self):
        """A section with no spec of its own takes any sub-section, as an
        add-on's own new section is written before its spec arrives."""
        return not self.spec

    def __contains__(self, key):
        return dict.__contains__(self, key) or key in self.spec

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def isSet(self, key):
        return dict.__contains__(self, key)

    def __setitem__(self, key, value):
        if isinstance(value, dict) and not isinstance(value, Section):
            made = Section(spec=self.spec.child(key))
            for name, item in value.items():
                made[name] = item
            value = made
        dict.__setitem__(self, key, value)
        _changed()

    def dict(self):
        return {key: (value.dict() if isinstance(value, Section) else value)
                for key, value in self.items()}

    def copy(self):
        return Section(self, spec=self.spec)


def _sectioned(value):
    out = Section()
    for key, item in value.items():
        dict.__setitem__(out, key, _sectioned(item)
                         if isinstance(item, dict) else item)
    return out


def _path():
    from titan_access.nvda_host import config_folder
    return os.path.join(config_folder(), 'nvda_config.json')


def _load():
    try:
        with open(_path(), 'r', encoding='utf-8') as handle:
            return _sectioned(json.load(handle))
    except Exception:                                # noqa: BLE001
        return Section()


conf = _load()
_dirty = [False]
for _name, _value in (('speech', {'outputDevice': 'default'}),
                      ('audio', {'outputDevice': 'default'}),
                      ('general', {'language': 'Windows'}),
                      ('keyboard', {}), ('braille', {})):
    for _key, _item in _value.items():
        if _key not in conf[_name]:
            dict.__setitem__(conf[_name], _key, _item)


def _changed():
    _dirty[0] = True


def save():
    with _LOCK:
        try:
            os.makedirs(os.path.dirname(_path()), exist_ok=True)
            with open(_path(), 'w', encoding='utf-8') as handle:
                json.dump(conf.dict(), handle, ensure_ascii=False, indent=1)
            _dirty[0] = False
        except Exception:                            # noqa: BLE001
            pass


conf.save = save
post_configSave = extensionPoints.Action()
pre_configSave = extensionPoints.Action()
post_configProfileSwitch = extensionPoints.Action()
post_configReset = extensionPoints.Action()
pre_configReset = extensionPoints.Action()


def isInstalledCopy():
    return True


def isAppX():
    return False


def getUserDefaultConfigPath(useInstalledPathIfExists=False):
    from titan_access.nvda_host import config_folder
    return config_folder()


class ConfigManager(object):
    pass


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
