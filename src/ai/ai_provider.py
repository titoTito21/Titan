"""Shared, multi-provider AI layer for Titan (the "AI features" / AI creation
kit). Generalises the generation core that already lived in
``titan_net_mod_components`` so both the moderator-component creator and the new
add-on creation kit call one place.

Three communication METHODS (chosen in Settings -> AI features):

* ``api``        - call the provider SDK directly with a stored API key.
* ``claude_cli`` - delegate to a locally installed ``claude`` CLI.
* ``codex``      - delegate to a locally installed ``codex`` CLI.

All methods STREAM: :func:`generate` takes an ``on_chunk`` callback that fires
with each partial text delta, so the UI can show real, moving progress and live
output instead of a frozen dialog.

API keys are stored ENCRYPTED at rest via :mod:`src.titan_core.secret_store`
(DPAPI on Windows), under settings section ``ai`` as ``api_key_<provider>``.
Legacy plaintext keys from the moderator-component creator
(``titannet_component_ai_key_<provider>``) are still read for back-compat.
"""

import base64
import os
import re
import shutil
import subprocess
import sys

from src.settings.settings import get_setting, set_setting
from src.titan_core.secret_store import encrypt_secret, decrypt_secret

# --------------------------------------------------------------------------- #
# Providers / models (mirrors titan_net_mod_components + interactive_games)
# --------------------------------------------------------------------------- #
PROVIDERS = (
    ('anthropic', 'Anthropic Claude'),
    ('gemini', 'Google Gemini'),
    ('openai', 'OpenAI'),
)

METHODS = (
    ('api', 'API key'),
    ('claude_cli', 'Claude CLI'),
    ('codex', 'Codex CLI'),
)

# The provider the voice assistant is built on. Everything that needs the
# assistant's own configuration (its key, its models) reads this rather than
# repeating the literal, so the assistant and AI OCR can never end up pointed
# at different accounts.
ASSISTANT_PROVIDER = 'gemini'

# Fallback model per provider, used only when the newest model cannot be
# resolved from the provider (offline, old SDK, etc.).
_DEFAULT_MODELS = {
    'anthropic': 'claude-opus-4-8',
    'gemini': 'gemini-2.0-flash',
    'openai': 'gpt-4o',
}

_MODEL_CACHE = {}

_SETTINGS_SECTION = 'ai'


def provider_label(provider_id):
    for pid, label in PROVIDERS:
        if pid == provider_id:
            return label
    return provider_id or '?'


# --------------------------------------------------------------------------- #
# Settings accessors
# --------------------------------------------------------------------------- #
def is_ai_enabled():
    return str(get_setting('enabled', '0', section=_SETTINGS_SECTION)) == '1'


def set_ai_enabled(enabled):
    set_setting('enabled', '1' if enabled else '0', section=_SETTINGS_SECTION)


def get_ai_method():
    method = get_setting('method', 'api', section=_SETTINGS_SECTION)
    return method if method in dict(METHODS) else 'api'


def set_ai_method(method):
    set_setting('method', method, section=_SETTINGS_SECTION)


def get_ai_provider():
    provider = get_setting('provider', 'anthropic', section=_SETTINGS_SECTION)
    return provider if provider in dict(PROVIDERS) else 'anthropic'


def set_ai_provider(provider):
    set_setting('provider', provider, section=_SETTINGS_SECTION)


def get_ai_key(provider):
    """Return the decrypted API key for ``provider`` ('' if none). Reads the new
    encrypted ``ai.api_key_<provider>`` first, then falls back to the legacy
    plaintext ``titannet_component_ai_key_<provider>`` so existing keys work."""
    stored = get_setting('api_key_' + provider, '', section=_SETTINGS_SECTION)
    if stored:
        return decrypt_secret(stored)
    # Back-compat: moderator-component creator stored plaintext keys.
    legacy = get_setting('titannet_component_ai_key_' + provider, '')
    return decrypt_secret(legacy) if legacy else ''


