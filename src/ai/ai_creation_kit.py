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

import os
import re
import shutil
import tempfile
import threading
import time
import traceback

import wx

from src.ai import ai_provider
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
    """Announce ``text`` to the screen reader (best effort, never raises)."""
    try:
        from src.accessibility.messages import speak_sr_only
        speak_sr_only(text)
        return
    except Exception:
        pass
    try:
        from src.system.notifications import speak_notification
        speak_notification(text, 'info')
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Kind catalogue
# --------------------------------------------------------------------------- #
# Each kind: id (matches titan_package.NAME_TO_KIND for packageable kinds),
# display label, data subdir, manifest filename (for the prompt/validation),
# and whether it can be packed into a .TCA/.TCD.
KINDS = [
    {'id': 'app',              'label': _("Application"),      'subdir': 'applications',      'manifest': '__app.TCE',           'package': True},
    {'id': 'game',             'label': _("Game"),            'subdir': 'games',             'manifest': '__game.TCE',          'package': True},
    {'id': 'component',        'label': _("Component"),       'subdir': 'components',        'manifest': '__component__.TCE',   'package': True},
    {'id': 'launcher',         'label': _("Launcher"),        'subdir': 'launchers',         'manifest': '__launcher.TCE',      'package': True},
    {'id': 'im_module',        'label': _("IM Module"),       'subdir': 'titanIM_modules',   'manifest': '__im_module.TCE',     'package': True},
    {'id': 'gamepad_mode',     'label': _("Gamepad Mode"),    'subdir': 'gamepad/modes',     'manifest': '__mode.TCE',          'package': True},
    {'id': 'tts_engine',       'label': _("TTS Engine"),      'subdir': 'titantts engines',  'manifest': '__engine.TCE',        'package': True},
    {'id': 'widget',           'label': _("Widget"),          'subdir': 'applets',           'manifest': '__applet.TCE',        'package': True},
    {'id': 'statusbar_applet', 'label': _("Statusbar Applet"),'subdir': 'statusbar_applets', 'manifest': '__statusbar.TCE',     'package': True},
    {'id': 'language',         'label': _("Language"),        'subdir': None,                'manifest': None,                  'package': False},
]

_KIND_BY_ID = {k['id']: k for k in KINDS}

# Line marker that delimits generated files. Chosen to be extremely unlikely to
# appear at the start of a real source/manifest/po line.
_FILE_MARKER = re.compile(r'^@@FILE:\s*(.+?)\s*$')

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


def build_system_prompt(kind):
    manifest_line = (
        f"- Include the manifest file exactly as the reference shows (named "
        f"'{kind['manifest']}').\n" if kind['manifest'] else
        "- Follow the file naming and format shown in the reference example.\n")
    prompt = [
        f"You are the Titan add-on creator. You generate a complete, working "
        f"Titan {kind['label']} as a set of files.",
        "",
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
        manifest_line.rstrip('\n'),
        "- All user-facing UI text and messages MUST be in English. Use the "
        "gettext function _() for translatable strings wherever the reference "
        "example does.",
        "- Never use emojis in user-facing text or notifications.",
        "- Follow the structure, manifest keys and conventions shown in the "
        "reference example below.",
        "- Make the code self-contained and runnable; the entry point named in "
        "the manifest must exist.",
        "",
        f"REFERENCE EXAMPLE (an existing Titan {kind['label']}):",
    ]
    example = _read_example_files(kind)
    if example:
        for rel, content in example:
            prompt.append(f"@@FILE: {rel}")
            prompt.append(content.rstrip('\n'))
    else:
        prompt.append("(no reference example available; use standard Titan "
                       "add-on conventions)")
    return '\n'.join(prompt)


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


def validate_files(kind, files):
    """Return (ok, message). Lenient: needs at least one non-empty file, and —
    when the kind has a known manifest — that manifest to be present."""
    if not files:
        return False, _("The model returned no files.")
    if not any(v.strip() for v in files.values()):
        return False, _("The generated files are empty.")
    if kind['manifest'] and not any(
            os.path.basename(p) == kind['manifest'] for p in files):
        return False, _("The manifest file {name} is missing.").format(
            name=kind['manifest'])
    return True, ''


def _derive_name(kind, files):
    """Best-effort add-on folder name from the manifest 'shortname' key, else
    the first path component, else a timestamp."""
    for path, content in files.items():
        if kind['manifest'] and os.path.basename(path) == kind['manifest']:
            m = re.search(r'^\s*shortname\s*=\s*"?([^"\r\n]+)"?', content, re.M)
            if m:
                return _safe_dirname(m.group(1))
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

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.gen_btn = wx.Button(panel, label=_("Generate"))
        self.gen_btn.Bind(wx.EVT_BUTTON, self.OnGenerate)
        row.Add(self.gen_btn, flag=wx.RIGHT, border=6)
        self.status = wx.StaticText(panel, label='')
        row.Add(self.status, flag=wx.ALIGN_CENTER_VERTICAL)
        vbox.Add(row, flag=wx.LEFT | wx.TOP, border=10)

        # Real, moving progress: an indeterminate gauge pulsed on a timer while
        # the model streams, so the dialog never looks frozen.
        self.gauge = wx.Gauge(panel, range=100, size=(-1, 16))
        vbox.Add(self.gauge, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, border=10)
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

    # -- generation ------------------------------------------------------- #
    def OnGenerate(self, event):
        text = self.desc.GetValue().strip()
        if not text:
            wx.MessageBox(_("Please describe what to create."), _("Error"),
                          wx.OK | wx.ICON_WARNING, self)
            return
        if not ai_provider.is_ai_ready():
            wx.MessageBox(_("AI features are not configured. Enable them and set "
                            "a method in Settings, AI features."),
                          _("AI not configured"), wx.OK | wx.ICON_WARNING, self)
            return
        # Multi-turn: include the previous generation so the model refines.
        if self.generated_files and (not self.messages or self.messages[-1]['role'] != 'assistant'):
            self.messages.append({"role": "assistant",
                                  "content": self._last_raw or ''})
        self.messages.append({"role": "user", "content": text})
        self._append_transcript(_("You"), text)
        self.desc.SetValue("")

        self.gen_btn.Enable(False)
        self.save_btn.Enable(False)
        self._stream_buf = []
        self._file_announced = set()
        self._gen_start = time.time()
        self.status.SetLabel(_("Generating..."))
        self._pulse_timer.Start(100)
        _speak(_("Generating {kind}").format(kind=self.kind['label']))

        system = build_system_prompt(self.kind)
        convo = list(self.messages)

        def _work():
            try:
                raw = ai_provider.generate(system, convo, on_chunk=self._on_chunk)
                wx.CallAfter(self._on_done, raw, None)
            except Exception as e:
                traceback.print_exc()
                wx.CallAfter(self._on_done, None, str(e))

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
        # Keep the status as a live counter when not mid-file-announce.
        if not self._file_announced:
            self.status.SetLabel(_("Generating... {n} chars, {s}s").format(n=chars, s=elapsed))

    def _on_pulse(self, event):
        self.gauge.Pulse()

    def _on_done(self, raw, error):
        self._pulse_timer.Stop()
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
        files = parse_files(raw)
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
        self.status.SetLabel(_("Done: {n} file(s). Review below, then Save.").format(
            n=len(files)))
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
