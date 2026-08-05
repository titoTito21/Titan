"""What the AI remembers between one request and the next.

The agent and the assistant each began every run with an empty history, so
"and now save it" or "what did I just ask you?" had nothing to refer to. Each
run was a stranger.

Two stores, because two different things are being remembered:

- **The conversation** (``conversation.jsonl``) - what was said, in order.
  Recent exchanges are replayed verbatim into the next run; older ones survive
  only as a one-line digest of what was talked about, which is what keeps a
  long day from eating the whole context window.
- **Notes** (``notes.jsonl``) - facts the user asked to be kept ("my sister's
  address is...", "always sign my mail Klaudiusz"). These are small, few, and
  injected in full every time, because a fact the user deliberately gave is
  worth more than any number of old exchanges.

The agent and the assistant share both by default: a user who asks the voice
assistant something and then opens the agent window is one person having one
conversation, and that is what they expect.
"""

import json
import os
import threading
import time

from src.settings.settings import get_setting

_SETTINGS_SECTION = 'ai'

DEFAULT_TURNS = 20
MAX_TURNS = 100
_MAX_TEXT = 4000            # one stored message
_MAX_NOTES = 200
_MAX_FILE_BYTES = 2 * 1024 * 1024
_DIGEST_ITEMS = 12

_lock = threading.RLock()


# --------------------------------------------------------------------------- #
# Settings and files
# --------------------------------------------------------------------------- #
def enabled():
    value = get_setting('memory_enabled', True, section=_SETTINGS_SECTION)
    return str(value).strip().lower() not in ('0', 'false', 'no', 'off')


def turns():
    try:
        value = int(get_setting('memory_turns', DEFAULT_TURNS,
                                section=_SETTINGS_SECTION))
    except (TypeError, ValueError):
        value = DEFAULT_TURNS
    return max(0, min(MAX_TURNS, value))


def _directory():
    try:
        from src import platform_utils
        return platform_utils.ensure_user_data_subdir('ai')
    except Exception:
        base = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'),
                            'titosoft', 'Titan', 'ai')
        os.makedirs(base, exist_ok=True)
        return base


def conversation_path():
    return os.path.join(_directory(), 'conversation.jsonl')


def notes_path():
    return os.path.join(_directory(), 'notes.jsonl')


def _read(path):
    entries = []
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[ai.memory] Could not read {os.path.basename(path)}: {e}")
    return entries


def _append(path, entry):
    try:
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f"[ai.memory] Could not write {os.path.basename(path)}: {e}")


def _rewrite(path, entries):
    try:
        with open(path, 'w', encoding='utf-8') as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f"[ai.memory] Could not rewrite {os.path.basename(path)}: {e}")


