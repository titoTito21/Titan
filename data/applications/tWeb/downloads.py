# -*- coding: utf-8 -*-
"""Real streaming download manager for tWeb.

Ported from data/applications/tDownloader/downloader.py's pattern:
requests.get(stream=True) + iter_content, driving a wx.ProgressDialog via
wx.CallAfter. Replaces the old memory-only downloads list with a
JSON-persisted one so it survives an app restart.
"""
import wx
import os
import json
import platform
import subprocess
import threading
import time
import requests
from translation import _

from common import _apply_skin_to_tree, play_sound, speak, get_data_path

DOWNLOADS_PATH = get_data_path('tbrowser_downloads.json')

# Extensions that are always treated as a download rather than navigated to.
DOWNLOAD_EXTENSIONS = {
    '.zip', '.exe', '.msi', '.rar', '.7z', '.tar', '.gz', '.pdf', '.doc', '.docx',
    '.xls', '.xlsx', '.ppt', '.pptx', '.mp3', '.mp4', '.avi', '.mkv', '.iso',
    '.dmg', '.apk',
}


def _load_downloads():
    if not os.path.exists(DOWNLOADS_PATH):
        return []
    try:
        with open(DOWNLOADS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def _save_downloads(items):
    try:
        os.makedirs(os.path.dirname(DOWNLOADS_PATH), exist_ok=True)
        with open(DOWNLOADS_PATH, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(_("Nie można zapisać listy pobrań: {}").format(e))


def default_download_directory():
    directory = os.path.join(os.path.expanduser('~'), 'Downloads')
    os.makedirs(directory, exist_ok=True)
    return directory


def _unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while True:
        candidate = f"{base} ({i}){ext}"
        if not os.path.exists(candidate):
            return candidate
        i += 1


def should_download(url):
    """Fast, synchronous heuristic usable inside EVT_WEBVIEW_NAVIGATING: does
    the URL's extension look like a file rather than a page?

    Deliberately extension-only (no HEAD-request sniffing): this runs on the
    UI thread for every single navigation, and a blocking network call there
    would reintroduce exactly the kind of UI stall/freeze this app just had
    fixed for the Alt key. URLs without a download-like extension fall
    through to WebView2's own default download handling, which we don't
    track in our list -- a known limitation, not a crash."""
    path = url.split('?')[0].split('#')[0]
    ext = os.path.splitext(path)[1].lower()
    return ext in DOWNLOAD_EXTENSIONS


class DownloadManager:
    """Owns the persisted download list and drives streaming downloads."""

    def __init__(self, frame):
        self.frame = frame  # top-level BrowserFrame (wx.CallAfter target)
        self.items = _load_downloads()

    def start_download(self, url, suggested_name=None):
        file_name = suggested_name or os.path.basename(url.split('?')[0]) or 'download'
        target_dir = default_download_directory()
        target_path = _unique_path(os.path.join(target_dir, file_name))

        entry = {
            'url': url,
            'file_name': os.path.basename(target_path),
            'path': target_path,
            'status': 'downloading',
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        self.items.insert(0, entry)
        _save_downloads(self.items)

        holder = {}

        def worker():
            try:
                wx.CallAfter(self._show_progress, holder, entry['file_name'])
                with requests.get(url, stream=True, timeout=30) as r:
                    r.raise_for_status()
                    total = r.headers.get('content-length')
                    total = int(total) if total else 0
                    downloaded = 0
                    with open(target_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                pct = int(downloaded / total * 100) if total > 0 else 0
                                wx.CallAfter(self._update_progress, holder, pct)
                entry['status'] = 'completed'
                threading.Thread(target=play_sound, args=('ding.ogg',), daemon=True).start()
                threading.Thread(
                    target=speak,
                    args=(_("Pobrano plik: {}").format(entry['file_name']),),
                    daemon=True).start()
            except Exception as e:
                entry['status'] = 'error'
                entry['error'] = str(e)
                threading.Thread(
                    target=speak,
                    args=(_("Błąd pobierania: {}").format(entry['file_name']),),
                    daemon=True).start()
            finally:
                _save_downloads(self.items)
                wx.CallAfter(self._close_progress, holder)

        threading.Thread(target=worker, daemon=True).start()
        return entry

    def _show_progress(self, holder, file_name):
        dlg = wx.ProgressDialog(
            _("Pobieranie"), _("Pobieranie {}").format(file_name),
            maximum=100,
            style=wx.PD_ELAPSED_TIME | wx.PD_REMAINING_TIME | wx.PD_AUTO_HIDE)
        holder['dlg'] = dlg

    def _update_progress(self, holder, pct):
        dlg = holder.get('dlg')
        if dlg:
            try:
                dlg.Update(min(pct, 100))
            except Exception:
                pass

    def _close_progress(self, holder):
        dlg = holder.get('dlg')
        if dlg:
            try:
                dlg.Destroy()
            except Exception:
                pass
            holder['dlg'] = None

    def open_file(self, path):
        try:
            if platform.system() == 'Windows':
                os.startfile(path)
            elif platform.system() == 'Darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            wx.MessageBox(_("Nie można otworzyć pliku: {}").format(e), _("Błąd"), wx.OK | wx.ICON_ERROR)

    def remove(self, index):
        if 0 <= index < len(self.items):
            del self.items[index]
            _save_downloads(self.items)


class DownloadsDialog(wx.Dialog):
    def __init__(self, parent, manager):
        super(DownloadsDialog, self).__init__(parent, title=_("Pobrane pliki"))
        self.manager = manager

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        info_text = wx.StaticText(panel, label=_("Lista plików pobranych przez tBrowser:"))
        vbox.Add(info_text, flag=wx.ALL, border=5)

        self.listbox = wx.ListBox(panel, choices=self._labels(), style=wx.LB_SINGLE)
        vbox.Add(self.listbox, proportion=1, flag=wx.ALL | wx.EXPAND, border=5)

        # Enter i Del w liście
        self.listbox.Bind(wx.EVT_KEY_DOWN, self.onKeyDown)

        panel.SetSizer(vbox)
        self.SetSize((450, 320))
        self.Centre()
        _apply_skin_to_tree(self)

    def _labels(self):
        status_labels = {
            'downloading': _("pobieranie..."),
            'completed': _("ukończono"),
            'error': _("błąd"),
        }
        return [
            "{} ({})".format(item.get('file_name', ''), status_labels.get(item.get('status'), item.get('status', '')))
            for item in self.manager.items
        ]

    def onKeyDown(self, event):
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_RETURN:
            self.openSelectedFile()
        elif keycode == wx.WXK_DELETE:
            self.removeSelectedFile()
        else:
            event.Skip()

    def openSelectedFile(self):
        selection = self.listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        item = self.manager.items[selection]
        if item.get('status') != 'completed':
            speak(_("Plik nie został jeszcze pobrany."))
            return
        self.manager.open_file(item['path'])

    def removeSelectedFile(self):
        selection = self.listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        self.manager.remove(selection)
        self.listbox.Delete(selection)
