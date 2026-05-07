# -*- coding: utf-8 -*-
"""TeamTalk - Titan IM external module.

This module provides a Titan-styled TeamTalk front end. It supports server
profiles, .tt/tt:// import, Titan IM sounds, and optional BearWare TeamTalk 5
SDK integration when TeamTalk5.py and the native TeamTalk5 library are bundled
in this module's lib/ or sdk/ directory.
"""

import configparser
import ctypes
import builtins
import json
import os
import sys
import threading
import time
import traceback
import urllib.parse
import xml.etree.ElementTree as ET

_MODULE_DIR = os.path.dirname(__file__)
_TCE_ROOT = os.path.abspath(os.path.join(_MODULE_DIR, "..", "..", ".."))
if _TCE_ROOT not in sys.path:
    sys.path.insert(0, _TCE_ROOT)

_module = sys.modules[__name__]

DEFAULT_TCP_PORT = 10333
DEFAULT_UDP_PORT = 10333
SDK_HINT = (
    "TeamTalk SDK was not found. Put TeamTalk5.py and TeamTalk5.dll "
    "from the BearWare TeamTalk 5 SDK into data/titanIM_modules/TeamTalk/lib "
    "or data/titanIM_modules/TeamTalk/sdk, then restart Titan."
)

_state = {
    "connected": False,
    "server": "",
    "username": "",
    "sdk_available": False,
}
_window = None


def _t(text):
    local_gettext = getattr(_module, "_", lambda value: value)
    return local_gettext(text)


def _sounds():
    return getattr(_module, "sounds", None)


def _notify(text, kind="info"):
    sounds = _sounds()
    if sounds:
        sounds.notify(text, kind)


def _apply_skin_tree(window):
    try:
        from src.titan_core.skin_manager import (
            apply_skin_to_button,
            apply_skin_to_listbox,
            apply_skin_to_window,
        )
    except Exception:
        return

    def walk(child):
        try:
            apply_skin_to_window(child)
            if hasattr(child, "GetClassName"):
                cls = child.GetClassName()
                if cls in ("wxListBox", "wxTreeCtrl", "wxListCtrl"):
                    apply_skin_to_listbox(child)
                elif cls in ("wxButton",):
                    apply_skin_to_button(child)
        except Exception:
            pass
        try:
            for grandchild in child.GetChildren():
                walk(grandchild)
        except Exception:
            pass

    walk(window)


def _message(parent, text, title=None, style=None):
    import wx

    title = title or _t("TeamTalk")
    style = style or (wx.OK | wx.ICON_INFORMATION)
    dlg = wx.MessageDialog(parent, text, title, style)
    _apply_skin_tree(dlg)
    result = dlg.ShowModal()
    dlg.Destroy()
    return result


def _config_key_variants(key):
    clean = key.strip().lower().replace("-", "").replace("_", "")
    aliases = {
        "host": {"host", "hostname", "address", "server", "ipaddr", "hostaddr"},
        "tcpport": {"tcpport", "tcp", "tcp_port", "teamtalktcpport"},
        "udpport": {"udpport", "udp", "udp_port", "teamtalkudpport"},
        "encrypted": {"encrypted", "encryption", "secure", "ssl"},
        "username": {"username", "user", "account", "login"},
        "password": {"password", "passwd", "pwd"},
        "nickname": {"nickname", "nick", "displayname", "name"},
        "channel": {"channel", "chan", "channelpath", "joinchannel"},
        "chanpasswd": {"chanpasswd", "channelpassword", "chanpassword", "channelpasswd"},
        "entry_name": {"entryname", "entry", "title", "servername", "name"},
    }
    for canonical, names in aliases.items():
        if clean in {name.replace("_", "") for name in names}:
            return canonical
    return clean


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "encrypted")


def _as_int(value, default):
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _value(value, default=0):
    try:
        return int(getattr(value, "value", value))
    except Exception:
        return default


def _tt_text(value):
    if value is None:
        return ""
    try:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace").rstrip("\x00")
        return str(value).rstrip("\x00")
    except Exception:
        return ""


def _normalize_profile(data):
    profile = {
        "entry_name": "",
        "host": "",
        "tcpport": DEFAULT_TCP_PORT,
        "udpport": DEFAULT_UDP_PORT,
        "encrypted": False,
        "username": "",
        "password": "",
        "nickname": "",
        "channel": "",
        "chanpasswd": "",
    }

    for key, value in (data or {}).items():
        canonical = _config_key_variants(str(key))
        if canonical in profile:
            profile[canonical] = value

    profile["host"] = str(profile["host"]).strip()
    profile["entry_name"] = str(profile["entry_name"] or profile["host"] or _t("TeamTalk server")).strip()
    profile["tcpport"] = _as_int(profile["tcpport"], DEFAULT_TCP_PORT)
    profile["udpport"] = _as_int(profile["udpport"], profile["tcpport"] or DEFAULT_UDP_PORT)
    profile["encrypted"] = _as_bool(profile["encrypted"])
    for key in ("username", "password", "nickname", "channel", "chanpasswd"):
        profile[key] = str(profile.get(key) or "").strip()
    return profile


def _parse_tt_url(text):
    text = text.strip()
    if not text.lower().startswith("tt://"):
        return None
    parsed = urllib.parse.urlparse(text)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    data = {key: values[-1] for key, values in query.items()}
    data["host"] = parsed.netloc or parsed.path.strip("/")
    return _normalize_profile(data)


def _parse_xml_tt(text):
    try:
        root = ET.fromstring(text)
    except Exception:
        return None

    data = {}
    for elem in root.iter():
        tag = _config_key_variants(elem.tag)
        if elem.text and elem.text.strip():
            data[tag] = elem.text.strip()
        for key, value in elem.attrib.items():
            data[_config_key_variants(key)] = value
    profile = _normalize_profile(data)
    return profile if profile["host"] else None


def _parse_ini_tt(text):
    parser = configparser.ConfigParser()
    try:
        parser.read_string(text)
    except Exception:
        parser = None

    data = {}
    if parser and parser.sections():
        preferred = None
        for section in parser.sections():
            lower = section.lower()
            if lower in ("server", "teamtalk", "teamtalk5", "connection"):
                preferred = section
                break
        preferred = preferred or parser.sections()[0]
        data.update(dict(parser.items(preferred)))
        if "entry_name" not in data:
            data["entry_name"] = preferred
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(("#", ";")) or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip().strip('"')

    profile = _normalize_profile(data)
    return profile if profile["host"] else None


