# -*- coding: utf-8 -*-
"""TeamTalk - Titan IM external module.

Full-featured TeamTalk 5 client styled like Titan-Net main GUI:
- Saved server profiles, .tt / tt:// import
- Manual channel join only (no auto-jump after login)
- Channel tree with users nested
- ListCtrl chat (Nick / Message / Time) - same shape as Titan-Net rooms
- Row-0 virtual tab bar on the right pane (Channel chat / Server log /
  Private messages) - same convention as TitanApp / Feedback Hub
- Per-user private message windows
- User context menu: PM / info / mute / volume / kick / ban / move / subscribe
- Channel actions: join, leave, create, update, delete, files
- Push-to-talk (F4 hold), mute mic (F2), mute speakers (F3)
- Full Titan IM sound API + Titan skin manager wired through every window
"""

import builtins
import configparser
import ctypes
import os
import sys
import threading
import time
import traceback
import urllib.parse
import xml.etree.ElementTree as ET

_MODULE_DIR = os.path.dirname(__file__)
_module = sys.modules[__name__]

DEFAULT_TCP_PORT = 10333
DEFAULT_UDP_PORT = 10333

# Tab indices on the right-pane row-0 virtual tab bar.
TAB_CHAT = 0
TAB_LOG = 1
TAB_PM = 2

# TeamTalk 5 status-mode bitfield (TT Classic constants - the Python wrapper
# does not export them, so we define them locally and OR them into the
# integer passed to doChangeStatus()).
STATUSMODE_AVAILABLE = 0x00000000
STATUSMODE_AWAY = 0x00000001
STATUSMODE_QUESTION = 0x00000002
STATUSMODE_FEMALE = 0x00000100
STATUSMODE_NEUTRAL = 0x00001000

GENDER_MALE = 0
GENDER_FEMALE = 1
GENDER_NEUTRAL = 2

_GENDER_FLAGS = {
    GENDER_MALE: 0,
    GENDER_FEMALE: STATUSMODE_FEMALE,
    GENDER_NEUTRAL: STATUSMODE_NEUTRAL,
}


def _build_status_mode(gender, away=False):
    """Combine an availability state with a gender flag into a TT status int."""
    base = STATUSMODE_AWAY if away else STATUSMODE_AVAILABLE
    return base | _GENDER_FLAGS.get(gender, 0)


# =============================================================================
# Helpers
# =============================================================================

def _t(text):
    local_gettext = getattr(_module, "_", lambda value: value)
    return local_gettext(text)


def _sounds():
    return getattr(_module, "sounds", None)


def _notify(text, kind="info", play_sound=True):
    """Speak a notification through the Titan IM sound API.

    Important: kind='info' in the central API maps to ui/dialog.ogg as the
    earcon (see src.network.titan_net_gui.speak_notification). When the
    caller is already playing its own contextual sound (e.g. new_message
    for an arriving PM) it should pass play_sound=False to avoid stacking
    the dialog earcon on top of the message earcon.
    """
    snd = _sounds()
    if snd:
        try:
            snd.notify(text, kind, play_sound_effect=play_sound)
        except TypeError:
            # Older sound API without the keyword - fall back to the
            # default behaviour rather than crash.
            try:
                snd.notify(text, kind)
            except Exception:
                pass
        except Exception:
            pass


def _play_sound(name, pan=None):
    """Play a relative sound file via the Titan sound system."""
    try:
        from src.titan_core.sound import play_sound
        if pan is not None:
            play_sound(name, pan=pan)
        else:
            play_sound(name)
    except Exception:
        pass


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


def _now_hhmm():
    return time.strftime("%H:%M:%S")


def _is_screen_reader_running():
    """Best-effort detection of NVDA / JAWS / Narrator on Windows."""
    if sys.platform != "win32":
        return False
    try:
        import psutil
        names = {p.info.get("name", "").lower() for p in psutil.process_iter(["name"])}
        return any(n in names for n in ("nvda.exe", "jfw.exe", "narrator.exe"))
    except Exception:
        return False


# =============================================================================
# Skin manager integration
# =============================================================================

def _apply_skin_recursive(window):
    """Apply the active TCE skin to a window and all of its descendants.

    Mirrors src.network.titan_net_gui._apply_skin_recursive so the TeamTalk
    module always picks up the user's selected skin (TCE Settings > Theme).
    """
    if window is None:
        return
    try:
        from src.titan_core.skin_manager import apply_skin_to_window
    except Exception:
        return
    try:
        apply_skin_to_window(window)
    except Exception:
        pass
    try:
        for child in window.GetChildren():
            _apply_skin_recursive(child)
    except Exception:
        pass


def _message(parent, text, title=None, style=None):
    import wx

    title = title or _t("TeamTalk")
    style = style or (wx.OK | wx.ICON_INFORMATION)
    dlg = wx.MessageDialog(parent, text, title, style)
    _apply_skin_recursive(dlg)
    result = dlg.ShowModal()
    dlg.Destroy()
    return result


def _ask_text(parent, message, title="", default=""):
    import wx
    dlg = wx.TextEntryDialog(parent, message, title, default)
    _apply_skin_recursive(dlg)
    ok = dlg.ShowModal() == wx.ID_OK
    value = dlg.GetValue() if ok else None
    dlg.Destroy()
    return value


def _ask_password(parent, message, title=""):
    import wx
    dlg = wx.PasswordEntryDialog(parent, message, title)
    _apply_skin_recursive(dlg)
    ok = dlg.ShowModal() == wx.ID_OK
    value = dlg.GetValue() if ok else None
    dlg.Destroy()
    return value


# =============================================================================
# .tt / tt:// parsers (preserved from previous version)
# =============================================================================

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
        if clean in {n.replace("_", "") for n in names}:
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
        # TT Classic style gender flag, sent via doChangeStatus on login.
        # 0 = male (default), 1 = female, 2 = neutral.
        "gender": GENDER_MALE,
    }
    for key, value in (data or {}).items():
        canonical = _config_key_variants(str(key))
        if canonical in profile:
            profile[canonical] = value
    profile["host"] = str(profile["host"]).strip()
    profile["entry_name"] = str(
        profile["entry_name"] or profile["host"] or _t("TeamTalk server")
    ).strip()
    profile["tcpport"] = _as_int(profile["tcpport"], DEFAULT_TCP_PORT)
    profile["udpport"] = _as_int(profile["udpport"], profile["tcpport"] or DEFAULT_UDP_PORT)
    profile["encrypted"] = _as_bool(profile["encrypted"])
    for key in ("username", "password", "nickname", "channel", "chanpasswd"):
        profile[key] = str(profile.get(key) or "").strip()
    try:
        gender = int(profile.get("gender", GENDER_MALE))
        profile["gender"] = gender if gender in _GENDER_FLAGS else GENDER_MALE
    except Exception:
        profile["gender"] = GENDER_MALE
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
            if section.lower() in ("server", "teamtalk", "teamtalk5", "connection"):
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
    text = (text or "").strip()
    if not text:
        raise ValueError(_t("The selected .tt file is empty."))
    for parser in (_parse_tt_url, _parse_xml_tt, _parse_ini_tt):
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


# =============================================================================
# Config storage
# =============================================================================

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
    profiles = [
        _normalize_profile(item)
        for item in teamtalk.get("profiles", [])
        if isinstance(item, dict)
    ]
    return {
        "profiles": profiles,
        "last_profile": teamtalk.get("last_profile", ""),
        "ptt_enabled": bool(teamtalk.get("ptt_enabled", True)),
    }


def save_teamtalk_config(teamtalk_config):
    config = _load_all_config()
    config["teamtalk"] = teamtalk_config
    return _save_all_config(config)


# =============================================================================
# Module-level connection state (used by get_status_text)
# =============================================================================

_state = {
    "connected": False,
    "server": "",
    "username": "",
    "sdk_available": False,
}
_window = None


def _sdk_native_lib_name():
    if sys.platform == "win32":
        return "TeamTalk5.dll"
    if sys.platform == "darwin":
        return "libTeamTalk5.dylib"
    return "libTeamTalk5.so"


def _sdk_hint():
    return _t(
        "TeamTalk SDK was not found. Place TeamTalk5.py and the native "
        "TeamTalk5 library ({lib}) from the BearWare TeamTalk 5 SDK into "
        "data/titanIM_modules/TeamTalk/lib (and TeamTalk_DLL/ on Windows), "
        "then restart Titan."
    ).format(lib=_sdk_native_lib_name())


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


# =============================================================================
# TeamTalk SDK wrapper
# =============================================================================

