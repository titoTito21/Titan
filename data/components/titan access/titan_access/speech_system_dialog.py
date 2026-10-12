# -*- coding: utf-8 -*-
"""Insert+Ctrl+S: choose what the reader speaks with.

A real dialog of real lists - the speech system, the synthesizer in it,
the voice of that synthesizer and, where it has them, the voice's variant
(Cerence's compact / embedded-pro / embedded-high) - with Test, OK and
Cancel. Native
controls, so the reader reads them like any other dialog and a second
reader (NVDA, Orca) would too. The model behind it is `speech_systems`.

Two things make it usable rather than merely present:

* **The voices are read on a worker.** A Titan TTS engine may have to start
  its bridge to answer (a 32-bit DLL, or Wine on Linux - seconds the first
  time), and a dialog that froze while it did would read as a reader that
  had hung. The list says "Reading the voices..." and fills itself in.
* **Opened over another program, it takes the foreground.** Titan is
  usually not the program in front when the key is pressed, and Windows
  refuses the foreground to a process that does not own it - so it is
  taken the same way the walked lists take it (`hostWindow._take`).

Escape is Cancel; Enter in a list is OK; the reader's voice changes only
on OK (Test borrows the voice for one sentence and gives it back).
"""

import threading

from .localization import L
from . import speech_systems

_open = {'dialog': None}


def open_dialog(engine):
    """Put the dialog up on the GUI thread. ``(ok, sentence)``."""
    try:
        import wx
    except Exception:                                # noqa: BLE001
        return False, L('speechSystem.noWindow')
    if wx.GetApp() is None:
        return False, L('speechSystem.noWindow')
    wx.CallAfter(_show, engine)
    return True, ''


def _show(engine):
    import wx
    existing = _open.get('dialog')
    if existing is not None:
        try:
            existing.Raise()
            _take(existing)
            return
        except Exception:                            # noqa: BLE001
            _open['dialog'] = None
    dialog = SpeechSystemDialog(engine)
    _open['dialog'] = dialog
    dialog.Show()
    dialog.Raise()
    _take(dialog)
    wx.CallLater(150, dialog.focus_first)


def _take(window):
    try:
        from . import foreground
        foreground.take(int(window.GetHandle() or 0))
    except Exception:                                # noqa: BLE001
        pass


def _engine_settings(engine):
    settings = getattr(engine, 'settings', None)
    if settings is None:
        from .settings_store import get_settings
        settings = get_settings()
    return settings


try:
    import wx as _wx
    _Base = _wx.Dialog
except Exception:                                    # noqa: BLE001
    _wx = None
    _Base = object