def parse_tt_content(text):
    """Parse .tt text or tt:// URL into a normalized TeamTalk profile."""
    text = (text or "").strip()
    if not text:
        raise ValueError(_t("The selected .tt file is empty."))

    parsers = (_parse_tt_url, _parse_xml_tt, _parse_ini_tt)
    for parser in parsers:
        profile = parser(text)
        if profile and profile.get("host"):
            return profile
    raise ValueError(_t("Could not find TeamTalk server information in this file."))


def parse_tt_file(path):
    with builtins.open(path, "r", encoding="utf-8-sig") as handle:
        return parse_tt_content(handle.read())


def profile_to_tt_url(profile):
    profile = _normalize_profile(profile)
    query = {
        "tcpport": profile["tcpport"],
        "udpport": profile["udpport"],
        "encrypted": "true" if profile["encrypted"] else "false",
    }
    for key in ("username", "password", "channel", "chanpasswd"):
        if profile.get(key):
            query[key] = profile[key]
    return "tt://{}?{}".format(profile["host"], urllib.parse.urlencode(query))


def _load_all_config():
    try:
        from src.settings.titan_im_config import load_titan_im_config
        return load_titan_im_config()
    except Exception:
        return {}


def _save_all_config(config):
    try:
        from src.settings.titan_im_config import save_titan_im_config
        return save_titan_im_config(config)
    except Exception as exc:
        print(f"[TeamTalk] Failed to save config: {exc}")
        return False


def load_teamtalk_config():
    config = _load_all_config()
    teamtalk = config.get("teamtalk", {})
    profiles = [_normalize_profile(item) for item in teamtalk.get("profiles", []) if isinstance(item, dict)]
    return {
        "profiles": profiles,
        "last_profile": teamtalk.get("last_profile", ""),
        "ptt_enabled": bool(teamtalk.get("ptt_enabled", True)),
    }


def save_teamtalk_config(teamtalk_config):
    config = _load_all_config()
    config["teamtalk"] = teamtalk_config
    return _save_all_config(config)


def _find_sdk_module():
    candidates = [
        _MODULE_DIR,
        os.path.join(_MODULE_DIR, "lib"),
        os.path.join(_MODULE_DIR, "sdk"),
        os.path.join(_MODULE_DIR, "Library", "TeamTalkPy"),
    ]
    for path in candidates:
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)
        if os.path.isdir(path) and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(path)
            except Exception:
                pass
    try:
        import TeamTalk5
        _state["sdk_available"] = True
        return TeamTalk5, None
    except Exception as exc:
        _state["sdk_available"] = False
        return None, exc