class TeamTalkSdkClient:
    """Thin async wrapper around BearWare's TeamTalk5.py.

    Important: this client never auto-joins a channel after login. The UI
    decides when (and which) channel to join based on user input.
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

    # ---- Lifecycle -------------------------------------------------------

    def available(self):
        return self.sdk is not None

    def status_message(self):
        if self.available():
            return _t("TeamTalk SDK loaded")
        return f"{_sdk_hint()}\n\n{self.import_error}"

    def connect(self, profile):
        if not self.available():
            raise RuntimeError(_sdk_hint())
        profile = _normalize_profile(profile)
        self.pending_profile = profile

        teamtalk_class = getattr(self.sdk, "TeamTalk", None)
        if not teamtalk_class:
            raise RuntimeError(
                _t("The loaded TeamTalk SDK does not expose a TeamTalk initializer.")
            )
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
        if not ok:
            raise RuntimeError(_t("Could not start TeamTalk connection."))
        self.connected = True
        self._start_polling()
        return True

    def _init_default_audio_devices(self):
        """Initialize the default microphone and speakers.

        Stores results on self so the UI can surface them on the server-log
        tab and the user can see why voice transmission may be silent
        (e.g. no microphone, or a device id of -1 from getDefaultSoundDevices).
        """
        self.input_device_id = None
        self.output_device_id = None
        self.input_device_name = ""
        self.output_device_name = ""
        self.input_init_ok = False
        self.output_init_ok = False
        if not self.obj:
            return
        try:
            indev, outdev = self.obj.getDefaultSoundDevices()
            indev = getattr(indev, "value", indev)
            outdev = getattr(outdev, "value", outdev)
            self.input_device_id = int(indev) if indev is not None else None
            self.output_device_id = int(outdev) if outdev is not None else None
        except Exception as exc:
            print(f"[TeamTalk] getDefaultSoundDevices failed: {exc}")
            return
        # Resolve device names so we can log something meaningful.
        try:
            for dev in self.obj.getSoundDevices():
                dev_id = _value(getattr(dev, "nDeviceID", None), -999)
                name = _tt_text(getattr(dev, "szDeviceName", ""))
                if self.input_device_id is not None and dev_id == self.input_device_id:
                    self.input_device_name = name
                if self.output_device_id is not None and dev_id == self.output_device_id:
                    self.output_device_name = name
        except Exception as exc:
            print(f"[TeamTalk] getSoundDevices failed: {exc}")
        try:
            if self.input_device_id is not None and self.input_device_id != -1:
                self.input_init_ok = bool(
                    self.obj.initSoundInputDevice(self.input_device_id)
                )
            if self.output_device_id is not None and self.output_device_id != -1:
                self.output_init_ok = bool(
                    self.obj.initSoundOutputDevice(self.output_device_id)
                )
        except Exception as exc:
            print(f"[TeamTalk] initSoundDevice failed: {exc}")

    def login(self, profile):
        if not self.available() or not self.obj:
            return False
        nickname = profile.get("nickname") or profile.get("username") or "Titan"
        username = profile.get("username", "")
        password = profile.get("password", "")
        try:
            self.obj.doLogin(nickname, username, password, "Titan IM")
            self.logged_in = True
            return True
        except Exception as exc:
            print(f"[TeamTalk] Login error: {exc}")
            return False

    def disconnect(self):
        self.polling = False
        if self.obj:
            try:
                self.obj.disconnect()
                self.obj.closeTeamTalk()
            except Exception:
                pass
        self.obj = None
        self.tt = None
        self.connected = False
        self.logged_in = False
        self.my_user_id = 0
        self.my_channel_id = 0

    # ---- Channels --------------------------------------------------------

    def join_channel_by_id(self, channel_id, password=""):
        if not (self.available() and self.obj and channel_id):
            return False
        try:
            return bool(self.obj.doJoinChannelByID(channel_id, password))
        except Exception:
            return False

    def join_channel_path(self, channel_path, password=""):
        if not channel_path or not (self.available() and self.obj):
            return False
        try:
            channel_id = self.obj.getChannelIDFromPath(channel_path)
            if channel_id:
                return self.join_channel_by_id(channel_id, password)
        except Exception:
            pass
        return False

    def leave_channel(self):
        if self.available() and self.obj:
            try:
                return bool(self.obj.doLeaveChannel())
            except Exception:
                return False
        return False

    def get_channel_users(self, channel_id):
        if not (self.available() and self.obj and channel_id):
            return []
        try:
            return list(self.obj.getChannelUsers(channel_id))
        except Exception:
            return []

    def get_channel_path(self, channel_id):
        if not (self.available() and self.obj and channel_id):
            return ""
        try:
            return _tt_text(self.obj.getChannelPath(channel_id))
        except Exception:
            return ""

    def get_channel(self, channel_id):
        if not (self.available() and self.obj and channel_id):
            return None
        try:
            return self.obj.getChannel(channel_id)
        except Exception:
            return None

    def remove_channel(self, channel_id):
        if not (self.available() and self.obj and channel_id):
            return False
        try:
            self.obj.doRemoveChannel(channel_id)
            return True
        except Exception:
            return False

    # ---- Refresh ---------------------------------------------------------

    def refresh_state(self):
        if not (self.available() and self.obj):
            return {
                "channels": [],
                "users": [],
                "root_id": 0,
                "my_channel_id": 0,
                "my_user_id": 0,
            }
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

    def get_user(self, user_id):
        if not (self.available() and self.obj and user_id):
            return None
        try:
            return self.obj.getUser(user_id)
        except Exception:
            return None

    # ---- Voice / audio ---------------------------------------------------

    def enable_voice(self, enabled):
        """Toggle our outgoing voice transmission.

        TT5 will accept the call only when:
            * a sound input device is initialized (initSoundInputDevice),
            * we are logged in and inside a channel (getMyChannelID != 0),
            * our account has USERRIGHT_TRANSMIT_VOICE.
        Returns the boolean the SDK returns - False means TT5 rejected it.
        """
        if not (self.available() and self.obj):
            return False
        try:
            result = bool(self.obj.enableVoiceTransmission(enabled))
            print(f"[TeamTalk] enableVoiceTransmission({enabled}) -> {result}")
            return result
        except Exception as exc:
            print(f"[TeamTalk] enableVoiceTransmission error: {exc}")
            return False

    def set_speaker_mute(self, muted):
        if not (self.available() and self.tt):
            return False
        fn = getattr(self.sdk, "_SetSoundOutputMute", None)
        if fn:
            try:
                return bool(fn(self.tt, bool(muted)))
            except Exception:
                return False
        return False

    def set_user_mute(self, user_id, muted, voice=True):
        """Mute or unmute a specific user's voice (or media file) stream."""
        if not (self.available() and self.tt and user_id):
            return False
        fn = getattr(self.sdk, "_SetUserMute", None)
        stream_types = getattr(self.sdk, "StreamType", None)
        stream = (
            _value(getattr(stream_types, "STREAMTYPE_VOICE", 0x1)) if voice
            else _value(getattr(stream_types, "STREAMTYPE_MEDIAFILE_AUDIO", 0x4))
        )
        if fn:
            try:
                return bool(fn(self.tt, int(user_id), int(stream), bool(muted), 0))
            except Exception:
                return False
        return False

    def set_user_volume(self, user_id, volume):
        """Volume 0..32000 - SDK clamps. Uses voice stream."""
        if not (self.available() and self.tt and user_id):
            return False
        fn = getattr(self.sdk, "_SetUserVolume", None)
        stream_types = getattr(self.sdk, "StreamType", None)
        stream = _value(getattr(stream_types, "STREAMTYPE_VOICE", 0x1))
        if fn:
            try:
                return bool(fn(self.tt, int(user_id), int(stream), int(volume)))
            except Exception:
                return False
        return False

    # ---- Subscriptions ---------------------------------------------------

    def subscribe(self, user_id, sub_flag):
        if not (self.available() and self.obj and user_id):
            return False
        try:
            return bool(self.obj.doSubscribe(user_id, sub_flag))
        except Exception:
            return False

    def unsubscribe(self, user_id, sub_flag):
        if not (self.available() and self.obj and user_id):
            return False
        try:
            return bool(self.obj.doUnsubscribe(user_id, sub_flag))
        except Exception:
            return False

    # ---- Messaging -------------------------------------------------------

    def send_channel_message(self, text):
        if not (self.available() and self.obj):
            return False
        try:
            # Always ask the SDK for the current channel - the cached value
            # can be stale right after a join. TT5 won't deliver a channel
            # message unless we are still in that channel server-side.
            channel_id = _value(self.obj.getMyChannelID())
            self.my_channel_id = channel_id
            if not channel_id:
                return False
            msg_type = getattr(self.sdk.TextMsgType, "MSGTYPE_CHANNEL", 2)
            # buildTextMessage chunks long content (TT_STRLEN limit) and
            # marks every non-final chunk with bMore=True; doTextMessage
            # must be called for every chunk in order.
            messages = self.sdk.buildTextMessage(text, msg_type, nChannelID=channel_id)
            sent = False
            for message in messages:
                if self.obj.doTextMessage(message):
                    sent = True
            return sent
        except Exception as exc:
            print(f"[TeamTalk] send_channel_message error: {exc}")
            return False

    def in_channel(self):
        """Return True if we are currently logged in AND in a channel."""
        if not (self.available() and self.obj):
            return False
        try:
            return _value(self.obj.getMyChannelID()) != 0
        except Exception:
            return False

    def can_transmit_voice(self):
        """Check USERRIGHT_TRANSMIT_VOICE on our user account."""
        if not (self.available() and self.obj):
            return False
        try:
            account = self.obj.getMyUserAccount()
            rights = _value(getattr(account, "uUserRights", 0))
            voice_right = _value(self.sdk.UserRight.USERRIGHT_TRANSMIT_VOICE)
            return bool(rights & voice_right)
        except Exception:
            # If we cannot read the account fall back to True - the SDK will
            # simply reject the transmit later if the right is missing.
            return True

    def send_user_message(self, user_id, text):
        if not (self.available() and self.obj and user_id):
            return False
        try:
            msg_type = getattr(self.sdk.TextMsgType, "MSGTYPE_USER", 1)
            messages = self.sdk.buildTextMessage(text, msg_type, nToUserID=user_id)
            sent = False
            for message in messages:
                if self.obj.doTextMessage(message):
                    sent = True
            return sent
        except Exception as exc:
            print(f"[TeamTalk] send_user_message error: {exc}")
            return False

    # ---- Admin actions ---------------------------------------------------

    def kick_user(self, user_id, channel_id=0):
        if not (self.available() and self.obj and user_id):
            return False
        try:
            self.obj.doKickUser(user_id, channel_id)
            return True
        except Exception:
            return False

    def ban_user(self, user_id, channel_id=0):
        if not (self.available() and self.obj and user_id):
            return False
        try:
            self.obj.doBanUser(user_id, channel_id)
            return True
        except Exception:
            return False

    def move_user(self, user_id, channel_id):
        if not (self.available() and self.obj and user_id and channel_id):
            return False
        try:
            self.obj.doMoveUser(user_id, channel_id)
            return True
        except Exception:
            return False

    def change_status(self, mode, message_text):
        if not (self.available() and self.obj):
            return False
        try:
            self.obj.doChangeStatus(int(mode), message_text or "")
            return True
        except Exception:
            return False

    def change_nickname(self, nickname):
        if not (self.available() and self.obj):
            return False
        try:
            self.obj.doChangeNickname(nickname)
            return True
        except Exception:
            return False

    # ---- Polling ---------------------------------------------------------

    def _start_polling(self):
        if self.polling:
            return
        self.polling = True
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()

    def _poll_loop(self):
        while self.polling and self.obj:
            try:
                msg = self.obj.getMessage(250)
                self._dispatch(msg)
            except Exception:
                time.sleep(0.25)

    def _dispatch(self, msg):
        events = getattr(self.sdk, "ClientEvent", None)
        try:
            event = _value(getattr(msg, "nClientEvent", 0))
            # Auto-login is the only auto-step we keep — that is the standard
            # TeamTalk session handshake. We deliberately do NOT auto-join
            # any channel after CMD_MYSELF_LOGGEDIN.
            if (
                events
                and event == _value(events.CLIENTEVENT_CON_SUCCESS)
                and self.pending_profile
            ):
                self.login(self.pending_profile)
        except Exception:
            pass
        if self.on_event:
            try:
                self.on_event(msg)
            except Exception:
                pass


# =============================================================================
# Profile editor dialog
# =============================================================================

class ProfileDialog:
    def __init__(self, parent, profile=None):
        import wx

        self.wx = wx
        self.profile = _normalize_profile(profile or {})
        self.dialog = wx.Dialog(parent, title=_t("TeamTalk Server"), size=(440, 540))
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
            ("channel", _t("Default channel (optional - never auto-joined):"), 0),
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
        _apply_skin_recursive(self.dialog)

    def show_modal(self):
        result = self.dialog.ShowModal()
        if result == self.wx.ID_OK:
            profile = {key: ctrl.GetValue().strip() for key, ctrl in self.controls.items()}
            profile["encrypted"] = self.encrypted.GetValue()
            self.profile = _normalize_profile(profile)
        self.dialog.Destroy()
        return result == self.wx.ID_OK


# =============================================================================
# User info dialog (read-only)
# =============================================================================

class UserInfoDialog:
    def __init__(self, parent, sdk, user):
        import wx

        self.wx = wx
        nick = _tt_text(getattr(user, "szNickname", "")) or _tt_text(
            getattr(user, "szUsername", "")
        )
        self.dialog = wx.Dialog(parent, title=_t("User info: {nick}").format(nick=nick))
        panel = wx.Panel(self.dialog)
        sizer = wx.BoxSizer(wx.VERTICAL)

        rows = [
            (_t("Nickname"), _tt_text(getattr(user, "szNickname", ""))),
            (_t("Username"), _tt_text(getattr(user, "szUsername", ""))),
            (_t("Status message"), _tt_text(getattr(user, "szStatusMsg", ""))),
            (_t("Client"), _tt_text(getattr(user, "szClientName", ""))),
            (_t("IP address"), _tt_text(getattr(user, "szIPAddress", ""))),
            (_t("User ID"), str(_value(getattr(user, "nUserID", 0)))),
            (_t("Channel ID"), str(_value(getattr(user, "nChannelID", 0)))),
            (_t("Voice volume"), str(_value(getattr(user, "nVolumeVoice", 0)))),
        ]
        grid = wx.FlexGridSizer(rows=len(rows), cols=2, vgap=6, hgap=10)
        for label, value in rows:
            grid.Add(wx.StaticText(panel, label=label + ":"))
            ctrl = wx.TextCtrl(panel, value=str(value), style=wx.TE_READONLY)
            ctrl.SetMinSize((360, -1))
            grid.Add(ctrl, 1, wx.EXPAND)
        sizer.Add(grid, 1, wx.ALL | wx.EXPAND, 12)

        buttons = self.dialog.CreateSeparatedButtonSizer(wx.OK)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)

        panel.SetSizer(sizer)
        wrapper = wx.BoxSizer(wx.VERTICAL)
        wrapper.Add(panel, 1, wx.EXPAND)
        self.dialog.SetSizer(wrapper)
        self.dialog.SetSize((480, 440))
        self.dialog.CentreOnParent()
        _apply_skin_recursive(self.dialog)

    def show_modal(self):
        self.dialog.ShowModal()
        self.dialog.Destroy()


