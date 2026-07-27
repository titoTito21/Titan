"""AI creation kit: generate a complete Titan add-on (app, game, component,
launcher, IM module, gamepad mode, TTS engine, widget, statusbar applet or
language) from a natural-language description, using the shared multi-provider
AI layer (:mod:`src.ai.ai_provider`).

Flow (see :class:`AICreationWizardDialog`): the user describes the add-on -> the
model STREAMS a set of files (live progress, no frozen dialog) -> a preview lets
the user inspect every generated file -> on accept the user is asked whether to
save it as a plain folder or pack it into a single ``.TCA``/``.TCD`` file, and
it is written into the per-user data overlay.

The model is grounded on a REAL existing add-on of the same kind (read from the
bundled ``data/<subdir>/``) rather than a hand-maintained format description, so
each kind's manifest and layout stay authoritative without duplication here.
"""

import ast
import json
import math
import os
import re
import shutil
import tempfile
import threading
import time
import traceback

import wx

from src.ai import ai_provider
from src.ai import creation_docs
from src.ai import web_search
from src.titan_core import titan_package
from src import platform_utils
from src.titan_core.translation import set_language
from src.settings.settings import get_setting

try:
    from src.titan_core.sound import play_sound
except Exception:  # pragma: no cover - sound is optional
    def play_sound(*_a, **_k):
        pass

_ = set_language(get_setting('language', 'pl'))


def _speak(text):
    """Announce ``text`` (Titan TTS when enabled, else screen reader / notification
    voice; best effort, never raises).

    Every milestone of a generation run goes through here (Planning, Plan ready,
    Generating, questions, Done, failures, Saved, Cancelled), so this is also
    where they are recorded in the AI notifications buffer - a spoken milestone
    can then be reviewed afterwards with the buffer keys.
    """
    from src.ai.ai_speech import speak
    speak(text)
    try:
        from src.buffers import ai_buffer
        ai_buffer.push_notice(text, author=_("Creation kit"))
    except Exception as e:
        print(f"[AICreationKit] buffer feed error: {e}")


# --------------------------------------------------------------------------- #
# Kind catalogue
# --------------------------------------------------------------------------- #
# Each kind: id (matches titan_package.NAME_TO_KIND for packageable kinds),
# display label, data subdir, the acceptable manifest/entry filenames (the first
# is the primary one; used for prompt guidance and validation), and whether it
# can be packed into a .TCA/.TCD.
#
# IMPORTANT: these manifest names are the REAL ones used by each kind's manager
# (verified against data/<subdir>/ and the programming guides). Getting them
# wrong makes the model emit an add-on the host cannot load.
KINDS = [
    {'id': 'app',              'label': _("Application"),      'subdir': 'applications',      'manifests': ('__app.TCE',),                        'package': True},
    {'id': 'game',             'label': _("Game"),            'subdir': 'games',             'manifests': ('__game.TCE',),                       'package': True},
    {'id': 'component',        'label': _("Component"),       'subdir': 'components',        'manifests': ('__component__.TCE',),                'package': True},
    {'id': 'launcher',         'label': _("Launcher"),        'subdir': 'launchers',         'manifests': ('__launcher__.TCE',),                'package': True},
    {'id': 'im_module',        'label': _("IM Module"),       'subdir': 'titanIM_modules',   'manifests': ('__im.TCE',),                        'package': True},
    {'id': 'gamepad_mode',     'label': _("Gamepad Mode"),    'subdir': 'gamepad/modes',     'manifests': ('__mode__.TCE',),                    'package': True},
    {'id': 'tts_engine',       'label': _("TTS Engine"),      'subdir': 'titantts engines',  'manifests': ('__engine__.TCE',),                  'package': True},
    {'id': 'widget',           'label': _("Widget"),          'subdir': 'applets',           'manifests': ('applet.json', 'init.py', 'main.py'), 'package': True},
    {'id': 'statusbar_applet', 'label': _("Statusbar Applet"),'subdir': 'statusbar_applets', 'manifests': ('applet.json',),                     'package': True},
    {'id': 'language',         'label': _("Language"),        'subdir': None,                'manifests': (),                                   'package': False},
]

_KIND_BY_ID = {k['id']: k for k in KINDS}


def primary_manifest(kind):
    """The main manifest/entry filename for a kind, or None (e.g. language)."""
    manifests = kind.get('manifests') or ()
    return manifests[0] if manifests else None

# Line marker that delimits generated files. Chosen to be extremely unlikely to
# appear at the start of a real source/manifest/po line.
_FILE_MARKER = re.compile(r'^@@FILE:\s*(.+?)\s*$')

# How many corrective round-trips the auto-fix loop may make after a generation
# that fails static checks (Python syntax / JSON validity).
_MAX_AUTOFIX_ROUNDS = 2
# Number of web results pulled in when "search the web" is enabled.
_WEB_SEARCH_RESULTS = 5

_MAX_EXAMPLE_FILES = 6
_MAX_EXAMPLE_FILE_CHARS = 4000
_MAX_EXAMPLE_TOTAL_CHARS = 16000
_TEXT_EXTS = ('.tce', '.py', '.txt', '.po', '.ini', '.json', '.md', '.cfg')


def get_kind(kind_id):
    return _KIND_BY_ID.get(kind_id)


# --------------------------------------------------------------------------- #
# Reference example (grounds the model on a real add-on of this kind)
# --------------------------------------------------------------------------- #
def _example_root(kind):
    if kind['id'] == 'language':
        return platform_utils.get_resource_path('languages')
    return platform_utils.get_data_path(kind['subdir'])