def set_ai_key(provider, plaintext):
    """Store ``plaintext`` API key for ``provider`` encrypted at rest (empty
    string clears it)."""
    value = encrypt_secret(plaintext) if plaintext else ''
    set_setting('api_key_' + provider, value, section=_SETTINGS_SECTION)


def get_assistant_model():
    """Selected voice-assistant persona id (folder name under data/ai/), e.g.
    'Perun' or 'Melitele'. '' means "first available"."""
    return get_setting('assistant_model', '', section=_SETTINGS_SECTION) or ''


def set_assistant_model(model):
    set_setting('assistant_model', model or '', section=_SETTINGS_SECTION)


def get_assistant_hotkey():
    """Global hotkey (normalized 'ctrl+alt+a' form) that launches the voice
    assistant from anywhere. '' = unset."""
    return get_setting('assistant_hotkey', '', section=_SETTINGS_SECTION) or ''


def set_assistant_hotkey(hotkey):
    set_setting('assistant_hotkey', hotkey or '', section=_SETTINGS_SECTION)


def get_assistant_titan_hotkey():
    """Hotkey that launches the assistant, active ONLY while the Titan UI is on.
    '' = unset."""
    return get_setting('assistant_titan_hotkey', '', section=_SETTINGS_SECTION) or ''


def set_assistant_titan_hotkey(hotkey):
    set_setting('assistant_titan_hotkey', hotkey or '', section=_SETTINGS_SECTION)


# Which providers actually expose a text-to-speech API. Anthropic/Claude is
# deliberately absent: Claude has no TTS endpoint yet, so it is not offered.
# (Flip a provider to True here the day it ships one and it appears in the UI.)
_PROVIDER_TTS = {
    'gemini': ('gemini', 'Gemini TTS'),
    'openai': ('openai', 'OpenAI TTS'),
    'anthropic': None,
}


def assistant_tts_options():
    """Ordered [(value, label)] for the assistant text-to-speech choice:
    'Automatic' first (pick the engine that matches the configured API key), then
    each cloud provider that supports TTS (and only if it does), then Titan TTS
    which is always available. Cloud order follows PROVIDERS."""
    opts = [('auto', 'Automatic (match the API key you configured)')]
    for pid, _label in PROVIDERS:
        entry = _PROVIDER_TTS.get(pid)
        if entry:
            opts.append(entry)
    opts.append(('titan', 'Titan TTS'))
    return opts


def get_assistant_tts():
    """The stored assistant text-to-speech CHOICE: 'auto' (default), a provider
    id that supports TTS ('gemini' / 'openai'), or 'titan' (Titan TTS). This is
    the raw preference - call :func:`resolve_assistant_tts` to get the engine to
    actually speak with, which also takes the available API keys into account."""
    valid = [v for v, _l in assistant_tts_options()]
    val = get_setting('assistant_tts', 'auto', section=_SETTINGS_SECTION)
    return val if val in valid else (valid[0] if valid else 'titan')


def set_assistant_tts(engine):
    set_setting('assistant_tts', engine or 'auto', section=_SETTINGS_SECTION)


def tts_providers_with_key():
    """Provider ids that both offer a TTS API and have an API key configured,
    in PROVIDERS order."""
    return [pid for pid, _l in PROVIDERS
            if _PROVIDER_TTS.get(pid) and get_ai_key(pid)]


def resolve_assistant_tts():
    """The engine the assistant should actually speak with ('gemini' / 'openai' /
    'titan'), derived from the stored choice AND the keys that are really set.

    A cloud voice only works if that provider's key is configured, so a mismatch
    (e.g. "OpenAI TTS" selected while only a Gemini key exists) would fail on
    every utterance and fall back to Titan TTS after an error. Instead:

    * 'auto' (default) - use the configured main provider when it can speak,
      otherwise the first TTS-capable provider that has a key, otherwise Titan TTS;
    * an explicit cloud engine - honoured when its key is present, otherwise
      another provider that does have one, otherwise Titan TTS;
    * 'titan' - always honoured (no key needed).
    """
    choice = get_assistant_tts()
    if choice == 'titan':
        return 'titan'
    with_key = tts_providers_with_key()
    if choice != 'auto':
        if get_ai_key(choice):
            return choice
        return with_key[0] if with_key else 'titan'
    main = get_ai_provider()
    if main in with_key:
        return main
    return with_key[0] if with_key else 'titan'