# =============================================================================
# Nickname + gender dialog (TeamTalk Classic "Change nickname" style)
# =============================================================================

class NicknameGenderDialog:
    """Lets the user set their nickname and TT5 gender flag.

    Mirrors the TeamTalk Classic preferences dialog: nickname text field +
    Male / Female / Neutral radio. The result is applied with
    doChangeNickname() and doChangeStatus(STATUSMODE_FEMALE/NEUTRAL).
    """

    def __init__(self, parent, current_nickname="", current_gender=GENDER_MALE):
        import wx

        self.wx = wx
        self.result_nickname = current_nickname
        self.result_gender = current_gender

        self.dialog = wx.Dialog(parent, title=_t("Set nickname and gender"))
        panel = wx.Panel(self.dialog)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(panel, label=_t("Nickname:")),
                  0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        self.nick_ctrl = wx.TextCtrl(panel)
        self.nick_ctrl.SetValue(str(current_nickname or ""))
        self.nick_ctrl.SetName(_t("Nickname"))
        sizer.Add(self.nick_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        choices = [_t("Male"), _t("Female"), _t("Neutral")]
        self.gender_radio = wx.RadioBox(
            panel,
            label=_t("Gender"),
            choices=choices,
            majorDimension=1,
            style=wx.RA_SPECIFY_COLS,
        )
        try:
            self.gender_radio.SetSelection(
                int(current_gender) if int(current_gender) in (0, 1, 2) else 0
            )
        except Exception:
            self.gender_radio.SetSelection(0)
        sizer.Add(self.gender_radio, 0, wx.EXPAND | wx.ALL, 8)

        buttons = self.dialog.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)

        panel.SetSizer(sizer)
        wrapper = wx.BoxSizer(wx.VERTICAL)
        wrapper.Add(panel, 1, wx.EXPAND)
        self.dialog.SetSizer(wrapper)
        self.dialog.Fit()
        self.dialog.CentreOnParent()
        _apply_skin_recursive(self.dialog)

        self.nick_ctrl.SetFocus()
        try:
            self.nick_ctrl.SetInsertionPointEnd()
        except Exception:
            pass

    def show_modal(self):
        ok = self.dialog.ShowModal() == self.wx.ID_OK
        if ok:
            self.result_nickname = self.nick_ctrl.GetValue().strip()
            self.result_gender = int(self.gender_radio.GetSelection())
        self.dialog.Destroy()
        return ok


# =============================================================================
# Per-user private message window
# =============================================================================

class PrivateMessageWindow:
    """Per-user PM window styled like Titan-Net room chat.

    Layout:
        - Header label with peer nickname
        - wx.ListCtrl with columns Nick / Message / Time (matches
          src.network.titan_net_gui.message_display)
        - Message input + Send button
    """

    def __init__(self, parent_frame, frame_owner, user_id, nickname):
        import wx

        self.wx = wx
        self.frame_owner = frame_owner  # TeamTalkFrame, owns the SDK client
        self.user_id = user_id
        self.nickname = nickname or _t("user")
        title = _t("Private message: {nick}").format(nick=self.nickname)

        self.frame = wx.Frame(parent_frame, title=title, size=(640, 460))
        self.frame.Bind(wx.EVT_CLOSE, self._on_close)
        panel = wx.Panel(self.frame)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(
            wx.StaticText(panel, label=_t("Conversation with {nick}").format(nick=self.nickname)),
            0,
            wx.ALL,
            8,
        )

        self.messages = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.messages.AppendColumn(_t("Nick"), width=140)
        self.messages.AppendColumn(_t("Message"), width=380)
        self.messages.AppendColumn(_t("Time"), width=100)
        self.messages.SetName(_t("Private message history with {nick}").format(nick=self.nickname))
        sizer.Add(self.messages, 1, wx.EXPAND | wx.ALL, 8)

        send_row = wx.BoxSizer(wx.HORIZONTAL)
        self.input = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.input.SetName(_t("Type private message"))
        self.input.Bind(wx.EVT_TEXT_ENTER, self._on_send)
        send_btn = wx.Button(panel, label=_t("Send"))
        send_btn.Bind(wx.EVT_BUTTON, self._on_send)
        close_btn = wx.Button(panel, label=_t("Close"))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.frame.Close())
        send_row.Add(self.input, 1, wx.EXPAND | wx.RIGHT, 6)
        send_row.Add(send_btn, 0, wx.RIGHT, 4)
        send_row.Add(close_btn, 0)
        sizer.Add(send_row, 0, wx.EXPAND | wx.ALL, 8)

        panel.SetSizer(sizer)
        _apply_skin_recursive(self.frame)

    def show(self):
        self.frame.Show()
        self.frame.Raise()
        self.input.SetFocus()

    def append(self, sender, text):
        idx = self.messages.GetItemCount()
        self.messages.InsertItem(idx, sender)
        self.messages.SetItem(idx, 1, text)
        self.messages.SetItem(idx, 2, _now_hhmm())
        self.messages.EnsureVisible(idx)

    def _on_send(self, event):
        text = self.input.GetValue().strip()
        if not text:
            return
        if not self.frame_owner.client.send_user_message(self.user_id, text):
            self.frame_owner._log_event(_t("Could not send private message."))
            snd = _sounds()
            if snd:
                try:
                    snd.error()
                except Exception:
                    pass
            return
        self.append(_t("Me"), text)
        self.input.SetValue("")
        snd = _sounds()
        if snd:
            try:
                snd.message_sent()
            except Exception:
                pass

    def _on_close(self, event):
        try:
            self.frame_owner.pm_windows.pop(self.user_id, None)
        except Exception:
            pass
        self.frame.Destroy()


# =============================================================================
# Main TeamTalk frame
# =============================================================================

