# -*- coding: utf-8 -*-
"""Titan Antivirus: a scanner built on the ClamAV engine.

How it is started, and what each start means:

* with no argument - the window;
* with the path of a request file (what the shell add-on's
  "Scan with antivirus" writes) - the window, scanning what was asked;
* with ``--guard`` - no window: the Downloads watcher and the scheduled scan,
  and the window only when there is something to show.

Only one runs at a time. A second start leaves its request in the requests
folder and exits; the running one picks it up within a second, which is how
a second "Scan with antivirus" from the shell reaches the window that is
already open instead of opening another.

Accessibility is native, which is what makes a screen reader's semantics
possible at all: the results are a real report-mode list whose columns are
File, Threat, Status and Location (`readerModules/tantivirus.py` tells both
of Titan's readers that the Threat column is what a row IS), the progress is
a real `wx.Gauge` (a reader's progress monitor hears it as tones), the
status bar is a live region, and a threat is put in front of the user as a
real warning dialog - the icon is how a reader knows it is a warning before
it reads a word of it.
"""

import os
import sys
import threading
import time

import wx

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from translation import _                                   # noqa: E402
import av_store                                             # noqa: E402
import av_engine                                            # noqa: E402
import av_defender                                          # noqa: E402
import av_quarantine                                        # noqa: E402
import av_guard                                             # noqa: E402
import av_dialogs                                           # noqa: E402

TITLE = 'Titan Antivirus'
#: How often the status bar is rewritten while a scan runs. It is a live
#: region: rewritten per file it would be read per file.
STATUS_EVERY = 3.0


# --------------------------------------------------------------------------
# Titan's voice and sounds, when Titan is there
# --------------------------------------------------------------------------
def speak(text):
    try:
        from src.titan_core.tce_speech import speak as titan_speak
        titan_speak(text)
        return
    except Exception:                                # noqa: BLE001
        pass
    try:
        import accessible_output3.outputs.auto as auto
        auto.Auto().speak(text, interrupt=True)
    except Exception:                                # noqa: BLE001
        pass


def play(name):
    try:
        from src.titan_core.sound import play_sound
        play_sound(name)
    except Exception:                                # noqa: BLE001
        pass


def error_text(code):
    """The sentence for an `EngineError` code."""
    code = str(code or '')
    head = code.split(':', 1)[0]
    words = {
        'not_installed': _("The ClamAV engine is not installed."),
        'no_databases': _("The virus signatures have not been downloaded "
                          "yet. Update the signatures first."),
        'clamd_died': _("The ClamAV scanning service stopped while "
                        "starting."),
        'clamd_timeout': _("The ClamAV scanning service did not start in "
                           "time."),
        'clamd_closed': _("The ClamAV scanning service closed the "
                          "connection."),
        'update_failed': _("The signatures could not be updated. Check the "
                           "internet connection."),
        'release_list': _("The list of ClamAV releases could not be read."),
        'no_windows_build': _("No ClamAV build for Windows was found."),
        'download': _("ClamAV could not be downloaded."),
        'checksum': _("The downloaded ClamAV did not match its checksum and "
                      "was thrown away."),
        'archive': _("The downloaded ClamAV archive is damaged."),
        'install_with_system': _("Install ClamAV with your system's package "
                                 "manager (clamav, clamav-daemon, "
                                 "clamav-freshclam)."),
        'defender_missing': _("Microsoft Defender is not available on this "
                              "computer."),
        'refused': _("The ClamAV update server refused this ClamAV, "
                     "usually because it is too old. Install a current "
                     "ClamAV, or let your system's freshclam service keep "
                     "the signatures up to date."),
        'cancelled': _("Cancelled."),
    }
    return words.get(head, _("Error: {error}").format(error=code))


STATUS_WORDS = {
    'found': lambda: _("Detected"),
    'quarantined': lambda: _("Quarantined"),
    'deleted': lambda: _("Deleted"),
    'ignored': lambda: _("Ignored"),
    'excluded': lambda: _("Excluded"),
    'failed': lambda: _("Action failed"),
}


def engine_word(engine):
    return _("Microsoft Defender") if engine == 'defender' else 'ClamAV'


# --------------------------------------------------------------------------
# Acting on a threat
# --------------------------------------------------------------------------
def act_on(finding, action):
    """Quarantine, delete, ignore or exclude one finding; answer its new
    status. Never raises: a file Windows holds open is reported as an
    action that failed."""
    try:
        if action == 'quarantine':
            av_quarantine.put(finding.path, finding.threat, finding.engine)
            finding.status = 'quarantined'
        elif action == 'delete':
            os.remove(finding.path)
            finding.status = 'deleted'
        elif action == 'exclude':
            exclusions = list(av_store.get('exclusions') or [])
            if finding.path not in exclusions:
                exclusions.append(finding.path)
            av_store.update(exclusions=exclusions)
            finding.status = 'excluded'
        else:
            finding.status = 'ignored'
    except OSError:
        finding.status = 'failed'
    return finding.status