# --------------------------------------------------------------------------- #
# AI OCR (the accessible mimic of an inaccessible app - src/ai/ocr/)
# --------------------------------------------------------------------------- #
def get_ocr_enabled():
    """Master switch for AI OCR. Off by default: it sends pictures of the
    screen to the model, which is a decision the user has to make knowingly."""
    val = get_setting('ocr_enabled', False, section=_SETTINGS_SECTION)
    return str(val).strip().lower() not in ('0', 'false', 'no', 'off', '')


def set_ocr_enabled(enabled):
    set_setting('ocr_enabled', bool(enabled), section=_SETTINGS_SECTION)


def get_ocr_hotkey():
    """Global AI OCR shortcut (normalized 'ctrl+alt+o' form). '' = unset."""
    return get_setting('ocr_hotkey', '', section=_SETTINGS_SECTION) or ''


def set_ocr_hotkey(hotkey):
    set_setting('ocr_hotkey', hotkey or '', section=_SETTINGS_SECTION)


def get_ocr_titan_hotkey():
    """AI OCR shortcut active only while the Titan UI is on. '' = unset."""
    return get_setting('ocr_titan_hotkey', '', section=_SETTINGS_SECTION) or ''


def set_ocr_titan_hotkey(hotkey):
    set_setting('ocr_titan_hotkey', hotkey or '', section=_SETTINGS_SECTION)


OCR_SCOPES = (
    ('window', 'The window in front (recommended)'),
    ('screen', 'The whole screen'),
)


def get_ocr_scope():
    """What a scan looks at: the foreground window (default) or the screen."""
    val = get_setting('ocr_scope', 'window', section=_SETTINGS_SECTION)
    return val if val in dict(OCR_SCOPES) else 'window'


def set_ocr_scope(scope):
    set_setting('ocr_scope', scope if scope in dict(OCR_SCOPES) else 'window',
                section=_SETTINGS_SECTION)


OCR_VIEWS = (
    ('overlay', 'On the real window itself, control by control (recommended)'),
    ('list', 'In a Titan window, as a list to read'),
)


def get_ocr_open_as():
    """What the AI OCR shortcut opens: the overlay, or the reading list.

    The overlay by default. It is what the feature is for - the program the
    user is already in gains an accessible surface where its own controls are,
    and no window of Titan's appears at all. The list is still one keystroke
    away (Escape) and is the better shape for a wall of text, for a window that
    is not on screen, and for anything the overlay could not place.
    """
    value = get_setting('ocr_open_as', 'overlay', section=_SETTINGS_SECTION)
    return value if value in dict(OCR_VIEWS) else 'overlay'


def set_ocr_open_as(view):
    set_setting('ocr_open_as', view if view in dict(OCR_VIEWS) else 'overlay',
                section=_SETTINGS_SECTION)


def get_ocr_live_seconds():
    """Seconds between automatic re-scans in the mimic's live mode; 0 = off.

    Live mode only spends a request when the picture actually changed, but the
    interval is still the ceiling on how much a forgotten window can cost.
    """
    try:
        value = int(get_setting('ocr_live_seconds', 0, section=_SETTINGS_SECTION))
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        return 0
    return max(3, min(600, value))


def set_ocr_live_seconds(seconds):
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        seconds = 0
    set_setting('ocr_live_seconds', max(0, min(600, seconds)),
                section=_SETTINGS_SECTION)


