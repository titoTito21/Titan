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
from src.ai import creation_project
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


def _macro_text(text):
    """Translate wording that belongs to the MACRO MANAGER, not to Titan.

    The Titan Script and its manager are a component with its own catalogue, so
    the few strings this kit says *about macros* are looked up there rather than
    copied into Titan's own translations - one component, one set of words for
    it. Falls back to the English text if the component is not installed.
    """
    try:
        import gettext
        from src import platform_utils
        from src.titan_core.translation import language_code
        for base in platform_utils.iter_resource_paths(
                os.path.join('data', 'components', 'macros', 'languages'),
                prefer_user=True):
            if os.path.isdir(base):
                return gettext.translation(
                    'macros', base, languages=[language_code],
                    fallback=True).gettext(text)
    except Exception as e:
        print(f"[AICreationKit] macro translations unavailable: {e}")
    return text


def _question_sound():
    """The sound of the AI asking something - see `ai_speech.SOUND_QUESTION`."""
    try:
        from src.ai.ai_speech import play_question_sound
        play_question_sound()
    except Exception:
        pass


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
    {'id': 'shell_addon',      'label': _("Shell Add-on"),    'subdir': 'shell addons',      'manifests': ('__shell_addon__.TCE',),             'package': True},
    {'id': 'settings_interface', 'label': _("Settings Interface"), 'subdir': 'settings interfaces', 'manifests': ('__settings_ui__.TCE',),        'package': True},
    {'id': 'macro',            'label': _macro_text("Macro (Titan Script)"), 'subdir': 'macros', 'manifests': ('__macro__.TCE',),             'package': False},
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
_TEXT_EXTS = ('.tce', '.py', '.txt', '.po', '.ini', '.json', '.md', '.cfg',
              '.tcs')


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
        "to this request. Ask as much as the add-on really needs - a small "
        "one needs three questions and a complicated one may need fifteen - "
        "but never ask what the user has already told you.",
        "- Group them: give every question a 'section' (\"Names\", "
        "\"Behaviour\", \"Sounds\"...) and Titan renders each section as a "
        "real group in the form. Add a 'help' sentence wherever the question "
        "alone is not clear, and mark a question the add-on cannot be built "
        "without as \"required\": true.",
        "- Ask about a branch only when the user is on it: a question with "
        "'depends_on' (another question's id) and 'depends_value' appears "
        "only once that answer is given, so a form that covers every option "
        "asks only about the one being built.",
        "- The questions JSON schema is:",
        '  {"questions": [',
        '    {"id": "name_en", "text": "English name?", "type": "text",',
        '     "section": "Names", "required": true, "default": ""},',
        '    {"id": "summary", "text": "What should it do?",',
        '     "type": "longtext", "section": "Names",',
        '     "help": "A few sentences - this shapes the whole add-on."},',
        '    {"id": "layout", "text": "Which layout?", "type": "choice",',
        '     "section": "Interface", "options": ["List", "Grid"],',
        '     "default": "List"},',
        '    {"id": "columns", "text": "How many columns?", "type": "number",',
        '     "section": "Interface", "minimum": 1, "maximum": 8,',
        '     "depends_on": "layout", "depends_value": "Grid"},',
        '    {"id": "features", "text": "Which features?",',
        '     "type": "multichoice", "section": "Behaviour",',
        '     "options": ["Sound", "Notifications"]},',
        '    {"id": "settings", "text": "Include settings?", "type": "boolean",',
        '     "section": "Behaviour", "default": true},',
        '    {"id": "data_file", "text": "A data file to start from?",',
        '     "type": "path", "section": "Data"}',
        '  ]}',
        f"- 'type' is one of: {', '.join(_QUESTION_TYPES)} - 'text' one line, "
        f"'longtext' several, 'number' a spin control (give 'minimum' and "
        f"'maximum'), 'path' a file and 'folder' a directory, both with a "
        f"Browse button. 'choice'/'multichoice' need an 'options' list. Ask "
        f"at most {_MAX_QUESTIONS}.",
        "- Once the request is clear (either originally or after answers), STOP "
        "asking and output the files in the strict format below.",
        "",
    ])


# A macro is not code: it is a Titan Script, checked by the macro manager
# itself before it is saved. Telling the model to write Python here is how you
# get a macro that is not a macro, so this kind gets its own requirements.
_MACRO_REQUIREMENTS = [
    "- Generate exactly two files: the manifest '__macro__.TCE' and one Titan "
    "Script whose filename is named by the manifest's 'openfile' key and ends "
    "in '.tcs'. Add extra .tcs helper scripts only if the user asked for them.",
    "- Write NO Python. A macro is a Titan Script: one statement per line, "
    "made of the statements of the language and of actions Titan really has.",
    "- Use ONLY the statements and the actions in the language reference and "
    "action list below. Never invent a statement, an argument name, an action "
    "name or a number outside the range a setting takes - the script is "
    "checked before it is saved and anything invented is refused with its "
    "line number.",
    "- Do NOT write pseudocode. A line in plain words ('do \"...\"', or a line "
    "that names no action) needs AI features switched on every time the macro "
    "runs. Speech position, pitch and rate, placed and moving sounds, dialogs, "
    "questions, conditions and loops are all part of the language: use them.",
    "- A macro is for automation, so build a real window whenever the user "
    "needs to give or choose something: 'dialog' with 'field', 'multiline', "
    "'choice', 'check' and its own 'buttons', then branch on which button was "
    "pressed (by its text or by its number). Do not settle for one 'ask' when "
    "the user described a form.",
    "- The manifest's name_en and name_pl are the name the user will see in "
    "their macro list. Comments (#) in the script are in English.",
]