def _read_example_files(kind):
    """Return [(relpath, content), ...] from one existing add-on of this kind,
    capped in count/size. Empty list if nothing suitable is found."""
    root = _example_root(kind)
    if not root or not os.path.isdir(root):
        return []
    # Pick a source: a subdirectory (folder add-on) whose tree has a manifest,
    # else (languages) just gather a couple of small text files at the root.
    candidates = []
    try:
        for name in sorted(os.listdir(root)):
            full = os.path.join(root, name)
            if os.path.isdir(full):
                candidates.append(full)
    except OSError:
        return []

    def _gather(base):
        out, total = [], 0
        for dirpath, _dirs, files in os.walk(base):
            for fn in sorted(files):
                if not fn.lower().endswith(_TEXT_EXTS):
                    continue
                fp = os.path.join(dirpath, fn)
                rel = os.path.relpath(fp, base).replace(os.sep, '/')
                try:
                    with open(fp, 'r', encoding='utf-8', errors='replace') as fh:
                        content = fh.read(_MAX_EXAMPLE_FILE_CHARS + 1)
                except OSError:
                    continue
                if len(content) > _MAX_EXAMPLE_FILE_CHARS:
                    content = content[:_MAX_EXAMPLE_FILE_CHARS] + "\n... (truncated)\n"
                out.append((rel, content))
                total += len(content)
                if len(out) >= _MAX_EXAMPLE_FILES or total >= _MAX_EXAMPLE_TOTAL_CHARS:
                    return out
        return out

    for base in candidates:
        files = _gather(base)
        if files:
            return files
    # Languages: fall back to loose files at the root.
    if kind['id'] == 'language':
        return _gather(root)
    return []


def _manifest_line(kind):
    manifest = primary_manifest(kind)
    if not manifest:
        return ("- Follow the file naming and format shown in the reference "
                "example and the guide.")
    manifests = kind.get('manifests') or ()
    if len(manifests) > 1:
        allowed = ", ".join(f"'{m}'" for m in manifests)
        return (f"- Include the manifest/entry file the guide requires "
                f"(one of {allowed}); name it EXACTLY, do not invent a new name.")
    return (f"- Include the manifest file named EXACTLY '{manifest}', as the "
            f"guide and reference example show. Do NOT invent a different name.")


def _docs_and_example_block(kind):
    """The reference material appended to every prompt: the kind's full guide,
    the shared core API, and a real example add-on of this kind."""
    parts = []
    docs = creation_docs.build_docs_block(kind['id'])
    if docs:
        parts.append("===== TITAN DOCUMENTATION (authoritative) =====")
        parts.append(docs)
    parts.append("")
    parts.append(f"===== REFERENCE EXAMPLE (an existing Titan {kind['label']}) =====")
    example = _read_example_files(kind)
    if example:
        for rel, content in example:
            parts.append(f"@@FILE: {rel}")
            parts.append(content.rstrip('\n'))
    else:
        parts.append("(no reference example available; use the documentation "
                     "above and standard Titan add-on conventions)")
    return '\n'.join(parts)


def _questions_protocol_block(kind):
    """Instructions that let the model PAUSE generation and ask the user
    structured questions (rendered by Titan as a GUI wizard) before it writes
    any files. Mirrors Titan's own 'Create {kind} Wizard' setup flow."""
    return '\n'.join([
        "ASKING QUESTIONS (interactive wizard):",
        "- If ANYTHING about the request is unclear or under-specified, do NOT "
        "guess. FIRST ask the user, exactly like Titan's own setup wizard for "
        "this add-on.",
        "- To ask, output ONLY a JSON object of questions wrapped between a line "
        f"'{_QJSON_START}' and a line '{_QJSON_END}', and NOTHING else (no files, "
        "no prose). Titan will show the user a GUI wizard and send you their "
        "answers, then you continue.",
        "- Ask the standard wizard details for this kind (for example: display "
        "names, a short id/shortname, an optional description, the entry point, "
        "and the key feature/behaviour/layout choices), plus anything specific "
        "to this request. Keep it to the few questions that actually matter.",
        "- The questions JSON schema is:",
        '  {"questions": [',
        '    {"id": "name_en", "text": "English name?", "type": "text",',
        '     "default": ""},',
        '    {"id": "layout", "text": "Which layout?", "type": "choice",',
        '     "options": ["List", "Grid"], "default": "List"},',
        '    {"id": "features", "text": "Which features?", "type": "multichoice",',
        '     "options": ["Sound", "Notifications"]},',
        '    {"id": "settings", "text": "Include settings?", "type": "boolean",',
        '     "default": true}',
        '  ]}',
        f"- 'type' is one of: {', '.join(_QUESTION_TYPES)}; ask at most "
        f"{_MAX_QUESTIONS}. 'choice'/'multichoice' need an 'options' list.",
        "- Once the request is clear (either originally or after answers), STOP "
        "asking and output the files in the strict format below.",
        "",
    ])


def build_system_prompt(kind, extra_context=None, allow_questions=True):
    """System prompt for the file-generation phase. ``extra_context`` (e.g. web
    search results) is appended verbatim when provided. When ``allow_questions``
    is set, the model may pause to ask the user structured questions (shown as a
    GUI wizard) before writing files."""
    prompt = [
        f"You are the Titan add-on creator. You generate a complete, working "
        f"Titan {kind['label']} as a set of files. You have the full Titan "
        f"programming documentation below; follow it exactly.",
        "",
    ]
    if allow_questions:
        prompt.append(_questions_protocol_block(kind))
    prompt += [
        "OUTPUT FORMAT (STRICT):",
        "- Output ONLY file blocks. Immediately before each file, emit a line "
        "that is EXACTLY: @@FILE: <relative/path>",
        "- Then the raw file content on the following lines.",
        "- Do NOT wrap file content in markdown code fences.",
        "- Do NOT write any commentary before, between, or after the files.",
        "- Use forward slashes in paths; keep every path relative to the "
        "add-on root.",
        "",
        "REQUIREMENTS:",
        _manifest_line(kind),
        "- The code MUST be valid Python with no syntax errors and must import "
        "cleanly. Any manifest JSON must be valid JSON.",
        "- All user-facing UI text and messages MUST be in English. Use the "
        "gettext function _() for translatable strings wherever the guide and "
        "reference example do.",
        "- Never use emojis in user-facing text or notifications.",
        "- Follow the structure, required entry-point functions, manifest keys "
        "and conventions from the documentation and reference example below.",
        "- Make the code self-contained and runnable; the entry point named in "
        "the manifest/guide must exist and have the exact expected signature.",
        "- Wrap risky work in try/except so a failure never crashes the host.",
        "",
    ]
    if extra_context:
        prompt.append(extra_context)
        prompt.append("")
    prompt.append(_docs_and_example_block(kind))
    return '\n'.join(prompt)