def get_ocr_can_act():
    """Whether Enter in the mimic may really click/type in the target app.

    On by default - a mimic you cannot press anything in is only half the
    feature - but it is the one thing here that touches another program, so it
    is switchable.
    """
    val = get_setting('ocr_can_act', True, section=_SETTINGS_SECTION)
    return str(val).strip().lower() not in ('0', 'false', 'no', 'off')


def set_ocr_can_act(enabled):
    set_setting('ocr_can_act', bool(enabled), section=_SETTINGS_SECTION)


def get_ocr_use_uia():
    """Merge UI Automation geometry into the model's reading (default on).

    Where a control really is on screen is something Windows can answer
    exactly; asking a vision model to guess pixel rectangles is the weakest
    part of the pipeline. When both agree on a control, Windows wins.
    """
    val = get_setting('ocr_use_uia', True, section=_SETTINGS_SECTION)
    return str(val).strip().lower() not in ('0', 'false', 'no', 'off')


def set_ocr_use_uia(enabled):
    set_setting('ocr_use_uia', bool(enabled), section=_SETTINGS_SECTION)


# --------------------------------------------------------------------------- #
# Automatic reminder announcements (tReminder -> assistant)
# --------------------------------------------------------------------------- #
def get_reminder_announce():
    """How due tReminder reminders are announced by Titan itself, even when the
    tReminder window is closed: 'voice' (spoken in the assistant's voice,
    default), 'text' (notification + screen reader / Titan TTS) or 'off'."""
    v = get_setting('reminder_announce', 'voice', section=_SETTINGS_SECTION)
    return v if v in ('off', 'text', 'voice') else 'voice'


def set_reminder_announce(mode):
    set_setting('reminder_announce', mode if mode in ('off', 'text', 'voice')
                else 'voice', section=_SETTINGS_SECTION)


def get_reminder_ai_phrasing():
    """When True (default) the announcement is written by the AI in the
    assistant's own words instead of a fixed template."""
    val = get_setting('reminder_ai_phrasing', True, section=_SETTINGS_SECTION)
    return str(val).strip().lower() not in ('0', 'false', 'no', 'off')


def set_reminder_ai_phrasing(enabled):
    set_setting('reminder_ai_phrasing', bool(enabled), section=_SETTINGS_SECTION)


def get_assistant_dictation():
    """When True, pressing an assistant hotkey while an editable text field is
    focused just DICTATES: the assistant transcribes what you say and types it
    into the field instead of running the command agent. Default on."""
    val = get_setting('assistant_dictation', True, section=_SETTINGS_SECTION)
    return str(val).strip().lower() not in ('0', 'false', 'no', 'off')


def set_assistant_dictation(enabled):
    set_setting('assistant_dictation', bool(enabled), section=_SETTINGS_SECTION)


def get_agent_confirm():
    """Agent confirmation policy: 'tiered' (default; confirm mutating/system
    tools), 'all' (confirm every action) or 'none' (Autonomous: never ask, not
    even for always-confirm tools like run_shell)."""
    v = get_setting('agent_confirm', 'tiered', section=_SETTINGS_SECTION)
    return v if v in ('tiered', 'all', 'none') else 'tiered'


def set_agent_confirm(policy):
    set_setting('agent_confirm', policy, section=_SETTINGS_SECTION)


def is_ai_ready():
    """True if AI features are enabled AND the chosen method is usable
    (API key present for 'api', or the CLI is assumed installed otherwise)."""
    if not is_ai_enabled():
        return False
    if get_ai_method() == 'api':
        return bool(get_ai_key(get_ai_provider()))
    return True


# --------------------------------------------------------------------------- #
# Latest-model resolution (copied verbatim from the proven mod-components impl)
# --------------------------------------------------------------------------- #
def _gemini_version_key(name):
    """Sort key so newer gemini versions rank higher."""
    m = re.search(r'gemini-(\d+)(?:\.(\d+))?', name)
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2) or 0))