def ask_about_threat(parent, finding, where=''):
    """One threat, one warning dialog: Quarantine / Delete / Ignore.

    A classic message box holding the real warning icon (`av_dialogs`):
    a reader says "warning" before the text because it can see the icon,
    which is the only honest way an application in its own process can say
    it.
    """
    message = _("Threat found: {threat}\n\nFile: {path}").format(
        threat=finding.threat, path=finding.path)
    if where:
        message = where + '\n\n' + message
    play('core/error.ogg')
    answer = av_dialogs.warning(parent, message,
                                _("Titan Antivirus - threat found"),
                                (_("&Quarantine"), _("&Delete"), _("&Ignore")))
    if answer == 'yes':
        return act_on(finding, 'quarantine')
    if answer == 'no':
        if wx.MessageBox(_("Delete {name} permanently?").format(
                name=os.path.basename(finding.path)), TITLE,
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                parent) == wx.YES:
            return act_on(finding, 'delete')
    return act_on(finding, 'ignore')


# --------------------------------------------------------------------------
# Engine setup: download ClamAV, then the signatures
# --------------------------------------------------------------------------
class SetupDialog(wx.Dialog):
    """Downloading the engine and the signatures, with a real progress bar
    and freshclam's own words in a read-only box the reader can review."""

    def __init__(self, parent, install_engine):
        super().__init__(parent, title=_("Preparing the ClamAV engine"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.install_engine = install_engine
        self.cancelled = False
        self.ok = False
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.label = wx.StaticText(self, label=_("Starting..."))
        self.gauge = wx.Gauge(self, range=100, size=(400, -1))
        self.gauge.SetName(_("Download progress"))
        log_label = wx.StaticText(self, label=_("&Details:"))
        self.log = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY,
                               size=(500, 200))
        self.button = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        for control in (self.label, self.gauge, log_label, self.log):
            sizer.Add(control, 0 if control is not self.log else 1,
                      wx.EXPAND | wx.ALL, 6)
        sizer.Add(self.button, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
        self.SetSizerAndFit(sizer)
        self.button.Bind(wx.EVT_BUTTON, self._on_cancel)
        self.Bind(wx.EVT_CLOSE, self._on_cancel)
        threading.Thread(target=self._work, daemon=True).start()

    def _on_cancel(self, event):
        if self.ok or self.cancelled:
            self.EndModal(wx.ID_OK if self.ok else wx.ID_CANCEL)
            return
        self.cancelled = True
        self.label.SetLabel(_("Cancelling..."))

    def _say(self, text):
        wx.CallAfter(self._set_label, text)

    def _set_label(self, text):
        if self:
            self.label.SetLabel(text)
            self.log.AppendText(text + '\n')

    def _work(self):
        try:
            if self.install_engine:
                self._say(_("Downloading the ClamAV engine..."))

                def progress(done, total):
                    if total:
                        wx.CallAfter(self._set_gauge, int(done * 100 / total))
                av_engine.download_engine(progress, lambda: self.cancelled)
                self._say(_("The ClamAV engine is installed."))
            self._say(_("Downloading the virus signatures. The first time "
                        "this is about 300 MB and takes several minutes."))
            wx.CallAfter(self._pulse)
            av_engine.update_databases(
                lambda line: wx.CallAfter(self._log_line, line),
                lambda: self.cancelled)
            self.ok = True
            self._say(_("The signatures are up to date."))
            play('ui/notify.ogg')
        except av_engine.EngineError as error:
            self._say(error_text(error))
            play('core/error.ogg')
        wx.CallAfter(self._finished)

    def _set_gauge(self, value):
        if self:
            self.gauge.SetValue(max(0, min(100, value)))

    def _pulse(self):
        if self:
            self.gauge.Pulse()

    def _log_line(self, line):
        if self:
            self.log.AppendText(line + '\n')
            self.gauge.Pulse()

    def _finished(self):
        if not self:
            return
        self.gauge.SetValue(100 if self.ok else 0)
        self.button.SetLabel(_("&Close"))
        self.button.SetFocus()
        speak(self.label.GetLabel())


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
class SettingsDialog(wx.Dialog):
    ACTIONS = ('ask', 'quarantine', 'delete', 'report')
    SCOPES = ('quick', 'full', 'custom')

    def __init__(self, parent):
        super().__init__(parent, title=_("Titan Antivirus settings"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        settings = av_store.settings()
        sizer = wx.BoxSizer(wx.VERTICAL)

        threats = wx.StaticBoxSizer(wx.VERTICAL, self, _("Threats"))
        threats.Add(wx.StaticText(threats.GetStaticBox(),
                                  label=_("&When a threat is found:")),
                    0, wx.ALL, 4)
        self.action = wx.Choice(threats.GetStaticBox(), choices=[
            _("Ask what to do"), _("Quarantine automatically"),
            _("Delete automatically"), _("Only report")])
        self.action.SetSelection(self.ACTIONS.index(
            settings['threat_action']) if settings['threat_action']
            in self.ACTIONS else 0)
        threats.Add(self.action, 0, wx.EXPAND | wx.ALL, 4)
        sizer.Add(threats, 0, wx.EXPAND | wx.ALL, 6)

        engine = wx.StaticBoxSizer(wx.VERTICAL, self, _("Engine"))
        box = engine.GetStaticBox()
        self.use_clamd = wx.CheckBox(box, label=_(
            "Keep the &scanning service loaded between scans (faster, uses "
            "about 1 GB of memory)"))
        self.use_clamd.SetValue(bool(settings['use_clamd']))
        engine.Add(self.use_clamd, 0, wx.ALL, 4)
        engine.Add(wx.StaticText(box, label=_(
            "Stop the scanning service after this many &idle minutes "
            "(0 = never):")), 0, wx.ALL, 4)
        self.idle = wx.SpinCtrl(box, min=0, max=1440,
                                initial=int(settings['clamd_idle_minutes']))
        engine.Add(self.idle, 0, wx.ALL, 4)
        engine.Add(wx.StaticText(box, label=_(
            "&Largest file to scan, in megabytes:")), 0, wx.ALL, 4)
        self.max_mb = wx.SpinCtrl(box, min=1, max=4000,
                                  initial=int(settings['max_file_mb']))
        engine.Add(self.max_mb, 0, wx.ALL, 4)
        self.archives = wx.CheckBox(box, label=_("Scan inside &archives"))
        self.archives.SetValue(bool(settings['scan_archives']))
        engine.Add(self.archives, 0, wx.ALL, 4)
        self.update_on_start = wx.CheckBox(box, label=_(
            "&Update the signatures when Titan Antivirus starts, if they are "
            "older than a day"))
        self.update_on_start.SetValue(bool(settings['update_on_start']))
        engine.Add(self.update_on_start, 0, wx.ALL, 4)
        sizer.Add(engine, 0, wx.EXPAND | wx.ALL, 6)

        guard = wx.StaticBoxSizer(wx.VERTICAL, self, _("Background protection"))
        box = guard.GetStaticBox()
        self.watch = wx.CheckBox(box, label=_(
            "&Watch the Downloads folder and scan every new file"))
        self.watch.SetValue(bool(settings['watch_downloads']))
        guard.Add(self.watch, 0, wx.ALL, 4)
        self.schedule = wx.CheckBox(box, label=_("Run a scheduled scan &every day"))
        self.schedule.SetValue(bool(settings['schedule_enabled']))
        guard.Add(self.schedule, 0, wx.ALL, 4)
        guard.Add(wx.StaticText(box, label=_(
            "Scheduled scan &time (hours:minutes):")), 0, wx.ALL, 4)
        self.time = wx.TextCtrl(box, value=str(settings['schedule_time']))
        guard.Add(self.time, 0, wx.ALL, 4)
        guard.Add(wx.StaticText(box, label=_("Scheduled scan &covers:")),
                  0, wx.ALL, 4)
        self.scope = wx.Choice(box, choices=[
            _("Quick scan (Downloads, Desktop, Documents, temporary files)"),
            _("Full scan (every fixed drive)"),
            _("The folders below")])
        self.scope.SetSelection(self.SCOPES.index(settings['schedule_scope'])
                                if settings['schedule_scope'] in self.SCOPES
                                else 0)
        guard.Add(self.scope, 0, wx.EXPAND | wx.ALL, 4)
        self.folders = self._path_list(box, guard, _("Scheduled scan &folders:"),
                                       settings['schedule_folders'])
        guard.Add(wx.StaticText(box, label=_(
            "Background protection runs while Titan's shell is on, or while "
            "Titan Antivirus is open.")), 0, wx.ALL, 4)
        sizer.Add(guard, 0, wx.EXPAND | wx.ALL, 6)

        exclusions = wx.StaticBoxSizer(wx.VERTICAL, self, _("Exclusions"))
        self.exclusions = self._path_list(exclusions.GetStaticBox(), exclusions,
                                          _("&Never scan:"),
                                          settings['exclusions'])
        sizer.Add(exclusions, 0, wx.EXPAND | wx.ALL, 6)

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizerAndFit(sizer)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.action.SetFocus()

    def _path_list(self, parent, sizer, label, paths):
        sizer.Add(wx.StaticText(parent, label=label), 0, wx.ALL, 4)
        box = wx.ListBox(parent, choices=list(paths or []), size=(-1, 80))
        box.SetName(label.replace('&', '').rstrip(':'))
        sizer.Add(box, 0, wx.EXPAND | wx.ALL, 4)
        row = wx.BoxSizer(wx.HORIZONTAL)
        add_folder = wx.Button(parent, label=_("Add folder..."))
        add_file = wx.Button(parent, label=_("Add file..."))
        remove = wx.Button(parent, label=_("Remove"))
        for button in (add_folder, add_file, remove):
            row.Add(button, 0, wx.RIGHT, 4)
        sizer.Add(row, 0, wx.ALL, 4)

        def on_folder(event):
            with wx.DirDialog(self, _("Choose a folder")) as chooser:
                if chooser.ShowModal() == wx.ID_OK:
                    box.Append(chooser.GetPath())

        def on_file(event):
            with wx.FileDialog(self, _("Choose a file")) as chooser:
                if chooser.ShowModal() == wx.ID_OK:
                    box.Append(chooser.GetPath())

        def on_remove(event):
            index = box.GetSelection()
            if index != wx.NOT_FOUND:
                box.Delete(index)

        add_folder.Bind(wx.EVT_BUTTON, on_folder)
        add_file.Bind(wx.EVT_BUTTON, on_file)
        remove.Bind(wx.EVT_BUTTON, on_remove)
        return box

    def _on_ok(self, event):
        text = self.time.GetValue().strip()
        try:
            hour, minute = (int(part) for part in text.split(':'))
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError
        except ValueError:
            wx.MessageBox(_("Write the time as hours:minutes, for example "
                            "12:30."), TITLE, wx.OK | wx.ICON_ERROR, self)
            self.time.SetFocus()
            return
        av_store.update(
            threat_action=self.ACTIONS[self.action.GetSelection()],
            use_clamd=self.use_clamd.GetValue(),
            clamd_idle_minutes=self.idle.GetValue(),
            max_file_mb=self.max_mb.GetValue(),
            scan_archives=self.archives.GetValue(),
            update_on_start=self.update_on_start.GetValue(),
            watch_downloads=self.watch.GetValue(),
            schedule_enabled=self.schedule.GetValue(),
            schedule_time='%02d:%02d' % (hour, minute),
            schedule_scope=self.SCOPES[self.scope.GetSelection()],
            schedule_folders=list(self.folders.GetItems()),
            exclusions=list(self.exclusions.GetItems()))
        self.EndModal(wx.ID_OK)


# --------------------------------------------------------------------------
# Quarantine and history
# --------------------------------------------------------------------------
def _report_list(parent, name, columns):
    control = wx.ListCtrl(parent, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
    control.SetName(name)
    for index, (title, width) in enumerate(columns):
        control.InsertColumn(index, title, width=width)
    return control


def _when(stamp):
    try:
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(float(stamp)))
    except (TypeError, ValueError):
        return ''


class QuarantineDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Quarantine"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.list = _report_list(self, _("Quarantined files"), [
            (_("Name"), 200), (_("Threat"), 220),
            (_("Original location"), 260), (_("Date"), 130)])
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.restore = wx.Button(self, label=_("&Restore"))
        self.delete = wx.Button(self, label=_("&Delete permanently"))
        close = wx.Button(self, wx.ID_CANCEL, _("&Close"))
        for button in (self.restore, self.delete, close):
            row.Add(button, 0, wx.RIGHT, 6)
        sizer.Add(row, 0, wx.ALL, 6)
        self.SetSizer(sizer)
        self.SetSize((860, 420))
        self.restore.Bind(wx.EVT_BUTTON, lambda e: self._restore())
        self.delete.Bind(wx.EVT_BUTTON, lambda e: self._delete())
        self.list.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self._fill()
        self.list.SetFocus()

    def _fill(self):
        self.records = av_quarantine.items()
        self.list.DeleteAllItems()
        for record in self.records:
            index = self.list.InsertItem(self.list.GetItemCount(),
                                         record.get('name', ''))
            self.list.SetItem(index, 1, record.get('threat', ''))
            self.list.SetItem(index, 2, os.path.dirname(record.get('path', '')))
            self.list.SetItem(index, 3, _when(record.get('time')))
        if self.records:
            self.list.Select(0)
            self.list.Focus(0)
        enabled = bool(self.records)
        self.restore.Enable(enabled)
        self.delete.Enable(enabled)

    def _selected(self):
        index = self.list.GetFirstSelected()
        return self.records[index] if 0 <= index < len(self.records) else None

    def _on_key(self, event):
        if event.GetKeyCode() == wx.WXK_DELETE:
            self._delete()
        else:
            event.Skip()

    def _restore(self):
        record = self._selected()
        if not record:
            return
        if wx.MessageBox(_("Restore {name}? It was detected as {threat}.")
                         .format(name=record.get('name'),
                                 threat=record.get('threat')),
                         TITLE, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
                         self) != wx.YES:
            return
        try:
            path = av_quarantine.restore(record['id'])
            speak(_("Restored to {path}").format(path=path))
        except (OSError, ValueError, KeyError):
            wx.MessageBox(_("The file could not be restored."), TITLE,
                          wx.OK | wx.ICON_ERROR, self)
        self._fill()

    def _delete(self):
        record = self._selected()
        if not record:
            return
        if wx.MessageBox(_("Delete {name} permanently?").format(
                name=record.get('name')), TITLE,
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) != wx.YES:
            return
        try:
            av_quarantine.delete(record['id'])
        except (OSError, ValueError, KeyError):
            pass
        self._fill()


class HistoryDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Scan history"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.list = _report_list(self, _("Finished scans"), [
            (_("Date"), 130), (_("Scanned"), 300), (_("Engine"), 120),
            (_("Files"), 70), (_("Threats"), 70)])
        for record in av_store.history():
            index = self.list.InsertItem(self.list.GetItemCount(),
                                         _when(record.get('time')))
            what = record.get('label') or ', '.join(record.get('paths') or [])
            self.list.SetItem(index, 1, what)
            self.list.SetItem(index, 2, engine_word(record.get('engine')))
            self.list.SetItem(index, 3, str(record.get('files', 0)))
            self.list.SetItem(index, 4, str(len(record.get('findings') or [])))
        if self.list.GetItemCount():
            self.list.Select(0)
            self.list.Focus(0)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
        sizer.Add(wx.Button(self, wx.ID_CANCEL, _("&Close")), 0,
                  wx.ALIGN_RIGHT | wx.ALL, 6)
        self.SetSizer(sizer)
        self.SetSize((760, 420))
        self.list.SetFocus()