def _shell_addon_requirements():
    """Written from the live tables, so the prompt cannot describe a Titan
    that does not exist: the hooks are `shell.addons.HOOKS`, the surfaces and
    the providable parts are that module's own constants, and the API is the
    real `ShellAddonAPI`."""
    try:
        from src.shell import addons
    except Exception:
        return []
    hooks = []
    for surface in ('shell', 'start_menu', 'explorer', 'taskbar', 'desktop'):
        for name in addons.HOOKS.get(surface, ()):
            hooks.append(name + addons.HOOK_SIGNATURES.get(name, '(api, ...)'))
    api = ", ".join("api." + name
                    for name in sorted(_public_attributes(addons.ShellAddonAPI)))
    return [
        "- EVERY function Titan calls in init.py is one of these, spelled "
        "exactly, with exactly that many arguments (`api` is always the "
        "first): " + ", ".join(hooks) + ". Define only the ones your add-on "
        "needs; give any helper of your own a name starting with '_'. A "
        "function with an invented name is never called and the add-on "
        "silently does nothing.",
        "- Do NOT invent hooks, manifest keys, surfaces or API methods. The "
        "manifest keys are: " + ", ".join(addons.MANIFEST_KEYS)
        + " (plus name_<lang> / description_<lang>). The surfaces are: "
        + ", ".join(addons.SURFACES) + ".",
        "- The only methods the api object has are: " + api + ". Anything "
        "else Titan can do is reached with api.run_action(addon, action, "
        "**params).",
        "- Every contributed entry is a dict with 'label' and something "
        "behind it - 'action' (a callable taking no arguments), 'children' "
        "(more entries), 'control' (a callable(parent) -> wx.Window) or "
        "'value' (a callable(entry) -> str for an explorer column). An entry "
        "without both is dropped.",
        "- status = 1 in the manifest: a shell add-on starts doing things the "
        "moment it is switched on, so the user switches it on.",
        "- Set provides = start_menu or provides = explorer ONLY if the "
        "add-on really replaces that window, and then define "
        + " or ".join(addons.PROVIDER_HOOKS[part]
                      + addons.HOOK_SIGNATURES[addons.PROVIDER_HOOKS[part]]
                      for part in addons.PROVIDABLE)
        + ", answering a window.",
        "- Never speak what the screen reader already says, and build every "
        "control as a real focusable window (src.shell.controls, or "
        "src.shell.a11y.name_control for a native one).",
    ]


def _settings_interface_requirements():
    """The same, from `SettingsUIAPI` and the interfaces module's constants."""
    try:
        from src.settings import interfaces
        from src.settings import ui_model
    except Exception:
        return []
    api = ", ".join(
        "api." + name
        for name in sorted(_public_attributes(interfaces.SettingsUIAPI)))
    kinds = ", ".join(sorted({
        getattr(ui_model, name) for name in dir(ui_model)
        if name.startswith('KIND_')}))
    return [
        "- init.py defines exactly one entry point: {0}(api), taking one "
        "argument, answering the window it opened (or True when it opened "
        "something that is not a window). Anything else and Titan opens its "
        "own settings window instead.".format(interfaces.ENTRY_POINT),
        "- Render from api.categories() - NEVER hard-code a list of Titan's "
        "settings. Each item is {'id', 'category', 'label', 'kind', 'value', "
        "'options', 'minimum', 'maximum', 'enabled'} and 'kind' is one of: "
        + kinds + ".",
        "- Change a setting with api.set(item_id, value) and SAVE with "
        "api.save(). Never write bg5settings.ini yourself and never import "
        "set_setting/save_settings: that sets the value and changes nothing.",
        "- The only methods the api object has are: " + api + ".",
        "- Do not invent manifest keys. They are: "
        + ", ".join(interfaces.MANIFEST_KEYS)
        + " (plus name_<lang> / description_<lang>), and status = 0, because "
        "an interface changes nothing until the user chooses it.",
        "- A loop of your own (a console, a server) runs on its own thread and "
        "touches the settings only through api.call(function, *args), which "
        "runs it on the GUI thread; the settings are wx controls.",
        "- Use real, named, focusable controls; for a 'multi' use "
        "src.ui.check_list.CheckList, never wx.CheckListBox, which tells a "
        "screen reader nothing about what is ticked.",
    ]