class TeamTalkFrame:
    def __init__(self, parent):
        import wx

        self.wx = wx
        self.config = load_teamtalk_config()
        self.profiles = self.config["profiles"]
        self.current_profile = None
        self.client = TeamTalkSdkClient(on_event=self._on_sdk_event)

        # Channel/user model
        self.channels = {}
        self.users = {}
        self.channel_items = {}
        self.user_items = {}
        self.current_channel_id = 0
        self.connected_announced = False
        self.focus_tree_after_login = False

        # PM windows by user id
        self.pm_windows = {}

        # Right-pane tab bar
        self.current_tab = TAB_CHAT
        self.chat_messages = []  # list of (sender, text, time_str)
        self.log_entries = []  # list of (text, time_str)
        self.pm_threads = {}  # user_id -> {"nick": str, "last": str, "time": str}

        # Multi-part text-message buffers (TT chunks long messages with
        # bMore=True; we re-assemble per (msg_type, from_user, to_user/channel)).
        self._pm_partials = {}

        # Initial-roster guard: while True, we suppress the user_online /
        # user_offline earcons. The TT5 server fires CMD_USER_LOGGEDIN /
        # CMD_USER_JOINED for every account already on the server right
        # after we connect; without this guard a busy server bombs the user
        # with dozens of presence sounds at login. Lifted once login has
        # settled (see _on_connected).
        self._suppress_presence_sounds = True

        # Voice/audio state
        self.ptt_held = False
        self.ptt_toggle = False
        self.mic_muted = False
        self.speakers_muted = False

        # Frame
        self.frame = wx.Frame(parent, title=_t("TeamTalk - Titan IM"), size=(940, 660))
        self.frame.Bind(wx.EVT_CLOSE, self.on_close)
        self.frame.Bind(wx.EVT_CHAR_HOOK, self._on_key_hook)
        self.frame.Bind(wx.EVT_KEY_UP, self._on_key_up)

        self._build_ui()
        self._build_menu()
        self._refresh_profiles()
        self._set_status(self.client.status_message())
        _apply_skin_recursive(self.frame)

        snd = _sounds()
        if snd:
            try:
                snd.welcome()
            except Exception:
                pass

    # ---- UI construction ------------------------------------------------

    def _build_ui(self):
        wx = self.wx
        self.root_panel = wx.Panel(self.frame)
        self.root_sizer = wx.BoxSizer(wx.VERTICAL)

        self._build_connection_panel()
        self._build_connected_panel()

        self.root_sizer.Add(self.connection_panel, 1, wx.EXPAND)
        self.root_sizer.Add(self.connected_panel, 1, wx.EXPAND)
        self.root_panel.SetSizer(self.root_sizer)
        self._show_connection_view()

        self.frame.CreateStatusBar()
        self._setup_accessibility_names()

    def _build_connection_panel(self):
        wx = self.wx
        panel = wx.Panel(self.root_panel)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(
            wx.StaticText(panel, label=_t("TeamTalk servers")), 0, wx.ALL, 8
        )

        self.profile_list = wx.ListBox(panel, style=wx.LB_SINGLE | wx.WANTS_CHARS)
        self.profile_list.Bind(wx.EVT_LISTBOX, self.on_profile_selected)
        self.profile_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_connect)
        self.profile_list.Bind(wx.EVT_KEY_DOWN, self.on_profile_key)
        sizer.Add(self.profile_list, 1, wx.EXPAND | wx.ALL, 8)

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        self.connect_btn = wx.Button(panel, label=_t("Connect"))
        self.add_btn = wx.Button(panel, label=_t("Add"))
        self.edit_btn = wx.Button(panel, label=_t("Edit"))
        self.remove_btn = wx.Button(panel, label=_t("Remove"))
        self.import_btn = wx.Button(panel, label=_t("Import .tt"))
        for btn in (
            self.connect_btn,
            self.add_btn,
            self.edit_btn,
            self.remove_btn,
            self.import_btn,
        ):
            button_row.Add(btn, 0, wx.RIGHT, 5)
        sizer.Add(button_row, 0, wx.ALL, 8)

        self.connect_btn.Bind(wx.EVT_BUTTON, self.on_connect)
        self.add_btn.Bind(wx.EVT_BUTTON, self.on_add_profile)
        self.edit_btn.Bind(wx.EVT_BUTTON, self.on_edit_profile)
        self.remove_btn.Bind(wx.EVT_BUTTON, self.on_remove_profile)
        self.import_btn.Bind(wx.EVT_BUTTON, self.on_import_tt)

        panel.SetSizer(sizer)
        self.connection_panel = panel

    def _build_connected_panel(self):
        wx = self.wx
        panel = wx.Panel(self.root_panel)
        outer = wx.BoxSizer(wx.VERTICAL)

        # ---- Top toolbar ----
        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        self.disconnect_btn = wx.Button(panel, label=_t("Disconnect"))
        self.ptt_btn = wx.ToggleButton(panel, label=_t("Push to talk"))
        self.mute_mic_btn = wx.ToggleButton(panel, label=_t("Mute microphone"))
        self.mute_spk_btn = wx.ToggleButton(panel, label=_t("Mute speakers"))
        self.status_btn = wx.Button(panel, label=_t("Set status..."))
        for btn in (
            self.disconnect_btn,
            self.ptt_btn,
            self.mute_mic_btn,
            self.mute_spk_btn,
            self.status_btn,
        ):
            toolbar.Add(btn, 0, wx.RIGHT, 6)
        outer.Add(toolbar, 0, wx.ALL, 8)

        self.disconnect_btn.Bind(wx.EVT_BUTTON, self.on_disconnect)
        self.ptt_btn.Bind(wx.EVT_TOGGLEBUTTON, self.on_ptt_toggle)
        self.mute_mic_btn.Bind(wx.EVT_TOGGLEBUTTON, self.on_mute_mic_toggle)
        self.mute_spk_btn.Bind(wx.EVT_TOGGLEBUTTON, self.on_mute_speakers_toggle)
        self.status_btn.Bind(wx.EVT_BUTTON, self.on_set_status)

        # ---- Splitter: tree on the left, tabbed list on the right ----
        self.splitter = wx.SplitterWindow(panel, style=wx.SP_LIVE_UPDATE)
        left = wx.Panel(self.splitter)
        right = wx.Panel(self.splitter)

        # Left: channel tree
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        left_sizer.Add(
            wx.StaticText(left, label=_t("Channels and users")),
            0,
            wx.ALL,
            6,
        )
        self.channel_tree = wx.TreeCtrl(
            left,
            style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT | wx.TR_SINGLE,
        )
        self.channel_root = self.channel_tree.AddRoot(_t("TeamTalk"))
        self.channel_tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.on_tree_activated)
        self.channel_tree.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_tree_selected)
        self.channel_tree.Bind(wx.EVT_TREE_ITEM_RIGHT_CLICK, self.on_tree_right_click)
        self.channel_tree.Bind(wx.EVT_CONTEXT_MENU, self._on_tree_context_menu)
        self.channel_tree.Bind(wx.EVT_KEY_DOWN, self.on_tree_key_down)
        left_sizer.Add(self.channel_tree, 1, wx.EXPAND | wx.ALL, 6)
        left.SetSizer(left_sizer)

        # Right: tab-bar driven ListCtrl + message input
        right_sizer = wx.BoxSizer(wx.VERTICAL)
        self.right_label = wx.StaticText(right, label=self._right_label_for_tab())
        right_sizer.Add(self.right_label, 0, wx.ALL, 6)

        self.right_list = wx.ListCtrl(right, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.right_list.AppendColumn(_t("Nick"), width=140)
        self.right_list.AppendColumn(_t("Message"), width=420)
        self.right_list.AppendColumn(_t("Time"), width=100)
        self.right_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_right_activated)
        self.right_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_right_selected)
        self.right_list.Bind(wx.EVT_KEY_DOWN, self._on_right_key)
        right_sizer.Add(self.right_list, 1, wx.EXPAND | wx.ALL, 6)

        send_row = wx.BoxSizer(wx.HORIZONTAL)
        self.message_input = wx.TextCtrl(right, style=wx.TE_PROCESS_ENTER)
        self.message_input.Bind(wx.EVT_TEXT_ENTER, self.on_send_message)
        self.send_btn = wx.Button(right, label=_t("Send"))
        self.send_btn.Bind(wx.EVT_BUTTON, self.on_send_message)
        send_row.Add(self.message_input, 1, wx.EXPAND | wx.RIGHT, 6)
        send_row.Add(self.send_btn, 0)
        right_sizer.Add(send_row, 0, wx.EXPAND | wx.ALL, 6)
        right.SetSizer(right_sizer)

        self.splitter.SplitVertically(left, right, 320)
        self.splitter.SetMinimumPaneSize(220)
        outer.Add(self.splitter, 1, wx.EXPAND | wx.ALL, 4)

        panel.SetSizer(outer)
        self.connected_panel = panel

    def _build_menu(self):
        wx = self.wx
        menubar = wx.MenuBar()

        server_menu = wx.Menu()
        m_import = server_menu.Append(wx.ID_ANY, _t("Import .tt file"))
        m_connect = server_menu.Append(wx.ID_ANY, _t("Connect"))
        m_disconnect = server_menu.Append(wx.ID_ANY, _t("Disconnect"))
        server_menu.AppendSeparator()
        m_nick = server_menu.Append(wx.ID_ANY, _t("Set nickname and gender...\tCtrl+N"))
        server_menu.AppendSeparator()
        m_close = server_menu.Append(wx.ID_EXIT, _t("Close"))
        self.frame.Bind(wx.EVT_MENU, self.on_import_tt, m_import)
        self.frame.Bind(wx.EVT_MENU, self.on_connect, m_connect)
        self.frame.Bind(wx.EVT_MENU, self.on_disconnect, m_disconnect)
        self.frame.Bind(wx.EVT_MENU, lambda e: self._show_nickname_dialog(), m_nick)
        self.frame.Bind(wx.EVT_MENU, self.on_close, m_close)
        menubar.Append(server_menu, _t("Server"))

        chan_menu = wx.Menu()
        m_join = chan_menu.Append(wx.ID_ANY, _t("Join selected channel\tCtrl+J"))
        m_leave = chan_menu.Append(wx.ID_ANY, _t("Leave channel\tCtrl+L"))
        chan_menu.AppendSeparator()
        m_create = chan_menu.Append(wx.ID_ANY, _t("Create channel..."))
        m_delete = chan_menu.Append(wx.ID_ANY, _t("Delete selected channel"))
        self.frame.Bind(wx.EVT_MENU, lambda e: self._join_selected(), m_join)
        self.frame.Bind(wx.EVT_MENU, lambda e: self._leave_current(), m_leave)
        self.frame.Bind(wx.EVT_MENU, lambda e: self._create_channel(), m_create)
        self.frame.Bind(wx.EVT_MENU, lambda e: self._delete_selected_channel(), m_delete)
        menubar.Append(chan_menu, _t("Channels"))

        user_menu = wx.Menu()
        m_pm = user_menu.Append(wx.ID_ANY, _t("Send private message...\tCtrl+M"))
        m_info = user_menu.Append(wx.ID_ANY, _t("User info\tCtrl+I"))
        user_menu.AppendSeparator()
        m_mute_user = user_menu.Append(wx.ID_ANY, _t("Toggle mute for selected user"))
        m_volume = user_menu.Append(wx.ID_ANY, _t("Set volume for selected user..."))
        user_menu.AppendSeparator()
        m_kick = user_menu.Append(wx.ID_ANY, _t("Kick selected user"))
        m_ban = user_menu.Append(wx.ID_ANY, _t("Ban selected user"))
        self.frame.Bind(wx.EVT_MENU, lambda e: self._pm_selected_user(), m_pm)
        self.frame.Bind(wx.EVT_MENU, lambda e: self._show_user_info(), m_info)
        self.frame.Bind(wx.EVT_MENU, lambda e: self._toggle_mute_selected_user(), m_mute_user)
        self.frame.Bind(wx.EVT_MENU, lambda e: self._set_volume_selected_user(), m_volume)
        self.frame.Bind(wx.EVT_MENU, lambda e: self._kick_selected_user(), m_kick)
        self.frame.Bind(wx.EVT_MENU, lambda e: self._ban_selected_user(), m_ban)
        menubar.Append(user_menu, _t("Users"))

        view_menu = wx.Menu()
        m_chat = view_menu.Append(wx.ID_ANY, _t("Channel chat\tCtrl+1"))
        m_log = view_menu.Append(wx.ID_ANY, _t("Server log\tCtrl+2"))
        m_pms = view_menu.Append(wx.ID_ANY, _t("Private messages\tCtrl+3"))
        self.frame.Bind(wx.EVT_MENU, lambda e: self._set_tab(TAB_CHAT), m_chat)
        self.frame.Bind(wx.EVT_MENU, lambda e: self._set_tab(TAB_LOG), m_log)
        self.frame.Bind(wx.EVT_MENU, lambda e: self._set_tab(TAB_PM), m_pms)
        menubar.Append(view_menu, _t("View"))

        help_menu = wx.Menu()
        m_sdk = help_menu.Append(wx.ID_ANY, _t("SDK status"))
        self.frame.Bind(wx.EVT_MENU, self.on_sdk_status, m_sdk)
        menubar.Append(help_menu, _t("Help"))

        self.frame.SetMenuBar(menubar)

    def _setup_accessibility_names(self):
        try:
            self.profile_list.SetName(_t("TeamTalk servers"))
            self.channel_tree.SetName(_t("TeamTalk channels and users"))
            self.right_list.SetName(_t("TeamTalk view"))
            self.message_input.SetName(_t("Type TeamTalk message"))
            self.connect_btn.SetName(_t("Connect to selected TeamTalk server"))
            self.disconnect_btn.SetName(_t("Disconnect from TeamTalk"))
            self.ptt_btn.SetName(_t("Push to talk"))
            self.mute_mic_btn.SetName(_t("Mute microphone"))
            self.mute_spk_btn.SetName(_t("Mute speakers"))
        except Exception:
            pass

    # ---- View toggling --------------------------------------------------

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

    def show(self):
        self.frame.Show()
        self.frame.Raise()

    def _set_status(self, text):
        try:
            self.frame.SetStatusText(text)
        except Exception:
            pass

    # ---- Profiles -------------------------------------------------------

    def _save(self):
        self.config["profiles"] = self.profiles
        if self.current_profile:
            self.config["last_profile"] = self.current_profile.get("entry_name", "")
        save_teamtalk_config(self.config)

    def _refresh_profiles(self):
        self.profile_list.Clear()
        for profile in self.profiles:
            encrypted = " TLS" if profile.get("encrypted") else ""
            channel = f"  {profile['channel']}" if profile.get("channel") else ""
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
        idx = self.profile_list.GetSelection()
        return idx if idx != self.wx.NOT_FOUND else None

    def on_profile_selected(self, event):
        idx = self._selected_index()
        if idx is None:
            return
        self.current_profile = self.profiles[idx]
        snd = _sounds()
        if snd:
            try:
                snd.focus(pan=0.0)
            except Exception:
                pass

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
                _message(
                    self.frame,
                    _t("Server address is required."),
                    style=self.wx.OK | self.wx.ICON_WARNING,
                )
                return
            self.profiles.append(dlg.profile)
            self.current_profile = dlg.profile
            self._save()
            self._refresh_profiles()
            snd = _sounds()
            if snd:
                try:
                    snd.success()
                except Exception:
                    pass

    def on_edit_profile(self, event):
        idx = self._selected_index()
        if idx is None:
            return
        dlg = ProfileDialog(self.frame, self.profiles[idx])
        if dlg.show_modal():
            if not dlg.profile["host"]:
                _message(
                    self.frame,
                    _t("Server address is required."),
                    style=self.wx.OK | self.wx.ICON_WARNING,
                )
                return
            self.profiles[idx] = dlg.profile
            self.current_profile = dlg.profile
            self._save()
            self._refresh_profiles()
            snd = _sounds()
            if snd:
                try:
                    snd.success()
                except Exception:
                    pass

    def on_remove_profile(self, event):
        idx = self._selected_index()
        if idx is None:
            return
        if (
            _message(
                self.frame,
                _t("Remove selected TeamTalk server profile?"),
                style=self.wx.YES_NO | self.wx.NO_DEFAULT | self.wx.ICON_QUESTION,
            )
            == self.wx.ID_YES
        ):
            del self.profiles[idx]
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
        _apply_skin_recursive(dlg)
        if dlg.ShowModal() == self.wx.ID_OK:
            path = dlg.GetPath()
            try:
                profile = parse_tt_file(path)
                if not profile["entry_name"] or profile["entry_name"] == _t(
                    "TeamTalk server"
                ):
                    profile["entry_name"] = os.path.splitext(
                        os.path.basename(path)
                    )[0]
                self.profiles.append(profile)
                self.current_profile = profile
                self._save()
                self._refresh_profiles()
                self._set_status(
                    _t("Imported TeamTalk file: {name}").format(name=profile["entry_name"])
                )
                _notify(_t("TeamTalk file imported"), "success")
            except Exception as exc:
                _message(
                    self.frame,
                    str(exc),
                    _t("Import failed"),
                    self.wx.OK | self.wx.ICON_ERROR,
                )
                snd = _sounds()
                if snd:
                    try:
                        snd.error()
                    except Exception:
                        pass
        dlg.Destroy()

    # ---- Connect / disconnect ------------------------------------------

    def on_connect(self, event):
        idx = self._selected_index()
        if idx is not None:
            self.current_profile = self.profiles[idx]
        if not self.current_profile:
            _message(
                self.frame,
                _t("Select or add a TeamTalk server first."),
                style=self.wx.OK | self.wx.ICON_WARNING,
            )
            return
        if not self.client.available():
            _message(
                self.frame,
                self.client.status_message(),
                _t("TeamTalk SDK not available"),
                self.wx.OK | self.wx.ICON_WARNING,
            )
            snd = _sounds()
            if snd:
                try:
                    snd.error()
                except Exception:
                    pass
            return

        profile = self.current_profile
        self._set_status(
            _t("Connecting to {host}...").format(host=profile["host"])
        )

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
        # Apply the saved gender flag right after login so peers see the
        # correct status bit (TT5 transmits the gender as part of the status
        # mode bitfield - it is not part of doLogin).
        try:
            gender = int(profile.get("gender", GENDER_MALE))
        except Exception:
            gender = GENDER_MALE
        if gender != GENDER_MALE:
            self.client.change_status(_build_status_mode(gender, away=False), "")
        # Channel-list snapshot: at the moment CMD_MYSELF_LOGGEDIN fires the
        # server has typically already pushed every CMD_CHANNEL_NEW for the
        # tree, so refresh once. We will refresh again on later events.
        self.focus_tree_after_login = True
        self._refresh_teamtalk_state()
        if not self.connected_announced:
            self.connected_announced = True
            label = _t("Connected to {server}").format(server=profile["entry_name"])
            self._set_status(label)
            self._log_event(label)
            self._log_audio_devices()
            snd = _sounds()
            if snd:
                try:
                    snd.call_connected()
                except Exception:
                    pass
            _notify(_t("Connected to TeamTalk server"), "success")

    def _log_audio_devices(self):
        """Surface microphone / speaker init state on the Server log tab.

        Lets the user verify, without external tools, why voice may not
        transmit (e.g. no input device picked up, or initSoundInputDevice
        rejected). Combined with the [TeamTalk] enableVoiceTransmission(...)
        return-value print line in the SDK wrapper, this gives a complete
        diagnostic trail.
        """
        cli = self.client
        in_name = cli.input_device_name or _t("(unknown)")
        out_name = cli.output_device_name or _t("(unknown)")
        self._log_event(
            _t("Microphone: {name}, ready: {ok}").format(
                name=in_name, ok=_t("yes") if cli.input_init_ok else _t("no")
            )
        )
        self._log_event(
            _t("Speakers: {name}, ready: {ok}").format(
                name=out_name, ok=_t("yes") if cli.output_init_ok else _t("no")
            )
        )
        # Blind users won't hunt for the tree with a mouse, so we *force*
        # focus onto the channel tree. wxPython needs the panel switch to
        # finish first - schedule a delayed second SetFocus so the layout
        # has settled and the tree is visible. Re-run a few times to cover
        # the case where channel data arrives slightly after CMD_LOGGEDIN.
        self.wx.CallAfter(self._focus_channel_tree)
        for delay in (120, 350, 800):
            self.wx.CallLater(delay, self._focus_channel_tree)
        # Lift the presence-sound guard once any tail-end CMD_USER_LOGGEDIN
        # from the initial roster dump has had a chance to land.
        self.wx.CallLater(800, self._lift_presence_guard)

    def _lift_presence_guard(self):
        self._suppress_presence_sounds = False

    def _focus_channel_tree(self):
        """Move keyboard focus to the channel tree (post-login UX).

        Called repeatedly after login until the user moves focus elsewhere
        (e.g. into the message input or a button). This is what blind users
        need - the tree is the primary control once we are connected.
        """
        try:
            if not self.connected_panel.IsShown():
                return
            current = self.frame.FindFocus()
            if current is self.message_input or current is self.send_btn:
                # User has already started typing - don't yank their focus.
                return
            self.channel_tree.SetFocus()
            # Make sure something is selected so SR reads it on focus.
            try:
                if self.current_channel_id in self.channel_items:
                    self.channel_tree.SelectItem(
                        self.channel_items[self.current_channel_id]
                    )
                elif self.channel_items:
                    first = next(iter(self.channel_items.values()))
                    self.channel_tree.SelectItem(first)
            except Exception:
                pass
        except Exception:
            pass

    def _on_connection_failed(self, exc):
        self.client.disconnect()
        _state["connected"] = False
        self.connected_announced = False
        self.focus_tree_after_login = False
        self._show_connection_view()
        self._set_status(_t("Connection failed"))
        _message(
            self.frame,
            str(exc),
            _t("TeamTalk connection failed"),
            self.wx.OK | self.wx.ICON_ERROR,
        )
        snd = _sounds()
        if snd:
            try:
                snd.error()
            except Exception:
                pass

    def on_disconnect(self, event):
        was_connected = self.client.connected or _state["connected"]
        self.client.disconnect()
        _state["connected"] = False
        _state["server"] = ""
        _state["username"] = ""
        self.connected_announced = False
        self.focus_tree_after_login = False
        # Re-arm the presence guard so the next connection's initial roster
        # dump does not blast online/offline sounds again.
        self._suppress_presence_sounds = True
        self.current_channel_id = 0
        self.channels = {}
        self.users = {}
        self.channel_items = {}
        self.user_items = {}
        self.chat_messages.clear()
        self.pm_threads.clear()
        try:
            self.channel_tree.DeleteChildren(self.channel_root)
            self.right_list.DeleteAllItems()
        except Exception:
            pass
        self._show_connection_view()
        self._set_status(_t("Disconnected from TeamTalk"))
        if was_connected:
            self._log_event(_t("Disconnected from TeamTalk"))
            snd = _sounds()
            if snd:
                try:
                    snd.goodbye()
                except Exception:
                    pass

    # ---- Channel tree ---------------------------------------------------

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
        nickname = _tt_text(getattr(user, "szNickname", "")) or _tt_text(
            getattr(user, "szUsername", "")
        )
        username = _tt_text(getattr(user, "szUsername", ""))
        state = _value(getattr(user, "uUserState", 0))
        speaking = ""
        try:
            voice_flag = _value(self.client.sdk.UserState.USERSTATE_VOICE)
            if state & voice_flag:
                speaking = _t(" speaking")
        except Exception:
            pass
        if username and username != nickname:
            return f"{nickname} ({username}){speaking}"
        return f"{nickname}{speaking}"

    def _tree_item_data(self, kind, item_id):
        return {"kind": kind, "id": item_id}

    def _refresh_teamtalk_state(self):
        snapshot = self.client.refresh_state()
        self.channels = {
            _value(ch.nChannelID): ch for ch in snapshot["channels"]
        }
        self.users = {
            _value(user.nUserID): user for user in snapshot["users"]
        }
        my_channel_id = snapshot.get("my_channel_id", 0)
        if my_channel_id:
            self.current_channel_id = my_channel_id
        self._populate_channel_tree(snapshot.get("root_id", 0))

    def _populate_channel_tree(self, root_id=0):
        tree = self.channel_tree
        # Preserve which logical item was selected and whether the tree had
        # keyboard focus, so a refresh triggered by a server event does not
        # snatch focus away from a blind user mid-navigation.
        had_focus = self.frame.FindFocus() is tree
        prev_selection = self._selected_tree_data()

        tree.DeleteChildren(self.channel_root)
        self.channel_items = {}
        self.user_items = {}
        children = {}
        for channel in self.channels.values():
            parent_id = _value(getattr(channel, "nParentID", 0))
            children.setdefault(parent_id, []).append(channel)

        def add_children(parent_item, parent_id):
            chans = children.get(parent_id, [])
            chans.sort(
                key=lambda ch: _tt_text(getattr(ch, "szName", "")).lower()
            )
            for channel in chans:
                channel_id = _value(getattr(channel, "nChannelID", 0))
                item = tree.AppendItem(parent_item, self._channel_label(channel))
                tree.SetItemData(item, self._tree_item_data("channel", channel_id))
                self.channel_items[channel_id] = item
                for user in sorted(
                    self.client.get_channel_users(channel_id),
                    key=lambda u: self._user_label(u).lower(),
                ):
                    user_id = _value(getattr(user, "nUserID", 0))
                    user_item = tree.AppendItem(item, self._user_label(user))
                    tree.SetItemData(user_item, self._tree_item_data("user", user_id))
                    self.user_items[user_id] = user_item
                add_children(item, channel_id)
                tree.Expand(item)

        root_children_id = root_id if root_id in children else 0
        add_children(self.channel_root, root_children_id)
        tree.Expand(self.channel_root)

        # Restore selection: prefer the item the user was on, fall back to
        # our channel, then to the first channel in the tree.
        target = None
        if prev_selection.get("kind") == "user":
            target = self.user_items.get(prev_selection.get("id"))
        elif prev_selection.get("kind") == "channel":
            target = self.channel_items.get(prev_selection.get("id"))
        if target is None and self.current_channel_id in self.channel_items:
            target = self.channel_items[self.current_channel_id]
        if target is None and self.channel_items:
            target = next(iter(self.channel_items.values()))
        if target is not None:
            try:
                tree.SelectItem(target)
                tree.EnsureVisible(target)
            except Exception:
                pass

        if self.focus_tree_after_login or had_focus:
            self.focus_tree_after_login = False
            try:
                tree.SetFocus()
            except Exception:
                pass

    def _get_tree_data(self, item):
        try:
            data = self.channel_tree.GetItemData(item)
            return data if isinstance(data, dict) else {"kind": "channel", "id": data}
        except Exception:
            return {"kind": "", "id": 0}

    def _selected_tree_data(self):
        try:
            item = self.channel_tree.GetSelection()
            if item.IsOk():
                return self._get_tree_data(item)
        except Exception:
            pass
        return {"kind": "", "id": 0}

    def on_tree_selected(self, event):
        item = event.GetItem()
        data = self._get_tree_data(item)
        snd = _sounds()
        if snd:
            try:
                snd.focus(pan=0.0)
            except Exception:
                pass
        if data.get("kind") == "channel":
            channel_id = data.get("id")
            path = (
                self.client.get_channel_path(channel_id)
                or self.channel_tree.GetItemText(item)
            )
            self._set_status(_t("Selected channel {channel}").format(channel=path))
        elif data.get("kind") == "user":
            user = self.users.get(data.get("id"))
            label = (
                self._user_label(user)
                if user is not None
                else self.channel_tree.GetItemText(item)
            )
            self._set_status(label)

    def on_tree_activated(self, event):
        """Enter / double-click on a tree item.

        - On a channel: prompt for a password if needed and JOIN. This is
          the ONLY path that joins a channel - there is no auto-join.
        - On a user: open the private message window.
        """
        item = event.GetItem()
        data = self._get_tree_data(item)
        if data.get("kind") == "user":
            self._open_pm(data.get("id"))
            return
        channel_id = data.get("id") if data.get("kind") == "channel" else 0
        if not channel_id:
            return
        password = ""
        channel = self.channels.get(channel_id)
        if channel is not None and bool(getattr(channel, "bPassword", False)):
            password = _ask_password(
                self.frame,
                _t("Enter channel password:"),
                _t("Join TeamTalk channel"),
            )
            if password is None:
                return
        if self.client.join_channel_by_id(channel_id, password):
            self.current_channel_id = channel_id
            path = (
                self.client.get_channel_path(channel_id)
                or self.channel_tree.GetItemText(item)
            )
            self._set_status(_t("Joining channel {channel}").format(channel=path))
            self._log_event(_t("Joining channel {channel}").format(channel=path))
            snd = _sounds()
            if snd:
                try:
                    snd.new_chat()
                except Exception:
                    pass
        else:
            _message(
                self.frame,
                _t("Could not join the selected channel."),
                _t("TeamTalk"),
                self.wx.OK | self.wx.ICON_WARNING,
            )

    def on_tree_right_click(self, event):
        try:
            self.channel_tree.SelectItem(event.GetItem())
        except Exception:
            pass
        self._show_tree_context_menu()

    def _on_tree_context_menu(self, event):
        self._show_tree_context_menu()

    def on_tree_key_down(self, event):
        wx = self.wx
        key = event.GetKeyCode()
        modifiers = event.GetModifiers()
        if key == wx.WXK_F10 and modifiers == wx.MOD_SHIFT:
            self._show_tree_context_menu()
            return
        if key == wx.WXK_RETURN and modifiers == wx.MOD_NONE:
            # Activate handler does the right thing.
            event.Skip()
            return
        event.Skip()

    def _show_tree_context_menu(self):
        wx = self.wx
        data = self._selected_tree_data()
        kind = data.get("kind")
        if kind not in ("user", "channel"):
            return
        menu = wx.Menu()
        if kind == "user":
            i_pm = menu.Append(wx.ID_ANY, _t("Send private message..."))
            i_info = menu.Append(wx.ID_ANY, _t("User info"))
            menu.AppendSeparator()
            i_mute = menu.Append(wx.ID_ANY, _t("Toggle mute"))
            i_volume = menu.Append(wx.ID_ANY, _t("Set volume..."))
            menu.AppendSeparator()
            i_kick = menu.Append(wx.ID_ANY, _t("Kick from channel"))
            i_ban = menu.Append(wx.ID_ANY, _t("Ban"))
            self.frame.Bind(wx.EVT_MENU, lambda e: self._pm_selected_user(), i_pm)
            self.frame.Bind(wx.EVT_MENU, lambda e: self._show_user_info(), i_info)
            self.frame.Bind(
                wx.EVT_MENU,
                lambda e: self._toggle_mute_selected_user(),
                i_mute,
            )
            self.frame.Bind(
                wx.EVT_MENU,
                lambda e: self._set_volume_selected_user(),
                i_volume,
            )
            self.frame.Bind(
                wx.EVT_MENU,
                lambda e: self._kick_selected_user(),
                i_kick,
            )
            self.frame.Bind(
                wx.EVT_MENU,
                lambda e: self._ban_selected_user(),
                i_ban,
            )
        else:
            i_join = menu.Append(wx.ID_ANY, _t("Join this channel"))
            i_leave = menu.Append(wx.ID_ANY, _t("Leave channel"))
            menu.AppendSeparator()
            i_create = menu.Append(wx.ID_ANY, _t("Create sub-channel..."))
            i_delete = menu.Append(wx.ID_ANY, _t("Delete this channel"))
            self.frame.Bind(wx.EVT_MENU, lambda e: self._join_selected(), i_join)
            self.frame.Bind(wx.EVT_MENU, lambda e: self._leave_current(), i_leave)
            self.frame.Bind(wx.EVT_MENU, lambda e: self._create_channel(), i_create)
            self.frame.Bind(
                wx.EVT_MENU,
                lambda e: self._delete_selected_channel(),
                i_delete,
            )
        snd = _sounds()
        if snd:
            try:
                snd.context_menu()
            except Exception:
                pass
        self.frame.PopupMenu(menu)
        menu.Destroy()
        if snd:
            try:
                snd.context_menu_close()
            except Exception:
                pass

    # ---- Channel actions ------------------------------------------------

    def _join_selected(self):
        data = self._selected_tree_data()
        if data.get("kind") != "channel":
            return
        channel_id = data.get("id")
        if not channel_id:
            return
        password = ""
        channel = self.channels.get(channel_id)
        if channel is not None and bool(getattr(channel, "bPassword", False)):
            password = _ask_password(
                self.frame,
                _t("Enter channel password:"),
                _t("Join TeamTalk channel"),
            )
            if password is None:
                return
        if not self.client.join_channel_by_id(channel_id, password):
            _message(
                self.frame,
                _t("Could not join the selected channel."),
                _t("TeamTalk"),
                self.wx.OK | self.wx.ICON_WARNING,
            )
            return
        self.current_channel_id = channel_id
        snd = _sounds()
        if snd:
            try:
                snd.new_chat()
            except Exception:
                pass

    def _leave_current(self):
        if not self.client.leave_channel():
            self._log_event(_t("Could not leave channel."))
            return
        self.current_channel_id = 0
        self._log_event(_t("Left channel."))

    def _create_channel(self):
        data = self._selected_tree_data()
        parent_id = data.get("id") if data.get("kind") == "channel" else 0
        sdk = self.client.sdk
        if not (self.client.obj and sdk):
            return
        name = _ask_text(self.frame, _t("Channel name:"), _t("Create channel"))
        if not name:
            return
        password = _ask_password(self.frame, _t("Channel password (leave blank for none):"), _t("Create channel"))
        if password is None:
            password = ""
        try:
            channel = sdk.Channel()
            channel.nParentID = parent_id or _value(self.client.obj.getRootChannelID())
            channel.szName = name
            channel.szPassword = password
            channel.bPassword = bool(password)
            channel.nMaxUsers = 50
            self.client.obj.doMakeChannel(channel)
            self._log_event(_t("Channel '{name}' creation requested.").format(name=name))
        except Exception as exc:
            _message(
                self.frame,
                str(exc),
                _t("TeamTalk"),
                self.wx.OK | self.wx.ICON_ERROR,
            )

    def _delete_selected_channel(self):
        data = self._selected_tree_data()
        if data.get("kind") != "channel":
            return
        channel_id = data.get("id")
        if not channel_id:
            return
        if (
            _message(
                self.frame,
                _t("Delete the selected channel?"),
                style=self.wx.YES_NO | self.wx.NO_DEFAULT | self.wx.ICON_QUESTION,
            )
            != self.wx.ID_YES
        ):
            return
        if not self.client.remove_channel(channel_id):
            self._log_event(_t("Could not delete channel."))

    # ---- User actions ---------------------------------------------------

    def _selected_user(self):
        data = self._selected_tree_data()
        if data.get("kind") != "user":
            return None
        return self.users.get(data.get("id"))

    def _open_pm(self, user_id):
        user = self.users.get(user_id) or self.client.get_user(user_id)
        nickname = _t("user")
        if user is not None:
            nickname = (
                _tt_text(getattr(user, "szNickname", ""))
                or _tt_text(getattr(user, "szUsername", ""))
                or nickname
            )
        win = self.pm_windows.get(user_id)
        if win is None:
            win = PrivateMessageWindow(self.frame, self, user_id, nickname)
            self.pm_windows[user_id] = win
        win.show()

    def _pm_selected_user(self):
        user = self._selected_user()
        if user is None:
            return
        self._open_pm(_value(getattr(user, "nUserID", 0)))

    def _show_user_info(self):
        user = self._selected_user()
        if user is None:
            return
        UserInfoDialog(self.frame, self.client.sdk, user).show_modal()

    def _toggle_mute_selected_user(self):
        user = self._selected_user()
        if user is None:
            return
        user_id = _value(getattr(user, "nUserID", 0))
        state = _value(getattr(user, "uUserState", 0))
        try:
            mute_flag = _value(self.client.sdk.UserState.USERSTATE_MUTE_VOICE)
        except Exception:
            mute_flag = 0x2
        currently_muted = bool(state & mute_flag)
        if self.client.set_user_mute(user_id, not currently_muted, voice=True):
            label = self._user_label(user)
            if currently_muted:
                self._set_status(_t("Unmuted {user}").format(user=label))
            else:
                self._set_status(_t("Muted {user}").format(user=label))
        else:
            self._log_event(_t("Could not toggle user mute."))

    def _set_volume_selected_user(self):
        user = self._selected_user()
        if user is None:
            return
        user_id = _value(getattr(user, "nUserID", 0))
        current = str(_value(getattr(user, "nVolumeVoice", 0)))
        text = _ask_text(
            self.frame,
            _t("Volume (0..32000):"),
            _t("Set user volume"),
            default=current,
        )
        if text is None:
            return
        try:
            volume = max(0, min(32000, int(text.strip())))
        except Exception:
            return
        if self.client.set_user_volume(user_id, volume):
            self._set_status(_t("Volume set to {volume}").format(volume=volume))
        else:
            self._log_event(_t("Could not set volume."))

    def _kick_selected_user(self):
        user = self._selected_user()
        if user is None:
            return
        user_id = _value(getattr(user, "nUserID", 0))
        channel_id = _value(getattr(user, "nChannelID", 0))
        if (
            _message(
                self.frame,
                _t("Kick {user} from the channel?").format(user=self._user_label(user)),
                style=self.wx.YES_NO | self.wx.NO_DEFAULT | self.wx.ICON_QUESTION,
            )
            == self.wx.ID_YES
        ):
            if not self.client.kick_user(user_id, channel_id):
                self._log_event(_t("Could not kick user."))

    def _ban_selected_user(self):
        user = self._selected_user()
        if user is None:
            return
        user_id = _value(getattr(user, "nUserID", 0))
        channel_id = _value(getattr(user, "nChannelID", 0))
        if (
            _message(
                self.frame,
                _t("Ban {user}?").format(user=self._user_label(user)),
                style=self.wx.YES_NO | self.wx.NO_DEFAULT | self.wx.ICON_QUESTION,
            )
            == self.wx.ID_YES
        ):
            if not self.client.ban_user(user_id, channel_id):
                self._log_event(_t("Could not ban user."))

    # ---- Voice / mic / speakers ----------------------------------------

    def _gate_voice(self, enable):
        """Apply the voice-transmission gate around enable_voice().

        Voice will not actually leave the client unless we are in a channel
        AND have USERRIGHT_TRANSMIT_VOICE. We surface a clear message to
        the user instead of silently failing.
        """
        if not enable:
            self.client.enable_voice(False)
            return True
        if not self.client.in_channel():
            self._set_status(_t("Join a channel before transmitting voice."))
            self._log_event(_t("Join a channel before transmitting voice."))
            snd = _sounds()
            if snd:
                try:
                    snd.error()
                except Exception:
                    pass
            return False
        if not self.client.can_transmit_voice():
            self._set_status(_t("This account is not allowed to transmit voice."))
            self._log_event(_t("This account is not allowed to transmit voice."))
            snd = _sounds()
            if snd:
                try:
                    snd.error()
                except Exception:
                    pass
            return False
        self.client.enable_voice(True)
        return True

    def on_ptt_toggle(self, event):
        self.ptt_toggle = self.ptt_btn.GetValue()
        ok = self._gate_voice(self.ptt_toggle and not self.mic_muted)
        if not ok and self.ptt_toggle:
            # Roll back the toggle state if voice could not be enabled.
            self.ptt_toggle = False
            self.ptt_btn.SetValue(False)
            return
        snd = _sounds()
        if snd:
            try:
                if self.ptt_toggle:
                    snd.walkie_talkie_start()
                else:
                    snd.walkie_talkie_end()
            except Exception:
                pass

    def on_mute_mic_toggle(self, event):
        self.mic_muted = self.mute_mic_btn.GetValue()
        if self.mic_muted:
            self.client.enable_voice(False)
            self._set_status(_t("Microphone muted"))
        else:
            self._gate_voice(self.ptt_toggle or self.ptt_held)
            self._set_status(_t("Microphone ready"))

    def on_mute_speakers_toggle(self, event):
        self.speakers_muted = self.mute_spk_btn.GetValue()
        if self.client.set_speaker_mute(self.speakers_muted):
            if self.speakers_muted:
                self._set_status(_t("Speakers muted"))
            else:
                self._set_status(_t("Speakers unmuted"))

    def on_set_status(self, event):
        msg = _ask_text(self.frame, _t("Status message:"), _t("Set status"), default="")
        if msg is None:
            return
        # Preserve the gender flag on the saved profile when sending status.
        gender = GENDER_MALE
        if self.current_profile:
            gender = int(self.current_profile.get("gender", GENDER_MALE))
        if self.client.change_status(_build_status_mode(gender, away=False), msg):
            self._set_status(_t("Status updated"))

    def _show_nickname_dialog(self):
        """Open the TT-Classic-style nickname + gender dialog.

        - Pre-fills with the nickname/gender from the active profile (or
          the last-used profile when offline).
        - On OK, stores both back into the profile + persistent config.
        - If we are already connected, applies the change immediately via
          doChangeNickname() and doChangeStatus(STATUSMODE_FEMALE/NEUTRAL).
        """
        profile = self.current_profile
        if profile is None and self.profiles:
            profile = self.profiles[0]
        nickname = (profile or {}).get("nickname", "") if profile else ""
        gender = int((profile or {}).get("gender", GENDER_MALE)) if profile else GENDER_MALE

        dlg = NicknameGenderDialog(self.frame, nickname, gender)
        if not dlg.show_modal():
            return
        new_nick = dlg.result_nickname
        new_gender = dlg.result_gender

        # Persist on the active profile and on the config.
        if profile is not None:
            profile["nickname"] = new_nick
            profile["gender"] = new_gender
            self.current_profile = profile
            self._save()
            self._refresh_profiles()

        # Apply live if we are connected. doChangeNickname reaches the
        # server immediately; doChangeStatus carries the gender bitfield.
        if self.client.connected:
            if new_nick:
                self.client.change_nickname(new_nick)
            self.client.change_status(_build_status_mode(new_gender, away=False), "")
            self._set_status(
                _t("Nickname set to {nick}").format(nick=new_nick or _t("(empty)"))
            )
        else:
            self._set_status(
                _t("Saved nickname and gender for next connection.")
            )

    # ---- Hotkeys --------------------------------------------------------

    def _on_key_hook(self, event):
        wx = self.wx
        key = event.GetKeyCode()
        modifiers = event.GetModifiers()

        # Frame-level Enter handler. EVT_KEY_DOWN on a wx.ListBox is
        # unreliable across platforms once an EVT_CHAR_HOOK is in place
        # (the hook swallows the event before it reaches the listbox).
        # The TitanApp / Titan-Net main GUI / Feedback Hub all handle Enter
        # exactly like this: route it from the frame based on focus, so
        # every list reacts to Enter the same way the user expects.
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and modifiers == wx.MOD_NONE:
            focus = self.frame.FindFocus()

            def _is(widget):
                # GetId() comparison is more reliable than identity checks:
                # FindFocus() can return a wrapped/proxy widget on some
                # wxPython builds, but the integer id is always stable.
                if widget is None or focus is None:
                    return False
                if focus is widget:
                    return True
                try:
                    return focus.GetId() == widget.GetId()
                except Exception:
                    return False

            # --- Connection view: Enter on the server list -> connect ---
            # Belt-and-suspenders: also try HasFocus() and a "list is the
            # active widget on the connection panel" fallback so a stray
            # focus state still produces the expected behaviour. Buttons
            # consume Enter natively (EVT_BUTTON), so guarding on
            # isinstance(focus, wx.Button) keeps Connect/Add/Edit clicks
            # from being intercepted as a server-connect.
            try:
                listbox_has_focus = self.profile_list.HasFocus()
            except Exception:
                listbox_has_focus = False
            on_button = isinstance(focus, wx.Button)
            if (
                _is(self.profile_list)
                or listbox_has_focus
                or (
                    self.connection_panel.IsShown()
                    and not on_button
                    and not isinstance(focus, wx.TextCtrl)
                )
            ):
                self.on_connect(event)
                return

            if _is(getattr(self, "right_list", None)):
                idx = self.right_list.GetFirstSelected()
                if idx > 0 and not self._is_tab_bar_row(idx):
                    evt = wx.ListEvent(wx.wxEVT_LIST_ITEM_ACTIVATED, self.right_list.GetId())
                    evt.SetIndex(idx)
                    self._on_right_activated(evt)
                return
            if _is(getattr(self, "channel_tree", None)):
                item = self.channel_tree.GetSelection()
                if item.IsOk():
                    evt = wx.TreeEvent(
                        wx.wxEVT_COMMAND_TREE_ITEM_ACTIVATED,
                        self.channel_tree.GetId(),
                    )
                    evt.SetItem(item)
                    self.on_tree_activated(evt)
                return
            # Anything else (text fields, buttons) handles Enter natively.

        # F2 toggles mic mute, F3 toggles speakers mute, F4 PTT-while-held.
        if key == wx.WXK_F2 and modifiers == wx.MOD_NONE:
            self.mute_mic_btn.SetValue(not self.mute_mic_btn.GetValue())
            self.on_mute_mic_toggle(event)
            return
        if key == wx.WXK_F3 and modifiers == wx.MOD_NONE:
            self.mute_spk_btn.SetValue(not self.mute_spk_btn.GetValue())
            self.on_mute_speakers_toggle(event)
            return
        if key == wx.WXK_F4 and modifiers == wx.MOD_NONE:
            if not self.ptt_held and not self.mic_muted:
                if self._gate_voice(True):
                    self.ptt_held = True
                    snd = _sounds()
                    if snd:
                        try:
                            snd.walkie_talkie_start()
                        except Exception:
                            pass
            return

        if key == wx.WXK_TAB and modifiers == wx.MOD_CONTROL:
            self._cycle_tab(+1)
            return
        if key == wx.WXK_TAB and modifiers == (wx.MOD_CONTROL | wx.MOD_SHIFT):
            self._cycle_tab(-1)
            return

        if modifiers == wx.MOD_CONTROL:
            if key == ord("1"):
                self._set_tab(TAB_CHAT)
                return
            if key == ord("2"):
                self._set_tab(TAB_LOG)
                return
            if key == ord("3"):
                self._set_tab(TAB_PM)
                return

        event.Skip()

    def _on_key_up(self, event):
        wx = self.wx
        key = event.GetKeyCode()
        if key == wx.WXK_F4 and self.ptt_held:
            self.ptt_held = False
            self._gate_voice(self.ptt_toggle and not self.mic_muted)
            snd = _sounds()
            if snd:
                try:
                    snd.walkie_talkie_end()
                except Exception:
                    pass
            return
        event.Skip()

    # ---- Tab bar (right pane) -------------------------------------------

    def _right_label_for_tab(self):
        if self.current_tab == TAB_CHAT:
            return _t("Channel chat")
        if self.current_tab == TAB_LOG:
            return _t("Server log")
        return _t("Private messages")

    def _tab_bar_text(self):
        labels = [_t("Channel chat"), _t("Server log"), _t("Private messages")]
        idx = self.current_tab
        return _t("{label}, {n} of {total}").format(
            label=labels[idx], n=idx + 1, total=len(labels)
        )

    def _is_tab_bar_row(self, idx):
        if idx != 0 or self.right_list.GetItemCount() == 0:
            return False
        try:
            data = self.right_list.GetItemData(0)
        except Exception:
            return False
        return data == 1  # tab-bar marker

    def _cycle_tab(self, direction):
        new_tab = self.current_tab + direction
        if new_tab < TAB_CHAT or new_tab > TAB_PM:
            _play_sound("ui/endoftapbar.ogg")
            return
        self._set_tab(new_tab, play_switch_sound=True)

    def _set_tab(self, tab, play_switch_sound=False):
        if tab not in (TAB_CHAT, TAB_LOG, TAB_PM):
            return
        if play_switch_sound and tab != self.current_tab:
            _play_sound("ui/switch_list.ogg")
        self.current_tab = tab
        self.right_label.SetLabel(self._right_label_for_tab())
        self._refresh_right_list(announce_tab_bar=True)

    def _refresh_right_list(self, announce_tab_bar=False):
        self.right_list.DeleteAllItems()
        # Row 0 = virtual tab bar.
        idx = self.right_list.InsertItem(0, self._tab_bar_text())
        self.right_list.SetItem(idx, 1, "")
        self.right_list.SetItem(idx, 2, "")
        self.right_list.SetItemData(idx, 1)

        if self.current_tab == TAB_CHAT:
            for sender, text, time_str in self.chat_messages:
                row = self.right_list.GetItemCount()
                self.right_list.InsertItem(row, sender)
                self.right_list.SetItem(row, 1, text)
                self.right_list.SetItem(row, 2, time_str)
                self.right_list.SetItemData(row, 0)
        elif self.current_tab == TAB_LOG:
            for text, time_str in self.log_entries:
                row = self.right_list.GetItemCount()
                self.right_list.InsertItem(row, _t("Server"))
                self.right_list.SetItem(row, 1, text)
                self.right_list.SetItem(row, 2, time_str)
                self.right_list.SetItemData(row, 0)
        else:
            for user_id, info in self.pm_threads.items():
                row = self.right_list.GetItemCount()
                self.right_list.InsertItem(row, info.get("nick", ""))
                self.right_list.SetItem(row, 1, info.get("last", ""))
                self.right_list.SetItem(row, 2, info.get("time", ""))
                self.right_list.SetItemData(row, user_id)

        # Always land on row 0 so Left/Right keeps cycling tabs without
        # requiring the user to arrow back up after every switch.
        try:
            self.right_list.Select(0)
            self.right_list.Focus(0)
            self.right_list.EnsureVisible(0)
        except Exception:
            pass
        if announce_tab_bar:
            _play_sound("ui/tapbar.ogg")

    def _on_right_selected(self, event):
        idx = event.GetIndex()
        if self._is_tab_bar_row(idx):
            return
        snd = _sounds()
        if snd:
            try:
                pan = 0.0
                count = max(0, self.right_list.GetItemCount() - 1)
                if count > 1:
                    pan = (idx - 1) / (count - 1)
                snd.focus(pan=pan)
            except Exception:
                pass

    def _on_right_activated(self, event):
        idx = event.GetIndex()
        if self._is_tab_bar_row(idx):
            return
        if self.current_tab == TAB_PM:
            try:
                user_id = self.right_list.GetItemData(idx)
            except Exception:
                user_id = 0
            if user_id:
                self._open_pm(user_id)

    def _on_right_key(self, event):
        wx = self.wx
        key = event.GetKeyCode()
        modifiers = event.GetModifiers()
        idx = self.right_list.GetFirstSelected()
        if idx == 0 and self._is_tab_bar_row(0) and modifiers == wx.MOD_NONE:
            if key == wx.WXK_LEFT:
                self._cycle_tab(-1)
                return
            if key == wx.WXK_RIGHT:
                self._cycle_tab(+1)
                return
        event.Skip()

    # ---- Chat / log -----------------------------------------------------

    def _append_chat(self, sender, text):
        time_str = _now_hhmm()
        self.chat_messages.append((sender, text, time_str))
        if self.current_tab == TAB_CHAT:
            row = self.right_list.GetItemCount()
            self.right_list.InsertItem(row, sender)
            self.right_list.SetItem(row, 1, text)
            self.right_list.SetItem(row, 2, time_str)
            self.right_list.SetItemData(row, 0)
            try:
                self.right_list.EnsureVisible(row)
            except Exception:
                pass

    def _log_event(self, text):
        time_str = _now_hhmm()
        self.log_entries.append((text, time_str))
        if self.current_tab == TAB_LOG:
            row = self.right_list.GetItemCount()
            self.right_list.InsertItem(row, _t("Server"))
            self.right_list.SetItem(row, 1, text)
            self.right_list.SetItem(row, 2, time_str)
            self.right_list.SetItemData(row, 0)

    def _record_pm_thread(self, user_id, nickname, last_message):
        self.pm_threads[user_id] = {
            "nick": nickname or _t("user"),
            "last": last_message,
            "time": _now_hhmm(),
        }
        if self.current_tab == TAB_PM:
            self._refresh_right_list()

    def on_send_message(self, event):
        text = self.message_input.GetValue().strip()
        if not text:
            return
        if not self.client.in_channel():
            _message(
                self.frame,
                _t("Join a TeamTalk channel before sending channel messages."),
                _t("TeamTalk"),
                self.wx.OK | self.wx.ICON_WARNING,
            )
            return
        if self.client.send_channel_message(text):
            self._append_chat(_t("Me"), text)
            self.message_input.SetValue("")
            snd = _sounds()
            if snd:
                try:
                    snd.message_sent()
                except Exception:
                    pass
        else:
            self._set_status(_t("Could not send TeamTalk message."))
            snd = _sounds()
            if snd:
                try:
                    snd.error()
                except Exception:
                    pass

    def on_sdk_status(self, event):
        _message(self.frame, self.client.status_message(), _t("TeamTalk SDK status"))

    # ---- SDK event dispatch --------------------------------------------

    def _on_sdk_event(self, msg):
        events = getattr(self.client.sdk, "ClientEvent", None)
        if events is None:
            return
        try:
            name = _value(getattr(msg, "nClientEvent", -1))
        except Exception:
            return
        wx = self.wx
        try:
            if name == _value(events.CLIENTEVENT_CON_SUCCESS):
                wx.CallAfter(self._set_status, _t("Connected. Logging in..."))
                return
            if name == _value(events.CLIENTEVENT_CMD_MYSELF_LOGGEDIN):
                profile = self.client.pending_profile or self.current_profile
                if profile:
                    wx.CallAfter(self._on_connected, profile)
                return
            if name == _value(events.CLIENTEVENT_CON_FAILED):
                wx.CallAfter(
                    self._on_connection_failed,
                    RuntimeError(_t("TeamTalk connection failed.")),
                )
                return
            if name == _value(events.CLIENTEVENT_CON_LOST):
                wx.CallAfter(self.on_disconnect, None)
                return
            if name == _value(events.CLIENTEVENT_CMD_ERROR):
                err = getattr(msg, "clienterrormsg", None)
                text = (
                    _tt_text(getattr(err, "szErrorMsg", ""))
                    or _t("TeamTalk command failed.")
                )
                wx.CallAfter(self._log_event, text)
                wx.CallAfter(self._set_status, text)
                snd = _sounds()
                if snd:
                    try:
                        snd.error()
                    except Exception:
                        pass
                return
            if name == _value(events.CLIENTEVENT_CMD_USER_TEXTMSG):
                text_msg = getattr(msg, "textmessage", None)
                self._handle_text_message(text_msg)
                return

            channel_events = {
                _value(events.CLIENTEVENT_CMD_CHANNEL_NEW),
                _value(events.CLIENTEVENT_CMD_CHANNEL_UPDATE),
                _value(events.CLIENTEVENT_CMD_CHANNEL_REMOVE),
            }
            user_events = {
                _value(events.CLIENTEVENT_CMD_USER_LOGGEDIN),
                _value(events.CLIENTEVENT_CMD_USER_LOGGEDOUT),
                _value(events.CLIENTEVENT_CMD_USER_UPDATE),
                _value(events.CLIENTEVENT_CMD_USER_JOINED),
                _value(events.CLIENTEVENT_CMD_USER_LEFT),
                _value(events.CLIENTEVENT_USER_STATECHANGE),
            }
            if name in channel_events or name in user_events:
                wx.CallAfter(self._refresh_teamtalk_state)
                user = getattr(msg, "user", None)
                if user is not None:
                    user_id = _value(getattr(user, "nUserID", 0))
                    is_me = bool(user_id and user_id == self.client.my_user_id)
                    display = (
                        _tt_text(getattr(user, "szNickname", ""))
                        or _tt_text(getattr(user, "szUsername", ""))
                    )
                    if (
                        display
                        and not is_me
                        and name == _value(events.CLIENTEVENT_CMD_USER_LOGGEDIN)
                    ):
                        wx.CallAfter(
                            self._set_status,
                            _t("{user} logged in").format(user=display),
                        )
                        wx.CallAfter(
                            self._log_event,
                            _t("{user} logged in").format(user=display),
                        )
                        # Skip the earcon during the initial roster dump so
                        # we don't bomb the user with dozens of online
                        # sounds at login on a busy server.
                        if not self._suppress_presence_sounds:
                            snd = _sounds()
                            if snd:
                                try:
                                    snd.user_online()
                                except Exception:
                                    pass
                    elif (
                        display
                        and not is_me
                        and name == _value(events.CLIENTEVENT_CMD_USER_LOGGEDOUT)
                    ):
                        wx.CallAfter(
                            self._set_status,
                            _t("{user} logged out").format(user=display),
                        )
                        wx.CallAfter(
                            self._log_event,
                            _t("{user} logged out").format(user=display),
                        )
                        if not self._suppress_presence_sounds:
                            snd = _sounds()
                            if snd:
                                try:
                                    snd.user_offline()
                                except Exception:
                                    pass
                    elif display and name == _value(events.CLIENTEVENT_CMD_USER_JOINED):
                        wx.CallAfter(
                            self._set_status,
                            _t("{user} joined the channel").format(user=display),
                        )
                    elif display and name == _value(events.CLIENTEVENT_CMD_USER_LEFT):
                        wx.CallAfter(
                            self._set_status,
                            _t("{user} left the channel").format(user=display),
                        )
                return
        except Exception:
            pass

    def _handle_text_message(self, text_msg):
        if text_msg is None:
            return
        wx = self.wx
        sdk = self.client.sdk
        try:
            msg_type = _value(getattr(text_msg, "nMsgType", 0))
        except Exception:
            msg_type = 0
        text = _tt_text(getattr(text_msg, "szMessage", ""))
        sender = _tt_text(getattr(text_msg, "szFromUsername", ""))
        from_user_id = _value(getattr(text_msg, "nFromUserID", 0))
        to_user_id = _value(getattr(text_msg, "nToUserID", 0))
        channel_id = _value(getattr(text_msg, "nChannelID", 0))
        more = bool(getattr(text_msg, "bMore", False))

        # TT5 chunks long messages and sets bMore=True on every non-final
        # chunk. The receiver must concatenate them in order before showing
        # to the user (mirrors TeamTalk5.rebuildTextMessage).
        partial_key = (msg_type, from_user_id, to_user_id, channel_id)
        buffered = self._pm_partials.get(partial_key, "")
        if more:
            self._pm_partials[partial_key] = buffered + text
            return
        if buffered:
            text = buffered + text
            self._pm_partials.pop(partial_key, None)

        # Resolve a friendly nickname for the sender.
        nick = sender
        sender_user = self.client.get_user(from_user_id) if from_user_id else None
        if sender_user is not None:
            n = _tt_text(getattr(sender_user, "szNickname", ""))
            if n:
                nick = n

        if not text:
            return

        try:
            channel_type = _value(sdk.TextMsgType.MSGTYPE_CHANNEL)
            user_type = _value(sdk.TextMsgType.MSGTYPE_USER)
        except Exception:
            channel_type, user_type = 2, 1

        if msg_type == channel_type:
            # Server-side echo guard: when we send a channel message, the
            # TT5 server broadcasts it to *every* member of the channel,
            # including ourselves. We've already rendered it locally as
            # "Me" inside on_send_message, so dropping the echo here keeps
            # the channel chat from showing every outgoing line twice.
            if from_user_id and from_user_id == self.client.my_user_id:
                return
            wx.CallAfter(self._append_chat, nick or _t("user"), text)
            # Use the same "new message arrived" earcon for channel chat
            # and private chat - the user wants a single, consistent sound
            # whenever a message is received (chat or PM).
            snd = _sounds()
            if snd:
                try:
                    snd.new_message()
                except Exception:
                    pass
        elif msg_type == user_type:
            wx.CallAfter(self._deliver_pm, from_user_id, nick, text)
        else:
            wx.CallAfter(
                self._log_event,
                _t("[{user}] {message}").format(user=nick or _t("user"), message=text),
            )

    def _deliver_pm(self, user_id, nickname, text):
        if not user_id:
            return
        win = self.pm_windows.get(user_id)
        if win is None:
            win = PrivateMessageWindow(self.frame, self, user_id, nickname or _t("user"))
            self.pm_windows[user_id] = win
            win.frame.Show(False)  # don't auto-pop window; user opens from PM tab
        win.append(nickname or _t("user"), text)
        self._record_pm_thread(user_id, nickname, text)
        snd = _sounds()
        if snd:
            try:
                snd.new_message()
            except Exception:
                pass
        # We already played snd.new_message() above for the arriving PM -
        # tell _notify to skip its own earcon (which would otherwise be
        # ui/dialog.ogg for the 'info' notification type) and only speak
        # the announcement.
        _notify(
            _t("Private message from {user}").format(user=nickname or _t("user")),
            "info",
            play_sound=False,
        )

    # ---- Close ---------------------------------------------------------

    def on_close(self, event):
        # Close any open PM windows first.
        try:
            for win in list(self.pm_windows.values()):
                try:
                    win.frame.Destroy()
                except Exception:
                    pass
            self.pm_windows.clear()
        except Exception:
            pass
        self.client.disconnect()
        _state["connected"] = False
        _state["server"] = ""
        _state["username"] = ""
        global _window
        _window = None
        self.frame.Destroy()


# =============================================================================
# Module entry points (required by TitanIMModuleManager)
# =============================================================================

def open(parent_frame):
    """Open the TeamTalk window."""
    global _window
    try:
        snd = _sounds()
        if snd:
            try:
                snd.welcome()
            except Exception:
                pass
        if _window is None:
            _window = TeamTalkFrame(parent_frame)
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
        if _state["username"]:
            return _t("- connected to {server} as {user}").format(
                server=_state["server"], user=_state["username"]
            )
        return _t("- connected to {server}").format(server=_state["server"])
    if _state["sdk_available"]:
        return _t("- ready")
    return ""


def open_tt_file(parent_frame, path):
    """Import a .tt file and open the module window (no auto-connect)."""
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
