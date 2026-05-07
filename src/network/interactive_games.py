"""
Titan-Net Interactive Games (Entertainment tab)
================================================

Standalone GUI module that lets Titan-Net users browse, create and run
interactive games where an AI (Gemini, OpenAI or Anthropic) acts as the
game master. Architecture mirrors ``src.network.feedback_hub``:

    - virtual tab bar in row 0 of the main listbox
        (``All games, 1 of 3`` / ``My games, 2 of 3`` / ``Active sessions, 3 of 3``)
    - Left / Right on row 0 cycles tabs
    - Up / Down navigates entries (focus earcons + end-of-list bell)
    - Enter activates the focused entry (opens detail dialog)
    - Ctrl+N creates a new game, F5 refreshes
    - Escape returns to Titan-Net

A session lobby is launched in its own frame (see
``src.network.interactive_game_session``) so the catalog window stays
usable while a game is in progress.

All notification messages and on-screen text are in English; translation
is handled by the ``interactive_games`` gettext domain.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Optional, Dict, List

import wx

from src.titan_core.translation import set_language
from src.settings.settings import get_setting
from src.titan_core.sound import (
    play_sound,
    initialize_sound,
    play_focus_sound,
    play_endoflist_sound,
)
from src.titan_core.skin_manager import apply_skin_to_window

# Pull translations through the multi-domain wrapper. The dedicated
# ``interactive_games`` gettext domain is registered in
# src/titan_core/translation.py so strings here resolve from
# languages/<lang>/LC_MESSAGES/interactive_games.mo.
_ = set_language(get_setting('language', 'pl'))

try:
    import accessible_output3.outputs.auto as _ao_auto
    _local_speaker = _ao_auto.Auto()
except Exception as _e:
    print(f"[Interactive Games] accessible_output3 unavailable: {_e}")
    _local_speaker = None


def speak_titannet(text, position=0.0, pitch_offset=0, interrupt=True):
    """Speak via titan_net_gui's stereo helper, falling back to ao3."""
    if not text:
        return
    try:
        from src.network import titan_net_gui  # late import - circular safe
        helper = getattr(titan_net_gui, 'speak_titannet', None)
        if helper is not None:
            helper(text, position=position, pitch_offset=pitch_offset, interrupt=interrupt)
            return
    except Exception as e:
        print(f"[Interactive Games] speak_titannet helper failed: {e}")
    if _local_speaker is not None:
        try:
            _local_speaker.speak(str(text), interrupt=interrupt)
        except Exception as e:
            print(f"[Interactive Games] ao3 speak failed: {e}")
    print(f"[Interactive Games] {text}")


def speak_notification(text, notification_type='info', play_sound_effect=True):
    """Mirror titan_net_gui.speak_notification panoramic notification."""
    if not text:
        return
    try:
        from src.network import titan_net_gui
        helper = getattr(titan_net_gui, 'speak_notification', None)
        if helper is not None:
            helper(text, notification_type=notification_type, play_sound_effect=play_sound_effect)
            return
    except Exception as e:
        print(f"[Interactive Games] speak_notification helper failed: {e}")

    if play_sound_effect:
        sound_map = {
            'error': 'core/error.ogg',
            'warning': 'core/error.ogg',
            'success': 'core/SELECT.ogg',
            'info': 'ui/dialog.ogg',
        }
        try:
            play_sound(sound_map.get(notification_type, 'ui/dialog.ogg'))
        except Exception:
            pass
    speak_titannet(text)


# Make sure the sound mixer is up even when the catalog is launched in a
# context where the main TCE GUI never started (idempotent).
try:
    initialize_sound()
except Exception as _e:
    print(f"[Interactive Games] initialize_sound() failed at import: {_e}")


def _show_skinned_message(message, caption, style=wx.OK | wx.ICON_INFORMATION, parent=None):
    dlg = wx.MessageDialog(parent, message, caption, style)
    try:
        apply_skin_to_window(dlg)
    except Exception:
        pass
    result = dlg.ShowModal()
    dlg.Destroy()
    return result


def _is_screen_reader_running() -> bool:
    """Same SR detection contract as TitanApp/Feedback Hub."""
    try:
        from src.ui.gui import _is_screen_reader_running as _gui_check
        return bool(_gui_check())
    except Exception:
        pass
    try:
        if _local_speaker is None:
            return False
        output = _local_speaker.get_first_available_output()
        if output is None:
            return False
        if output.is_system_output():
            return False
        is_active = getattr(output, 'is_active', None)
        if callable(is_active):
            return bool(is_active())
        return True
    except Exception:
        return False


def _announce_tab_bar() -> None:
    try:
        from src.accessibility.messages import announce_tab_bar as _a
        _a()
        return
    except Exception as e:
        print(f"[Interactive Games] announce_tab_bar import failed: {e}")
    try:
        play_sound('ui/tapbar.ogg')
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GAME_TABS = (
    ('all',      lambda: _("All games")),
    ('mine',     lambda: _("My games")),
    ('sessions', lambda: _("Active sessions")),
)

PROVIDER_LABELS = (
    ('gemini',    'Google Gemini'),
    ('openai',    'OpenAI'),
    ('anthropic', 'Anthropic Claude'),
)

ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024      # 25 MB per file
TOTAL_ATTACHMENT_BYTES = 250 * 1024 * 1024   # 250 MB total — folder uploads
                                             # let creators ship larger games
                                             # (gamebooks, soundscape packs)