def build_plan_prompt(kind, extra_context=None):
    """System prompt for the PLANNING phase: the model asks clarifying questions
    and proposes a build plan (a wizard), but writes NO files yet."""
    prompt = [
        f"You are the Titan add-on architect. The user wants to create a Titan "
        f"{kind['label']}. Your job in THIS step is to plan it, not to write "
        f"the files yet.",
        "",
        "Respond in plain text (no code, no @@FILE blocks) with exactly these "
        "two sections:",
        "",
        "QUESTIONS:",
        "- Up to 5 short, numbered clarifying questions about anything "
        "ambiguous (features, behaviour, options). If the request is already "
        "clear, write 'None'.",
        "",
        "PLAN:",
        "- A concise, numbered build plan: the exact files you will create "
        "(with their correct manifest/entry filenames from the documentation), "
        "what each file does, the entry-point functions required by this kind, "
        "and the Titan APIs you will use.",
        "",
        "Keep it brief and concrete. Base every filename and API on the Titan "
        "documentation and reference example below - do not invent names.",
        "",
    ]
    if extra_context:
        prompt.append(extra_context)
        prompt.append("")
    prompt.append(_docs_and_example_block(kind))
    return '\n'.join(prompt)


# --------------------------------------------------------------------------- #
# Interactive questionnaire (structured questions -> GUI wizard -> answers)
# --------------------------------------------------------------------------- #
# The model returns a machine-readable set of questions which the app renders as
# an accessible GUI wizard (see :class:`QuestionnaireDialog`); the collected
# answers are folded back into the conversation before generation.
_MAX_QUESTIONS = 8
# How many times the model may pause to ask the user questions during a single
# generation before we insist it just build with its best judgement.
_MAX_QUESTION_ROUNDS = 3
_QUESTION_TYPES = ('text', 'choice', 'multichoice', 'boolean')
# Delimiters the model wraps the JSON in, so we can extract it even if the model
# adds stray prose despite instructions.
_QJSON_START = '@@QUESTIONS_JSON'
_QJSON_END = '@@END_QUESTIONS_JSON'


def build_questions_prompt(kind, extra_context=None):
    """System prompt for the INTERVIEW phase: the model produces a small set of
    STRUCTURED clarifying questions as JSON (rendered later as a GUI wizard). It
    writes no plan and no files here."""
    prompt = [
        f"You are the Titan add-on architect interviewing the user before "
        f"building a Titan {kind['label']}. Ask only what you genuinely need to "
        f"build the best add-on: features, behaviour, layout, options, wording.",
        "",
        "Return ONLY a JSON object describing your questions, wrapped exactly "
        f"between a line '{_QJSON_START}' and a line '{_QJSON_END}'. No prose, "
        "no markdown, no code fences.",
        "",
        "The JSON schema is:",
        '{"questions": [',
        '  {"id": "short_key", "text": "the question?", "type": "text",',
        '   "multiline": false, "default": ""},',
        '  {"id": "layout", "text": "Which layout?", "type": "choice",',
        '   "options": ["List", "Grid"], "default": "List"},',
        '  {"id": "features", "text": "Which features?", "type": "multichoice",',
        '   "options": ["Sound", "Notifications"], "default": []},',
        '  {"id": "settings", "text": "Include a settings page?",',
        '   "type": "boolean", "default": true}',
        ']}',
        "",
        "RULES:",
        f"- Ask AT MOST {_MAX_QUESTIONS} questions; fewer is better. If the "
        "request is already fully clear, return {\"questions\": []}.",
        f"- 'type' must be one of: {', '.join(_QUESTION_TYPES)}.",
        "- 'choice'/'multichoice' MUST include a non-empty 'options' list.",
        "- 'text' may set 'multiline': true for long free-form answers.",
        "- Every question needs a unique 'id' and a clear 'text'. Provide a "
        "sensible 'default' whenever you can.",
        "- Questions must be answerable by a non-programmer; do not ask about "
        "file names, code, or Titan internals.",
        "",
    ]
    if extra_context:
        prompt.append(extra_context)
        prompt.append("")
    prompt.append(_docs_and_example_block(kind))
    return '\n'.join(prompt)


def looks_like_questions(text):
    """True if a generation response is a request for clarification (a questions
    block) rather than generated files."""
    if not text:
        return False
    return _QJSON_START in text and '@@FILE:' not in text


def parse_questions(text):
    """Extract the questions list from a model response. Tolerant of stray text,
    code fences, and the delimiter lines. Returns a list of normalised question
    dicts (possibly empty). Raises ValueError if no JSON object can be found."""
    if not text:
        return []
    blob = text
    # Prefer the delimited region if present.
    if _QJSON_START in blob:
        blob = blob.split(_QJSON_START, 1)[1]
    if _QJSON_END in blob:
        blob = blob.split(_QJSON_END, 1)[0]
    blob = blob.strip()
    # Strip a leading/trailing markdown code fence if the model added one.
    blob = re.sub(r'^```[a-zA-Z]*\n', '', blob)
    blob = re.sub(r'\n```$', '', blob).strip()
    # Fall back to the first {...} span.
    if not blob.startswith('{'):
        start = blob.find('{')
        end = blob.rfind('}')
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in the model's response.")
        blob = blob[start:end + 1]
    data = json.loads(blob)
    raw = data.get('questions', []) if isinstance(data, dict) else []
    return _normalise_questions(raw)


def _normalise_questions(raw):
    """Coerce a raw questions list into safe, well-formed dicts. Malformed
    entries are dropped rather than raising."""
    out = []
    seen_ids = set()
    for i, q in enumerate(raw):
        if not isinstance(q, dict):
            continue
        text = str(q.get('text', '')).strip()
        if not text:
            continue
        qtype = str(q.get('type', 'text')).strip().lower()
        if qtype not in _QUESTION_TYPES:
            qtype = 'text'
        qid = str(q.get('id') or f"q{i + 1}").strip() or f"q{i + 1}"
        if qid in seen_ids:
            qid = f"{qid}_{i + 1}"
        seen_ids.add(qid)
        options = []
        if qtype in ('choice', 'multichoice'):
            options = [str(o).strip() for o in q.get('options', [])
                       if str(o).strip()]
            if not options:
                # A choice with no options is useless; degrade to free text.
                qtype = 'text'
        out.append({
            'id': qid,
            'text': text,
            'type': qtype,
            'options': options,
            'multiline': bool(q.get('multiline', False)),
            'default': q.get('default'),
        })
        if len(out) >= _MAX_QUESTIONS:
            break
    return out