def resolve_latest_model(provider, api_key):
    """Query the provider for its newest suitable model. Cached per provider for
    the session; falls back to ``_DEFAULT_MODELS`` on any error."""
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
            from google import genai
            client = genai.Client(api_key=api_key)
            names = []
            for m in client.models.list():
                actions = (getattr(m, 'supported_actions', None)
                           or getattr(m, 'supported_generation_methods', None) or [])
                nm = getattr(m, 'name', '') or ''
                short = nm.split('/')[-1]
                if 'generateContent' in actions and short.startswith('gemini') \
                        and not any(t in short for t in ('vision', 'embedding', 'aqa')):
                    names.append(short)
            if names:
                names.sort(key=_gemini_version_key, reverse=True)
                model = names[0]
    except Exception as e:
        print(f"[ai_provider] could not resolve latest model for {provider}: {e}")
    if not model:
        model = _DEFAULT_MODELS.get(provider, _DEFAULT_MODELS['anthropic'])
    _MODEL_CACHE[provider] = model
    return model


# --------------------------------------------------------------------------- #
# Generation (streaming)
# --------------------------------------------------------------------------- #
def _as_messages(conversation):
    if isinstance(conversation, str):
        return [{"role": "user", "content": conversation}]
    return list(conversation)


def _strip_fences(text):
    text = text.strip()
    if text.startswith('```'):
        lines = text.split('\n')
        if lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith('```'):
            lines = lines[:-1]
        text = '\n'.join(lines)
    return text.strip()


def _import_sdk(provider):
    """Import a provider's SDK, raising a clear, actionable error (not a raw
    ModuleNotFoundError) when it isn't installed so every provider fails gracefully."""
    try:
        if provider == 'anthropic':
            import anthropic
            return anthropic
        if provider == 'openai':
            import openai
            return openai
        if provider == 'gemini':
            from google import genai
            return genai
    except ImportError as e:
        raise RuntimeError(
            f"The {provider_label(provider)} SDK is not installed. Install the AI "
            f"dependencies with: pip install -r requirements.txt") from e
    raise RuntimeError(f"Unsupported provider: {provider}")


def generate(system, conversation, method=None, provider=None, model=None,
             on_chunk=None, max_tokens=8000):
    """Generate text from the model, STREAMING partial output to ``on_chunk``.

    ``conversation`` is a description string or a list of ``{role, content}``
    messages (for multi-turn refinement). ``method`` defaults to the configured
    AI method; ``provider`` to the configured provider (API method only).
    ``on_chunk(delta_str)`` is called on the calling thread for each streamed
    piece -- run :func:`generate` in a worker thread and marshal UI updates with
    ``wx.CallAfter``. Returns the full text (markdown fences stripped). Raises on
    failure (missing SDK/CLI, bad key, network)."""
    method = method or get_ai_method()
    messages = _as_messages(conversation)

    def emit(delta):
        if delta and on_chunk:
            on_chunk(delta)

    if method in ('claude_cli', 'codex'):
        return _strip_fences(_generate_cli(method, system, messages, emit))

    # --- API method -------------------------------------------------------- #
    provider = provider or get_ai_provider()
    api_key = get_ai_key(provider)
    if not api_key:
        raise RuntimeError(f"No API key configured for provider '{provider}'")
    if not model:
        model = (get_setting(provider + '_model', '', section=_SETTINGS_SECTION) or '').strip() or None
    if not model:
        model = resolve_latest_model(provider, api_key)

    parts = []
    if provider == 'anthropic':
        anthropic = _import_sdk('anthropic')
        client = anthropic.Anthropic(api_key=api_key)
        with client.messages.stream(model=model, max_tokens=max_tokens,
                                     system=system, messages=messages) as stream:
            for text in stream.text_stream:
                parts.append(text)
                emit(text)
    elif provider == 'openai':
        openai = _import_sdk('openai')
        client = openai.OpenAI(api_key=api_key)
        stream = client.chat.completions.create(
            model=model, max_tokens=max_tokens, stream=True,
            messages=[{"role": "system", "content": system}] + messages)
        for chunk in stream:
            delta = (chunk.choices[0].delta.content or '') if chunk.choices else ''
            if delta:
                parts.append(delta)
                emit(delta)
    elif provider == 'gemini':
        genai = _import_sdk('gemini')
        from google.genai import types
        client = genai.Client(api_key=api_key)
        contents = [
            types.Content(role='model' if m['role'] == 'assistant' else 'user',
                          parts=[types.Part(text=m['content'])])
            for m in messages
        ]
        stream = client.models.generate_content_stream(
            model=model, contents=contents,
            config=types.GenerateContentConfig(system_instruction=system))
        for chunk in stream:
            delta = getattr(chunk, 'text', '') or ''
            if delta:
                parts.append(delta)
                emit(delta)
    else:
        raise RuntimeError(f"Unsupported provider: {provider}")

    return _strip_fences(''.join(parts))