class SpeechSystemDialog(_Base):
    """The three lists. Built only where wx is."""

    def __init__(self, engine):
        wx = _wx
        super().__init__(None, title=L('speechSystem.title'),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
                         | wx.STAY_ON_TOP)
        self.engine = engine
        self.settings = _engine_settings(engine)
        self._systems = []
        self._synths = []
        self._voices = []
        self._variants = []
        self._token = 0
        self._variant_token = 0
        self._wanted = speech_systems.current(self.settings)
        self._wanted_variant = speech_systems.current_variant(self.settings)

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.systems = self._list(sizer, L('speechSystem.label.system'))
        self.synths = self._list(sizer, L('speechSystem.label.synth'))
        self.voices = self._list(sizer, L('speechSystem.label.voice'))
        # **The fourth level, only where a synthesizer has it**: Cerence
        # installs a voice as compact, embedded-pro or embedded-high.
        self.variants = self._list(sizer, L('speechSystem.label.variant'))
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.test = wx.Button(self, label=L('speechSystem.test'))
        ok = wx.Button(self, wx.ID_OK, L('speechSystem.ok'))
        cancel = wx.Button(self, wx.ID_CANCEL, L('speechSystem.cancel'))
        for button in (self.test, ok, cancel):
            buttons.Add(button, 0, wx.ALL, 4)
        sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
        self.SetSizer(sizer)
        self.SetSize((520, 680))
        ok.SetDefault()
        self.SetEscapeId(wx.ID_CANCEL)

        self.systems.Bind(wx.EVT_LISTBOX, lambda e: self._system_chosen())
        self.synths.Bind(wx.EVT_LISTBOX, lambda e: self._synth_chosen())
        self.voices.Bind(wx.EVT_LISTBOX, lambda e: self._voice_chosen())
        for box in (self.systems, self.synths, self.voices, self.variants):
            box.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._ok())
        self.test.Bind(wx.EVT_BUTTON, lambda e: self._test())
        ok.Bind(wx.EVT_BUTTON, lambda e: self._ok())
        cancel.Bind(wx.EVT_BUTTON, lambda e: self._close())
        self.Bind(wx.EVT_CLOSE, lambda e: self._close())
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self._fill_systems()

    def _list(self, sizer, label):
        wx = _wx
        text = wx.StaticText(self, label=label)
        box = wx.ListBox(self, style=wx.LB_SINGLE)
        box.SetName(label.replace('&', '').rstrip(':'))
        sizer.Add(text, 0, wx.LEFT | wx.TOP, 6)
        sizer.Add(box, 1, wx.EXPAND | wx.ALL, 6)
        return box

    def focus_first(self):
        try:
            self.systems.SetFocus()
        except Exception:                            # noqa: BLE001
            pass

    # ------------------------------------------------------------------ #
    def _on_key(self, event):
        wx = _wx
        key = event.GetKeyCode()
        if key == wx.WXK_ESCAPE:
            self._close()
            return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and \
                isinstance(self.FindFocus(), wx.ListBox):
            self._ok()
            return
        event.Skip()

    def _fill_systems(self):
        self._systems = speech_systems.systems()
        self.systems.Set([label for _id, label in self._systems])
        ids = [one for one, _label in self._systems]
        at = ids.index(self._wanted[0]) if self._wanted[0] in ids else 0
        if ids:
            self.systems.SetSelection(at)
        self._system_chosen()

    def _system(self):
        at = self.systems.GetSelection()
        return self._systems[at][0] if 0 <= at < len(self._systems) else ''

    def _synth(self):
        at = self.synths.GetSelection()
        return self._synths[at][0] if 0 <= at < len(self._synths) else ''

    def _voice(self):
        at = self.voices.GetSelection()
        return self._voices[at][0] if 0 <= at < len(self._voices) else ''

    def _variant(self):
        at = self.variants.GetSelection()
        return self._variants[at][0] if 0 <= at < len(self._variants) else ''

    def _system_chosen(self):
        system = self._system()
        self._synths = speech_systems.synthesizers(system)
        self.synths.Set([label for _id, label in self._synths])
        ids = [one for one, _label in self._synths]
        wanted = self._wanted[1] if system == self._wanted[0] else ''
        if ids:
            self.synths.SetSelection(ids.index(wanted) if wanted in ids else 0)
        self._synth_chosen()

    def _synth_chosen(self):
        synth = self._synth()
        system = self._system()
        self._voices = []
        self._token += 1
        token = self._token
        if system == speech_systems.SYSTEM_TITAN or not synth:
            self.voices.Set([L('speechSystem.voice.titan')])
            self.voices.Enable(False)
            self._no_variants()
            return
        self.voices.Enable(True)
        self.voices.Set([L('speechSystem.reading')])
        wanted = self._wanted[2] if synth == self._wanted[1] else ''

        def work():
            found = speech_systems.voices(synth)
            _wx.CallAfter(self._voices_arrived, token, found, wanted)
        threading.Thread(target=work, name='TitanAccessVoices',
                         daemon=True).start()

    def _voices_arrived(self, token, found, wanted):
        if token != self._token:
            return
        try:
            self._voices = list(found)
            if not self._voices:
                self.voices.Set([L('speechSystem.noVoices')])
                self._no_variants()
                return
            self.voices.Set([label for _id, label in self._voices])
            ids = [one for one, _label in self._voices]
            self.voices.SetSelection(ids.index(wanted) if wanted in ids
                                     else 0)
            self._voice_chosen()
        except RuntimeError:
            # The dialog closed while the voices were being read.
            pass

    def _no_variants(self):
        self._variants = []
        self._variant_token += 1
        self.variants.Set([L('speechSystem.noVariants')])
        self.variants.Enable(False)

    def _voice_chosen(self):
        synth, voice = self._synth(), self._voice()
        if not _variants_possible(synth) or not voice:
            self._no_variants()
            return
        self._variant_token += 1
        token = self._variant_token
        self.variants.Enable(True)
        self.variants.Set([L('speechSystem.reading')])
        wanted = self._wanted_variant if (synth, voice) == \
            (self._wanted[1], self._wanted[2]) else ''

        def work():
            found = speech_systems.variants(synth, voice)
            _wx.CallAfter(self._variants_arrived, token, found, wanted)
        threading.Thread(target=work, name='TitanAccessVariants',
                         daemon=True).start()

    def _variants_arrived(self, token, found, wanted):
        if token != self._variant_token:
            return
        try:
            self._variants = list(found)
            if not self._variants:
                self._no_variants()
                return
            self.variants.Enable(True)
            self.variants.Set([label for _id, label in self._variants])
            ids = [one for one, _label in self._variants]
            if wanted in ids:
                self.variants.SetSelection(ids.index(wanted))
            else:
                # Nothing chosen yet: the one the synthesizer is using.
                from .nvda_host import external
                now = external.variant(self._synth())
                self.variants.SetSelection(ids.index(now) if now in ids
                                           else 0)
        except RuntimeError:
            pass

    # ------------------------------------------------------------------ #
    def _test(self):
        system = self._system()
        sample = L('speechSystem.sample')
        try:
            from . import speech_adapter
            if system == speech_systems.SYSTEM_TITAN:
                speech_adapter.speak(sample)
                return
            profile = speech_systems.profile_of(self._synth(), self._voice(),
                                                self._variant())
            if not speech_adapter.speak_with(profile, sample):
                speech_adapter.speak(sample)
        except Exception as error:                   # noqa: BLE001
            print(f"[TitanAccess] speech system test: {error}")

    def _ok(self):
        system = self._system()
        if system != speech_systems.SYSTEM_TITAN and not self._synth():
            return
        voice = self._voice()
        said = speech_systems.choose(self.settings, system, self._synth(),
                                     voice, engine=self.engine,
                                     variant=self._variant())
        self._close()
        try:
            from . import speech_adapter
            threading.Timer(0.3, lambda: speech_adapter.speak(said)).start()
        except Exception:                            # noqa: BLE001
            pass

    def _close(self):
        _open['dialog'] = None
        self._token += 1
        self._variant_token += 1
        try:
            self.Destroy()
        except Exception:                            # noqa: BLE001
            pass


def _variants_possible(synth):
    """A synthesizer with a variant level: an NVDA add-on synthesizer
    (Cerence's compact / embedded-pro...) or eSpeak (its voices/!v)."""
    synth = str(synth or '')
    return synth.startswith('nvda:') or synth in ('espeak', 'espeak_dll')