# --------------------------------------------------------------------------
# The main window
# --------------------------------------------------------------------------
class MainFrame(wx.Frame):
    def __init__(self, app):
        super().__init__(None, title=TITLE, size=(860, 520))
        self.app = app
        self.job = None
        self.findings = []
        self.queue = []
        self.last_status = 0.0
        self.background_only = False

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.state = wx.StaticText(panel, label='')
        sizer.Add(self.state, 0, wx.EXPAND | wx.ALL, 6)
        # Its own label, right before it: UI Automation names a control
        # after the text in front of it, and without this the progress bar
        # was read as the engine's status sentence.
        sizer.Add(wx.StaticText(panel, label=_("Scan progress")), 0,
                  wx.LEFT | wx.TOP, 6)
        self.gauge = wx.Gauge(panel, range=100)
        self.gauge.SetName(_("Scan progress"))
        sizer.Add(self.gauge, 0, wx.EXPAND | wx.ALL, 6)
        sizer.Add(wx.StaticText(panel, label=_("&Threats found:")), 0,
                  wx.LEFT | wx.TOP, 6)
        self.results = _report_list(panel, _("Scan results"), [
            (_("File"), 220), (_("Threat"), 240), (_("Status"), 130),
            (_("Location"), 260)])
        sizer.Add(self.results, 1, wx.EXPAND | wx.ALL, 6)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.quick_button = wx.Button(panel, label=_("&Quick scan"))
        self.folder_button = wx.Button(panel, label=_("Scan a &folder..."))
        self.update_button = wx.Button(panel, label=_("&Update signatures"))
        self.cancel_button = wx.Button(panel, label=_("&Cancel scan"))
        for button in (self.quick_button, self.folder_button,
                       self.update_button, self.cancel_button):
            row.Add(button, 0, wx.RIGHT, 6)
        sizer.Add(row, 0, wx.ALL, 6)
        panel.SetSizer(sizer)

        self.status = self.CreateStatusBar()
        self._build_menu()

        self.quick_button.Bind(wx.EVT_BUTTON, lambda e: self.quick_scan())
        self.folder_button.Bind(wx.EVT_BUTTON, lambda e: self.choose_and_scan(
            folder=True))
        self.update_button.Bind(wx.EVT_BUTTON, lambda e: self.update_signatures())
        self.cancel_button.Bind(wx.EVT_BUTTON, lambda e: self.cancel_scan())
        self.results.Bind(wx.EVT_LIST_ITEM_ACTIVATED,
                          lambda e: self.result_menu())
        self.results.Bind(wx.EVT_CONTEXT_MENU, lambda e: self.result_menu())
        self.results.Bind(wx.EVT_KEY_DOWN, self._on_results_key)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self._set_busy(False)
        self.refresh_state()

    # ------------------------------------------------------------------
    def _build_menu(self):
        bar = wx.MenuBar()
        scan = wx.Menu()
        self._item(scan, _("&Quick scan\tF5"), self.quick_scan)
        self._item(scan, _("F&ull scan"), self.full_scan)
        self._item(scan, _("Scan a &file...\tCtrl+O"),
                   lambda: self.choose_and_scan(folder=False))
        self._item(scan, _("Scan a f&older...\tCtrl+Shift+O"),
                   lambda: self.choose_and_scan(folder=True))
        scan.AppendSeparator()
        self.defender_item = self._item(
            scan, _("Scan a folder with Microsoft &Defender..."),
            lambda: self.choose_and_scan(folder=True, engine='defender'))
        self.defender_item.Enable(av_defender.available())
        scan.AppendSeparator()
        self._item(scan, _("&Cancel scan"), self.cancel_scan)
        scan.AppendSeparator()
        self._item(scan, _("E&xit"), self.exit_completely)
        bar.Append(scan, _("&Scan"))

        engine = wx.Menu()
        self._item(engine, _("&Update signatures\tCtrl+U"),
                   self.update_signatures)
        self._item(engine, _("Engine &status\tCtrl+I"), self.say_state)
        bar.Append(engine, _("&Engine"))

        tools = wx.Menu()
        self._item(tools, _("&Quarantine...\tCtrl+Q"), self.open_quarantine)
        self._item(tools, _("Scan &history...\tCtrl+H"), self.open_history)
        self._item(tools, _("&Settings...\tCtrl+P"), self.open_settings)
        bar.Append(tools, _("&Tools"))
        self.SetMenuBar(bar)

    def _item(self, menu, label, handler):
        item = menu.Append(wx.ID_ANY, label)
        self.Bind(wx.EVT_MENU, lambda event: handler(), item)
        return item

    # ------------------------------------------------------------------
    def state_text(self):
        programs = av_engine.locate()
        if not programs['clamscan']:
            return _("The ClamAV engine is not installed.")
        age = av_engine.database_age_days()
        if age is None:
            return _("The virus signatures have not been downloaded yet.")
        days = int(age)
        if days == 0:
            when = _("today")
        elif days == 1:
            when = _("yesterday")
        else:
            when = _("{days} days ago").format(days=days)
        service = _("loaded") if self.app.clamd.running() else _("not loaded")
        return _("ClamAV ready. Signatures updated {when}. Scanning service "
                 "{service}.").format(when=when, service=service)

    def refresh_state(self):
        self.state.SetLabel(self.state_text())
        self.state.SetName(_("Engine status"))

    def say_state(self):
        self.refresh_state()
        speak(self.state.GetLabel())

    def set_status(self, text, force=False):
        now = time.time()
        if force or now - self.last_status >= STATUS_EVERY:
            self.last_status = now
            self.status.SetStatusText(text)

    def _set_busy(self, busy):
        self.cancel_button.Enable(busy)
        for button in (self.quick_button, self.folder_button,
                       self.update_button):
            button.Enable(not busy)

    # ------------------------------------------------------------------
    def ensure_engine(self):
        """True when ClamAV and its signatures are there - downloading them
        first, with the user's permission, when they are not."""
        installed = av_engine.installed()
        if installed and av_engine.has_databases():
            return True
        if not installed and not av_engine.IS_WINDOWS:
            wx.MessageBox(error_text('install_with_system'), TITLE,
                          wx.OK | wx.ICON_INFORMATION, self)
            return False
        if not installed:
            question = _("The ClamAV engine is not installed yet. Download "
                         "it now from the official ClamAV releases, and then "
                         "the virus signatures (about 300 MB)?")
        else:
            question = _("The virus signatures have not been downloaded yet. "
                         "Download them now (about 300 MB)?")
        if wx.MessageBox(question, TITLE, wx.YES_NO | wx.ICON_QUESTION,
                         self) != wx.YES:
            return False
        dialog = SetupDialog(self, install_engine=not installed)
        dialog.ShowModal()
        ok = dialog.ok
        dialog.Destroy()
        self.refresh_state()
        return ok

    def update_signatures(self):
        if not av_engine.installed() or not av_engine.has_databases():
            self.ensure_engine()
            return
        if self.job:
            return
        dialog = SetupDialog(self, install_engine=False)
        dialog.ShowModal()
        dialog.Destroy()
        self.refresh_state()
        # A loaded clamd holds the old signatures; the next scan starts
        # it again with the new ones.
        threading.Thread(target=self.app.clamd.stop, daemon=True).start()

    # ------------------------------------------------------------------
    def quick_scan(self):
        self.start_scan(av_engine.quick_scan_folders(), label=_("Quick scan"))

    def full_scan(self):
        self.start_scan(av_engine.full_scan_folders(), label=_("Full scan"))

    def choose_and_scan(self, folder=True, engine='clamav'):
        if folder:
            with wx.DirDialog(self, _("Choose a folder to scan")) as chooser:
                if chooser.ShowModal() != wx.ID_OK:
                    return
                paths = [chooser.GetPath()]
        else:
            with wx.FileDialog(self, _("Choose files to scan"),
                               style=wx.FD_OPEN | wx.FD_MULTIPLE
                               | wx.FD_FILE_MUST_EXIST) as chooser:
                if chooser.ShowModal() != wx.ID_OK:
                    return
                paths = chooser.GetPaths()
        self.start_scan(paths, engine=engine)

    def start_scan(self, paths, engine='clamav', label='', quiet=False):
        """Start one scan, or queue it behind the one running."""
        paths = [path for path in paths if path]
        if not paths:
            return
        if self.job is not None:
            self.queue.append((paths, engine, label, quiet))
            if not quiet:
                speak(_("The scan will start when the current one finishes."))
            return
        if engine == 'clamav' and not self.ensure_engine():
            return
        if engine == 'defender' and not av_defender.available():
            wx.MessageBox(error_text('defender_missing'), TITLE,
                          wx.OK | wx.ICON_ERROR, self)
            return
        if not label:
            label = paths[0] if len(paths) == 1 else _(
                "{count} items").format(count=len(paths))
        self.findings = []
        self.results.DeleteAllItems()
        self.gauge.SetValue(0)
        self._set_busy(True)
        self.current_label = label
        self.current_quiet = quiet
        self.job = av_engine.ScanJob(
            paths, engine=engine, label=label, clamd=self.app.clamd,
            on_status=lambda key, **values: wx.CallAfter(self._on_status, key),
            on_progress=lambda done, total, path: wx.CallAfter(
                self._on_progress, done, total, path),
            on_found=lambda finding: wx.CallAfter(self._on_found, finding),
            on_done=lambda summary: wx.CallAfter(self._on_done, summary))
        self.job.start()
        if not quiet:
            speak(_("Scanning {what} with {engine}").format(
                what=label, engine=engine_word(engine)))

    def cancel_scan(self):
        if self.job is not None:
            self.job.cancel()
            self.set_status(_("Cancelling..."), force=True)

    def _on_status(self, key):
        words = {'counting': _("Counting files..."),
                 'starting_engine': _("Starting the scanning engine. Loading "
                                      "the signatures takes a while..."),
                 'scanning': _("Scanning...")}
        self.set_status(words.get(key, key), force=True)
        if key == 'starting_engine':
            self.gauge.Pulse()

    def _on_progress(self, done, total, path):
        if total:
            self.gauge.SetValue(int(done * 100 / total))
        self.set_status(_("Scanned {done} of {total} files").format(
            done=done, total=total))

    def _on_found(self, finding):
        self.findings.append(finding)
        self._show_finding(finding)
        play('core/error.ogg')
        action = av_store.get('threat_action')
        if action in ('quarantine', 'delete'):
            act_on(finding, action)
            self._update_row(finding)

    def _show_finding(self, finding):
        index = self.results.InsertItem(self.results.GetItemCount(),
                                        os.path.basename(finding.path))
        self.results.SetItem(index, 1, finding.threat)
        self.results.SetItem(index, 3, os.path.dirname(finding.path))
        self._update_row(finding, index)
        if index == 0:
            self.results.Select(0)
            self.results.Focus(0)

    def _update_row(self, finding, index=None):
        if index is None:
            try:
                index = self.findings.index(finding)
            except ValueError:
                return
        word = STATUS_WORDS.get(finding.status, STATUS_WORDS['found'])()
        self.results.SetItem(index, 2, word)

    def _on_done(self, summary):
        self.job = None
        self._set_busy(False)
        self.gauge.SetValue(100 if not summary.get('error') else 0)
        if summary.get('error'):
            text = error_text(summary['error'])
        elif summary.get('cancelled'):
            text = _("Scan cancelled after {files} files. Threats: "
                     "{threats}.").format(**summary)
        elif summary['threats']:
            text = _("Scan finished: {files} files, {threats} threats "
                     "found.").format(**summary)
        else:
            text = _("Scan finished: {files} files, no threats found.").format(
                **summary)
        if summary.get('errors') or summary.get('skipped'):
            text += ' ' + _("{errors} files could not be read, {skipped} were "
                            "too large.").format(**summary)
        self.set_status(text, force=True)
        self.refresh_state()
        quiet = getattr(self, 'current_quiet', False)
        if summary.get('error'):
            play('core/error.ogg')
        elif not summary['threats']:
            play('ui/notify.ogg')
        if not quiet or summary['threats']:
            speak(text)
        if summary['threats'] and av_store.get('threat_action') == 'ask':
            self._ask_about_findings()
        if self.queue:
            paths, engine, label, quiet = self.queue.pop(0)
            wx.CallLater(300, self.start_scan, paths, engine, label, quiet)
        elif self.background_only and not self.IsShown():
            self.app.maybe_exit()

    def _ask_about_findings(self):
        """One question about every threat at once, then the list."""
        waiting = [one for one in self.findings if one.status == 'found']
        if not waiting:
            return
        if not self.IsShown():
            self.app.show_window()
        if len(waiting) == 1:
            ask_about_threat(self, waiting[0])
            self._update_row(waiting[0])
            return
        answer = av_dialogs.warning(
            self, _("{count} threats were found. Quarantine all of them now?")
            .format(count=len(waiting)), _("Titan Antivirus - threats found"),
            (_("&Quarantine all"), _("&Review in the list")))
        if answer == 'yes':
            for finding in waiting:
                act_on(finding, 'quarantine')
                self._update_row(finding)
            failed = [one for one in waiting if one.status == 'failed']
            if failed:
                speak(_("{count} files could not be quarantined.").format(
                    count=len(failed)))
        self.results.SetFocus()

    # ------------------------------------------------------------------
    def _selected_finding(self):
        index = self.results.GetFirstSelected()
        if 0 <= index < len(self.findings):
            return self.findings[index]
        return None

    def result_menu(self):
        finding = self._selected_finding()
        if finding is None:
            return
        menu = wx.Menu()
        choices = [(_("&Quarantine"), 'quarantine'), (_("&Delete"), 'delete'),
                   (_("&Ignore"), 'ignore'),
                   (_("Never scan this file (&exclude)"), 'exclude')]
        for label, action in choices:
            item = menu.Append(wx.ID_ANY, label)
            item.Enable(finding.status in ('found', 'ignored', 'failed'))
            self.Bind(wx.EVT_MENU, lambda event, action=action:
                      self._act_selected(action), item)
        menu.AppendSeparator()
        folder = menu.Append(wx.ID_ANY, _("Open the &containing folder"))
        self.Bind(wx.EVT_MENU, lambda event: self._open_folder(finding), folder)
        self.results.PopupMenu(menu)
        menu.Destroy()

    def _act_selected(self, action):
        finding = self._selected_finding()
        if finding is None:
            return
        if action == 'delete' and wx.MessageBox(
                _("Delete {name} permanently?").format(
                    name=os.path.basename(finding.path)), TITLE,
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) != wx.YES:
            return
        status = act_on(finding, action)
        self._update_row(finding)
        speak(STATUS_WORDS.get(status, STATUS_WORDS['found'])())

    def _open_folder(self, finding):
        folder = os.path.dirname(finding.path)
        try:
            from src.shell import explorer
            explorer.open_explorer(folder)
            return
        except Exception:                            # noqa: BLE001
            pass
        try:
            if sys.platform == 'win32':
                os.startfile(folder)
            else:
                import subprocess
                subprocess.Popen(['xdg-open', folder])
        except OSError:
            pass

    def _on_results_key(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_DELETE:
            self._act_selected('delete')
        else:
            event.Skip()

    def _on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE and self.job is not None:
            self.cancel_scan()
            return
        event.Skip()

    # ------------------------------------------------------------------
    def open_quarantine(self):
        dialog = QuarantineDialog(self)
        dialog.ShowModal()
        dialog.Destroy()

    def open_history(self):
        dialog = HistoryDialog(self)
        dialog.ShowModal()
        dialog.Destroy()

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.ShowModal() == wx.ID_OK:
            self.app.apply_settings()
        dialog.Destroy()

    def _on_close(self, event):
        if self.job is not None and wx.MessageBox(
                _("A scan is running. Stop it and close?"), TITLE,
                wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            event.Veto()
            return
        if self.job is not None:
            self.job.cancel()
        if self.app.guard.active() and event.CanVeto():
            event.Veto()
            self.Hide()
            self.background_only = True
            speak(_("Titan Antivirus keeps protecting in the background."))
            return
        self.exit_completely()

    def exit_completely(self):
        if self.job is not None:
            self.job.cancel()
        self.app.shutdown()


# --------------------------------------------------------------------------
# The application
# --------------------------------------------------------------------------
class AntivirusApp(wx.App):
    def __init__(self, arguments):
        self.arguments = arguments
        super().__init__(False)

    def OnInit(self):
        self.SetAppName(TITLE)
        self.clamd = av_engine.Clamd()
        self.guard = av_guard.Guard(
            on_download=lambda path: wx.CallAfter(self._downloaded, path),
            on_schedule=lambda scope: wx.CallAfter(self._scheduled, scope))
        self.frame = MainFrame(self)
        guard_mode = '--guard' in self.arguments
        requests = [one for one in self.arguments
                    if one.endswith('.json') and os.path.isfile(one)]
        self.apply_settings()
        if not guard_mode:
            self.show_window()
        else:
            self.frame.background_only = True
        for path in requests:
            self._handle(av_store.read_request(path))
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_timer, self.timer)
        self.timer.Start(1000)
        if av_store.get('update_on_start') and av_engine.installed():
            age = av_engine.database_age_days()
            if age is not None and age >= 1:
                threading.Thread(target=self._quiet_update, daemon=True).start()
        if guard_mode and not self.guard.active() and not requests:
            wx.CallAfter(self.maybe_exit)
        return True

    def _quiet_update(self):
        try:
            av_engine.update_databases()
            self.clamd.stop()
        except av_engine.EngineError:
            pass
        wx.CallAfter(lambda: self.frame and self.frame.refresh_state())

    def apply_settings(self):
        av_engine.write_configs()
        if self.guard.active():
            self.guard.start()
        else:
            self.guard.stop()

    def show_window(self):
        self.frame.background_only = False
        self.frame.Show()
        self.frame.Raise()
        self.frame.results.SetFocus()

    def _on_timer(self, event):
        for path in av_store.pending_requests():
            self._handle(av_store.read_request(path))

    def _handle(self, request):
        if not request:
            return
        if request['kind'] == 'show':
            self.show_window()
        elif request['kind'] == 'guard':
            self.apply_settings()
        elif request['kind'] == 'quick':
            self.show_window()
            self.frame.quick_scan()
        elif request['kind'] == 'scan' and request['paths']:
            self.show_window()
            self.frame.start_scan(request['paths'],
                                  engine=request.get('engine') or 'clamav')

    def _downloaded(self, path):
        """A new file in Downloads: scanned quietly, said only if bad."""
        if not (av_engine.installed() and av_engine.has_databases()):
            return
        self.frame.start_scan([path], label=os.path.basename(path),
                              quiet=True)

    def _scheduled(self, scope):
        if scope == 'full':
            paths, label = av_engine.full_scan_folders(), _("Full scan")
        elif scope == 'custom':
            paths = av_store.get('schedule_folders') or []
            label = _("Scheduled scan")
        else:
            paths, label = av_engine.quick_scan_folders(), _("Quick scan")
        speak(_("Scheduled scan started."))
        self.frame.start_scan(paths, label=label, quiet=True)

    def maybe_exit(self):
        """In the background with nothing to guard and nothing running:
        there is no reason to stay."""
        if self.frame.IsShown() or self.frame.job is not None:
            return
        if not self.guard.active():
            self.shutdown()

    def shutdown(self):
        try:
            self.timer.Stop()
        except Exception:                            # noqa: BLE001
            pass
        self.guard.stop()
        self.clamd.stop()
        av_store.release_instance()
        if self.frame:
            self.frame.Destroy()
            self.frame = None
        self.ExitMainLoop()


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if not av_store.claim_instance():
        # Another one is running: hand it what this start was for.
        requests = [one for one in arguments if one.endswith('.json')]
        if not requests and '--guard' not in arguments:
            av_store._write_json(os.path.join(
                av_store.folder('requests'), 'show-%d.json' % os.getpid()),
                {'kind': 'show', 'paths': []})
        elif '--guard' in arguments:
            av_store._write_json(os.path.join(
                av_store.folder('requests'), 'guard-%d.json' % os.getpid()),
                {'kind': 'guard', 'paths': []})
        return 0
    try:
        app = AntivirusApp(arguments)
        app.MainLoop()
    finally:
        av_store.release_instance()
    return 0


if __name__ == '__main__':
    sys.exit(main())