class TeamTalkSdkClient:
    """Small compatibility wrapper around BearWare's TeamTalk5.py.

    The official SDK is not bundled with Titan. This wrapper only imports it at
    runtime and keeps every call guarded, so the module remains usable for
    profile and .tt handling when the SDK is absent.
    """

    def __init__(self, on_event=None):
        self.sdk, self.import_error = _find_sdk_module()
        self.on_event = on_event
        self.obj = None
        self.tt = None
        self.polling = False
        self.poll_thread = None
        self.connected = False
        self.logged_in = False
        self.pending_profile = None
        self.my_user_id = 0
        self.my_channel_id = 0

    def available(self):
        return self.sdk is not None

    def status_message(self):
        if self.available():
            return _t("TeamTalk SDK loaded")
        return f"{SDK_HINT}\n\n{self.import_error}"

    def _call(self, *names, default=None):
        for name in names:
            func = getattr(self.sdk, name, None)
            if callable(func):
                return func
        return default

    def connect(self, profile):
        if not self.available():
            raise RuntimeError(SDK_HINT)
        profile = _normalize_profile(profile)
        self.pending_profile = profile

        teamtalk_class = getattr(self.sdk, "TeamTalk", None)
        if teamtalk_class:
            self.obj = teamtalk_class()
            self.tt = getattr(self.obj, "_tt", None)
            ok = self.obj.connect(
                profile["host"],
                profile["tcpport"],
                profile["udpport"],
                0,
                0,
                profile["encrypted"],
            )
            self._init_default_audio_devices()
        else:
            init = self._call("_InitTeamTalkPoll", "TT_InitTeamTalkPoll")
            if not init:
                raise RuntimeError(_t("The loaded TeamTalk SDK does not expose a TeamTalk initializer."))
            self.tt = init()
            if not self.tt:
                raise RuntimeError(_t("Could not initialize TeamTalk client."))

            connect = self._call("_Connect", "TT_Connect")
            if not connect:
                raise RuntimeError(_t("The loaded TeamTalk SDK does not expose a connect function."))
            ok = connect(self.tt, profile["host"], profile["tcpport"], profile["udpport"], 0, 0, profile["encrypted"])
        if not ok:
            raise RuntimeError(_t("Could not start TeamTalk connection."))

        self.connected = True
        self._start_polling()
        return True

    def _init_default_audio_devices(self):
        if not self.obj:
            return
        try:
            indev, outdev = self.obj.getDefaultSoundDevices()
            indev = getattr(indev, "value", indev)
            outdev = getattr(outdev, "value", outdev)
            self.obj.initSoundInputDevice(indev)
            self.obj.initSoundOutputDevice(outdev)
        except Exception as exc:
            print(f"[TeamTalk] Could not initialize default audio devices: {exc}")

    def login(self, profile):
        if not self.available():
            return False
        nickname = profile.get("nickname") or profile.get("username") or "Titan"
        username = profile.get("username", "")
        password = profile.get("password", "")
        if self.obj:
            self.obj.doLogin(nickname, username, password, "Titan IM")
            self.logged_in = True
            return True
        if not self.tt:
            return False
        login = self._call("_DoLogin", "_DoLoginEx", "TT_DoLogin", "TT_DoLoginEx")
        if not login:
            return False
        try:
            login(self.tt, nickname, username, password)
        except TypeError:
            try:
                login(self.tt, nickname, username, password, "", "")
            except TypeError:
                login(self.tt, username, password)
        self.logged_in = True
        return True

    def join_channel_path(self, channel_path, password=""):
        if not channel_path or not self.available() or not self.obj:
            return False
        try:
            channel_id = self.obj.getChannelIDFromPath(channel_path)
            if channel_id:
                return self.join_channel_by_id(channel_id, password)
        except Exception:
            pass
        return False

    def join_channel_by_id(self, channel_id, password=""):
        if not self.available() or not self.obj or not channel_id:
            return False
        try:
            return bool(self.obj.doJoinChannelByID(channel_id, password))
        except Exception:
            return False

    def join_channel(self, profile):
        return self.join_channel_path(profile.get("channel", ""), profile.get("chanpasswd", ""))

    def refresh_state(self):
        if not self.available() or not self.obj:
            return {"channels": [], "users": [], "root_id": 0, "my_channel_id": 0, "my_user_id": 0}
        try:
            self.my_user_id = _value(self.obj.getMyUserID())
        except Exception:
            self.my_user_id = 0
        try:
            self.my_channel_id = _value(self.obj.getMyChannelID())
        except Exception:
            self.my_channel_id = 0
        try:
            root_id = _value(self.obj.getRootChannelID())
        except Exception:
            root_id = 0
        channels = []
        users = []
        try:
            channels = list(self.obj.getServerChannels())
        except Exception:
            pass
        try:
            users = list(self.obj.getServerUsers())
        except Exception:
            pass
        return {
            "channels": channels,
            "users": users,
            "root_id": root_id,
            "my_channel_id": self.my_channel_id,
            "my_user_id": self.my_user_id,
        }

    def get_channel_users(self, channel_id):
        if not self.available() or not self.obj or not channel_id:
            return []
        try:
            return list(self.obj.getChannelUsers(channel_id))
        except Exception:
            return []

    def get_channel_path(self, channel_id):
        if not self.available() or not self.obj or not channel_id:
            return ""
        try:
            return _tt_text(self.obj.getChannelPath(channel_id))
        except Exception:
            return ""

    def disconnect(self):
        self.polling = False
        if self.available() and self.obj:
            try:
                self.obj.disconnect()
                self.obj.closeTeamTalk()
            except Exception:
                pass
        elif self.available() and self.tt:
            try:
                close = self._call("_CloseTeamTalk", "TT_CloseTeamTalk")
                disconnect = self._call("_Disconnect", "TT_Disconnect")
                if disconnect:
                    disconnect(self.tt)
                if close:
                    close(self.tt)
            except Exception:
                pass
        self.obj = None
        self.tt = None
        self.connected = False
        self.logged_in = False
        self.my_user_id = 0
        self.my_channel_id = 0

    def enable_voice(self, enabled):
        if not self.available():
            return False
        if self.obj:
            try:
                return bool(self.obj.enableVoiceTransmission(enabled))
            except Exception:
                return False
        if not self.tt:
            return False
        flags = getattr(self.sdk, "StreamType", None)
        voice_flag = getattr(flags, "STREAMTYPE_VOICE", None) if flags else None
        enable = self._call("_EnableVoiceTransmission", "TT_EnableVoiceTransmission")
        if enable:
            try:
                return bool(enable(self.tt, enabled))
            except Exception:
                return False
        tx = self._call("TT_EnableTransmission")
        if tx and voice_flag is not None:
            try:
                return bool(tx(self.tt, voice_flag, enabled))
            except Exception:
                return False
        return False

    def send_channel_message(self, text):
        if not self.available():
            return False
        if self.obj and hasattr(self.sdk, "buildTextMessage"):
            try:
                msg_type = getattr(self.sdk.TextMsgType, "MSGTYPE_CHANNEL", 2)
                channel_id = self.my_channel_id
                if not channel_id:
                    try:
                        channel_id = _value(self.obj.getMyChannelID())
                        self.my_channel_id = channel_id
                    except Exception:
                        channel_id = 0
                messages = self.sdk.buildTextMessage(text, msg_type, nChannelID=channel_id)
                ok = False
                for message in messages:
                    ok = bool(self.obj.doTextMessage(message)) or ok
                return ok
            except Exception:
                return False
        if not self.tt:
            return False
        msg_class = getattr(self.sdk, "TextMessage", None)
        do_message = self._call("_DoTextMessage", "TT_DoTextMessage")
        if not (msg_class and do_message):
            return False
        try:
            message = msg_class()
            message.nMsgType = getattr(getattr(self.sdk, "TextMsgType", object), "MSGTYPE_CHANNEL", 2)
            message.szMessage = text
            do_message(self.tt, ctypes.byref(message))
            return True
        except Exception:
            return False

    def _start_polling(self):
        if self.polling:
            return
        self.polling = True
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()

    def _poll_loop(self):
        get_event = self._call("_GetMessage", "TT_GetMessage")
        if not get_event and not self.obj:
            return
        event_class = getattr(self.sdk, "TTMessage", None)
        while self.polling and self.tt:
            try:
                if self.obj:
                    msg = self.obj.getMessage(250)
                    self._emit_event(msg)
                elif event_class:
                    msg = event_class()
                    wait_ms = getattr(self.sdk, "INT32", ctypes.c_int)(250)
                    if get_event(self.tt, ctypes.byref(msg), ctypes.byref(wait_ms)):
                        self._emit_event(msg)
                else:
                    time.sleep(0.25)
            except Exception:
                time.sleep(0.25)

    def _emit_event(self, msg):
        try:
            event = _value(msg.nClientEvent)
            events = getattr(self.sdk, "ClientEvent", None)
            if events and event == _value(events.CLIENTEVENT_CON_SUCCESS) and self.pending_profile:
                self.login(self.pending_profile)
            elif events and event == _value(events.CLIENTEVENT_CMD_MYSELF_LOGGEDIN) and self.pending_profile:
                self.join_channel(self.pending_profile)
        except Exception:
            pass
        if self.on_event:
            self.on_event(msg)


