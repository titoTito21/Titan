"""Assistant personas: Perun, Melitele (and any other folder under ``data/ai/``).

Each persona is a directory ``data/ai/<Name>/`` containing a single JSON config
file (``<name>.<name>`` by convention, e.g. ``perun.perun``) plus a
``history.json`` transcript. The config carries the display names, the persona's
``system_instruction`` (its character), and its voice. Voice output uses a
Gemini prebuilt voice (``gemini_voice``); when Gemini TTS is unavailable the
assistant falls back to Titan TTS (``speak_stereo``), NOT SAPI. The legacy
``tts_voice``/``tts_rate`` keys in the config are ignored.
"""

import json
import os
import time

from src import platform_utils

# Map the persona's coarse voice gender to a sensible Gemini prebuilt voice when
# the config does not name one explicitly. (Gemini exposes ~30 named voices;
# these two read well for an authoritative male / warm female persona.)
_GEMINI_VOICE_BY_GENDER = {
    'male': 'Charon',
    'female': 'Aoede',
}
_DEFAULT_GEMINI_VOICE = 'Kore'


def personas_root():
    """The bundled/overlay ``data/ai`` directory that holds persona folders."""
    for cand in platform_utils.iter_resource_paths(os.path.join('data', 'ai'),
                                                    prefer_user=False):
        if os.path.isdir(cand):
            return cand
    return platform_utils.get_data_path('ai')


def _config_path(folder):
    """Find the persona's JSON config inside ``folder`` (skip history.json)."""
    name = os.path.basename(folder).lower()
    preferred = os.path.join(folder, f"{name}.{name}")
    if os.path.isfile(preferred):
        return preferred
    try:
        for fn in sorted(os.listdir(folder)):
            if fn.lower() == 'history.json':
                continue
            full = os.path.join(folder, fn)
            if os.path.isfile(full):
                try:
                    with open(full, 'r', encoding='utf-8') as fh:
                        json.load(fh)
                    return full
                except Exception:
                    continue
    except OSError:
        pass
    return None


def load_persona(folder):
    """Return a persona dict for one folder, or None if it has no valid config."""
    cfg_path = _config_path(folder)
    if not cfg_path:
        return None
    try:
        with open(cfg_path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except Exception as e:
        print(f"[personas] failed to load {cfg_path}: {e}")
        return None
    pid = os.path.basename(folder)
    gemini_voice = (data.get('gemini_voice') or '').strip()
    if not gemini_voice:
        gemini_voice = _GEMINI_VOICE_BY_GENDER.get(
            (data.get('voice') or '').lower(), _DEFAULT_GEMINI_VOICE)
    return {
        'id': pid,
        'folder': folder,
        'config_path': cfg_path,
        'name_en': data.get('name_en') or pid,
        'name_pl': data.get('name_pl') or pid,
        'description_en': data.get('description_en', ''),
        'description_pl': data.get('description_pl', ''),
        'system_instruction': data.get('system_instruction', ''),
        'gemini_voice': gemini_voice,
        'tts_voice': data.get('tts_voice', ''),
        'tts_rate': data.get('tts_rate', 0),
        'raw': data,
    }


def list_personas():
    """All available personas (sorted by id). Empty list if none are installed."""
    root = personas_root()
    out = []
    if not root or not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        folder = os.path.join(root, name)
        if not os.path.isdir(folder) or name.lower() == 'models':
            continue
        p = load_persona(folder)
        if p:
            out.append(p)
    return out


def get_persona(persona_id):
    """Return the persona with ``persona_id`` (case-insensitive), else the first
    available persona, else None."""
    personas = list_personas()
    if not personas:
        return None
    if persona_id:
        for p in personas:
            if p['id'].lower() == persona_id.lower():
                return p
    return personas[0]


# --------------------------------------------------------------------------- #
# Conversation history (per persona)
# --------------------------------------------------------------------------- #
def history_path(persona):
    return os.path.join(persona['folder'], 'history.json')


def load_history(persona):
    """Return the persona's saved [{role, content, timestamp}, ...] (or [])."""
    try:
        with open(history_path(persona), 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def append_history(persona, role, content):
    """Append one turn to the persona's history file (best effort)."""
    hist = load_history(persona)
    hist.append({'role': role, 'content': content, 'timestamp': time.time()})
    try:
        with open(history_path(persona), 'w', encoding='utf-8') as fh:
            json.dump(hist, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[personas] could not save history: {e}")