def _kind_requirements(kind):
    """The REQUIREMENTS lines that apply to this kind."""
    if kind['id'] == 'macro':
        return [_manifest_line(kind)] + _MACRO_REQUIREMENTS
    extra = []
    if kind['id'] == 'shell_addon':
        extra = _shell_addon_requirements()
    elif kind['id'] == 'settings_interface':
        extra = _settings_interface_requirements()
    return extra + [
        _manifest_line(kind),
        "- Do NOT invent Titan APIs. Every `from src...` import, every "
        "attribute you read off a Titan module, every action id and every "
        "manifest key you write is checked against the running Titan before "
        "the add-on is saved, and anything that does not exist is reported "
        "back to you by name. If you are unsure a helper exists, use the one "
        "the documentation and the reference example below actually show.",
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
    ]


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
    ] + _kind_requirements(kind) + [
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
# Enough for something real. A statusbar applet needs three questions and a
# component with four screens needs fifteen, which is only bearable because
# they arrive in named sections and a question can depend on an earlier
# answer - so the user answers what applies to the add-on they are actually
# describing, not every branch of it.
_MAX_QUESTIONS = 24
# How many times the model may pause to ask the user questions during a single
# generation before we insist it just build with its best judgement.
_MAX_QUESTION_ROUNDS = 3
#: What a question can be. Each is a real control in the wizard, so each is
#: something a screen reader already knows how to read.
_QUESTION_TYPES = ('text', 'longtext', 'choice', 'multichoice', 'boolean',
                   'number', 'path', 'folder')
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
        minimum, maximum = None, None
        if qtype == 'number':
            minimum = _as_number(q.get('minimum', q.get('min')))
            maximum = _as_number(q.get('maximum', q.get('max')))
            if minimum is not None and maximum is not None \
                    and maximum < minimum:
                minimum, maximum = maximum, minimum
        # A follow-up: shown only while an earlier answer says so.  Anything
        # that does not name a real earlier question is dropped rather than
        # hiding a question for ever.
        depends_on = str(q.get('depends_on') or '').strip()
        if depends_on and depends_on not in seen_ids:
            depends_on = ''
        depends_value = q.get('depends_value')
        if isinstance(depends_value, (list, tuple)):
            depends_value = [str(value).strip() for value in depends_value]
        elif depends_value is not None:
            depends_value = [str(depends_value).strip()]
        out.append({
            'id': qid,
            'text': text,
            'type': qtype,
            'options': options,
            'multiline': bool(q.get('multiline', False)) or qtype == 'longtext',
            'default': q.get('default'),
            # What the question is FOR, in a sentence - shown under it and
            # given to the control as its description, because a question
            # short enough to be a label is often too short to be clear.
            'help': str(q.get('help') or q.get('description') or '').strip(),
            # Questions arrive grouped: a static box is a grouping Windows
            # itself knows, so a screen reader says which part of the form
            # the keyboard has entered.
            'section': str(q.get('section') or q.get('group') or '').strip(),
            'required': bool(q.get('required', False)),
            'minimum': minimum,
            'maximum': maximum,
            'depends_on': depends_on,
            'depends_value': depends_value,
        })
        if len(out) >= _MAX_QUESTIONS:
            break
    return out


def _as_number(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def question_sections(questions):
    """The questions grouped, in the order the sections first appear."""
    sections = []
    index = {}
    for question in questions:
        name = question.get('section', '')
        if name not in index:
            index[name] = len(sections)
            sections.append((name, []))
        sections[index[name]][1].append(question)
    return sections


def question_applies(question, answers):
    """Is this follow-up's condition met by what has been answered?"""
    depends_on = question.get('depends_on')
    if not depends_on:
        return True
    given = answers.get(depends_on)
    if given is None:
        return False
    wanted = question.get('depends_value')
    if isinstance(given, (list, tuple)):
        given_values = [str(value).strip().lower() for value in given]
    else:
        given_values = [str(given).strip().lower()]
    if not wanted:
        # No value named: any answer that is not empty and not "no".
        return any(value not in ('', 'no', 'false', '0', _("No").lower())
                   for value in given_values)
    wanted_values = [str(value).strip().lower() for value in wanted]
    return any(value in wanted_values for value in given_values)


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
def check_titan_script(text):
    """Everything wrong with a generated Titan Script, line by line.

    The macro manager owns the language, so it owns the check too: asking it
    means a script is judged by the thing that will actually run it, and a
    model that invented a statement, an action or a number out of range is told
    which line, instead of the user finding out at a quarter to twelve. Any
    line still written in words is a problem here as well - a generated macro
    must run with AI features switched off.
    """
    try:
        from src.titan_core import actions
    except Exception:
        return []
    try:
        result = actions.run('macros', 'check_macro', script=text)
    except Exception:
        return []
    said = str(getattr(result, 'text', '') or '').strip()
    ok = bool(getattr(result, 'ok', False))
    # A script can also be reported as *runnable but written in words*, which is
    # still a problem for a generated macro: it would stop working the moment
    # AI features were switched off.
    if ok and 'written in words' not in said:
        return []
    # "- line 4: ..." in English, "- linia 4: ..." in Polish - the macro
    # manager writes its review in the user's language, so the anchor is
    # matched by its shape rather than by the English word.
    problems = [re.sub(r'^\s*-\s*', '', line).strip()
                for line in said.splitlines()
                if re.match(r'\s*-\s*\w+\s+\d+\s*:', line)]
    if problems and 'written in words' in said and ok:
        problems = [p + " - write it with real actions instead"
                    for p in problems]
    if problems:
        return problems
    return [said.splitlines()[0]] if said and not ok else []


# --------------------------------------------------------------------------- #
# Checking a generated add-on against the REAL host, not against a copy of it
# --------------------------------------------------------------------------- #
# The failures worth catching here are the ones that are invisible at run time.
# A shell add-on whose functions are ALMOST right (`start_menu_entries`,
# `on_taskbar_start`) loads, is listed and can be ticked - and contributes
# nothing; a settings interface that calls `api.get_settings()` raises inside a
# guard and Titan quietly opens its own window instead. Neither is a traceback
# anybody sees, so both are checked before the files are saved - against the
# LIVE classes and the live hook tables (`shell.addons.HOOKS`,
# `ShellAddonAPI`, `SettingsUIAPI`) rather than against a list copied in here,
# which is the only way the check cannot drift from what Titan really asks for.
_DUNDER = re.compile(r'^__.*__$')


def _generated_file(files, name):
    """One generated file by base name, wherever the model put it."""
    if name in files:
        return files[name]
    for path, text in files.items():
        if os.path.basename(path) == name:
            return text
    return None


def _module_tree(files, name='init.py'):
    """The parsed AST of one generated file, or None."""
    content = _generated_file(files, name)
    if content is None:
        return None
    try:
        return ast.parse(content, filename=name)
    except SyntaxError:
        return None          # already reported by the syntax pass


def _top_level_functions(tree):
    """{name: argument count} for every function defined at module level."""
    found = {}
    for node in getattr(tree, 'body', []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            found[node.name] = (len(getattr(args, 'posonlyargs', []))
                                + len(args.args)
                                + (1 if args.vararg else 0))
    return found


def _attributes_used_on(tree, variable):
    """Every `<variable>.<name>` read anywhere in the module."""
    used = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == variable):
            used.add(node.attr)
    return used


def _public_attributes(cls):
    """What that API object really offers - asked of the object, not the class.

    `dir(cls)` finds the methods but not `api.id` / `api.path`, which are
    assigned in `__init__`, and a check that did not know about those would
    refuse a generated add-on for using exactly what the guide tells it to.
    So one is BUILT, with a stand-in for every constructor argument (both API
    objects only store what they are handed), and its instance attributes are
    added. If that ever fails, the class's own names are still the answer.
    """
    names = {name for name in dir(cls) if not _DUNDER.match(name)}
    try:
        import inspect
        import types as _types
        stub = _types.SimpleNamespace(id='x', path='x', name='x')
        parameters = inspect.signature(cls).parameters
        instance = cls(*[stub] * len(parameters))
        names |= {name for name in vars(instance)
                  if not name.startswith('_')}
    except Exception:
        pass
    return names


def _did_you_mean(name, candidates):
    import difflib
    close = difflib.get_close_matches(str(name), sorted(candidates), n=1,
                                      cutoff=0.72)
    return close[0] if close else None


def _parse_manifest(files, filename, section):
    """(parser, problems) for the INI manifest a generated add-on must have."""
    import configparser
    content = _generated_file(files, filename)
    if content is None:
        return None, ["{0} is missing - it is the manifest Titan looks for "
                      "and its name is not negotiable.".format(filename)]
    parser = configparser.ConfigParser()
    try:
        parser.read_string(content)
    except Exception as error:
        return None, ["{0}: not a readable INI file ({1})".format(filename,
                                                                  error)]
    if not parser.has_section(section):
        return None, ["{0}: there is no [{1}] section - that exact heading is "
                      "what Titan reads.".format(filename, section)]
    return parser, []


def _check_manifest_keys(parser, filename, section, allowed):
    """A key nobody reads is a promise its author believes has been kept."""
    problems = []
    for key in parser.options(section):
        base = re.sub(r'_[a-z]{2}$', '', key)
        if key in allowed or base in ('name', 'description'):
            continue
        suggestion = _did_you_mean(key, allowed)
        problems.append(
            "{0}: '{1}' is not a key Titan reads{2}".format(
                filename, key,
                " - did you mean '{0}'?".format(suggestion) if suggestion
                else " - the keys are: {0}.".format(', '.join(allowed))))
    status = parser.get(section, 'status', fallback=None)
    if status is None:
        problems.append("{0}: 'status' is missing (0 = enabled, "
                        "1 = disabled).".format(filename))
    elif str(status).strip() not in ('0', '1'):
        problems.append("{0}: status must be 0 or 1, not {1!r}.".format(
            filename, status))
    return problems


def _check_api_use(tree, api_class, problems):
    """Every `api.<something>` must be something that object really has."""
    known = _public_attributes(api_class)
    for attribute in sorted(_attributes_used_on(tree, 'api')):
        if attribute in known:
            continue
        suggestion = _did_you_mean(attribute, known)
        problems.append(
            "init.py: api.{0} does not exist{1}".format(
                attribute,
                " - did you mean api.{0}?".format(suggestion) if suggestion
                else " - the API is: {0}.".format(', '.join(sorted(known)))))


def check_shell_addon(files):
    """Everything wrong with a generated shell add-on."""
    try:
        from src.shell import addons
    except Exception:
        return []
    problems = []
    parser, manifest_problems = _parse_manifest(files, addons.MANIFEST,
                                                addons.SECTION)
    problems += manifest_problems
    provides = ''
    if parser is not None:
        problems += _check_manifest_keys(parser, addons.MANIFEST,
                                         addons.SECTION, addons.MANIFEST_KEYS)
        surfaces = [part.strip() for part in parser.get(
            addons.SECTION, 'surfaces', fallback='').split(',') if part.strip()]
        for surface in surfaces:
            if surface in addons.SURFACES:
                continue
            suggestion = _did_you_mean(surface, addons.SURFACES)
            problems.append(
                "{0}: '{1}' is not a surface{2}".format(
                    addons.MANIFEST, surface,
                    " - did you mean '{0}'?".format(suggestion) if suggestion
                    else " - they are: {0}.".format(', '.join(addons.SURFACES))))
        provides = parser.get(addons.SECTION, 'provides',
                              fallback='').strip().lower()
        if provides and provides not in addons.PROVIDABLE:
            problems.append(
                "{0}: an add-on can only provide {1}, not '{2}'.".format(
                    addons.MANIFEST, ' or '.join(addons.PROVIDABLE), provides))

    tree = _module_tree(files, 'init.py')
    if tree is None:
        if _generated_file(files, 'init.py') is None:
            problems.append("init.py is missing - it is where every hook "
                            "Titan calls has to live.")
        return problems

    functions = _top_level_functions(tree)
    real = [name for name in functions if name in addons.ALL_HOOKS]
    for name in sorted(functions):
        count = functions[name]
        if name in addons.ALL_HOOKS:
            expected = addons.HOOK_ARGS.get(name)
            if expected is not None and count != expected:
                problems.append(
                    "init.py: {0}() takes {1} argument(s); Titan calls it with "
                    "{2} (the first is always `api`).".format(name, count,
                                                              expected))
            continue
        if name.startswith('_'):
            continue
        suggestion = _did_you_mean(name, addons.ALL_HOOKS)
        if suggestion:
            problems.append(
                "init.py: {0}() is not a function Titan ever calls - did you "
                "mean {1}()? Anything else is a helper of your own and should "
                "start with an underscore.".format(name, suggestion))
    if not real:
        problems.append(
            "init.py: not one of Titan's hooks is defined, so this add-on "
            "would load and do nothing. They are: {0}.".format(
                ', '.join(sorted(addons.ALL_HOOKS))))
    if provides in addons.PROVIDER_HOOKS:
        needed = addons.PROVIDER_HOOKS[provides]
        if needed not in functions:
            problems.append(
                "init.py: the manifest says provides = {0}, so {1}() must be "
                "defined - it is what Titan calls to open it.".format(
                    provides, needed))

    _check_api_use(tree, addons.ShellAddonAPI, problems)
    return problems


def check_settings_interface(files):
    """Everything wrong with a generated settings interface."""
    try:
        from src.settings import interfaces
    except Exception:
        return []
    problems = []
    parser, manifest_problems = _parse_manifest(files, interfaces.MANIFEST,
                                                interfaces.SECTION)
    problems += manifest_problems
    if parser is not None:
        problems += _check_manifest_keys(parser, interfaces.MANIFEST,
                                         interfaces.SECTION,
                                         interfaces.MANIFEST_KEYS)

    tree = _module_tree(files, 'init.py')
    if tree is None:
        if _generated_file(files, 'init.py') is None:
            problems.append("init.py is missing - it is where {0}() has to "
                            "live.".format(interfaces.ENTRY_POINT))
        return problems

    functions = _top_level_functions(tree)
    if interfaces.ENTRY_POINT not in functions:
        suggestion = _did_you_mean(interfaces.ENTRY_POINT, functions)
        problems.append(
            "init.py: {0}(api) is missing - it is the whole contract, and "
            "Titan opens its own settings window when it is not there.{1}"
            .format(interfaces.ENTRY_POINT,
                    " ({0}() is not it.)".format(suggestion) if suggestion
                    else ""))
    elif functions[interfaces.ENTRY_POINT] != 1:
        problems.append(
            "init.py: {0}() takes {1} argument(s); Titan calls it with exactly "
            "one, the api object.".format(interfaces.ENTRY_POINT,
                                          functions[interfaces.ENTRY_POINT]))

    _check_api_use(tree, interfaces.SettingsUIAPI, problems)

    # Writing the ini file sets the value and changes nothing: Titan applies a
    # setting in the control's own event and in `OnSave`, which is what
    # `api.save()` runs.
    for path, content in files.items():
        if not path.lower().endswith('.py'):
            continue
        for written in ('save_settings(', 'set_setting('):
            if written in content:
                problems.append(
                    "{0}: {1}() writes the settings file behind Titan's back - "
                    "a settings interface changes a setting with "
                    "api.set(id, value) and saves with api.save().".format(
                        path, written[:-1]))
    return problems


#: Kinds Titan can check beyond syntax. A kind absent from here is checked
#: exactly as before.
_KIND_CHECKS = {
    'shell_addon': check_shell_addon,
    'settings_interface': check_settings_interface,
}


def static_check(files, kind=None):
    """Return a list of human-readable problems found by cheap static analysis:
    Python syntax errors (via :func:`ast.parse`), invalid JSON manifests,
    Titan Scripts that would not run, and - when ``kind`` is one Titan can
    check - everything the host would silently ignore at run time. Empty list
    means the files pass."""
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
        elif low.endswith('.tcs'):
            for problem in check_titan_script(content):
                problems.append(f"{path}: {problem}")
    kind_id = kind.get('id') if isinstance(kind, dict) else kind
    # What every kind is checked for: an import, an attribute, an action or a
    # manifest key that Titan does not have (`src/ai/creation_check.py`).
    try:
        from src.ai import creation_check
        problems += creation_check.check_everything(files, kind)
    except Exception as error:          # pragma: no cover - defensive
        print(f"[AI creation kit] the generic checks failed: {error}")
    check = _KIND_CHECKS.get(kind_id)
    if check is not None:
        try:
            problems += check(files)
        except Exception as error:      # pragma: no cover - defensive
            print(f"[AI creation kit] {kind_id} check failed: {error}")
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
    if kind['id'] == 'macro' and not any(
            p.lower().endswith('.tcs') for p in files):
        return False, _macro_text("The macro has no Titan Script (.tcs) file.")
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
            # A macro's manifest has no shortname; its English name is what the
            # user will look for, so the folder is named after that. A shell
            # add-on and a settings interface have neither, and for them the
            # folder name IS the add-on's id - `addon_1755...` would be what
            # the settings, the Start menu chooser and every action then call
            # it - so the plain `name` answers as well.
            for key in ('name_en', 'name'):
                m = re.search(r'^\s*' + key + r'\s*=\s*"?([^"\r\n]+)"?',
                              content, re.M)
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
    """The AI's questions as a real form.

    Every question is the control it deserves - a tick box, a radio group, a
    number field, a file picker - because a control a screen reader already
    knows how to read needs no explaining, and because "answer 12 things
    about the component you want" is only bearable when the answers are
    typed the way they would be in any settings window.

    Three things make it work for something complicated:

    - **Sections.** Questions carry a `section`, and each becomes a
      `wx.StaticBox` - a grouping Windows itself knows, so a reader says
      which part of the form the keyboard has just entered.
    - **Help.** A question may carry a sentence saying what it is for, shown
      under it and given to the control as its accessible description.
    - **Follow-ups.** A question may depend on an earlier answer and appears
      only when that answer is given, so a form covering every branch of an
      add-on asks only about the branch being built.
    """

    def __init__(self, parent, kind, questions):
        title = _("Answer questions about your {kind}").format(
            kind=kind['label'])
        super().__init__(parent, title=title, size=(660, 620),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.questions = questions
        self.answers = {}
        self._controls = {}       # id -> (question, control-or-list)
        self._rows = {}           # id -> [windows to show or hide]
        self._followers = [q for q in questions if q.get('depends_on')]

        outer = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label=_(
            "The AI has some questions. Answer what you can; leave anything "
            "blank to let the AI decide."))
        outer.Add(intro, flag=wx.ALL, border=10)

        self.scroller = wx.ScrolledWindow(self, style=wx.VSCROLL)
        self.scroller.SetScrollRate(0, 12)
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        number = 0
        for name, group in question_sections(questions):
            if name:
                box = wx.StaticBoxSizer(wx.VERTICAL, self.scroller, name)
                parent_window = box.GetStaticBox()
                target = box
                self.sizer.Add(box, flag=wx.EXPAND | wx.ALL, border=6)
            else:
                parent_window = self.scroller
                target = self.sizer
            for question in group:
                number += 1
                self._build_question(parent_window, target, number, question)
        self.scroller.SetSizer(self.sizer)
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
        self._apply_conditions()
        if self.questions:
            first = self._controls[self.questions[0]['id']][1]
            control = first[0] if isinstance(first, list) else first
            control.SetFocus()

    # -- building ---------------------------------------------------------
    def _build_question(self, parent, sizer, number, question):
        label = f"{number}. {question['text']}"
        if question.get('required'):
            label += " *"
        kind = question['type']
        default = question.get('default')
        rows = []

        def add(window, **flags):
            sizer.Add(window, **flags)
            rows.append(window)
            return window

        if kind == 'boolean':
            control = wx.CheckBox(parent, label=label)
            control.SetValue(_as_bool_answer(default))
            control.SetName(question['text'])
            add(control, flag=wx.EXPAND | wx.TOP, border=12)
        else:
            add(wx.StaticText(parent, label=label),
                flag=wx.EXPAND | wx.TOP, border=12)
            control = self._build_control(parent, sizer, question, rows)

        if question.get('help'):
            help_text = wx.StaticText(parent, label=question['help'])
            help_text.SetForegroundColour(
                wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
            add(help_text, flag=wx.EXPAND | wx.LEFT | wx.BOTTOM, border=8)
            for window in (control if isinstance(control, list) else [control]):
                try:
                    window.SetToolTip(question['help'])
                    window.SetHelpText(question['help'])
                except Exception:
                    pass

        self._controls[question['id']] = (question, control)
        self._rows[question['id']] = rows
        # An answer that a follow-up depends on has to be watched.
        for window in (control if isinstance(control, list) else [control]):
            for event in (wx.EVT_CHECKBOX, wx.EVT_RADIOBOX, wx.EVT_TEXT,
                          wx.EVT_CHOICE):
                try:
                    window.Bind(event, self._on_answer_changed)
                except Exception:
                    pass

    def _build_control(self, parent, sizer, question, rows):
        kind = question['type']
        default = question.get('default')

        def add(window, **flags):
            sizer.Add(window, **flags)
            rows.append(window)
            return window

        if kind == 'choice':
            options = question['options']
            control = wx.RadioBox(parent, label='', choices=options,
                                  majorDimension=1, style=wx.RA_SPECIFY_COLS)
            if isinstance(default, str) and default in options:
                control.SetSelection(options.index(default))
            control.SetName(question['text'])
            add(control, flag=wx.EXPAND | wx.LEFT, border=8)
            return control

        if kind == 'multichoice':
            defaults = default if isinstance(default, (list, tuple)) else []
            boxes = []
            for option in question['options']:
                box = wx.CheckBox(parent, label=option)
                box.SetValue(option in defaults)
                box.SetName(f"{question['text']}: {option}")
                add(box, flag=wx.EXPAND | wx.LEFT, border=16)
                boxes.append(box)
            return boxes

        if kind == 'number':
            minimum = question.get('minimum')
            maximum = question.get('maximum')
            control = wx.SpinCtrl(
                parent,
                min=minimum if minimum is not None else 0,
                max=maximum if maximum is not None else 100000,
                initial=_as_number(default) or (minimum or 0))
            control.SetName(question['text'])
            add(control, flag=wx.LEFT, border=8)
            return control

        if kind in ('path', 'folder'):
            row = wx.BoxSizer(wx.HORIZONTAL)
            field = wx.TextCtrl(parent)
            if isinstance(default, str):
                field.SetValue(default)
            field.SetName(question['text'])
            row.Add(field, proportion=1, flag=wx.EXPAND | wx.RIGHT, border=6)
            browse = wx.Button(parent, label=_("Browse..."))
            browse.SetName(_("Browse for {what}").format(
                what=question['text']))
            browse.Bind(wx.EVT_BUTTON,
                        lambda event, f=field, k=kind: self._browse(f, k))
            row.Add(browse)
            sizer.Add(row, flag=wx.EXPAND | wx.LEFT, border=8)
            rows.extend([field, browse])
            return field

        style = wx.TE_MULTILINE if (question.get('multiline')
                                    or kind == 'longtext') else 0
        control = wx.TextCtrl(parent, style=style,
                              size=(-1, 90 if style else -1))
        if isinstance(default, str) and default:
            control.SetValue(default)
        control.SetName(question['text'])
        add(control, flag=wx.EXPAND | wx.LEFT, border=8)
        return control

    def _browse(self, field, kind):
        if kind == 'folder':
            dialog = wx.DirDialog(self, _("Choose a folder"))
        else:
            dialog = wx.FileDialog(self, _("Choose a file"),
                                   style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        try:
            if dialog.ShowModal() == wx.ID_OK:
                field.SetValue(dialog.GetPath())
                field.SetFocus()
        finally:
            dialog.Destroy()

    # -- follow-ups -------------------------------------------------------
    def _on_answer_changed(self, event):
        event.Skip()
        if self._followers:
            self._apply_conditions()

    def _apply_conditions(self):
        """Show only the follow-ups whose condition the answers now meet.

        Hidden rather than disabled: a hidden control is not in the tab order
        at all, so a form that asks about the branch the user is not building
        does not make them tab past it.
        """
        if not self._followers:
            return
        answers = self.current_answers()
        changed = False
        for question in self._followers:
            wanted = question_applies(question, answers)
            for window in self._rows.get(question['id'], ()):
                try:
                    if window.IsShown() != wanted:
                        window.Show(wanted)
                        changed = True
                except Exception:
                    pass
        if changed:
            self.scroller.Layout()
            self.scroller.FitInside()

    # -- answers ----------------------------------------------------------
    def current_answers(self):
        """What the form says right now, without closing it."""
        answers = {}
        for question_id, (question, control) in self._controls.items():
            kind = question['type']
            try:
                if kind == 'boolean':
                    answers[question_id] = (_("Yes") if control.GetValue()
                                            else _("No"))
                elif kind == 'choice':
                    answers[question_id] = control.GetStringSelection()
                elif kind == 'multichoice':
                    answers[question_id] = [box.GetLabel() for box in control
                                            if box.GetValue()]
                elif kind == 'number':
                    answers[question_id] = str(control.GetValue())
                else:
                    answers[question_id] = control.GetValue().strip()
            except Exception:
                answers[question_id] = ''
        return answers

    def OnOk(self, event):
        answers = self.current_answers()
        # A question the user cannot see was not asked, and must not be
        # answered on their behalf.
        for question in self._followers:
            if not question_applies(question, answers):
                answers.pop(question['id'], None)
        missing = [question['text'] for question in self.questions
                   if question.get('required')
                   and question['id'] in answers
                   and not str(answers.get(question['id']) or '').strip()]
        if missing:
            wx.MessageBox(
                _("These still need an answer:\n\n{questions}").format(
                    questions="\n".join(missing)),
                _("Answer needed"), wx.OK | wx.ICON_INFORMATION, self)
            return
        self.answers = answers
        event.Skip()  # let the dialog close with wx.ID_OK


def _as_bool_answer(value):
    if isinstance(value, bool):
        return value
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'tak',
                                                'on')


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
        # A project is this whole session on disk (`creation_project.py`):
        # once it has a name, every generation is written to it, so closing
        # the dialog - or Titan - is not the end of an add-on that took an
        # afternoon.
        self.project_name = ''
        self._plan_text = ''
        self._interview = []        # [{'questions': [...], 'answers': {...}}]
        self._first_description = ''
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
        self.save_project_btn = wx.Button(panel, label=_("Save project"))
        self.save_project_btn.SetToolTip(_(
            "Keep this session - the description, the questions and answers, "
            "the conversation and the files - so you can carry on later."))
        self.save_project_btn.Bind(wx.EVT_BUTTON, self.OnSaveProject)
        btns.Add(self.save_project_btn, flag=wx.RIGHT, border=6)
        self.open_project_btn = wx.Button(panel, label=_("Open project..."))
        self.open_project_btn.Bind(wx.EVT_BUTTON, self.OnOpenProject)
        btns.Add(self.open_project_btn, flag=wx.RIGHT, border=6)
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
        if not self._first_description:
            self._first_description = text
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
                _question_sound()
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
        self._plan_text = raw or ''
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
                        # Kept for the project: the interview is most of what
                        # a complicated add-on knows about itself.
                        self._interview.append({'questions': questions,
                                                'answers': answers['answers']})
                        # Persist the interview so a later Generate/refine keeps it.
                        self.messages = list(convo)
                    self._begin_stream_section(
                        _("Generating") + " ({n})".format(n=q_rounds + 1))
                    raw = ai_provider.generate(system, convo,
                                               on_chunk=self._on_chunk)
                files = parse_files(raw)
                fixed_note = ''
                if autofix:
                    problems = static_check(files, self.kind)
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
                        problems = static_check(files, self.kind)
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
        # A named project is written after every generation: an hour of work
        # must not depend on the user remembering to press a button.
        if self.project_name:
            self._store_project(self.project_name, quiet=True)

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

    # -- projects ---------------------------------------------------------- #
    def _store_project(self, name, quiet=False):
        """Write the session to disk under `name`."""
        try:
            folder = creation_project.save(
                name,
                self.kind['id'],
                description=self._first_description or self.desc.GetValue(),
                messages=self.messages,
                files=self.generated_files,
                questions=[question for round_ in self._interview
                           for question in round_['questions']],
                answers={key: value for round_ in self._interview
                         for key, value in round_['answers'].items()},
                plan=self._plan_text,
                raw=self._last_raw,
                options={'web': self.web_cb.GetValue(),
                         'autofix': self.autofix_cb.GetValue(),
                         'ask': self.ask_cb.GetValue()})
        except Exception as error:
            traceback.print_exc()
            if not quiet:
                wx.MessageBox(str(error), _("Could not save the project"),
                              wx.OK | wx.ICON_ERROR, self)
            return None
        self.project_name = name
        self.SetTitle(_("Create {kind} with AI - {project}").format(
            kind=self.kind['label'], project=name))
        if quiet:
            self.status.SetLabel(_("Project saved."))
        else:
            play_sound('core/SELECT.ogg')
            _speak(_("Project saved"))
            wx.MessageBox(_("Saved to:\n{path}").format(path=folder),
                          _("Project saved"), wx.OK | wx.ICON_INFORMATION,
                          self)
        return folder

    def OnSaveProject(self, event):
        if not (self.messages or self.generated_files
                or self.desc.GetValue().strip()):
            wx.MessageBox(_("There is nothing to save yet."), _("Project"),
                          wx.OK | wx.ICON_INFORMATION, self)
            return
        suggestion = self.project_name or creation_project.suggest_name(
            self.kind['label'],
            self._first_description or self.desc.GetValue())
        dialog = wx.TextEntryDialog(self, _("Name for this project:"),
                                    _("Save project"), suggestion)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            name = dialog.GetValue().strip()
        finally:
            dialog.Destroy()
        if not name:
            return
        if (name != self.project_name and creation_project.exists(name)
                and wx.MessageBox(
                    _("A project called {name} already exists. Replace it?")
                    .format(name=name), _("Save project"),
                    wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES):
            return
        self._store_project(name)

    def OnOpenProject(self, event):
        projects = [entry for entry in creation_project.list_projects()
                    if entry['kind'] == self.kind['id']]
        if not projects:
            wx.MessageBox(
                _("There are no saved {kind} projects yet. Press Save "
                  "project to keep this one.").format(
                      kind=self.kind['label']),
                _("Open project"), wx.OK | wx.ICON_INFORMATION, self)
            return
        if self.messages and wx.MessageBox(
                _("Opening a project replaces what is in this window. "
                  "Continue?"), _("Open project"),
                wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        labels = [_("{name} - {files} file(s), last changed {when}").format(
            name=entry['name'], files=entry['files'],
            when=entry['updated']) for entry in projects]
        dialog = wx.SingleChoiceDialog(self, _("Which project?"),
                                       _("Open project"), labels)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            chosen = projects[dialog.GetSelection()]
        finally:
            dialog.Destroy()
        self.load_project(chosen['name'])

    def load_project(self, name):
        """Put a saved session back into this window."""
        data = creation_project.load(name)
        if not data:
            # Say where it looked: "could not be read" on its own is
            # something the user can do nothing about.
            wx.MessageBox(
                _("That project could not be read.\n\nIt should be in:\n"
                  "{path}").format(path=creation_project.project_path(name)),
                _("Project"), wx.OK | wx.ICON_ERROR, self)
            return False
        self.project_name = data.get('name', name)
        self.messages = list(data.get('messages') or [])
        self.generated_files = dict(data.get('files') or {})
        self._last_raw = str(data.get('raw') or '')
        self._plan_text = str(data.get('plan') or '')
        self._first_description = str(data.get('description') or '')
        answers = dict(data.get('answers') or {})
        questions = list(data.get('questions') or [])
        self._interview = ([{'questions': questions, 'answers': answers}]
                           if questions else [])
        options = data.get('options') or {}
        self.web_cb.SetValue(bool(options.get('web', False)))
        self.autofix_cb.SetValue(bool(options.get('autofix', True)))
        self.ask_cb.SetValue(bool(options.get('ask', True)))

        self.transcript.SetValue('')
        self._append_transcript(
            _("Project"),
            _("{name}: {files} file(s), {turns} turn(s) so far.\n"
              "Describe what to change and press Generate - the AI still has "
              "the whole conversation.").format(
                  name=self.project_name, files=len(self.generated_files),
                  turns=len(self.messages)))
        if self._first_description:
            self._append_transcript(_("Asked for"), self._first_description)
        if self._plan_text:
            self._append_transcript(_("Plan"), self._plan_text)
        self._populate_preview(self.generated_files)
        self.save_btn.Enable(bool(self.generated_files))
        self.SetTitle(_("Create {kind} with AI - {project}").format(
            kind=self.kind['label'], project=self.project_name))
        self.status.SetLabel(_("Project opened."))
        _speak(_("Project {name} opened").format(name=self.project_name))
        self.desc.SetFocus()
        return True

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
        # A macro belongs in the user's macro list, and the macro manager only
        # reads the folder when it is asked to - so it is asked now, and the
        # macro is there to run before this dialog has closed.
        if self.kind['id'] == 'macro':
            try:
                from src.titan_core import actions
                actions.run('macros', 'reload')
            except Exception as e:
                print(f"[AICreationKit] could not refresh the macro list: {e}")
        # The same for the two kinds whose managers scan once and remember:
        # without this the add-on exists on disk and is in no list until
        # Titan is restarted, which reads as "it did not save".
        elif self.kind['id'] in ('shell_addon', 'settings_interface'):
            try:
                if self.kind['id'] == 'shell_addon':
                    from src.shell import addons as _addons
                    _addons.manager().scan(force=True)
                else:
                    from src.settings import interfaces as _interfaces
                    _interfaces.manager().scan(force=True)
                from src.titan_core import actions
                actions.invalidate()
            except Exception as e:
                print(f"[AICreationKit] could not refresh the add-on "
                      f"list: {e}")
        wx.MessageBox(_("Saved to:\n{path}").format(path=dest), _("Saved"),
                      wx.OK | wx.ICON_INFORMATION, self)
        self.EndModal(wx.ID_OK)


def open_creation_wizard(parent, kind_id, project=None):
    """Entry point used by the Programmer menu.

    `project` opens a saved session (`creation_project`) in the wizard for
    its kind, which is what "carry on with the thing I was building" means.
    """
    if not ai_provider.is_ai_enabled():
        wx.MessageBox(_("Enable AI components in Settings, AI features first."),
                      _("AI features disabled"), wx.OK | wx.ICON_INFORMATION, parent)
        return
    dlg = AICreationWizardDialog(parent, kind_id)
    if project:
        dlg.load_project(project)
    dlg.ShowModal()
    dlg.Destroy()


def open_project_browser(parent):
    """Every saved project, of every kind, in one list.

    The wizard's own Open lists the projects of the kind it is building;
    this is the way in when what the user remembers is the add-on, not which
    kind of add-on it was.
    """
    if not ai_provider.is_ai_enabled():
        wx.MessageBox(_("Enable AI components in Settings, AI features first."),
                      _("AI features disabled"), wx.OK | wx.ICON_INFORMATION,
                      parent)
        return
    projects = creation_project.list_projects()
    if not projects:
        wx.MessageBox(
            _("No projects yet. Create an add-on with AI and press Save "
              "project to keep the session."),
            _("AI projects"), wx.OK | wx.ICON_INFORMATION, parent)
        return
    labels = []
    for entry in projects:
        kind = get_kind(entry['kind'])
        labels.append(_("{name} ({kind}) - {files} file(s), last changed "
                        "{when}").format(
                            name=entry['name'],
                            kind=kind['label'] if kind else entry['kind'],
                            files=entry['files'], when=entry['updated']))
    dialog = wx.SingleChoiceDialog(parent, _("Which project?"),
                                   _("AI projects"), labels)
    try:
        if dialog.ShowModal() != wx.ID_OK:
            return
        chosen = projects[dialog.GetSelection()]
    finally:
        dialog.Destroy()
    if not get_kind(chosen['kind']):
        wx.MessageBox(_("This project was made for {kind}, which this Titan "
                        "does not have.").format(kind=chosen['kind']),
                      _("AI projects"), wx.OK | wx.ICON_WARNING, parent)
        return
    open_creation_wizard(parent, chosen['kind'], project=chosen['name'])