def _trim_if_huge(path):
    """Keep the log from growing without limit. Half of it is thrown away at
    once rather than a line at a time, so this rewrite is rare."""
    try:
        if os.path.getsize(path) <= _MAX_FILE_BYTES:
            return
    except OSError:
        return
    entries = _read(path)
    _rewrite(path, entries[len(entries) // 2:])


def _clip(text, limit=_MAX_TEXT):
    text = str(text or '').strip()
    return text if len(text) <= limit else text[:limit].rstrip() + '...'


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #
def record(role, text, source='agent'):
    """Remember one thing that was said. ``role`` is 'user' or 'assistant'."""
    if not enabled() or not str(text).strip():
        return
    if role not in ('user', 'assistant'):
        return
    with _lock:
        path = conversation_path()
        _append(path, {'t': time.time(), 'role': role, 'source': source,
                       'text': _clip(text)})
        _trim_if_huge(path)


def record_exchange(user_text, assistant_text, source='agent'):
    record('user', user_text, source)
    record('assistant', assistant_text, source)


def add_note(text, source='agent'):
    """Keep a fact the user asked to be remembered."""
    if not str(text).strip():
        return "There is nothing to remember."
    with _lock:
        notes = _read(notes_path())
        cleaned = _clip(text, 600)
        for note in notes:
            if note.get('text', '').strip().lower() == cleaned.strip().lower():
                return "That is already remembered."
        notes.append({'t': time.time(), 'source': source, 'text': cleaned})
        if len(notes) > _MAX_NOTES:
            notes = notes[-_MAX_NOTES:]
        _rewrite(notes_path(), notes)
    return f"Remembered: {cleaned}"


def list_notes():
    return [note.get('text', '') for note in _read(notes_path())
            if note.get('text')]


def forget_note(query):
    """Drop the notes matching ``query``."""
    wanted = str(query or '').strip().lower()
    if not wanted:
        return "Say what to forget."
    with _lock:
        notes = _read(notes_path())
        keep = [n for n in notes if wanted not in n.get('text', '').lower()]
        removed = len(notes) - len(keep)
        if removed:
            _rewrite(notes_path(), keep)
    return (f"Forgot {removed} note(s)." if removed
            else f"Nothing remembered matches '{query}'.")


def clear_conversation():
    with _lock:
        _rewrite(conversation_path(), [])
    return "Forgot the conversation so far. Notes were kept."


# --------------------------------------------------------------------------- #
# Recalling
# --------------------------------------------------------------------------- #
def recent(limit=None):
    """The last exchanges, oldest first."""
    count = turns() if limit is None else max(0, int(limit))
    if not count:
        return []
    entries = _read(conversation_path())
    return entries[-(count * 2):]


def digest():
    """One line naming what was talked about before the replayed part.

    Not a summary in the AI sense - no request is spent on it. It is the
    opening words of older questions, which is enough for the model to know a
    subject was already covered and ask rather than assume.
    """
    entries = _read(conversation_path())
    kept = turns() * 2
    older = entries[:-kept] if kept and len(entries) > kept else []
    subjects = []
    for entry in reversed(older):
        if entry.get('role') != 'user':
            continue
        text = ' '.join(str(entry.get('text', '')).split())[:70]
        if text and text not in subjects:
            subjects.append(text)
        if len(subjects) >= _DIGEST_ITEMS:
            break
    if not subjects:
        return ''
    return ("Earlier in this conversation the user also asked about: "
            + "; ".join(reversed(subjects)) + ".")


def search(query, limit=10):
    """Find something said earlier."""
    words = [w for w in str(query or '').lower().split() if w]
    if not words:
        return []
    hits = []
    for entry in reversed(_read(conversation_path())):
        text = str(entry.get('text', ''))
        lowered = text.lower()
        if all(word in lowered for word in words):
            hits.append(entry)
            if len(hits) >= limit:
                break
    return list(reversed(hits))


def prompt_history():
    """The recalled part of a new run's history, ready to prepend.

    Returns entries in the same shape ``ai_agent`` uses, so every provider
    adapter already understands them.
    """
    if not enabled():
        return []
    history = []
    notes = list_notes()
    preface = []
    if notes:
        preface.append("Things the user asked you to remember:\n"
                       + "\n".join(f"- {note}" for note in notes))
    line = digest()
    if line:
        preface.append(line)
    if preface:
        history.append({'role': 'user', 'content': "\n\n".join(preface)})
        history.append({'role': 'assistant',
                        'content': "Understood - I have that in mind."})
    for entry in recent():
        role = entry.get('role')
        text = entry.get('text', '')
        if role in ('user', 'assistant') and text:
            history.append({'role': role, 'content': text})
    # A replayed history must not end on a user turn: the new request is about
    # to be appended, and two user turns in a row is invalid for some providers.
    while history and history[-1]['role'] == 'user':
        history.pop()
    return history


def status():
    entries = _read(conversation_path())
    return (f"Memory is {'on' if enabled() else 'off'}. "
            f"{len(entries)} messages remembered, "
            f"{len(list_notes())} notes, "
            f"replaying the last {turns()} exchanges.")


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
def ai_remember(fact, **_):
    """Keep a fact for later conversations."""
    return add_note(fact)


def ai_recall(query, **_):
    """Look something up in what was said earlier."""
    hits = search(query, limit=10)
    if not hits:
        return (f"Nothing in the earlier conversation matches '{query}'.")
    lines = [f"Earlier in the conversation, matching '{query}':"]
    for entry in hits:
        when = time.strftime('%Y-%m-%d %H:%M',
                             time.localtime(entry.get('t', 0)))
        who = "the user" if entry.get('role') == 'user' else "you"
        lines.append(f"- [{when}] {who}: {_clip(entry.get('text'), 400)}")
    return "\n".join(lines)


def ai_list_notes(**_):
    """Everything the user has asked to be remembered."""
    notes = list_notes()
    if not notes:
        return "Nothing has been saved to remember yet."
    return "Remembered:\n" + "\n".join(f"- {note}" for note in notes)


def ai_forget(query, **_):
    """Forget a saved fact."""
    return forget_note(query)


def get_memory_tools():
    from src.ai.agent_tools import _tool
    S = {'type': 'string'}
    return [
        _tool('ai_remember',
              "Keep a fact for later conversations - something the user says "
              "to remember, or something you learned about how they want "
              "things done. Recent exchanges are already replayed to you "
              "automatically; use this only for things worth keeping "
              "indefinitely.", ai_remember,
              properties={'fact': dict(S, description="The fact, in one sentence.")},
              required=['fact']),
        _tool('ai_recall',
              "Search everything said earlier, further back than the part you "
              "were given. Use this when the user refers to something you "
              "cannot see in this conversation.", ai_recall,
              properties={'query': dict(S, description="Words to look for.")},
              required=['query']),
        _tool('ai_list_notes', "Everything the user has asked to be remembered.",
              ai_list_notes),
        _tool('ai_forget', "Forget a saved fact.", ai_forget, risk='confirm',
              properties={'query': dict(S, description="Which fact - words it contains.")},
              required=['query']),
    ]