def format_answers_for_prompt(questions, answers):
    """Build the user-turn message that carries the questionnaire answers into
    the generation conversation. ``answers`` maps question id -> answer string."""
    lines = ["Here are my answers to your questions. Use them to build the "
             "add-on exactly as I have specified:", ""]
    for q in questions:
        ans = answers.get(q['id'], '')
        if isinstance(ans, (list, tuple)):
            ans = ", ".join(str(a) for a in ans)
        ans = str(ans).strip()
        if not ans:
            ans = "(no preference - use your best judgement)"
        lines.append(f"- {q['text']}")
        lines.append(f"  Answer: {ans}")
    lines.append("")
    lines.append("Now generate the complete add-on accordingly.")
    return '\n'.join(lines)


# --------------------------------------------------------------------------- #
# Static checking (drives the auto-fix loop)
# --------------------------------------------------------------------------- #
def static_check(files):
    """Return a list of human-readable problems found by cheap static analysis:
    Python syntax errors (via :func:`ast.parse`) and invalid JSON manifests.
    Empty list means the files pass these checks."""
    problems = []
    for path, content in files.items():
        low = path.lower()
        if low.endswith('.py'):
            try:
                ast.parse(content, filename=path)
            except SyntaxError as e:
                where = f"line {e.lineno}" if e.lineno else "?"
                problems.append(f"{path}: SyntaxError at {where}: {e.msg}")
            except Exception as e:  # pragma: no cover - defensive
                problems.append(f"{path}: could not parse ({e})")
        elif low.endswith('.json'):
            try:
                json.loads(content)
            except Exception as e:
                problems.append(f"{path}: invalid JSON ({e})")
    return problems


def build_fix_message(problems):
    """A user-turn message asking the model to fix the reported problems and
    re-emit ALL files."""
    listing = "\n".join(f"- {p}" for p in problems)
    return (
        "The files you generated have the following problems:\n"
        f"{listing}\n\n"
        "Fix every problem and output the COMPLETE corrected add-on again, "
        "using the exact same strict @@FILE format. Re-emit every file (not "
        "just the changed ones). Do not add any commentary.")


# --------------------------------------------------------------------------- #
# Multi-file parsing
# --------------------------------------------------------------------------- #
def parse_files(text):
    """Parse a model response into an ordered dict {relpath: content}. Content
    before the first @@FILE marker is ignored (stray preamble)."""
    files = {}
    current = None
    lines = []

    def _flush():
        if current is not None:
            files[current] = '\n'.join(lines).strip('\n') + '\n'

    for line in text.split('\n'):
        m = _FILE_MARKER.match(line)
        if m:
            _flush()
            current = _sanitize_relpath(m.group(1))
            lines = []
        elif current is not None:
            lines.append(line)
    _flush()
    return files


def _sanitize_relpath(rel):
    """Normalise a model-provided path and refuse traversal/absolute paths."""
    rel = rel.strip().strip('"').replace('\\', '/')
    parts = [p for p in rel.split('/') if p not in ('', '.', '..')]
    return '/'.join(parts)


def normalize_addon_paths(kind, files):
    """Flatten a generated add-on so its manifest sits at the ROOT.

    Models sometimes wrap every file under a single top-level folder (e.g.
    ``mywidget/applet.json`` instead of ``applet.json``). That is fine for a
    directory the user drops in themselves, but it breaks BOTH folder-save (we
    already create the name directory) and packaging (the package payload root
    IS the add-on root) -- the manager then cannot find the manifest and reports
    it missing. If the primary manifest lives under a common prefix shared by
    every file, strip that prefix. Kinds without a manifest (languages, whose
    locale directory is meaningful) are returned unchanged.

    Returns a new ordered dict; the input is not mutated."""
    manifests = kind.get('manifests') or ()
    if not manifests or not files:
        return files
    # Already at root? Nothing to do.
    if any(os.path.dirname(p) == '' and os.path.basename(p) in manifests
           for p in files):
        return files
    # Find the manifest and its directory prefix.
    manifest_path = next(
        (p for p in files if os.path.basename(p) in manifests), None)
    if not manifest_path:
        return files
    prefix = os.path.dirname(manifest_path)
    if not prefix:
        return files
    prefix += '/'
    # Only strip if EVERY file lives under that prefix (otherwise we'd drop
    # siblings that belong at the real root).
    if not all(p.startswith(prefix) for p in files):
        return files
    out = {}
    for p, content in files.items():
        out[p[len(prefix):]] = content
    return out


def validate_files(kind, files):
    """Return (ok, message). Lenient: needs at least one non-empty file, and —
    when the kind has known manifest/entry names — one of them to be present."""
    if not files:
        return False, _("The model returned no files.")
    if not any(v.strip() for v in files.values()):
        return False, _("The generated files are empty.")
    manifests = kind.get('manifests') or ()
    if manifests and not any(
            os.path.basename(p) in manifests for p in files):
        return False, _("The manifest file {name} is missing.").format(
            name=" / ".join(manifests))
    return True, ''


def _derive_name(kind, files):
    """Best-effort add-on folder name from the manifest 'shortname' key, else
    the first path component, else a timestamp."""
    manifests = kind.get('manifests') or ()
    for path, content in files.items():
        if manifests and os.path.basename(path) in manifests:
            m = re.search(r'^\s*shortname\s*=\s*"?([^"\r\n]+)"?', content, re.M)
            if m:
                return _safe_dirname(m.group(1))
            # applet.json manifests carry the name under a JSON key instead.
            if os.path.basename(path) == 'applet.json':
                try:
                    data = json.loads(content)
                    nm = data.get('name_en') or data.get('name')
                    if nm:
                        return _safe_dirname(str(nm))
                except Exception:
                    pass
    for path in files:
        top = path.split('/')[0]
        if top and not os.path.basename(top) == path:
            return _safe_dirname(os.path.splitext(top)[0])
    return f"addon_{int(time.time())}"


def _safe_dirname(name):
    name = re.sub(r'[^A-Za-z0-9 ._-]', '_', name).strip().strip('.')
    return name or f"addon_{int(time.time())}"