# Providers whose API can be shown a picture. All three current ones can; a
# provider that could not would simply be left out here.
VISION_PROVIDERS = ('gemini', 'anthropic', 'openai')


def resolve_vision_provider():
    """Which provider AI OCR should use - resolved exactly as the assistant is.

    The voice assistant never asks the user to configure it twice: it ignores
    the "communication method" radio (which is about the *creation kit*, and
    where a CLI cannot carry a picture anyway) and goes straight to the API key
    it needs. AI OCR does the same, so a user whose assistant already works has
    nothing further to set up.

    Order: the assistant's own provider, then the main configured provider,
    then any provider that has a key at all. '' when none has one.
    """
    if get_ai_key(ASSISTANT_PROVIDER):
        return ASSISTANT_PROVIDER
    main = get_ai_provider()
    if main in VISION_PROVIDERS and get_ai_key(main):
        return main
    for provider in VISION_PROVIDERS:
        if get_ai_key(provider):
            return provider
    return ''


def generate_vision(system, prompt, images, provider=None, model=None,
                    max_tokens=8000, temperature=0.0):
    """One-shot VISION call: send ``images`` plus ``prompt``, get text back.

    ``images`` is a list of raw PNG ``bytes``. Unlike :func:`generate` this does
    not stream, and the provider defaults to :func:`resolve_vision_provider` -
    the assistant's configuration - rather than to the creation kit's method
    radio, which has nothing to say about looking at a picture.

    Kept here rather than in the caller because the three SDKs disagree about
    everything: the block shape, the field names and how the system prompt is
    passed. ``temperature`` defaults to 0 - reading a screen is a transcription
    task, and creativity in it is called hallucination.
    """
    provider = provider or resolve_vision_provider() or get_ai_provider()
    api_key = get_ai_key(provider)
    if not api_key:
        raise RuntimeError(f"No API key configured for provider '{provider}'")
    if not model:
        model = (get_setting(provider + '_model', '',
                             section=_SETTINGS_SECTION) or '').strip() or None
    if not model:
        model = resolve_latest_model(provider, api_key)

    pngs = [png for png in (images or []) if png]
    if not pngs:
        raise RuntimeError("No image to look at")

    if provider == 'anthropic':
        anthropic = _import_sdk('anthropic')
        client = anthropic.Anthropic(api_key=api_key)
        blocks = [{'type': 'image',
                   'source': {'type': 'base64', 'media_type': 'image/png',
                              'data': base64.b64encode(png).decode('ascii')}}
                  for png in pngs]
        blocks.append({'type': 'text', 'text': prompt})
        resp = client.messages.create(
            model=model, system=system, max_tokens=max_tokens,
            temperature=temperature,
            messages=[{'role': 'user', 'content': blocks}])
        return _strip_fences(''.join(getattr(b, 'text', '') for b in resp.content
                                     if getattr(b, 'type', '') == 'text'))

    if provider == 'openai':
        openai = _import_sdk('openai')
        client = openai.OpenAI(api_key=api_key)
        content = [{'type': 'text', 'text': prompt}]
        for png in pngs:
            b64 = base64.b64encode(png).decode('ascii')
            content.append({'type': 'image_url',
                            'image_url': {'url': 'data:image/png;base64,' + b64,
                                          'detail': 'high'}})
        resp = client.chat.completions.create(
            model=model, max_tokens=max_tokens, temperature=temperature,
            messages=[{'role': 'system', 'content': system},
                      {'role': 'user', 'content': content}])
        return _strip_fences(resp.choices[0].message.content or '')

    if provider == 'gemini':
        genai = _import_sdk('gemini')
        from google.genai import types
        client = genai.Client(api_key=api_key)
        parts = [types.Part(inline_data=types.Blob(mime_type='image/png', data=png))
                 for png in pngs]
        parts.append(types.Part(text=prompt))
        resp = client.models.generate_content(
            model=model, contents=[types.Content(role='user', parts=parts)],
            config=types.GenerateContentConfig(system_instruction=system,
                                               temperature=temperature,
                                               max_output_tokens=max_tokens))
        return _strip_fences(getattr(resp, 'text', '') or '')

    raise RuntimeError(f"Unsupported provider: {provider}")