# Used by the file picker / classification on the client; mirrors
# server-side GAMES_ALLOWED_EXTS.
EXT_TO_TYPE = {
    '.zip': 'rules_zip',
    '.txt': 'prompt_txt',
    '.md': 'prompt_txt',
    '.json': 'prompt_txt',
    '.ogg': 'sound',
    '.wav': 'sound',
    '.mp3': 'sound',
    '.flac': 'sound',
    '.opus': 'sound',
}


def _classify_attachment(name: str) -> str:
    ext = os.path.splitext(name or '')[1].lower()
    return EXT_TO_TYPE.get(ext, 'other')


def _provider_label(provider_id: str) -> str:
    for pid, label in PROVIDER_LABELS:
        if pid == provider_id:
            return label
    return provider_id or '?'


# ---------------------------------------------------------------------------
# Dialog: New game
# ---------------------------------------------------------------------------

class NewGameDialog(wx.Dialog):
    """Form for publishing a new interactive game.

    Fields:
        - Name (single line, required)
        - Description (multi-line)
        - Provider (Gemini / OpenAI / Anthropic)
        - API key (single line, treated like a password — ``wx.TE_PASSWORD``)
        - Max tokens / max minutes / max players (advanced)
        - Rules text (multi-line — written by the creator, read by the AI
          as part of the system prompt)
        - Attachments (zip + txt + sound effects)
    """

    def __init__(self, parent):
        super().__init__(parent, title=_("New interactive game"), size=(640, 700),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.attachments: List[Dict] = []  # [{type, name, bytes, mime_type}]
        self.result_payload: Optional[Dict] = None
        self._build()
        self.Centre()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        try:
            play_sound('ui/dialog.ogg')
        except Exception:
            pass

    def _build(self):
        panel = wx.ScrolledWindow(self)
        panel.SetScrollRate(0, 16)
        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(panel, label=_("Name:")),
                 flag=wx.LEFT | wx.TOP, border=10)
        self.name_ctrl = wx.TextCtrl(panel)
        vbox.Add(self.name_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.Add(wx.StaticText(panel, label=_("Description:")),
                 flag=wx.LEFT | wx.TOP, border=10)
        self.desc_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE,
                                     size=(-1, 80))
        vbox.Add(self.desc_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.Add(wx.StaticText(panel, label=_("AI provider:")),
                 flag=wx.LEFT | wx.TOP, border=10)
        self.provider_ctrl = wx.Choice(panel, choices=[label for _id, label in PROVIDER_LABELS])
        self.provider_ctrl.SetSelection(0)
        vbox.Add(self.provider_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.Add(wx.StaticText(panel, label=_("API key (kept encrypted on the server):")),
                 flag=wx.LEFT | wx.TOP, border=10)
        self.api_ctrl = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        vbox.Add(self.api_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        # --- Limits row ---
        limits_label = wx.StaticText(panel, label=_("Per-session limits (cap to keep your bill safe):"))
        vbox.Add(limits_label, flag=wx.LEFT | wx.TOP, border=10)
        limits = wx.BoxSizer(wx.HORIZONTAL)
        limits.Add(wx.StaticText(panel, label=_("Max tokens:")),
                   flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=5)
        self.tokens_ctrl = wx.SpinCtrl(panel, min=10000, max=2_000_000, initial=200000)
        limits.Add(self.tokens_ctrl, flag=wx.LEFT | wx.RIGHT, border=5)
        limits.Add(wx.StaticText(panel, label=_("Max minutes:")),
                   flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=5)
        self.minutes_ctrl = wx.SpinCtrl(panel, min=5, max=240, initial=60)
        limits.Add(self.minutes_ctrl, flag=wx.LEFT | wx.RIGHT, border=5)
        limits.Add(wx.StaticText(panel, label=_("Max players:")),
                   flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=5)
        self.players_ctrl = wx.SpinCtrl(panel, min=1, max=12, initial=6)
        limits.Add(self.players_ctrl, flag=wx.LEFT | wx.RIGHT, border=5)
        vbox.Add(limits, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=5)

        vbox.Add(wx.StaticText(panel, label=_("Rules text for the AI game master (optional):")),
                 flag=wx.LEFT | wx.TOP, border=10)
        self.rules_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(-1, 120))
        vbox.Add(self.rules_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        rules_hint = wx.StaticText(panel, label=_(
            "Tip: instead of typing rules here, drop a folder via 'Add folder...'. "
            "Any .txt/.md at the root becomes the main rules. Subfolders such as "
            "objects/, classes/, quests/, npcs/ become labeled entity catalogs the "
            "AI references during play."))
        rules_hint.Wrap(580)
        vbox.Add(rules_hint, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        # --- Attachments row ---
        att_box = wx.BoxSizer(wx.HORIZONTAL)
        self.attach_btn = wx.Button(panel, label=_("Add attachment (zip / txt / sound)..."))
        self.attach_btn.Bind(wx.EVT_BUTTON, self._on_pick_attachment)
        att_box.Add(self.attach_btn, flag=wx.ALL, border=5)
        self.attach_folder_btn = wx.Button(panel, label=_("Add folder..."))
        self.attach_folder_btn.Bind(wx.EVT_BUTTON, self._on_pick_folder)
        att_box.Add(self.attach_folder_btn, flag=wx.ALL, border=5)
        self.clear_btn = wx.Button(panel, label=_("Remove last"))
        self.clear_btn.Disable()
        self.clear_btn.Bind(wx.EVT_BUTTON, self._on_remove_last_attachment)
        att_box.Add(self.clear_btn, flag=wx.ALL, border=5)
        vbox.Add(att_box, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=5)

        self.attach_list = wx.ListBox(panel, style=wx.LB_SINGLE, size=(-1, 100))
        vbox.Add(self.attach_list, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        # --- Action row ---
        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self.send_btn = wx.Button(panel, label=_("Publish game"))
        self.send_btn.Bind(wx.EVT_BUTTON, self._on_send)
        btn_box.Add(self.send_btn, flag=wx.ALL, border=5)
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, label=_("Cancel"))
        btn_box.Add(cancel_btn, flag=wx.ALL, border=5)
        vbox.Add(btn_box, flag=wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, border=5)

        panel.SetSizer(vbox)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(panel, proportion=1, flag=wx.EXPAND)
        self.SetSizer(sizer)
        self.name_ctrl.SetFocus()

    def _on_key(self, event: wx.KeyEvent):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        event.Skip()

    def _on_pick_attachment(self, event):
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass
        wildcard = (
            _("Game rules (*.zip)") + "|*.zip|"
            + _("Prompt / rules text (*.txt;*.md;*.json)") + "|*.txt;*.md;*.json|"
            + _("Sound effects (*.ogg;*.wav;*.mp3;*.flac;*.opus)") + "|*.ogg;*.wav;*.mp3;*.flac;*.opus|"
            + _("All files") + " (*.*)|*.*"
        )
        with wx.FileDialog(self, _("Select attachment"),
                           wildcard=wildcard,
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()

        try:
            size = os.path.getsize(path)
        except OSError as e:
            _show_skinned_message(_("Cannot read file: {error}").format(error=str(e)),
                          _("Attachment"), wx.OK | wx.ICON_ERROR)
            return
        if size > ATTACHMENT_MAX_BYTES:
            _show_skinned_message(_("Attachment is too large. Maximum size is 25 MB."),
                          _("Attachment"), wx.OK | wx.ICON_ERROR)
            return
        total = sum(len(a.get('bytes') or b'') for a in self.attachments) + size
        if total > TOTAL_ATTACHMENT_BYTES:
            _show_skinned_message(
                _("Total attachments exceed {limit} MB.").format(
                    limit=TOTAL_ATTACHMENT_BYTES // (1024 * 1024)),
                _("Attachment"), wx.OK | wx.ICON_ERROR)
            return

        try:
            with open(path, 'rb') as fh:
                data = fh.read()
        except OSError as e:
            _show_skinned_message(_("Cannot read file: {error}").format(error=str(e)),
                          _("Attachment"), wx.OK | wx.ICON_ERROR)
            return

        name = os.path.basename(path)
        atype = _classify_attachment(name)
        if atype == 'other':
            _show_skinned_message(
                _("Unsupported file type. Use .zip (rules), .txt/.md/.json (prompts) or .ogg/.wav/.mp3/.flac/.opus (sounds)."),
                _("Attachment"), wx.OK | wx.ICON_ERROR)
            return

        self.attachments.append({
            'type': atype,
            'name': name,
            'folder_path': '',
            'bytes': data,
            'mime_type': None,
        })
        self.attach_list.Append(_("[{type}] {name} ({size} KB)").format(
            type=atype, name=name, size=max(1, size // 1024)))
        self.clear_btn.Enable()
        speak_notification(_("Attachment added: {name}").format(name=name), 'info')

    def _on_pick_folder(self, event):
        """Recursively add every supported file from a directory tree.

        Lets a creator ship larger games (gamebook chapters, soundscape
        packs, multiple rules files) without picking each file by hand.
        Each file's relative path inside the folder is preserved as
        ``folder_path`` so the server can rebuild the structure on disk
        and the AI can refer to files by their relative path.
        """
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass
        with wx.DirDialog(self, _("Select folder to add"),
                          style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            root = dlg.GetPath()

        added = 0
        skipped_unsupported = 0
        skipped_too_large = 0
        rules_at_root = 0  # .txt / .md sitting in the upload root → main rules
        section_counts: Dict[str, int] = {}  # subfolder name → file count
        running_total = sum(len(a.get('bytes') or b'') for a in self.attachments)

        for dirpath, _dirnames, filenames in os.walk(root):
            for fname in filenames:
                full = os.path.join(dirpath, fname)
                ext = os.path.splitext(fname)[1].lower()
                if ext not in EXT_TO_TYPE:
                    skipped_unsupported += 1
                    continue
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                if size > ATTACHMENT_MAX_BYTES:
                    skipped_too_large += 1
                    continue
                if running_total + size > TOTAL_ATTACHMENT_BYTES:
                    _show_skinned_message(
                        _("Total attachments would exceed {limit} MB. "
                          "Stopping at {added} files.").format(
                              limit=TOTAL_ATTACHMENT_BYTES // (1024 * 1024),
                              added=added),
                        _("Attachment"), wx.OK | wx.ICON_WARNING)
                    break
                try:
                    with open(full, 'rb') as fh:
                        data = fh.read()
                except OSError:
                    continue
                rel = os.path.relpath(dirpath, root).replace('\\', '/')
                if rel in ('', '.'):
                    rel = ''
                atype = _classify_attachment(fname)
                self.attachments.append({
                    'type': atype,
                    'name': fname,
                    'folder_path': rel,
                    'bytes': data,
                    'mime_type': None,
                })
                shown_name = f"{rel}/{fname}" if rel else fname
                self.attach_list.Append(_("[{type}] {name} ({size} KB)").format(
                    type=atype, name=shown_name, size=max(1, size // 1024)))
                running_total += size
                added += 1
                # Track the new folder convention so we can announce what
                # the AI will see (main rules vs. labeled entity catalogs).
                if atype == 'prompt_txt':
                    if not rel:
                        rules_at_root += 1
                    else:
                        section_key = rel.split('/', 1)[0].strip().lower() or 'main'
                        section_counts[section_key] = section_counts.get(section_key, 0) + 1
            else:
                continue
            break  # propagate the inner break (size cap hit)

        if added:
            self.clear_btn.Enable()
            speak_notification(
                _("Added {n} files from folder").format(n=added), 'info')
            if rules_at_root:
                speak_notification(
                    _("Found {n} rules file(s) at folder root - "
                      "manual rules text is optional now").format(n=rules_at_root),
                    'success')
            if section_counts:
                summary = ', '.join(
                    f"{name} ({count})"
                    for name, count in sorted(section_counts.items()))
                speak_notification(
                    _("Entity catalogs detected: {sections}").format(sections=summary),
                    'info')
        else:
            speak_notification(_("No supported files found in folder"), 'warning')

        if skipped_unsupported or skipped_too_large:
            print(f"[Interactive Games] folder upload: {added} added, "
                  f"{skipped_unsupported} unsupported, {skipped_too_large} too large")

    def _on_remove_last_attachment(self, event):
        if not self.attachments:
            return
        removed = self.attachments.pop()
        self.attach_list.Delete(self.attach_list.GetCount() - 1)
        if not self.attachments:
            self.clear_btn.Disable()
        speak_notification(_("Removed: {name}").format(name=removed.get('name')), 'info')

    def _on_send(self, event):
        name = self.name_ctrl.GetValue().strip()
        api_key = self.api_ctrl.GetValue().strip()
        if not name:
            speak_notification(_("Name is required"), 'error')
            self.name_ctrl.SetFocus()
            return
        if not api_key:
            speak_notification(_("API key is required"), 'error')
            self.api_ctrl.SetFocus()
            return
        provider_idx = self.provider_ctrl.GetSelection()
        provider = PROVIDER_LABELS[provider_idx][0] if provider_idx >= 0 else 'gemini'

        self.result_payload = {
            'name': name,
            'description': self.desc_ctrl.GetValue().strip(),
            'provider': provider,
            'api_key': api_key,
            'max_tokens': self.tokens_ctrl.GetValue(),
            'max_minutes': self.minutes_ctrl.GetValue(),
            'max_players': self.players_ctrl.GetValue(),
            'rules_text': self.rules_ctrl.GetValue().strip(),
            'attachments': list(self.attachments),
        }
        self.EndModal(wx.ID_OK)


# ---------------------------------------------------------------------------
# Dialog: Game detail / start session / delete
# ---------------------------------------------------------------------------

class GameDetailDialog(wx.Dialog):
    """Inspect a game and decide what to do — start a session, join an
    existing one, delete (if owner / moderator) or download an attachment.
    """

    def __init__(self, parent, titan_client, game_id: int):
        super().__init__(parent, title=_("Game details"), size=(680, 600),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.titan_client = titan_client
        self.game_id = game_id
        self.game: Optional[Dict] = None
        self.deleted = False
        self.session_started: Optional[int] = None  # session_id of started lobby

        self._build()
        self.Centre()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        try:
            play_sound('ui/dialog.ogg')
        except Exception:
            pass
        self._reload(initial=True)

    @property
    def is_moderator(self) -> bool:
        return bool(getattr(self.titan_client, 'is_admin', False)
                    or getattr(self.titan_client, 'user_role', 'user') in ('moderator', 'developer'))

    @property
    def is_owner(self) -> bool:
        return bool(self.game and self.game.get('creator_id') == getattr(self.titan_client, 'user_id', None))

    def _build(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(panel, label=_("Name:")), flag=wx.LEFT | wx.TOP, border=10)
        self.name_ctrl = wx.TextCtrl(panel, style=wx.TE_READONLY)
        vbox.Add(self.name_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.Add(wx.StaticText(panel, label=_("Creator / provider / limits:")),
                 flag=wx.LEFT | wx.TOP, border=10)
        self.meta_ctrl = wx.TextCtrl(panel, style=wx.TE_READONLY)
        vbox.Add(self.meta_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.Add(wx.StaticText(panel, label=_("Description:")),
                 flag=wx.LEFT | wx.TOP, border=10)
        self.desc_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY,
                                     size=(-1, 80))
        vbox.Add(self.desc_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.Add(wx.StaticText(panel, label=_("Attachments:")),
                 flag=wx.LEFT | wx.TOP, border=10)
        self.att_list = wx.ListBox(panel, style=wx.LB_SINGLE, size=(-1, 90))
        vbox.Add(self.att_list, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        # --- Action row ---
        btn_box = wx.BoxSizer(wx.HORIZONTAL)

        self.start_btn = wx.Button(panel, label=_("Start session"))
        self.start_btn.Bind(wx.EVT_BUTTON, self._on_start_session)
        btn_box.Add(self.start_btn, flag=wx.ALL, border=5)

        self.open_att_btn = wx.Button(panel, label=_("Download attachment"))
        self.open_att_btn.Bind(wx.EVT_BUTTON, self._on_open_attachment)
        btn_box.Add(self.open_att_btn, flag=wx.ALL, border=5)

        self.delete_btn = wx.Button(panel, label=_("Delete game"))
        self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        self.delete_btn.Hide()
        btn_box.Add(self.delete_btn, flag=wx.ALL, border=5)

        close_btn = wx.Button(panel, wx.ID_CLOSE, label=_("Close"))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        btn_box.Add(close_btn, flag=wx.ALL, border=5)

        vbox.Add(btn_box, flag=wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, border=5)

        panel.SetSizer(vbox)
        self.SetEscapeId(wx.ID_CLOSE)

    def _on_key(self, event: wx.KeyEvent):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CLOSE)
            return
        event.Skip()

    def _reload(self, initial=False):
        def _fetch():
            result = self.titan_client.get_game(self.game_id)
            wx.CallAfter(self._apply_game, result, initial)
        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_game(self, result: Dict, initial: bool):
        if not result.get('success'):
            speak_notification(result.get('error') or _("Failed to load game"), 'error')
            if initial:
                self.EndModal(wx.ID_CANCEL)
            return
        self.game = result.get('game') or {}
        self.name_ctrl.SetValue(self.game.get('name', ''))
        meta = " | ".join([
            _("Creator: {name}").format(name=self.game.get('creator_username', '?')),
            _("Provider: {provider}").format(provider=_provider_label(self.game.get('provider', ''))),
            _("Tokens cap: {n}").format(n=self.game.get('max_tokens', 0)),
            _("Minutes cap: {n}").format(n=self.game.get('max_minutes', 0)),
            _("Max players: {n}").format(n=self.game.get('max_players', 0)),
        ])
        self.meta_ctrl.SetValue(meta)
        self.desc_ctrl.SetValue(self.game.get('description', '') or '')

        self.att_list.Clear()
        atts = self.game.get('attachments') or []
        if not atts:
            self.att_list.Append(_("(no attachments)"))
            self.open_att_btn.Disable()
        else:
            for att in atts:
                self.att_list.Append(_("[{type}] {name} ({size} KB)").format(
                    type=att.get('attachment_type', '?'),
                    name=att.get('file_name', '?'),
                    size=max(1, int(att.get('size_bytes') or 0) // 1024),
                ))
            self.att_list.SetSelection(0)
            self.open_att_btn.Enable()

        if self.is_owner or self.is_moderator:
            self.delete_btn.Show()
        else:
            self.delete_btn.Hide()
        self.Layout()

    # --- Actions ----------------------------------------------------------

    def _on_start_session(self, event):
        if not self.game:
            return
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass
        speak_notification(_("Opening session..."), 'info')

        def _send():
            result = self.titan_client.start_game_session(self.game_id)
            wx.CallAfter(self._on_started, result)
        threading.Thread(target=_send, daemon=True).start()

    def _on_started(self, result: Dict):
        if not result.get('success'):
            speak_notification(result.get('error') or _("Failed to start session"), 'error')
            return
        self.session_started = int(result.get('session_id') or 0)
        speak_notification(_("Session opened"), 'success')
        self.EndModal(wx.ID_OK)

    def _on_open_attachment(self, event):
        idx = self.att_list.GetSelection()
        atts = (self.game or {}).get('attachments') or []
        if idx < 0 or idx >= len(atts):
            return
        att = atts[idx]
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass
        speak_notification(_("Downloading {name}...").format(name=att.get('file_name', '?')), 'info')

        def _fetch():
            result = self.titan_client.get_game_attachment(int(att.get('id') or 0))
            wx.CallAfter(self._apply_attachment, result, att)
        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_attachment(self, result: Dict, att: Dict):
        if not result.get('success') or not result.get('bytes'):
            speak_notification(result.get('error') or _("Failed to download"), 'error')
            return
        # Save to a temp file, open with OS handler.
        import tempfile
        suffix = os.path.splitext(att.get('file_name') or '')[1] or '.bin'
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(result['bytes'])
                tmp_path = tmp.name
        except Exception as e:
            speak_notification(_("Cannot save attachment: {error}").format(error=str(e)), 'error')
            return
        try:
            if sys.platform == 'win32':
                os.startfile(tmp_path)  # type: ignore[attr-defined]
            elif sys.platform == 'darwin':
                import subprocess
                subprocess.Popen(['open', tmp_path])
            else:
                import subprocess
                subprocess.Popen(['xdg-open', tmp_path])
        except Exception as e:
            speak_notification(_("Cannot open attachment: {error}").format(error=str(e)), 'error')

    def _on_delete(self, event):
        if not self.game:
            return
        confirm = _show_skinned_message(
            _("Delete '{name}' and all its sessions? This cannot be undone.").format(
                name=self.game.get('name', '?')),
            _("Delete game"),
            wx.YES_NO | wx.ICON_WARNING,
        )
        if confirm != wx.YES:
            return

        def _send():
            result = self.titan_client.delete_game(self.game_id)
            wx.CallAfter(self._on_deleted, result)
        threading.Thread(target=_send, daemon=True).start()

    def _on_deleted(self, result: Dict):
        if not result.get('success'):
            speak_notification(result.get('error') or _("Failed to delete"), 'error')
            return
        speak_notification(_("Game deleted"), 'success')
        self.deleted = True
        self.EndModal(wx.ID_CLOSE)


# ---------------------------------------------------------------------------
# Main Frame: Interactive Games catalog
# ---------------------------------------------------------------------------

class InteractiveGamesFrame(wx.Frame):
    """Standalone Entertainment / Interactive Games window.

    Tabs (row 0 of the main listbox):
        - All games
        - My games
        - Active sessions

    Sounds:
        - row 0 focus -> ``ui/tapbar.ogg``
        - tab cycle -> ``ui/switch_list.ogg``
        - cycle past edge -> ``ui/endoftapbar.ogg``
        - new game / new session -> dedicated SFX in titannet/interactive games/
    """

    def __init__(self, parent, titan_client):
        super().__init__(parent, title=_("Interactive Games"), size=(760, 560))
        self.titan_client = titan_client
        self.current_tab: str = 'all'
        self.games_cache: List[Dict] = []
        self.sessions_cache: List[Dict] = []
        self._last_focus_idx: int = -1

        self._build()
        self.Centre()
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self._install_callbacks()

        try:
            play_sound('ui/popup.ogg')
        except Exception:
            pass
        wx.CallAfter(self._refresh, announce=False)

    def _build(self):
        self.panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.view_label = wx.StaticText(self.panel, label=_("Interactive Games (Entertainment)"))
        sizer.Add(self.view_label, flag=wx.ALL, border=8)

        bar = wx.BoxSizer(wx.HORIZONTAL)
        self.new_btn = wx.Button(self.panel, label=_("New game"))
        self.new_btn.Bind(wx.EVT_BUTTON, self._on_new_game)
        bar.Add(self.new_btn, flag=wx.RIGHT, border=6)
        self.refresh_btn = wx.Button(self.panel, label=_("Refresh"))
        self.refresh_btn.Bind(wx.EVT_BUTTON, lambda e: self._refresh(announce=False))
        bar.Add(self.refresh_btn, flag=wx.RIGHT, border=6)
        self.close_btn = wx.Button(self.panel, label=_("Close"))
        self.close_btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        bar.Add(self.close_btn, flag=wx.RIGHT, border=6)
        sizer.Add(bar, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=8)

        sizer.Add(wx.StaticText(self.panel, label=_("Catalog:")),
                  flag=wx.LEFT | wx.RIGHT | wx.TOP, border=8)
        self.listbox = wx.ListBox(self.panel, style=wx.LB_SINGLE)
        self.listbox.Bind(wx.EVT_LISTBOX, self._on_select)
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, self._on_activate)
        sizer.Add(self.listbox, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)

        self.CreateStatusBar()
        self.panel.SetSizer(sizer)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key_hook)

        new_id = self.new_btn.GetId()
        refresh_id = self.refresh_btn.GetId()
        accel = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('N'), new_id),
            (wx.ACCEL_NORMAL, wx.WXK_F5, refresh_id),
        ])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, self._on_new_game, id=new_id)
        self.Bind(wx.EVT_MENU, lambda e: self._refresh(announce=False), id=refresh_id)

        # Catalog can go stale while the user is in a session frame — they
        # may close the session via leave/end/window-close and expect the
        # catalog to no longer list the now-deleted lobby. The simplest
        # fix is to pull fresh data whenever the catalog window regains
        # focus (Activate event fires on switch-to and on first show).
        self.Bind(wx.EVT_ACTIVATE, self._on_window_activate)

    def _on_window_activate(self, event):
        """Refresh the catalog when the window regains focus.

        Aggressive: also drops the in-memory caches so a phantom game/
        session left over from a previous server response can't survive
        a refocus. This is what fixes the "I see a game but DB is empty"
        confusion when a creator deletes their game while we're idle.
        """
        try:
            if event.GetActive():
                self.games_cache = []
                self.sessions_cache = []
                wx.CallAfter(self._refresh, announce=False)
        except Exception:
            pass
        event.Skip()

    # --- Broadcast callbacks ----------------------------------------------

    def _install_callbacks(self):
        self._old_callbacks = {
            'game_new': getattr(self.titan_client, 'on_game_new', None),
            'game_deleted': getattr(self.titan_client, 'on_game_deleted', None),
            'game_session_started': getattr(self.titan_client, 'on_game_session_started', None),
            'game_session_ended': getattr(self.titan_client, 'on_game_session_ended', None),
        }
        self.titan_client.on_game_new = self._handle_remote_new
        self.titan_client.on_game_deleted = self._handle_remote_deleted
        self.titan_client.on_game_session_started = self._handle_remote_session_started
        self.titan_client.on_game_session_ended = self._handle_remote_session_ended

    def _restore_callbacks(self):
        if not hasattr(self, '_old_callbacks'):
            return
        for name, callback in self._old_callbacks.items():
            try:
                setattr(self.titan_client, f'on_{name}', callback)
            except Exception:
                pass

    def _handle_remote_new(self, message: Dict):
        try:
            play_sound('titannet/interactive games/new game.ogg')
        except Exception:
            pass
        text = _("New game: {name} by {user}").format(
            name=message.get('name', '?'), user=message.get('creator_username', '?'))
        speak_notification(text, 'info', play_sound_effect=False)
        wx.CallAfter(self._refresh, announce=False)

    def _handle_remote_deleted(self, message: Dict):
        try:
            play_sound('titannet/interactive games/game deleted.ogg')
        except Exception:
            pass
        wx.CallAfter(self._refresh, announce=False)

    def _handle_remote_session_started(self, message: Dict):
        try:
            play_sound('titannet/interactive games/session started.ogg')
        except Exception:
            pass
        text = _("New session for {name}: hosted by {user}").format(
            name=message.get('game_name', '?'), user=message.get('host_username', '?'))
        speak_notification(text, 'info', play_sound_effect=False)
        if self.current_tab == 'sessions':
            wx.CallAfter(self._refresh, announce=False)

    def _handle_remote_session_ended(self, message: Dict):
        if self.current_tab == 'sessions':
            wx.CallAfter(self._refresh, announce=False)

    # --- Tab + list helpers -----------------------------------------------

    def _tab_index(self, key: str) -> int:
        for i, (tab_key, _label) in enumerate(GAME_TABS):
            if tab_key == key:
                return i
        return 0

    def _tab_bar_text(self) -> str:
        idx = self._tab_index(self.current_tab)
        label = GAME_TABS[idx][1]()
        return _("{}, {} of {}").format(label, idx + 1, len(GAME_TABS))

    def _is_tab_bar_row(self, idx: int) -> bool:
        if idx != 0 or self.listbox.GetCount() == 0:
            return False
        try:
            data = self.listbox.GetClientData(0)
        except Exception:
            return False
        return isinstance(data, dict) and data.get('type') == 'tab_bar'

    def _format_game_row(self, game: Dict) -> str:
        return _("{name} by {user} ({provider}), {n} active session(s)").format(
            name=game.get('name', '?'),
            user=game.get('creator_username', '?'),
            provider=_provider_label(game.get('provider', '')),
            n=game.get('active_sessions', 0),
        )

    def _format_session_row(self, session: Dict) -> str:
        return _("{game} hosted by {user}, {n} player(s), status: {status}").format(
            game=session.get('game_name', '?'),
            user=session.get('host_username', '?'),
            n=session.get('player_count', 0),
            status=session.get('status', '?'),
        )

    def _refresh(self, announce: bool = False):
        tab = self.current_tab

        def _fetch():
            if tab == 'sessions':
                result = self.titan_client.list_game_sessions()
                wx.CallAfter(self._apply_sessions, result, tab)
            else:
                result = self.titan_client.list_games()
                wx.CallAfter(self._apply_games, result, tab)
        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_games(self, result: Dict, requested_tab: str):
        if requested_tab != self.current_tab:
            return
        if not result.get('success'):
            speak_notification(result.get('error') or _("Failed to load games"), 'error')
            return
        items = result.get('games') or []
        if requested_tab == 'mine':
            my_id = getattr(self.titan_client, 'user_id', None)
            items = [g for g in items if g.get('creator_id') == my_id]
        self.games_cache = items

        self.listbox.Clear()
        self.listbox.Append(self._tab_bar_text(), {'type': 'tab_bar'})
        if not items:
            self.listbox.Append(_("(no games yet)"), {'type': 'placeholder'})
        else:
            for g in items:
                self.listbox.Append(self._format_game_row(g), g)
        self.listbox.SetSelection(0)
        self.listbox.SetFocus()
        self._last_focus_idx = 0
        self._update_status_bar()

    def _apply_sessions(self, result: Dict, requested_tab: str):
        if requested_tab != self.current_tab:
            return
        if not result.get('success'):
            speak_notification(result.get('error') or _("Failed to load sessions"), 'error')
            return
        items = result.get('sessions') or []
        self.sessions_cache = items

        self.listbox.Clear()
        self.listbox.Append(self._tab_bar_text(), {'type': 'tab_bar'})
        if not items:
            self.listbox.Append(_("(no active sessions)"), {'type': 'placeholder'})
        else:
            for s in items:
                self.listbox.Append(self._format_session_row(s), s)
        self.listbox.SetSelection(0)
        self.listbox.SetFocus()
        self._last_focus_idx = 0
        self._update_status_bar()

    def _update_status_bar(self):
        label = GAME_TABS[self._tab_index(self.current_tab)][1]()
        if self.current_tab == 'sessions':
            count = len(self.sessions_cache)
        else:
            count = len(self.games_cache)
        self.SetStatusText(_("{tab}: {n} entries").format(tab=label, n=count))

    def _cycle_tab(self, direction: int):
        idx = self._tab_index(self.current_tab)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(GAME_TABS):
            try:
                play_sound('ui/endoftapbar.ogg')
            except Exception:
                pass
            return
        self.current_tab = GAME_TABS[new_idx][0]
        try:
            play_sound('ui/switch_list.ogg')
        except Exception:
            pass
        self._refresh(announce=False)

    # --- Event handlers ----------------------------------------------------

    def _emit_focus_feedback(self, idx: int) -> None:
        item_count = self.listbox.GetCount()
        if self._is_tab_bar_row(idx):
            _announce_tab_bar()
            self._last_focus_idx = idx
            return
        pan = 0.0
        real_count = max(0, item_count - 1)
        if real_count > 1:
            pan = (idx - 1) / (real_count - 1)
        try:
            play_focus_sound(pan=pan)
        except Exception:
            pass
        self._last_focus_idx = idx

    def _on_select(self, event):
        idx = self.listbox.GetSelection()
        if idx < 0:
            return
        self._emit_focus_feedback(idx)

    def _on_key_hook(self, event: wx.KeyEvent):
        keycode = event.GetKeyCode()
        modifiers = event.GetModifiers()
        focus = self.FindFocus()

        if keycode == wx.WXK_ESCAPE and modifiers == wx.MOD_NONE:
            try:
                play_sound('ui/popupclose.ogg')
            except Exception:
                pass
            self.Close()
            return

        if keycode == wx.WXK_TAB and modifiers == wx.MOD_CONTROL:
            self._cycle_tab(+1)
            return
        if keycode == wx.WXK_TAB and modifiers == (wx.MOD_CONTROL | wx.MOD_SHIFT):
            self._cycle_tab(-1)
            return

        if focus is self.listbox:
            idx = self.listbox.GetSelection()
            item_count = self.listbox.GetCount()

            if keycode in (wx.WXK_LEFT, wx.WXK_RIGHT) and self._is_tab_bar_row(idx):
                self._cycle_tab(-1 if keycode == wx.WXK_LEFT else +1)
                return
            if keycode in (wx.WXK_LEFT, wx.WXK_RIGHT):
                return
            if keycode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and not event.AltDown():
                self._on_activate(event)
                return
            if keycode == wx.WXK_DELETE:
                self._delete_selected()
                return

            new_idx = idx
            if keycode == wx.WXK_UP:
                new_idx = idx - 1
            elif keycode == wx.WXK_DOWN:
                new_idx = idx + 1
            elif keycode == wx.WXK_HOME:
                new_idx = 0
            elif keycode == wx.WXK_END:
                new_idx = item_count - 1
            else:
                event.Skip()
                return
            if 0 <= new_idx < item_count and new_idx != idx:
                self.listbox.SetSelection(new_idx)
                self._emit_focus_feedback(new_idx)
            else:
                try:
                    play_endoflist_sound()
                except Exception:
                    pass
            return
        event.Skip()

    def _on_activate(self, event):
        idx = self.listbox.GetSelection()
        if idx <= 0:
            return
        try:
            data = self.listbox.GetClientData(idx)
        except Exception:
            return
        if not isinstance(data, dict) or data.get('type') == 'placeholder':
            return
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass

        if self.current_tab == 'sessions':
            self._activate_session(data)
        else:
            self._activate_game(data)

    def _activate_game(self, game: Dict):
        game_id = int(game.get('id') or 0)
        if not game_id:
            return
        dlg = GameDetailDialog(self, self.titan_client, game_id)
        result = dlg.ShowModal()
        deleted = dlg.deleted
        session_id = dlg.session_started
        dlg.Destroy()
        if deleted:
            self._refresh(announce=False)
        if session_id:
            self._launch_session(session_id, game_id, host=True)

    def _activate_session(self, session: Dict):
        gs_id = int(session.get('id') or 0)
        if not gs_id:
            return
        speak_notification(_("Joining session..."), 'info')

        def _send():
            result = self.titan_client.join_game_session(gs_id)
            wx.CallAfter(self._on_session_joined, result, gs_id, session.get('game_id'))
        threading.Thread(target=_send, daemon=True).start()

    def _on_session_joined(self, result: Dict, gs_id: int, game_id: Optional[int]):
        if not result.get('success'):
            speak_notification(result.get('error') or _("Failed to join"), 'error')
            return
        self._launch_session(gs_id, int(game_id or 0), host=False)

    def _launch_session(self, session_id: int, game_id: int, host: bool):
        try:
            from src.network.interactive_game_session import open_game_session
            open_game_session(self, self.titan_client,
                              session_id=session_id, game_id=game_id, is_host=host)
        except Exception as e:
            print(f"[Interactive Games] open_game_session failed: {e}")
            import traceback
            traceback.print_exc()
            speak_notification(_("Failed to open session window"), 'error')

    def _delete_selected(self):
        idx = self.listbox.GetSelection()
        if idx <= 0 or self.current_tab == 'sessions':
            return
        try:
            data = self.listbox.GetClientData(idx)
        except Exception:
            return
        if not isinstance(data, dict) or data.get('type') == 'placeholder':
            return
        my_id = getattr(self.titan_client, 'user_id', None)
        is_owner = data.get('creator_id') == my_id
        is_mod = bool(getattr(self.titan_client, 'is_admin', False)
                      or getattr(self.titan_client, 'user_role', 'user') in ('moderator', 'developer'))
        if not (is_owner or is_mod):
            speak_notification(_("You can only delete your own games"), 'error')
            return
        confirm = _show_skinned_message(
            _("Delete '{name}'? This cannot be undone.").format(name=data.get('name', '?')),
            _("Delete game"),
            wx.YES_NO | wx.ICON_WARNING,
        )
        if confirm != wx.YES:
            return
        game_id = int(data.get('id') or 0)

        def _send():
            result = self.titan_client.delete_game(game_id)
            wx.CallAfter(self._on_delete_result, result, data.get('name', '?'))
        threading.Thread(target=_send, daemon=True).start()

    def _on_delete_result(self, result: Dict, name: str):
        if not result.get('success'):
            speak_notification(result.get('error') or _("Failed to delete"), 'error')
            return
        speak_notification(_("Deleted: {name}").format(name=name), 'success')
        self._refresh(announce=False)

    def _on_new_game(self, event):
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass
        with NewGameDialog(self) as dlg:
            if dlg.ShowModal() != wx.ID_OK or not dlg.result_payload:
                return
            payload = dlg.result_payload

        speak_notification(_("Publishing game..."), 'info')

        def _send():
            result = self.titan_client.create_game(
                name=payload['name'],
                description=payload['description'],
                provider=payload['provider'],
                api_key=payload['api_key'],
                attachments=payload['attachments'],
                max_tokens=payload['max_tokens'],
                max_minutes=payload['max_minutes'],
                max_players=payload['max_players'],
                rules_text=payload['rules_text'],
            )
            wx.CallAfter(self._on_new_result, result)
        threading.Thread(target=_send, daemon=True).start()

    def _on_new_result(self, result: Dict):
        if not result.get('success'):
            speak_notification(result.get('error') or _("Failed to publish"), 'error')
            return
        speak_notification(_("Game published"), 'success')
        # Server broadcasts game_new -> our handler will refresh.

    def _on_close(self, event):
        self._restore_callbacks()
        event.Skip()


# ---------------------------------------------------------------------------
# Convenience launcher
# ---------------------------------------------------------------------------

def open_interactive_games(parent, titan_client) -> Optional[InteractiveGamesFrame]:
    """Open the Interactive Games catalog. Returns the frame for caller bookkeeping.

    Refuses to open when the client is not connected; emits a screen-reader
    notification in that case.
    """
    if not titan_client or not getattr(titan_client, 'is_connected', False):
        speak_notification(_("You must be connected to Titan-Net"), 'error')
        return None
    frame = InteractiveGamesFrame(parent, titan_client)
    frame.Show()
    try:
        from src.ui.window_switcher import register_window
        register_window(_("Titan-Net: Interactive Games"), window=frame, category='messenger')
    except Exception:
        pass
    return frame