# --------------------------------------------------------------------------- #
# Saving / packaging
# --------------------------------------------------------------------------- #
def _write_tree(files, dest_dir):
    for rel, content in files.items():
        fp = os.path.join(dest_dir, rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(fp) or dest_dir, exist_ok=True)
        with open(fp, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(content)


def save_as_folder(kind, files, name=None):
    """Write ``files`` as a folder under the per-user data overlay. Returns the
    created directory path."""
    name = name or _derive_name(kind, files)
    if kind['id'] == 'language':
        root = platform_utils.ensure_user_data_subdir('languages')
    else:
        root = platform_utils.ensure_user_data_subdir('data', kind['subdir'])
    dest = os.path.join(root, name)
    if os.path.exists(dest):
        dest = f"{dest}_{int(time.time())}"
    os.makedirs(dest, exist_ok=True)
    _write_tree(files, dest)
    return dest


def save_as_package(kind, files, name=None):
    """Write ``files`` to a temp tree and pack it into a .TCA/.TCD placed in the
    per-user data overlay. Returns the package file path."""
    if not kind['package']:
        raise RuntimeError(f"Kind '{kind['id']}' cannot be packaged")
    name = name or _derive_name(kind, files)
    pkg_kind = titan_package.NAME_TO_KIND[kind['id']]
    ext = titan_package.default_extension(pkg_kind)
    root = platform_utils.ensure_user_data_subdir('data', kind['subdir'])
    out_path = os.path.join(root, name + ext)
    if os.path.exists(out_path):
        out_path = os.path.join(root, f"{name}_{int(time.time())}{ext}")
    tmp = tempfile.mkdtemp(prefix='titan_ai_pack_')
    try:
        _write_tree(files, tmp)
        titan_package.build_package(tmp, out_path, pkg_kind)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out_path


# --------------------------------------------------------------------------- #
# Questionnaire wizard (renders AI-generated structured questions)
# --------------------------------------------------------------------------- #
class QuestionnaireDialog(wx.Dialog):
    """An accessible GUI wizard that renders a list of AI-generated questions
    (see :func:`parse_questions`) using the control type appropriate to each
    question, and returns the user's answers as {question id -> value}.

    Text -> text field, choice -> radio group, multichoice -> checkbox group,
    boolean -> yes/no checkbox. Every control carries an accessible name so a
    screen reader announces the question it belongs to."""

    def __init__(self, parent, kind, questions):
        title = _("Answer questions about your {kind}").format(
            kind=kind['label'])
        super().__init__(parent, title=title, size=(620, 560),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.questions = questions
        self.answers = {}
        self._controls = {}   # id -> (question, control-or-list)

        outer = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label=_(
            "The AI has a few questions. Answer what you can; leave anything "
            "blank to let the AI decide."))
        outer.Add(intro, flag=wx.ALL, border=10)

        # Scrollable area so any number of questions fits.
        self.scroller = wx.ScrolledWindow(self, style=wx.VSCROLL)
        self.scroller.SetScrollRate(0, 12)
        sizer = wx.BoxSizer(wx.VERTICAL)
        for idx, q in enumerate(self.questions, 1):
            self._build_question(self.scroller, sizer, idx, q)
        self.scroller.SetSizer(sizer)
        outer.Add(self.scroller, proportion=1,
                  flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        btns = wx.StdDialogButtonSizer()
        ok = wx.Button(self, wx.ID_OK, _("Use these answers"))
        ok.SetDefault()
        btns.AddButton(ok)
        btns.AddButton(wx.Button(self, wx.ID_CANCEL, _("Cancel")))
        btns.Realize()
        outer.Add(btns, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)

        self.SetSizer(outer)
        self.Bind(wx.EVT_BUTTON, self.OnOk, id=wx.ID_OK)
        if self.questions:
            first = self._controls[self.questions[0]['id']][1]
            ctrl = first[0] if isinstance(first, list) else first
            ctrl.SetFocus()

    def _build_question(self, parent, sizer, idx, q):
        label = f"{idx}. {q['text']}"
        qtype = q['type']
        default = q.get('default')

        if qtype == 'boolean':
            cb = wx.CheckBox(parent, label=label)
            cb.SetValue(bool(default) if default is not None else False)
            cb.SetName(q['text'])
            sizer.Add(cb, flag=wx.EXPAND | wx.TOP, border=12)
            self._controls[q['id']] = (q, cb)
            return

        sizer.Add(wx.StaticText(parent, label=label),
                  flag=wx.EXPAND | wx.TOP, border=12)

        if qtype == 'choice':
            options = q['options']
            rb = wx.RadioBox(parent, label='', choices=options,
                             majorDimension=1, style=wx.RA_SPECIFY_COLS)
            if default in options:
                rb.SetSelection(options.index(default))
            rb.SetName(q['text'])
            sizer.Add(rb, flag=wx.EXPAND | wx.LEFT, border=8)
            self._controls[q['id']] = (q, rb)

        elif qtype == 'multichoice':
            defaults = default if isinstance(default, (list, tuple)) else []
            boxes = []
            for opt in q['options']:
                cb = wx.CheckBox(parent, label=opt)
                cb.SetValue(opt in defaults)
                cb.SetName(f"{q['text']}: {opt}")
                sizer.Add(cb, flag=wx.EXPAND | wx.LEFT, border=16)
                boxes.append(cb)
            self._controls[q['id']] = (q, boxes)

        else:  # text
            style = wx.TE_MULTILINE if q.get('multiline') else 0
            tc = wx.TextCtrl(parent, style=style,
                             size=(-1, 70 if q.get('multiline') else -1))
            if isinstance(default, str) and default:
                tc.SetValue(default)
            tc.SetName(q['text'])
            sizer.Add(tc, flag=wx.EXPAND | wx.LEFT, border=8)
            self._controls[q['id']] = (q, tc)

    def OnOk(self, event):
        for qid, (q, ctrl) in self._controls.items():
            qtype = q['type']
            if qtype == 'boolean':
                self.answers[qid] = _("Yes") if ctrl.GetValue() else _("No")
            elif qtype == 'choice':
                self.answers[qid] = ctrl.GetStringSelection()
            elif qtype == 'multichoice':
                self.answers[qid] = [cb.GetLabel() for cb in ctrl
                                     if cb.GetValue()]
            else:
                self.answers[qid] = ctrl.GetValue().strip()
        event.Skip()  # let the dialog close with wx.ID_OK


# --------------------------------------------------------------------------- #
# Wizard dialog
# --------------------------------------------------------------------------- #
class AICreationWizardDialog(wx.Dialog):
    """Describe -> stream-generate (live progress) -> preview -> save/pack."""

    def __init__(self, parent, kind_id):
        self.kind = get_kind(kind_id)
        title = _("Create {kind} with AI").format(kind=self.kind['label'])
        super().__init__(parent, title=title, size=(760, 640),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.messages = []          # multi-turn conversation
        self.generated_files = {}   # last parsed {relpath: content}
        self._last_raw = ''         # raw text of the last generation
        self._stream_buf = []       # streamed text accumulator (this turn)
        self._gen_start = 0.0
        self._file_announced = set()

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(panel, label=_("Describe the {kind} you want:").format(
            kind=self.kind['label'])), flag=wx.LEFT | wx.TOP, border=10)
        self.desc = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(-1, 90))
        self.desc.SetName(_("Description"))
        vbox.Add(self.desc, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        # Options that shape generation.
        opts = wx.BoxSizer(wx.HORIZONTAL)
        self.web_cb = wx.CheckBox(panel, label=_("Search the web for reference"))
        self.web_cb.SetName(_("Search the web for reference"))
        opts.Add(self.web_cb, flag=wx.RIGHT, border=12)
        self.autofix_cb = wx.CheckBox(panel, label=_("Auto-fix generated code"))
        self.autofix_cb.SetValue(True)
        self.autofix_cb.SetName(_("Auto-fix generated code"))
        opts.Add(self.autofix_cb, flag=wx.RIGHT, border=12)
        self.ask_cb = wx.CheckBox(panel, label=_("Let the AI ask me questions"))
        self.ask_cb.SetValue(True)
        self.ask_cb.SetName(_("Let the AI ask me questions"))
        self.ask_cb.SetToolTip(_("While generating, the AI may pause and ask you "
                                 "a few questions in a guided wizard."))
        opts.Add(self.ask_cb)
        vbox.Add(opts, flag=wx.LEFT | wx.TOP, border=10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.plan_btn = wx.Button(panel, label=_("Plan"))
        self.plan_btn.Bind(wx.EVT_BUTTON, self.OnPlan)
        row.Add(self.plan_btn, flag=wx.RIGHT, border=6)
        self.gen_btn = wx.Button(panel, label=_("Generate"))
        self.gen_btn.Bind(wx.EVT_BUTTON, self.OnGenerate)
        row.Add(self.gen_btn, flag=wx.RIGHT, border=6)
        self.status = wx.StaticText(panel, label='')
        row.Add(self.status, flag=wx.ALIGN_CENTER_VERTICAL)
        vbox.Add(row, flag=wx.LEFT | wx.TOP, border=10)

        # Real, moving progress: a determinate gauge whose percentage is driven
        # by how much output has streamed in (monotonic, asymptotic to ~95% and
        # snapped to 100% on completion), nudged by a timer so it keeps creeping
        # even during network stalls -- never a frozen or fake bar.
        self.gauge = wx.Gauge(panel, range=100, size=(-1, 16))
        self.gauge.SetName(_("Progress"))
        vbox.Add(self.gauge, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, border=10)
        self._progress = 0
        self._pulse_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_pulse, self._pulse_timer)

        vbox.Add(wx.StaticText(panel, label=_("Live output:")),
                 flag=wx.LEFT | wx.TOP, border=10)
        self.transcript = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
            size=(-1, 140))
        self.transcript.SetName(_("Live output"))
        vbox.Add(self.transcript, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        # Preview: file list + selected file content.
        vbox.Add(wx.StaticText(panel, label=_("Generated files:")),
                 flag=wx.LEFT | wx.TOP, border=10)
        prev = wx.BoxSizer(wx.HORIZONTAL)
        self.file_list = wx.ListBox(panel, size=(220, 150))
        self.file_list.SetName(_("Generated files"))
        self.file_list.Bind(wx.EVT_LISTBOX, self._on_pick_file)
        prev.Add(self.file_list, flag=wx.EXPAND | wx.RIGHT, border=6)
        self.file_view = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
            size=(-1, 150))
        self.file_view.SetName(_("File content"))
        prev.Add(self.file_view, proportion=1, flag=wx.EXPAND)
        vbox.Add(prev, proportion=1, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        self.save_btn = wx.Button(panel, label=_("Save..."))
        self.save_btn.Bind(wx.EVT_BUTTON, self.OnSave)
        self.save_btn.Enable(False)
        btns.Add(self.save_btn, flag=wx.RIGHT, border=6)
        close_btn = wx.Button(panel, wx.ID_CANCEL, _("Close"))
        btns.Add(close_btn)
        vbox.Add(btns, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)

        panel.SetSizer(vbox)
        self.desc.SetFocus()

    # -- shared task plumbing -------------------------------------------- #
    def _prepare_turn(self, text):
        """Common pre-flight for Plan/Generate. Returns False if not ready."""
        if not text:
            wx.MessageBox(_("Please describe what to create."), _("Error"),
                          wx.OK | wx.ICON_WARNING, self)
            return False
        if not ai_provider.is_ai_ready():
            wx.MessageBox(_("AI features are not configured. Enable them and set "
                            "a method in Settings, AI features."),
                          _("AI not configured"), wx.OK | wx.ICON_WARNING, self)
            return False
        # Multi-turn: fold the previous generation in so the model refines.
        if self._last_raw and (not self.messages or self.messages[-1]['role'] != 'assistant'):
            self.messages.append({"role": "assistant", "content": self._last_raw})
        self.messages.append({"role": "user", "content": text})
        self._append_transcript(_("You"), text)
        self.desc.SetValue("")
        self.plan_btn.Enable(False)
        self.gen_btn.Enable(False)
        self.save_btn.Enable(False)
        self._stream_buf = []
        self._file_announced = set()
        self._gen_start = time.time()
        self._progress = 0
        self.gauge.SetValue(0)
        self._pulse_timer.Start(150)
        return True

    def _set_progress(self, percent):
        """Move the gauge to ``percent`` but never backwards (monotonic)."""
        percent = max(0, min(100, int(percent)))
        if percent > self._progress:
            self._progress = percent
            self.gauge.SetValue(percent)

    def _maybe_web_context(self, query):
        """Run a web search if the option is ticked; return a prompt block ('')."""
        if not self.web_cb.GetValue():
            return ''
        wx.CallAfter(self.status.SetLabel, _("Searching the web..."))
        wx.CallAfter(_speak, _("Searching the web"))
        try:
            results = web_search.search(query, max_results=_WEB_SEARCH_RESULTS)
        except Exception:
            results = []
        if not results:
            wx.CallAfter(self.transcript.AppendText,
                         "\n" + _("(no web results)") + "\n")
            return ''
        wx.CallAfter(self.transcript.AppendText,
                     "\n=== " + _("Web results") + " ===\n"
                     + "\n".join(f"- {r['title']} ({r['url']})" for r in results)
                     + "\n")
        return web_search.format_results_for_prompt(results)

    # -- interactive questionnaire (during generation) ------------------- #
    def _ask_questions_blocking(self, questions):
        """Show the GUI questionnaire wizard on the main thread and block this
        (worker) thread until the user finishes. Returns {'answers': {...}} or
        {'cancelled': True}."""
        result = {}
        done = threading.Event()

        def _show():
            try:
                self.status.SetLabel(_("Waiting for your answers..."))
                _speak(_("The AI has some questions"))
                play_sound('core/NOTIFICATION.ogg')
                dlg = QuestionnaireDialog(self, self.kind, questions)
                try:
                    if dlg.ShowModal() == wx.ID_OK:
                        result['answers'] = dlg.answers
                    else:
                        result['cancelled'] = True
                finally:
                    dlg.Destroy()
            except Exception:
                traceback.print_exc()
                result['cancelled'] = True
            finally:
                done.set()

        wx.CallAfter(_show)
        done.wait()
        if 'answers' in result:
            # Echo the answers into the transcript for a durable record.
            wx.CallAfter(self.transcript.AppendText,
                         "\n=== " + _("Your answers") + " ===\n"
                         + format_answers_for_prompt(questions, result['answers'])
                         + "\n")
        return result

    def _begin_stream_section(self, header):
        """Reset streaming/progress state for a new generation round and label
        the transcript (thread-safe: runs on the GUI thread)."""
        def _do():
            self.status.SetLabel(header + "...")
            self.transcript.AppendText("\n=== " + header + " ===\n")
            self._stream_buf = []
            self._file_announced = set()
            self._gen_start = time.time()
        wx.CallAfter(_do)

    def _on_generation_cancelled(self):
        self._pulse_timer.Stop()
        self.gauge.SetValue(0)
        self.plan_btn.Enable(True)
        self.gen_btn.Enable(True)
        self.status.SetLabel(_("Cancelled."))
        _speak(_("Cancelled"))
        self.desc.SetFocus()

    # -- planning --------------------------------------------------------- #
    def OnPlan(self, event):
        text = self.desc.GetValue().strip()
        if not self._prepare_turn(text):
            return
        self.status.SetLabel(_("Planning..."))
        _speak(_("Planning"))
        convo = list(self.messages)

        def _work():
            try:
                extra = self._maybe_web_context(text)
                system = build_plan_prompt(self.kind, extra_context=extra)
                wx.CallAfter(self.transcript.AppendText,
                             "\n=== " + _("Plan") + " ===\n")
                raw = ai_provider.generate(system, convo, on_chunk=self._on_chunk)
                wx.CallAfter(self._on_plan_done, raw, None)
            except Exception as e:
                traceback.print_exc()
                wx.CallAfter(self._on_plan_done, None, str(e))

        threading.Thread(target=_work, daemon=True).start()

    def _on_plan_done(self, raw, error):
        self._pulse_timer.Stop()
        self.plan_btn.Enable(True)
        self.gen_btn.Enable(True)
        if error:
            self.gauge.SetValue(0)
            self.status.SetLabel(_("Planning failed."))
            play_sound('core/error.ogg')
            _speak(_("Planning failed"))
            wx.MessageBox(error, _("Planning error"), wx.OK | wx.ICON_ERROR, self)
            return
        # Keep the plan/questions in the conversation so Generate builds on them.
        self.messages.append({"role": "assistant", "content": raw or ''})
        self._last_raw = ''  # the plan is not a file set
        self.gauge.SetValue(100)
        self.status.SetLabel(_("Plan ready. Answer any questions above, then "
                               "Generate."))
        play_sound('core/SELECT.ogg')
        _speak(_("Plan ready"))
        self.desc.SetFocus()

    # -- generation ------------------------------------------------------- #
    def OnGenerate(self, event):
        text = self.desc.GetValue().strip()
        if not self._prepare_turn(text):
            return
        self.status.SetLabel(_("Generating..."))
        _speak(_("Generating {kind}").format(kind=self.kind['label']))
        convo = list(self.messages)
        autofix = self.autofix_cb.GetValue()
        allow_questions = self.ask_cb.GetValue()

        def _work():
            try:
                extra = self._maybe_web_context(text)
                system = build_system_prompt(self.kind, extra_context=extra,
                                             allow_questions=allow_questions)
                # Interactive phase: the model may pause to ask the user
                # questions (shown as a GUI wizard) before it writes any files.
                raw = ai_provider.generate(system, convo, on_chunk=self._on_chunk)
                q_rounds = 0
                iterations = 0
                # Hard ceiling so a model that ignores "stop asking" can never
                # loop forever (a few extra for the insist-and-retry turns).
                _max_iters = _MAX_QUESTION_ROUNDS + 3
                while (allow_questions and looks_like_questions(raw)
                       and iterations < _max_iters):
                    iterations += 1
                    try:
                        questions = parse_questions(raw)
                    except Exception:
                        questions = []
                    convo.append({"role": "assistant", "content": raw})
                    if not questions or q_rounds >= _MAX_QUESTION_ROUNDS:
                        # Nothing answerable, or we've asked enough: insist on
                        # building now.
                        convo.append({"role": "user", "content": (
                            "Do not ask more questions. Generate the complete "
                            "add-on now using your best judgement, in the strict "
                            "@@FILE format.")})
                    else:
                        answers = self._ask_questions_blocking(questions)
                        if answers.get('cancelled'):
                            wx.CallAfter(self._on_generation_cancelled)
                            return
                        q_rounds += 1
                        convo.append({"role": "user", "content":
                                      format_answers_for_prompt(
                                          questions, answers['answers'])})
                        # Persist the interview so a later Generate/refine keeps it.
                        self.messages = list(convo)
                    self._begin_stream_section(
                        _("Generating") + " ({n})".format(n=q_rounds + 1))
                    raw = ai_provider.generate(system, convo,
                                               on_chunk=self._on_chunk)
                files = parse_files(raw)
                fixed_note = ''
                if autofix:
                    problems = static_check(files)
                    rounds = 0
                    while problems and rounds < _MAX_AUTOFIX_ROUNDS:
                        rounds += 1
                        wx.CallAfter(self.status.SetLabel,
                                     _("Auto-fixing ({n})...").format(n=rounds))
                        wx.CallAfter(_speak, _("Fixing code"))
                        wx.CallAfter(self.transcript.AppendText,
                                     "\n=== " + _("Auto-fix {n}").format(n=rounds)
                                     + " ===\n")
                        convo.append({"role": "assistant", "content": raw})
                        convo.append({"role": "user",
                                      "content": build_fix_message(problems)})
                        raw = ai_provider.generate(system, convo,
                                                   on_chunk=self._on_chunk)
                        files = parse_files(raw)
                        problems = static_check(files)
                    if rounds:
                        fixed_note = (_("auto-fixed") if not problems
                                      else _("auto-fix incomplete"))
                wx.CallAfter(self._on_done, raw, files, fixed_note, None)
            except Exception as e:
                traceback.print_exc()
                wx.CallAfter(self._on_done, None, None, '', str(e))

        threading.Thread(target=_work, daemon=True).start()

    def _on_chunk(self, delta):
        # Called from the worker thread; marshal to the GUI thread.
        wx.CallAfter(self._apply_chunk, delta)

    def _apply_chunk(self, delta):
        if not delta:
            return
        self._stream_buf.append(delta)
        self.transcript.AppendText(delta)
        # Announce each new file as its marker streams in (quasi-staged progress).
        joined = ''.join(self._stream_buf)
        for name in re.findall(r'^@@FILE:\s*(.+?)\s*$', joined, re.M):
            if name not in self._file_announced:
                self._file_announced.add(name)
                self.status.SetLabel(_("Creating: {file}").format(file=name))
                _speak(_("Creating {file}").format(file=name))
        chars = len(joined)
        elapsed = int(time.time() - self._gen_start)
        # Real, data-driven percentage: rises fast then eases toward 95% as more
        # text streams in (we cannot know the true total up front). 100% is only
        # set on completion in _on_done.
        pct = int(95 * (1 - math.exp(-chars / 4000.0)))
        self._set_progress(pct)
        base = _("Generating") if not self._file_announced \
            else _("Creating: {file}").format(file=sorted(self._file_announced)[-1])
        self.status.SetLabel(_("{stage}... {pct}% ({n} chars, {s}s)").format(
            stage=base, pct=self._progress, n=chars, s=elapsed))

    def _on_pulse(self, event):
        # Creep forward a little between chunks so the bar keeps moving even
        # while waiting on the network, but never past the streamed estimate cap.
        if self._progress < 95:
            self._set_progress(self._progress + 1)

    def _on_done(self, raw, files, fixed_note, error):
        self._pulse_timer.Stop()
        self.plan_btn.Enable(True)
        self.gen_btn.Enable(True)
        if error:
            self.gauge.SetValue(0)
            self.status.SetLabel(_("Generation failed."))
            play_sound('core/error.ogg')
            _speak(_("Generation failed"))
            wx.MessageBox(error, _("Generation error"), wx.OK | wx.ICON_ERROR, self)
            return
        self._last_raw = raw
        self.gauge.SetValue(100)
        if files is None:
            files = parse_files(raw)
        # Flatten any stray wrapper folder so the manifest sits at the root
        # (otherwise a packaged/saved add-on has a "missing manifest").
        files = normalize_addon_paths(self.kind, files)
        ok, msg = validate_files(self.kind, files)
        if not ok:
            self.status.SetLabel(msg)
            play_sound('core/error.ogg')
            _speak(msg)
            wx.MessageBox(msg + "\n\n" + _("You can refine your description and "
                          "generate again."), _("Incomplete result"),
                          wx.OK | wx.ICON_WARNING, self)
            return
        self.generated_files = files
        self._populate_preview(files)
        self.save_btn.Enable(True)
        suffix = f" ({fixed_note})" if fixed_note else ''
        self.status.SetLabel(
            _("Done: {n} file(s).").format(n=len(files)) + suffix + " "
            + _("Review below, then Save."))
        play_sound('core/SELECT.ogg')
        _speak(_("Done, {n} files generated").format(n=len(files)))

    # -- preview ---------------------------------------------------------- #
    def _populate_preview(self, files):
        self.file_list.Clear()
        for path in files:
            self.file_list.Append(path)
        if files:
            self.file_list.SetSelection(0)
            self._show_file(next(iter(files)))

    def _on_pick_file(self, event):
        sel = self.file_list.GetStringSelection()
        if sel:
            self._show_file(sel)

    def _show_file(self, path):
        self.file_view.SetValue(self.generated_files.get(path, ''))

    def _append_transcript(self, who, text):
        self.transcript.AppendText(f"\n=== {who} ===\n{text}\n")

    # -- save ------------------------------------------------------------- #
    def OnSave(self, event):
        if not self.generated_files:
            return
        as_package = False
        if self.kind['package']:
            dlg = wx.MessageDialog(
                self,
                _("Package into a single {ext} file?\n\nYes = one portable "
                  "package file.\nNo = a plain folder in your data directory.").format(
                    ext=titan_package.default_extension(
                        titan_package.NAME_TO_KIND[self.kind['id']]).upper()),
                _("Package add-on?"),
                wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION)
            res = dlg.ShowModal()
            dlg.Destroy()
            if res == wx.ID_CANCEL:
                return
            as_package = (res == wx.ID_YES)
        try:
            if as_package:
                dest = save_as_package(self.kind, self.generated_files)
            else:
                dest = save_as_folder(self.kind, self.generated_files)
        except Exception as e:
            traceback.print_exc()
            wx.MessageBox(str(e), _("Save failed"), wx.OK | wx.ICON_ERROR, self)
            return
        play_sound('core/SELECT.ogg')
        _speak(_("Saved"))
        wx.MessageBox(_("Saved to:\n{path}").format(path=dest), _("Saved"),
                      wx.OK | wx.ICON_INFORMATION, self)
        self.EndModal(wx.ID_OK)


def open_creation_wizard(parent, kind_id):
    """Entry point used by the Programmer menu."""
    if not ai_provider.is_ai_enabled():
        wx.MessageBox(_("Enable AI components in Settings, AI features first."),
                      _("AI features disabled"), wx.OK | wx.ICON_INFORMATION, parent)
        return
    dlg = AICreationWizardDialog(parent, kind_id)
    dlg.ShowModal()
    dlg.Destroy()