def vision_unavailable_reason():
    """Why a vision call cannot run right now, or '' when it can.

    Returns an untranslated English sentence; the UI wraps it in ``_()``.
    """
    if not is_ai_enabled():
        return "AI features are switched off in Settings, AI features."
    if not resolve_vision_provider():
        return ("No API key is configured. AI OCR uses the same key as the AI "
                "Assistant - add one in Settings, AI features (a "
                f"{provider_label(ASSISTANT_PROVIDER)} key is what the "
                "assistant uses).")
    return ''


def _flatten_conversation(system, messages):
    """Collapse system + multi-turn messages into one prompt for the CLI tools,
    which take a single prompt string."""
    buf = [system, ""]
    for m in messages:
        who = 'ASSISTANT' if m['role'] == 'assistant' else 'USER'
        buf.append(f"[{who}]\n{m['content']}\n")
    buf.append("[ASSISTANT]")
    return '\n'.join(buf)


def _cli_command(method):
    """argv prefix for the chosen CLI, reading the prompt from stdin and
    printing the answer non-interactively. Overridable via settings
    ``ai.claude_cli_cmd`` / ``ai.codex_cmd``.

    Defaults:
    - Claude CLI: ``claude --print`` -- with no prompt argument, ``--print``
      reads the prompt from stdin and prints the plain-text answer.
    - Codex CLI:  ``codex exec -`` -- ``exec`` runs headless (non-interactive)
      and the ``-`` positional tells Codex to read the prompt from stdin.

    Both CLIs must be installed AND already authenticated (they use their own
    stored credentials, not Titan's API key); Titan only pipes the prompt in and
    reads the answer out."""
    if method == 'claude_cli':
        override = (get_setting('claude_cli_cmd', '', section=_SETTINGS_SECTION) or '').strip()
        return override.split() if override else ['claude', '--print']
    override = (get_setting('codex_cmd', '', section=_SETTINGS_SECTION) or '').strip()
    return override.split() if override else ['codex', 'exec', '-']


def _cli_search_dirs():
    """Extra directories the CLI installers use. A compiled, GUI-launched Titan
    inherits the PATH of whatever started it (Explorer, autostart), which often
    lacks the per-user npm / native-installer directories a terminal has."""
    home = os.path.expanduser('~')
    dirs = [
        os.path.join(home, '.local', 'bin'),        # native claude installer
        os.path.join(home, '.npm-global', 'bin'),
        os.path.join(home, '.bun', 'bin'),
        os.path.join(home, '.yarn', 'bin'),
    ]
    if sys.platform == 'win32':
        appdata = os.environ.get('APPDATA', '')
        localapp = os.environ.get('LOCALAPPDATA', '')
        if appdata:
            dirs.append(os.path.join(appdata, 'npm'))
        if localapp:
            dirs.append(os.path.join(localapp, 'Yarn', 'bin'))
        dirs.append(os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'nodejs'))
    else:
        dirs.extend(['/usr/local/bin', '/opt/homebrew/bin'])
    return [d for d in dirs if d and os.path.isdir(d)]


