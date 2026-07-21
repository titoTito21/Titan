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

API keys are stored ENCRYPTED at rest via :mod:`src.ai.secret_store`
(DPAPI on Windows), under settings section ``ai`` as ``api_key_<provider>``.
Legacy plaintext keys from the moderator-component creator
(``titannet_component_ai_key_<provider>``) are still read for back-compat.
"""

import re
import subprocess
import sys

from src.settings.settings import get_setting, set_setting
from src.ai.secret_store import encrypt_secret, decrypt_secret

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


def get_agent_confirm():
    """Agent confirmation policy: 'tiered' (default; confirm mutating/system
    tools), 'all' (confirm every action) or 'none' (auto, except always-confirm
    tools like run_shell)."""
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
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        with client.messages.stream(model=model, max_tokens=max_tokens,
                                     system=system, messages=messages) as stream:
            for text in stream.text_stream:
                parts.append(text)
                emit(text)
    elif provider == 'openai':
        import openai
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
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        gmodel = genai.GenerativeModel(model, system_instruction=system)
        contents = [
            {'role': 'model' if m['role'] == 'assistant' else 'user',
             'parts': [m['content']]}
            for m in messages
        ]
        for chunk in gmodel.generate_content(contents, stream=True):
            delta = getattr(chunk, 'text', '') or ''
            if delta:
                parts.append(delta)
                emit(delta)
    else:
        raise RuntimeError(f"Unsupported provider: {provider}")

    return _strip_fences(''.join(parts))


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
    ``ai.claude_cli_cmd`` / ``ai.codex_cmd``."""
    if method == 'claude_cli':
        override = (get_setting('claude_cli_cmd', '', section=_SETTINGS_SECTION) or '').strip()
        return override.split() if override else ['claude', '--print']
    override = (get_setting('codex_cmd', '', section=_SETTINGS_SECTION) or '').strip()
    return override.split() if override else ['codex', 'exec', '-']


def _generate_cli(method, system, messages, emit):
    argv = _cli_command(method)
    prompt = _flatten_conversation(system, messages)
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding='utf-8',
            errors='replace',
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0))
    except FileNotFoundError:
        raise RuntimeError(
            f"CLI '{argv[0]}' not found. Install it or set a custom command in "
            f"Settings, AI features.")
    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
    except Exception:
        pass
    parts = []
    for line in iter(proc.stdout.readline, ''):
        parts.append(line)
        emit(line)
    proc.stdout.close()
    code = proc.wait()
    if code != 0:
        err = proc.stderr.read() if proc.stderr else ''
        raise RuntimeError(f"CLI '{argv[0]}' exited with code {code}: {err.strip()[:500]}")
    return ''.join(parts)