class ProfileDialog:
    def __init__(self, parent, profile=None):
        import wx

        self.wx = wx
        self.profile = _normalize_profile(profile or {})
        self.dialog = wx.Dialog(parent, title=_t("TeamTalk Server"), size=(440, 520))
        panel = wx.Panel(self.dialog)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.controls = {}
        fields = [
            ("entry_name", _t("Entry name:"), 0),
            ("host", _t("Server address:"), 0),
            ("tcpport", _t("TCP port:"), 0),
            ("udpport", _t("UDP port:"), 0),
            ("username", _t("Username:"), 0),
            ("password", _t("Password:"), wx.TE_PASSWORD),
            ("nickname", _t("Nickname:"), 0),
            ("channel", _t("Channel path:"), 0),
            ("chanpasswd", _t("Channel password:"), wx.TE_PASSWORD),
        ]
        for key, label, style in fields:
            sizer.Add(wx.StaticText(panel, label=label), 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
            ctrl = wx.TextCtrl(panel, style=style)
            ctrl.SetValue(str(self.profile.get(key, "")))
            self.controls[key] = ctrl
            sizer.Add(ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.encrypted = wx.CheckBox(panel, label=_t("Encrypted server"))
        self.encrypted.SetValue(bool(self.profile.get("encrypted")))
        sizer.Add(self.encrypted, 0, wx.ALL, 8)

        buttons = self.dialog.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)

        panel.SetSizer(sizer)
        wrapper = wx.BoxSizer(wx.VERTICAL)
        wrapper.Add(panel, 1, wx.EXPAND)
        self.dialog.SetSizer(wrapper)
        self.dialog.CentreOnParent()
        _apply_skin_tree(self.dialog)

    def show_modal(self):
        result = self.dialog.ShowModal()
        if result == self.wx.ID_OK:
            profile = {key: ctrl.GetValue().strip() for key, ctrl in self.controls.items()}
            profile["encrypted"] = self.encrypted.GetValue()
            self.profile = _normalize_profile(profile)
        self.dialog.Destroy()
        return result == self.wx.ID_OK


class TeamTalkFrame:
    def __init__(self, parent):
        import wx

        self.wx = wx
        self.sounds = _sounds()
        self.config = load_teamtalk_config()
        self.profiles = self.config["profiles"]
        self.current_profile = None
        self.client = TeamTalkSdkClient(on_event=self._on_sdk_event)
        self.ptt_down = False
        self.force_voice = False
        self.channels = {}
        self.users = {}
        self.channel_items = {}
        self.user_items = {}
        self.current_channel_id = 0
        self.focus_tree_after_login = False
        self.connected_announced = False
        self.auto_join_attempted = False

        self.frame = wx.Frame(parent, title=_t("TeamTalk - Titan IM"), size=(820, 620))
        self.frame.Bind(wx.EVT_CLOSE, self.on_close)
        self.frame.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)
        self.frame.Bind(wx.EVT_KEY_UP, self.on_key_up)
        self._build_ui()
        self._build_menu()
        self._refresh_profiles()
        self._set_status(self.client.status_message())
        _apply_skin_tree(self.frame)

    def _build_ui(self):
        wx = self.wx
        self.root_panel = wx.Panel(self.frame)
        self.root_sizer = wx.BoxSizer(wx.VERTICAL)

        self.connection_panel = wx.Panel(self.root_panel)
        connection_sizer = wx.BoxSizer(wx.VERTICAL)
        connection_sizer.Add(wx.StaticText(self.connection_panel, label=_t("TeamTalk servers")), 0, wx.ALL, 8)

        self.profile_list = wx.ListBox(self.connection_panel, style=wx.LB_SINGLE | wx.WANTS_CHARS)
        self.profile_list.Bind(wx.EVT_LISTBOX, self.on_profile_selected)
        self.profile_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_connect)
        self.profile_list.Bind(wx.EVT_KEY_DOWN, self.on_profile_key)
        connection_sizer.Add(self.profile_list, 1, wx.EXPAND | wx.ALL, 8)

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        self.connect_btn = wx.Button(self.connection_panel, label=_t("Connect"))
        self.add_btn = wx.Button(self.connection_panel, label=_t("Add"))
        self.edit_btn = wx.Button(self.connection_panel, label=_t("Edit"))
        self.remove_btn = wx.Button(self.connection_panel, label=_t("Remove"))
        self.import_btn = wx.Button(self.connection_panel, label=_t("Import .tt"))
        for btn in (self.connect_btn, self.add_btn, self.edit_btn, self.remove_btn, self.import_btn):
            button_row.Add(btn, 0, wx.RIGHT, 5)
        connection_sizer.Add(button_row, 0, wx.ALL, 8)

        self.connect_btn.Bind(wx.EVT_BUTTON, self.on_connect)
        self.add_btn.Bind(wx.EVT_BUTTON, self.on_add_profile)
        self.edit_btn.Bind(wx.EVT_BUTTON, self.on_edit_profile)
        self.remove_btn.Bind(wx.EVT_BUTTON, self.on_remove_profile)
        self.import_btn.Bind(wx.EVT_BUTTON, self.on_import_tt)

        self.connection_panel.SetSizer(connection_sizer)

        self.connected_panel = wx.Panel(self.root_panel)
        connected_sizer = wx.BoxSizer(wx.VERTICAL)
        connected_sizer.Add(wx.StaticText(self.connected_panel, label=_t("Channels and users")), 0, wx.ALL, 8)

        self.channel_tree = wx.TreeCtrl(self.connected_panel, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT | wx.TR_SINGLE)
        self.channel_root = self.channel_tree.AddRoot(_t("TeamTalk"))
        self.channel_tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.on_tree_activated)
        self.channel_tree.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_tree_selected)
        connected_sizer.Add(self.channel_tree, 2, wx.EXPAND | wx.ALL, 8)

        chat_label = wx.StaticText(self.connected_panel, label=_t("Channel chat"))
        connected_sizer.Add(chat_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        self.chat = wx.TextCtrl(self.connected_panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        connected_sizer.Add(self.chat, 1, wx.EXPAND | wx.ALL, 8)

        send_row = wx.BoxSizer(wx.HORIZONTAL)
        self.message = wx.TextCtrl(self.connected_panel, style=wx.TE_PROCESS_ENTER)
        self.message.Bind(wx.EVT_TEXT_ENTER, self.on_send_message)
        self.send_btn = wx.Button(self.connected_panel, label=_t("Send"))
        self.send_btn.Bind(wx.EVT_BUTTON, self.on_send_message)
        send_row.Add(self.message, 1, wx.EXPAND | wx.RIGHT, 6)
        send_row.Add(self.send_btn, 0)
        connected_sizer.Add(send_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        control_row = wx.BoxSizer(wx.HORIZONTAL)
        self.disconnect_btn = wx.Button(self.connected_panel, label=_t("Disconnect"))
        self.ptt_btn = wx.ToggleButton(self.connected_panel, label=_t("Push to talk"))
        self.mute_btn = wx.ToggleButton(self.connected_panel, label=_t("Mute microphone"))
        for btn in (self.disconnect_btn, self.ptt_btn, self.mute_btn):
            control_row.Add(btn, 0, wx.RIGHT, 6)
        connected_sizer.Add(control_row, 0, wx.ALL, 8)

        self.disconnect_btn.Bind(wx.EVT_BUTTON, self.on_disconnect)
        self.ptt_btn.Bind(wx.EVT_TOGGLEBUTTON, self.on_ptt_toggle)
        self.mute_btn.Bind(wx.EVT_TOGGLEBUTTON, self.on_mute_toggle)

        self.connected_panel.SetSizer(connected_sizer)

        self.root_sizer.Add(self.connection_panel, 1, wx.EXPAND)
        self.root_sizer.Add(self.connected_panel, 1, wx.EXPAND)
        self.root_panel.SetSizer(self.root_sizer)
        self._show_connection_view()

        self.frame.CreateStatusBar()
        self._setup_accessibility_names()

    def _setup_accessibility_names(self):
        try:
            self.profile_list.SetName(_t("TeamTalk servers"))
            self.channel_tree.SetName(_t("TeamTalk channels and users"))
            self.chat.SetName(_t("TeamTalk chat history"))
            self.message.SetName(_t("Type TeamTalk message"))
            self.connect_btn.SetName(_t("Connect to selected TeamTalk server"))
            self.disconnect_btn.SetName(_t("Disconnect from TeamTalk"))
            self.ptt_btn.SetName(_t("Push to talk"))
            self.mute_btn.SetName(_t("Mute microphone"))
        except Exception:
            pass

    def _show_connection_view(self):
        try:
            self.connected_panel.Hide()
            self.connection_panel.Show()
            self.root_panel.Layout()
            self.profile_list.SetFocus()
        except Exception:
            pass

    def _show_connected_view(self):
        try:
            self.connection_panel.Hide()
            self.connected_panel.Show()
            self.root_panel.Layout()
        except Exception:
            pass

    def _build_menu(self):
        wx = self.wx
        menubar = wx.MenuBar()
        server_menu = wx.Menu()
        import_item = server_menu.Append(wx.ID_ANY, _t("Import .tt file"), _t("Import TeamTalk connection file"))
        connect_item = server_menu.Append(wx.ID_ANY, _t("Connect"), _t("Connect to selected server"))
        disconnect_item = server_menu.Append(wx.ID_ANY, _t("Disconnect"), _t("Disconnect from TeamTalk"))
        server_menu.AppendSeparator()
        close_item = server_menu.Append(wx.ID_EXIT, _t("Close"), _t("Close TeamTalk"))
        self.frame.Bind(wx.EVT_MENU, self.on_import_tt, import_item)
        self.frame.Bind(wx.EVT_MENU, self.on_connect, connect_item)
        self.frame.Bind(wx.EVT_MENU, self.on_disconnect, disconnect_item)
        self.frame.Bind(wx.EVT_MENU, self.on_close, close_item)
        menubar.Append(server_menu, _t("Server"))

        help_menu = wx.Menu()
        sdk_item = help_menu.Append(wx.ID_ANY, _t("SDK status"), _t("Show TeamTalk SDK status"))
        self.frame.Bind(wx.EVT_MENU, self.on_sdk_status, sdk_item)
        menubar.Append(help_menu, _t("Help"))
        self.frame.SetMenuBar(menubar)

    def show(self):
        self.frame.Show()
        self.frame.Raise()

    def _set_status(self, text):
        try:
            self.frame.SetStatusText(text)
        except Exception:
            pass

    def _save(self):
        self.config["profiles"] = self.profiles
        if self.current_profile:
            self.config["last_profile"] = self.current_profile.get("entry_name", "")
        save_teamtalk_config(self.config)

    def _refresh_profiles(self):
        self.profile_list.Clear()
        for profile in self.profiles:
            encrypted = " TLS" if profile.get("encrypted") else ""
            channel = f" {profile['channel']}" if profile.get("channel") else ""
            self.profile_list.Append(
                f"{profile['entry_name']} - {profile['host']}:{profile['tcpport']}{encrypted}{channel}"
            )
        if self.profiles:
            index = 0
            last = self.config.get("last_profile")
            for i, profile in enumerate(self.profiles):
                if profile.get("entry_name") == last:
                    index = i
                    break
            self.profile_list.SetSelection(index)
            self.current_profile = self.profiles[index]

    def _selected_index(self):
        index = self.profile_list.GetSelection()
        return index if index != self.wx.NOT_FOUND else None

    def _append_chat(self, text):
        if not text:
            return
        current = self.chat.GetValue()
        prefix = "\n" if current else ""
        self.chat.AppendText(prefix + text)

    def on_profile_selected(self, event):
        index = self._selected_index()
        if index is None:
            return
        self.current_profile = self.profiles[index]
        if self.sounds:
            self.sounds.select()

    def on_profile_key(self, event):
        key = event.GetKeyCode()
        if key in (self.wx.WXK_RETURN, self.wx.WXK_NUMPAD_ENTER):
            self.on_connect(event)
            return
        event.Skip()

    def on_add_profile(self, event):
        dlg = ProfileDialog(self.frame)
        if dlg.show_modal():
            if not dlg.profile["host"]:
                _message(self.frame, _t("Server address is required."), style=self.wx.OK | self.wx.ICON_WARNING)
                return
            self.profiles.append(dlg.profile)
            self.current_profile = dlg.profile
            self._save()
            self._refresh_profiles()
            if self.sounds:
                self.sounds.success()

    def on_edit_profile(self, event):
        index = self._selected_index()
        if index is None:
            return
        dlg = ProfileDialog(self.frame, self.profiles[index])
        if dlg.show_modal():
            if not dlg.profile["host"]:
                _message(self.frame, _t("Server address is required."), style=self.wx.OK | self.wx.ICON_WARNING)
                return
            self.profiles[index] = dlg.profile
            self.current_profile = dlg.profile
            self._save()
            self._refresh_profiles()
            if self.sounds:
                self.sounds.success()

    def on_remove_profile(self, event):
        index = self._selected_index()
        if index is None:
            return
        result = _message(
            self.frame,
            _t("Remove selected TeamTalk server profile?"),
            style=self.wx.YES_NO | self.wx.NO_DEFAULT | self.wx.ICON_QUESTION,
        )
        if result == self.wx.ID_YES:
            del self.profiles[index]
            self.current_profile = None
            self._save()
            self._refresh_profiles()

    def on_import_tt(self, event):
        wildcard = _t("TeamTalk files (*.tt)|*.tt|All files (*.*)|*.*")
        dlg = self.wx.FileDialog(
            self.frame,
            _t("Import TeamTalk .tt file"),
            wildcard=wildcard,
            style=self.wx.FD_OPEN | self.wx.FD_FILE_MUST_EXIST,
        )
        _apply_skin_tree(dlg)
        if dlg.ShowModal() == self.wx.ID_OK:
            path = dlg.GetPath()
            try:
                profile = parse_tt_file(path)
                if not profile["entry_name"] or profile["entry_name"] == _t("TeamTalk server"):
                    profile["entry_name"] = os.path.splitext(os.path.basename(path))[0]
                self.profiles.append(profile)
                self.current_profile = profile
                self._save()
                self._refresh_profiles()
                self._set_status(_t("Imported TeamTalk file: {name}").format(name=profile["entry_name"]))
                _notify(_t("TeamTalk file imported"), "success")
            except Exception as exc:
                _message(self.frame, str(exc), _t("Import failed"), self.wx.OK | self.wx.ICON_ERROR)
                if self.sounds:
                    self.sounds.error()
        dlg.Destroy()

    def on_connect(self, event):
        index = self._selected_index()
        if index is not None:
            self.current_profile = self.profiles[index]
        if not self.current_profile:
            _message(self.frame, _t("Select or add a TeamTalk server first."), style=self.wx.OK | self.wx.ICON_WARNING)
            return
        if not self.client.available():
            _message(self.frame, self.client.status_message(), _t("TeamTalk SDK not available"), self.wx.OK | self.wx.ICON_WARNING)
            if self.sounds:
                self.sounds.error()
            return

        profile = self.current_profile
        self.auto_join_attempted = False
        self._set_status(_t("Connecting to {host}...").format(host=profile["host"]))

        def worker():
            try:
                self.client.connect(profile)
                self.wx.CallAfter(
                    self._set_status,
                    _t("Connection started. Waiting for TeamTalk server..."),
                )
            except Exception as exc:
                self.wx.CallAfter(self._on_connection_failed, exc)

        threading.Thread(target=worker, daemon=True).start()

    def _on_connected(self, profile):
        _state["connected"] = True
        _state["server"] = profile["entry_name"]
        _state["username"] = profile.get("nickname") or profile.get("username") or ""
        self._save()
        self._show_connected_view()
        self.focus_tree_after_login = True
        self._refresh_teamtalk_state(select_my_channel=True)
        if not self.connected_announced:
            self.connected_announced = True
            self._set_status(_t("Connected to {server}").format(server=profile["entry_name"]))
            self._append_chat(_t("Connected to {server}").format(server=profile["entry_name"]))
            if self.sounds:
                self.sounds.call_connected()
            _notify(_t("Connected to TeamTalk server"), "success")

    def _on_connection_failed(self, exc):
        self.client.disconnect()
        _state["connected"] = False
        self.connected_announced = False
        self.auto_join_attempted = False
        self.focus_tree_after_login = False
        self._show_connection_view()
        self._set_status(_t("Connection failed"))
        _message(self.frame, str(exc), _t("TeamTalk connection failed"), self.wx.OK | self.wx.ICON_ERROR)
        if self.sounds:
            self.sounds.error()

    def _channel_label(self, channel):
        name = _tt_text(getattr(channel, "szName", "")) or "/"
        channel_id = _value(getattr(channel, "nChannelID", 0))
        user_count = len(self.client.get_channel_users(channel_id))
        password = bool(getattr(channel, "bPassword", False))
        parts = [name]
        if user_count:
            parts.append(_t("{count} users").format(count=user_count))
        if password:
            parts.append(_t("password"))
        return " - ".join(parts)

    def _user_label(self, user):
        nickname = _tt_text(getattr(user, "szNickname", "")) or _tt_text(getattr(user, "szUsername", ""))
        username = _tt_text(getattr(user, "szUsername", ""))
        state = _value(getattr(user, "uUserState", 0))
        speaking = ""
        try:
            if state & _value(self.client.sdk.UserState.USERSTATE_VOICE):
                speaking = _t(" speaking")
        except Exception:
            pass
        if username and username != nickname:
            return f"{nickname} ({username}){speaking}"
        return f"{nickname}{speaking}"

    def _tree_item_data(self, kind, item_id):
        return {"kind": kind, "id": item_id}

    def _refresh_teamtalk_state(self, select_my_channel=False):
        snapshot = self.client.refresh_state()
        self.channels = {_value(ch.nChannelID): ch for ch in snapshot["channels"]}
        self.users = {_value(user.nUserID): user for user in snapshot["users"]}
        my_channel_id = snapshot.get("my_channel_id", 0)
        if select_my_channel and my_channel_id:
            self.current_channel_id = my_channel_id
        elif not self.current_channel_id and my_channel_id:
            self.current_channel_id = my_channel_id
        self._populate_channel_tree(snapshot.get("root_id", 0))
        profile = self.client.pending_profile or self.current_profile
        if (
            profile
            and profile.get("channel")
            and not snapshot.get("my_channel_id")
            and not self.auto_join_attempted
        ):
            self.auto_join_attempted = True
            self.client.join_channel(profile)

    def _populate_channel_tree(self, root_id=0):
        self.channel_tree.DeleteChildren(self.channel_root)
        self.channel_items = {}
        self.user_items = {}
        children = {}
        for channel in self.channels.values():
            parent_id = _value(getattr(channel, "nParentID", 0))
            children.setdefault(parent_id, []).append(channel)

        def add_children(parent_item, parent_id):
            channels = children.get(parent_id, [])
            channels.sort(key=lambda ch: _tt_text(getattr(ch, "szName", "")).lower())
            for channel in channels:
                channel_id = _value(getattr(channel, "nChannelID", 0))
                item = self.channel_tree.AppendItem(parent_item, self._channel_label(channel))
                self.channel_tree.SetItemData(item, self._tree_item_data("channel", channel_id))
                self.channel_items[channel_id] = item
                for user in sorted(self.client.get_channel_users(channel_id), key=lambda u: self._user_label(u).lower()):
                    user_id = _value(getattr(user, "nUserID", 0))
                    user_item = self.channel_tree.AppendItem(item, self._user_label(user))
                    self.channel_tree.SetItemData(user_item, self._tree_item_data("user", user_id))
                    self.user_items[user_id] = user_item
                add_children(item, channel_id)
                self.channel_tree.Expand(item)

        root_children_id = root_id if root_id in children else 0
        add_children(self.channel_root, root_children_id)
        self.channel_tree.Expand(self.channel_root)
        if self.current_channel_id in self.channel_items:
            self.channel_tree.SelectItem(self.channel_items[self.current_channel_id])
        elif self.channel_items:
            first_channel_id = next(iter(self.channel_items))
            self.current_channel_id = first_channel_id
            self.channel_tree.SelectItem(self.channel_items[first_channel_id])
        if self.focus_tree_after_login:
            self.focus_tree_after_login = False
            self.channel_tree.SetFocus()

    def _get_tree_data(self, item):
        try:
            data = self.channel_tree.GetItemData(item)
            return data if isinstance(data, dict) else {"kind": "channel", "id": data}
        except Exception:
            return {"kind": "", "id": 0}

    def on_tree_selected(self, event):
        item = event.GetItem()
        data = self._get_tree_data(item)
        if data.get("kind") == "channel":
            channel_id = data.get("id")
            self.current_channel_id = channel_id
            path = self.client.get_channel_path(channel_id) or self.channel_tree.GetItemText(item)
            self._set_status(_t("Selected channel {channel}").format(channel=path))
        elif data.get("kind") == "user":
            user = self.users.get(data.get("id"))
            label = self._user_label(user) if user is not None else self.channel_tree.GetItemText(item)
            self._set_status(label)

    def on_tree_activated(self, event):
        item = event.GetItem()
        data = self._get_tree_data(item)
        if data.get("kind") == "user":
            user = self.users.get(data.get("id"))
            label = self._user_label(user) if user is not None else self.channel_tree.GetItemText(item)
            self._append_chat(_t("Selected user: {user}").format(user=label))
            if self.sounds:
                self.sounds.speak(_t("Selected user: {user}").format(user=label))
            return
        channel_id = data.get("id") if data.get("kind") == "channel" else 0
        if not channel_id:
            return
        password = ""
        channel = self.channels.get(channel_id)
        if channel is not None and bool(getattr(channel, "bPassword", False)):
            password = self.wx.GetPasswordFromUser(
                _t("Enter channel password:"),
                _t("Join TeamTalk channel"),
                parent=self.frame,
            )
            if password is None:
                return
        if self.client.join_channel_by_id(channel_id, password):
            self.current_channel_id = channel_id
            path = self.client.get_channel_path(channel_id) or self.channel_tree.GetItemText(item)
            self._set_status(_t("Joining channel {channel}").format(channel=path))
            if self.sounds:
                self.sounds.new_chat()
        else:
            _message(self.frame, _t("Could not join the selected channel."), _t("TeamTalk"), self.wx.OK | self.wx.ICON_WARNING)

    def on_disconnect(self, event):
        self.client.disconnect()
        _state["connected"] = False
        _state["server"] = ""
        _state["username"] = ""
        self.connected_announced = False
        self.auto_join_attempted = False
        self.focus_tree_after_login = False
        self.current_channel_id = 0
        self.channels = {}
        self.users = {}
        self.channel_tree.DeleteChildren(self.channel_root)
        self.channel_items = {}
        self.user_items = {}
        self._show_connection_view()
        self._set_status(_t("Disconnected from TeamTalk"))
        self._append_chat(_t("Disconnected from TeamTalk"))
        if self.sounds:
            self.sounds.goodbye()

    def on_ptt_toggle(self, event):
        enabled = self.ptt_btn.GetValue()
        self.force_voice = enabled
        self.client.enable_voice(enabled and not self.mute_btn.GetValue())
        if self.sounds:
            if enabled:
                self.sounds.walkie_talkie_start()
            else:
                self.sounds.walkie_talkie_end()

    def on_mute_toggle(self, event):
        muted = self.mute_btn.GetValue()
        if muted:
            self.client.enable_voice(False)
            self._set_status(_t("Microphone muted"))
        else:
            self.client.enable_voice(self.force_voice or self.ptt_down)
            self._set_status(_t("Microphone ready"))

    def on_send_message(self, event):
        text = self.message.GetValue().strip()
        if not text:
            return
        if not self.client.my_channel_id:
            _message(self.frame, _t("Join a TeamTalk channel before sending channel messages."), _t("TeamTalk"), self.wx.OK | self.wx.ICON_WARNING)
            return
        sent = self.client.send_channel_message(text)
        self._append_chat(_t("Me: {message}").format(message=text))
        self.message.SetValue("")
        if self.sounds:
            self.sounds.message_sent() if sent else self.sounds.chat_message()

    def on_sdk_status(self, event):
        _message(self.frame, self.client.status_message(), _t("TeamTalk SDK status"))

    def on_key_down(self, event):
        key = event.GetKeyCode()
        if key == self.wx.WXK_F12:
            if not self.ptt_down and not self.mute_btn.GetValue():
                self.ptt_down = True
                self.client.enable_voice(True)
                if self.sounds:
                    self.sounds.walkie_talkie_start()
            return
        event.Skip()

    def on_key_up(self, event):
        key = event.GetKeyCode()
        if key == self.wx.WXK_F12 and self.ptt_down:
            self.ptt_down = False
            self.client.enable_voice(self.force_voice and not self.mute_btn.GetValue())
            if self.sounds:
                self.sounds.walkie_talkie_end()
            return
        event.Skip()

    def _on_sdk_event(self, msg):
        # The SDK exposes many event fields that differ by wrapper version. Keep
        # this intentionally defensive so supported versions can at least surface
        # useful raw event names without crashing the GUI.
        name = _value(getattr(msg, "nClientEvent", None), -1)
        if name == -1:
            name = msg.__class__.__name__
        events = getattr(self.client.sdk, "ClientEvent", None)
        profile = self.client.pending_profile or self.current_profile
        try:
            if events and name == _value(events.CLIENTEVENT_NONE):
                return
            if events and name == _value(events.CLIENTEVENT_CON_SUCCESS):
                self.wx.CallAfter(self._set_status, _t("Connected. Logging in..."))
                return
            if events and name == _value(events.CLIENTEVENT_CMD_MYSELF_LOGGEDIN):
                if profile:
                    self.wx.CallAfter(self._on_connected, profile)
                return
            if events and name == _value(events.CLIENTEVENT_CON_FAILED):
                self.wx.CallAfter(self._on_connection_failed, RuntimeError(_t("TeamTalk connection failed.")))
                return
            if events and name == _value(events.CLIENTEVENT_CON_LOST):
                self.wx.CallAfter(self.on_disconnect, None)
                return
            if events and name == _value(events.CLIENTEVENT_CMD_ERROR):
                err = getattr(msg, "clienterrormsg", None)
                text = _tt_text(getattr(err, "szErrorMsg", "")) or _t("TeamTalk command failed.")
                self.wx.CallAfter(self._append_chat, text)
                self.wx.CallAfter(self._set_status, text)
                if self.sounds:
                    self.sounds.error()
                return
            if events and name == _value(events.CLIENTEVENT_CMD_USER_TEXTMSG):
                text_msg = getattr(msg, "textmessage", None)
                text = _tt_text(getattr(text_msg, "szMessage", "")) if text_msg else ""
                sender = _tt_text(getattr(text_msg, "szFromUsername", "")) if text_msg else ""
                if text:
                    line = f"{sender}: {text}" if sender else str(text)
                    self.wx.CallAfter(self._append_chat, line)
                    if self.sounds:
                        self.sounds.chat_message()
                return
            channel_events = {
                _value(events.CLIENTEVENT_CMD_CHANNEL_NEW),
                _value(events.CLIENTEVENT_CMD_CHANNEL_UPDATE),
                _value(events.CLIENTEVENT_CMD_CHANNEL_REMOVE),
            } if events else set()
            user_events = {
                _value(events.CLIENTEVENT_CMD_USER_LOGGEDIN),
                _value(events.CLIENTEVENT_CMD_USER_LOGGEDOUT),
                _value(events.CLIENTEVENT_CMD_USER_UPDATE),
                _value(events.CLIENTEVENT_CMD_USER_JOINED),
                _value(events.CLIENTEVENT_CMD_USER_LEFT),
                _value(events.CLIENTEVENT_USER_STATECHANGE),
            } if events else set()
            if name in channel_events or name in user_events:
                self.wx.CallAfter(self._refresh_teamtalk_state, False)
                user = getattr(msg, "user", None)
                if user is not None:
                    user_id = _value(getattr(user, "nUserID", 0))
                    is_me = bool(user_id and user_id == self.client.my_user_id)
                    display = _tt_text(getattr(user, "szNickname", "")) or _tt_text(getattr(user, "szUsername", ""))
                    if display and not is_me and name == _value(events.CLIENTEVENT_CMD_USER_LOGGEDIN):
                        self.wx.CallAfter(self._set_status, _t("{user} logged in").format(user=display))
                        if self.sounds:
                            self.sounds.user_online()
                    elif display and not is_me and name == _value(events.CLIENTEVENT_CMD_USER_LOGGEDOUT):
                        self.wx.CallAfter(self._set_status, _t("{user} logged out").format(user=display))
                        if self.sounds:
                            self.sounds.user_offline()
                    elif display and name == _value(events.CLIENTEVENT_CMD_USER_JOINED):
                        self.wx.CallAfter(self._set_status, _t("{user} joined the channel").format(user=display))
                    elif display and name == _value(events.CLIENTEVENT_CMD_USER_LEFT):
                        self.wx.CallAfter(self._set_status, _t("{user} left the channel").format(user=display))
                return
        except Exception:
            pass
        self.wx.CallAfter(self._append_chat, _t("TeamTalk event: {event}").format(event=name))

    def on_close(self, event):
        self.client.disconnect()
        _state["connected"] = False
        _state["server"] = ""
        _state["username"] = ""
        if self.sounds:
            self.sounds.window_close()
        global _window
        _window = None
        self.frame.Destroy()


def open(parent_frame):
    """Open TeamTalk window."""
    global _window
    try:
        sounds = _sounds()
        if sounds:
            sounds.welcome()
        if _window is None:
            _window = TeamTalkFrame(parent_frame)
            if sounds:
                sounds.window_open()
        _window.show()
    except Exception as exc:
        print(f"[TeamTalk] Error opening module: {exc}")
        traceback.print_exc()
        try:
            _notify(_t("Could not open TeamTalk module"), "error")
        except Exception:
            pass


def get_status_text():
    if _state["connected"]:
        suffix = f"- connected to {_state['server']}"
        if _state["username"]:
            suffix += f" as {_state['username']}"
        return suffix
    if _state["sdk_available"]:
        return "- ready"
    return ""


def open_tt_file(parent_frame, path):
    """Import a .tt file and open the module window."""
    global _window
    if _window is None:
        _window = TeamTalkFrame(parent_frame)
    profile = parse_tt_file(path)
    _window.profiles.append(profile)
    _window.current_profile = profile
    _window._save()
    _window._refresh_profiles()
    _window.show()
    return True