def resolve_cli_executable(name):
    """Full path to a CLI executable, or None when it cannot be found.

    ``shutil.which`` honours PATHEXT, so this also finds the ``.cmd``/``.bat``
    shims npm installs on Windows -- ``subprocess`` cannot locate those on its
    own (CreateProcess only ever appends ``.exe``), which is why an installed
    ``codex`` used to be reported as "not found"."""
    if os.path.sep in name or (os.path.altsep and os.path.altsep in name):
        return name if os.path.exists(name) else None
    found = shutil.which(name)
    if found:
        return found
    for d in _cli_search_dirs():
        found = shutil.which(name, path=d)
        if found:
            return found
    return None


def is_cli_available(method):
    """True if the CLI backing ``method`` ('claude_cli' / 'codex') is installed."""
    try:
        argv = _cli_command(method)
    except Exception:
        return False
    return bool(argv) and resolve_cli_executable(argv[0]) is not None


def _cli_argv(method):
    """Ready-to-run argv for ``method``: absolute executable path, wrapped in
    ``cmd /c`` when it resolves to a Windows batch shim (``.cmd``/``.bat``),
    which CreateProcess cannot execute directly."""
    argv = list(_cli_command(method))
    if not argv:
        raise RuntimeError("No CLI command configured. Set one in Settings, AI features.")
    exe = resolve_cli_executable(argv[0])
    if not exe:
        raise RuntimeError(
            f"CLI '{argv[0]}' not found. Install it or set a custom command in "
            f"Settings, AI features.")
    argv[0] = exe
    if sys.platform == 'win32' and exe.lower().endswith(('.cmd', '.bat')):
        argv = [os.environ.get('COMSPEC') or 'cmd.exe', '/c'] + argv
    return argv


def _generate_cli(method, system, messages, emit):
    import threading
    name = _cli_command(method)[0]  # what the user configured, for messages
    argv = _cli_argv(method)
    prompt = _flatten_conversation(system, messages)
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding='utf-8',
            errors='replace',
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0))
    except OSError as e:
        raise RuntimeError(
            f"CLI '{name}' could not be started: {e}. Install it or set a "
            f"custom command in Settings, AI features.")

    # Feed the prompt on a background thread so a large prompt (full docs +
    # multi-turn auto-fix history can exceed the OS pipe buffer) can never
    # deadlock against us reading stdout.
    def _feed():
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except Exception:
            pass
    feeder = threading.Thread(target=_feed, daemon=True)
    feeder.start()

    # Continuously drain stderr on its own thread; otherwise a chatty CLI can
    # fill the stderr pipe and block while we are busy reading stdout.
    err_parts = []

    def _drain_err():
        try:
            for line in iter(proc.stderr.readline, ''):
                err_parts.append(line)
        except Exception:
            pass
    draining = threading.Thread(target=_drain_err, daemon=True)
    draining.start()

    parts = []
    for line in iter(proc.stdout.readline, ''):
        parts.append(line)
        emit(line)
    proc.stdout.close()
    code = proc.wait()
    feeder.join(timeout=5)
    draining.join(timeout=5)
    err = ''.join(err_parts)
    if code != 0:
        raise RuntimeError(f"CLI '{name}' exited with code {code}: {err.strip()[:500]}")
    out = ''.join(parts)
    if not out.strip():
        raise RuntimeError(
            f"CLI '{name}' produced no output. Make sure it is installed and "
            f"logged in (try running it once in a terminal). "
            + (f"Details: {err.strip()[:300]}" if err.strip() else ""))
    return out
