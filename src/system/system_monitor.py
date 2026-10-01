# -*- coding: utf-8 -*-
import os
import threading
import time
import platform
import random
import subprocess
import ctypes
# Found, not imported: importing accessible_output3.outputs imports every
# backend, and the Window-Eyes one brings speech_recognition (8.7 MB) with
# it. The speaker below imports the library the first time it speaks.
try:
    import importlib.util as _ilu
    _ao3_mod_available = _ilu.find_spec('accessible_output3') is not None
except Exception:
    _ao3_mod_available = False
from src.titan_core.sound import play_sound, initialize_sound
from src.settings.settings import get_setting
from src.titan_core.translation import set_language
from src.system.com_fix import com_safe, init_com_safe
from src.titan_core.stereo_speech import get_stereo_speech
from src.platform_utils import get_subprocess_kwargs, IS_WINDOWS, IS_LINUX

# Get the translation function
_ = set_language(get_setting('language', 'pl'))


def _get_bool_setting(key, default=True, section='system_monitor'):
    """Read a checkbox-style setting as a real boolean.

    Settings are stored as plain strings, so an unchecked box comes back as the
    string "False" - which is truthy. Every switch that decides whether an
    announcement happens must go through this helper, otherwise turning the
    option off in Settings changes nothing.
    """
    value = get_setting(key, default, section=section)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('true', '1', 'yes', 'on')

# Speaker initialization moved to avoid TTS conflicts.
# Both the ao3 speaker and StereoSpeech are created lazily: building StereoSpeech
# at import time forced the whole TTS stack (SAPI worker, engine registry, voice
# enumeration) to load during startup imports.
_speaker = None
_stereo_speech = None

def _get_speaker():
    """Get ao3 speaker instance, initializing lazily."""
    global _speaker
    if _speaker is None and _ao3_mod_available:
        try:
            import accessible_output3.outputs.auto as _ao3_mod
            _speaker = _ao3_mod.Auto()
        except Exception as e:
            print(f"Error initializing system monitor speaker: {e}")
    return _speaker

def _get_stereo():
    """Get the shared StereoSpeech instance, initializing lazily."""
    global _stereo_speech
    if _stereo_speech is None:
        _stereo_speech = get_stereo_speech()
    return _stereo_speech

def _speak(message, interrupt=False):
    """Speak using Titan TTS: stereo_speech when enabled, ao3 otherwise, with cross-fallback."""
    stereo_enabled = get_setting('stereo_speech', 'False', 'invisible_interface').lower() in ['true', '1']
    ss = _get_stereo() if stereo_enabled else None
    if stereo_enabled and ss:
        try:
            ss.speak_async(message, use_fallback=True)
            return
        except Exception as stereo_e:
            print(f"Stereo speech failed: {stereo_e}")
    sp = _get_speaker()
    if sp:
        try:
            sp.speak(message, interrupt=interrupt)
            return
        except Exception as ao3_e:
            print(f"ao3 TTS failed: {ao3_e}")
            ss = _get_stereo()
            if ss:
                try:
                    ss.speak_async(message, use_fallback=True)
                except Exception as stereo_e:
                    print(f"All TTS methods failed: ao3={ao3_e}, stereo={stereo_e}")


def _speak_positional(message, position=0.0, pitch_offset=0):
    """Speak with stereo position and pitch using stereo_speech, fallback to _speak."""
    ss = _get_stereo()
    if ss:
        try:
            ss.speak_async(message, position=position, pitch_offset=pitch_offset, use_fallback=True)
            return
        except Exception as e:
            print(f"Positional speech failed: {e}")
    _speak(message)

# Attempt to import psutil for battery monitoring
try:
    import psutil
except ImportError:
    psutil = None
    print("psutil not found, battery monitoring will be disabled.")


class _SYSTEM_POWER_STATUS(ctypes.Structure):
    """Windows SYSTEM_POWER_STATUS structure for GetSystemPowerStatus."""
    _fields_ = [
        ('ACLineStatus', ctypes.c_byte),
        ('BatteryFlag', ctypes.c_byte),
        ('BatteryLifePercent', ctypes.c_byte),
        ('SystemStatusFlag', ctypes.c_byte),
        ('BatteryLifeTime', ctypes.c_ulong),
        ('BatteryFullLifeTime', ctypes.c_ulong),
    ]


def is_power_saving_active():
    """Return True if Windows battery saver (power saving) mode is currently on.

    Uses GetSystemPowerStatus; the low bit of SystemStatusFlag indicates that
    battery saver is enabled (Windows 10+). Returns False on other platforms
    or if the status cannot be read.
    """
    if not IS_WINDOWS:
        return False
    try:
        status = _SYSTEM_POWER_STATUS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return bool(status.SystemStatusFlag & 0x01)
    except Exception:
        return False
    return False

# Attempt to import pycaw for Windows volume monitoring
try:
    from pycaw.pycaw import AudioUtilities
    PYCAW_AVAILABLE = True
except ImportError:
    PYCAW_AVAILABLE = False
    print("pycaw not found, Windows volume monitoring will be disabled.")

# Check for Linux volume tools (pactl for PulseAudio/PipeWire, amixer for ALSA)
_LINUX_VOLUME_TOOL = None
if IS_LINUX:  # not platform.system(): its first call is a WMI query
    try:
        import alsaaudio
        _LINUX_VOLUME_TOOL = 'alsaaudio'
    except ImportError:
        result = subprocess.run(['which', 'pactl'], capture_output=True)
        if result.returncode == 0:
            _LINUX_VOLUME_TOOL = 'pactl'
        else:
            result = subprocess.run(['which', 'amixer'], capture_output=True)
            if result.returncode == 0:
                _LINUX_VOLUME_TOOL = 'amixer'
    if _LINUX_VOLUME_TOOL:
        print(f"Linux volume monitoring using: {_LINUX_VOLUME_TOOL}")
    else:
        print("No Linux volume tool found (install alsaaudio, pulseaudio-utils or alsa-utils)")

# Sound system will be initialized by main.py
# DO NOT initialize pygame here as it conflicts with sound.py
pygame = None

class SystemMonitor:
    """Main system monitor class that manages all monitoring threads"""

    def __init__(self):
        try:
            self.monitors = []
            self.running = False
        except Exception as e:
            print(f"Error in SystemMonitor.__init__: {e}")
            import traceback
            traceback.print_exc()
            self.monitors = []
            self.running = False

    def start(self):
        """Start all enabled monitors"""
        try:
            if self.running:
                return

            self.running = True

            # Start ChargerMonitor if charger monitoring or battery alerts are
            # enabled and a battery is available
            try:
                if ((_get_bool_setting('monitor_charger', True) or
                     _get_bool_setting('monitor_battery_alerts', True)) and
                    psutil and hasattr(psutil, 'sensors_battery') and
                    psutil.sensors_battery() is not None):
                    charger_monitor = ChargerMonitor()
                    charger_monitor.start()
                    self.monitors.append(charger_monitor)
            except Exception as e:
                print(f"Error starting ChargerMonitor: {e}")
                import traceback
                traceback.print_exc()

            # Start AudioMonitor based on volume monitor setting
            try:
                volume_monitor_mode = get_setting('volume_monitor', 'sound', section='system_monitor')
                if volume_monitor_mode != 'none':
                    can_monitor = (
                        (platform.system() == 'Windows' and PYCAW_AVAILABLE) or
                        (platform.system() == 'Darwin') or
                        (platform.system() == 'Linux' and _LINUX_VOLUME_TOOL is not None)
                    )
                    if can_monitor:
                        if platform.system() == 'Windows':
                            time.sleep(0.5)
                        audio_monitor = AudioMonitor(volume_monitor_mode)
                        audio_monitor.start()
                        self.monitors.append(audio_monitor)
                    else:
                        print("Volume monitoring disabled - no suitable audio API available")
            except Exception as e:
                print(f"Error starting AudioMonitor: {e}")
                import traceback
                traceback.print_exc()

            # Start NetworkMonitor on Windows if enabled
            try:
                if (platform.system() == 'Windows' and
                        _get_bool_setting('monitor_network', True)):
                    network_monitor = NetworkMonitor()
                    network_monitor.start()
                    self.monitors.append(network_monitor)
            except Exception as e:
                print(f"Error starting NetworkMonitor: {e}")
                import traceback
                traceback.print_exc()
        except Exception as e:
            print(f"Critical error in SystemMonitor.start: {e}")
            import traceback
            traceback.print_exc()
            self.running = False
    
    def stop(self):
        """Stop all running monitors"""
        self.running = False
        for monitor in self.monitors:
            monitor.stop()
        self.monitors.clear()

class ChargerMonitor(threading.Thread):
    """Monitor battery charging status and announce changes"""

    def __init__(self):
        try:
            super().__init__()
            self.daemon = True
            self.running = True
            self.charged_notification_sent = False
            self.low_battery_notified = False
            self.critical_battery_notified = False
            self.power_saving_was_active = is_power_saving_active()
            battery = psutil.sensors_battery()
            if battery:
                self.previous_status = battery.power_plugged
                self.previous_percentage = battery.percent
            else:
                self.previous_status = None
                self.previous_percentage = None
        except Exception as e:
            print(f"Error in ChargerMonitor.__init__: {e}")
            import traceback
            traceback.print_exc()
            self.daemon = True
            self.running = False  # Don't run if initialization failed
            self.charged_notification_sent = False
            self.low_battery_notified = False
            self.critical_battery_notified = False
            self.power_saving_was_active = False
            self.previous_status = None
            self.previous_percentage = None

    def run(self):
        while self.running:
            try:
                battery = psutil.sensors_battery()
                if battery:
                    current_status = battery.power_plugged
                    current_percentage = battery.percent
                    charger_alerts = _get_bool_setting('monitor_charger', True)

                    # Check for charger connection/disconnection
                    if self.previous_status is not None and current_status != self.previous_status:
                        if charger_alerts:
                            if current_status:
                                self.on_charger_connect(current_percentage)
                            else:
                                self.on_charger_disconnect(current_percentage)
                        self.previous_status = current_status

                    # Check for battery level changes during charging
                    battery_announce_interval = get_setting('battery_announce_interval', '10%', section='system_monitor')
                    if (charger_alerts and current_status and current_percentage != self.previous_percentage and
                        battery_announce_interval != 'never'):

                        # Parse interval setting
                        interval = 10  # default
                        if battery_announce_interval == '1%':
                            interval = 1
                        elif battery_announce_interval == '10%':
                            interval = 10
                        elif battery_announce_interval == '15%':
                            interval = 15
                        elif battery_announce_interval == '25%':
                            interval = 25

                        if current_percentage % interval == 0:
                            self.on_battery_charging(current_percentage)

                    # Check for fully charged battery
                    if charger_alerts and current_status and current_percentage == 100 and not self.charged_notification_sent:
                        self.on_battery_charged()
                        self.charged_notification_sent = True
                    elif not current_status:
                        self.charged_notification_sent = False

                    # Check for low / critical battery levels
                    self.check_battery_alerts(current_status, current_percentage)

                    self.previous_percentage = current_percentage
                else:
                    # No battery detected, stop the thread
                    self.running = False
            except Exception as e:
                print(f"Error in ChargerMonitor: {e}")
                self.running = False  # Stop thread on error
            time.sleep(1)

    def on_charger_connect(self, percentage):
        play_sound('system/charger_connect.ogg')
        _speak_positional(_("Connected to power adapter, battery level is {}%").format(percentage), position=0.8)

    def on_charger_disconnect(self, percentage):
        self.charged_notification_sent = False
        play_sound('system/charger_disconnect.ogg')
        _speak_positional(_("Power adapter disconnected, battery level is {}%").format(percentage), position=-0.8, pitch_offset=-10)

    def on_battery_charging(self, percentage):
        _speak(_("Charging battery, battery level {}%").format(percentage))

    def on_battery_charged(self):
        _speak(_("Battery is fully charged"))

    def check_battery_alerts(self, current_status, current_percentage):
        """Announce low and critical battery levels.

        Low battery is signalled either when the level drops to the low
        threshold or when Windows battery saver (power saving) mode turns on.
        Critical battery is signalled when the level drops to the critical
        threshold. Notifications fire once and reset when the charger is
        connected or the level recovers above the threshold.
        """
        try:
            if not _get_bool_setting('monitor_battery_alerts', True):
                return

            power_saving = is_power_saving_active()
            power_saving_started = power_saving and not self.power_saving_was_active
            self.power_saving_was_active = power_saving

            # While charging, clear all alert state so they can fire again later
            if current_status:
                self.low_battery_notified = False
                self.critical_battery_notified = False
                return

            try:
                low_threshold = int(get_setting('battery_low_threshold', 20, section='system_monitor'))
            except (TypeError, ValueError):
                low_threshold = 20
            try:
                critical_threshold = int(get_setting('battery_critical_threshold', 5, section='system_monitor'))
            except (TypeError, ValueError):
                critical_threshold = 5

            # Critical battery takes priority over low battery
            if current_percentage <= critical_threshold:
                if not self.critical_battery_notified:
                    self.on_critical_battery()
                    self.critical_battery_notified = True
                return

            # Recovered above critical level, allow critical to fire again
            self.critical_battery_notified = False

            if current_percentage <= low_threshold or power_saving_started:
                if not self.low_battery_notified:
                    self.on_low_battery()
                    self.low_battery_notified = True
            elif not power_saving:
                # Above low threshold and not in power saving, allow low to fire again
                self.low_battery_notified = False
        except Exception as e:
            print(f"Error in check_battery_alerts: {e}")

    def on_low_battery(self):
        sound_choice = get_setting('battery_low_sound', 'random', section='system_monitor')
        if sound_choice == 'external':
            sound = 'system/low_battery1.ogg'
        elif sound_choice == 'internal':
            sound = 'system/low_battery2.ogg'
        else:
            sound = random.choice(['system/low_battery1.ogg', 'system/low_battery2.ogg'])
        play_sound(sound)
        _speak(_("Low battery, please connect to charger"))

    def on_critical_battery(self):
        play_sound('system/critical_battery_level.ogg')
        # Speak one second after the sound so it is not masked by it
        message = _("Critical battery level, connect to charger now!")
        threading.Timer(1.0, lambda: _speak(message, interrupt=True)).start()

    def stop(self):
        self.running = False

class AudioMonitor(threading.Thread):
    """Monitor system volume changes and announce them"""

    def __init__(self, announce_mode='sound'):
        try:
            super().__init__()
            self.daemon = True
            self.running = True
            self.announce_mode = announce_mode  # 'none', 'sound', 'speech', 'both'
            self.com_initialized = False
            self.consecutive_errors = 0
            self.max_consecutive_errors = 100  # Increased to allow for longer initialization
            self.startup_grace_period = 60  # Don't count errors in first 60 checks (increased for COM init)
            self.check_count = 0
            self.previous_volume = -1  # Don't initialize volume here, let it initialize in run()
            self.last_error_message = None
        except Exception as e:
            print(f"Error in AudioMonitor.__init__: {e}")
            import traceback
            traceback.print_exc()
            self.daemon = True
            self.running = False  # Don't run if initialization failed
            self.announce_mode = announce_mode
            self.com_initialized = False
            self.consecutive_errors = 0
            self.max_consecutive_errors = 100
            self.startup_grace_period = 60
            self.check_count = 0
            self.previous_volume = -1
            self.last_error_message = None

    #: The safety poll (seconds). Windows tells this thread about a change
    #: through the endpoint-volume callback the moment it happens; the poll
    #: is for a callback that never arrives, and costs 0.02 ms on the cached
    #: endpoint. It used to be 0.2 s of ``GetSpeakers()`` + ``EndpointVolume``
    #: on a fresh thread per read - measured 13 ms of COM each, five times a
    #: second, for the life of the program.
    POLL_SECONDS = 0.5
    #: Polls the cached endpoint is trusted for before the default device is
    #: asked for again (~10 s), so a default that changed under us is still
    #: followed - at 13 ms per re-acquire rather than per read.
    REACQUIRE_EVERY = 20

    def run(self):
        self._wake = threading.Event()
        self._endpoint = None
        self._endpoint_polls = 0
        self._callback = None
        if platform.system() == 'Windows':
            # The multi-threaded apartment, asked for before anything else
            # COM happens on this thread: a callback registered from an STA
            # is only delivered through a message pump, and this thread has
            # none (the trap audio_devices.py documents). pycaw - and with
            # it comtypes - was imported at module level on the main thread,
            # so this is the first COM call this thread makes.
            try:
                import comtypes
                comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
                self.com_initialized = True
            except Exception as e:
                print(f"AudioMonitor: no multi-threaded apartment ({e}), "
                      f"polling from the thread's own")
                try:
                    init_com_safe()
                    self.com_initialized = True
                except Exception as e2:
                    print(f"Failed to initialize COM library: {e2}")
                    return  # Cannot run without COM

        try:
            while self.running and self.consecutive_errors < self.max_consecutive_errors:
                self.check_count += 1
                current_volume = self.get_volume_percentage_safe()

                if current_volume != -1:
                    self.consecutive_errors = 0  # Reset error counter on success
                    if self.previous_volume == -1:
                        # First successful read, just set it without announcing
                        self.previous_volume = current_volume
                    elif current_volume != self.previous_volume:
                        self.announce_volume_change(current_volume)
                        self.previous_volume = current_volume
                else:
                    # Only count errors after grace period
                    if self.check_count > self.startup_grace_period:
                        self.consecutive_errors += 1
                        if self.consecutive_errors >= self.max_consecutive_errors:
                            error_msg = "AudioMonitor: Too many consecutive errors, stopping monitor."
                            if not PYCAW_AVAILABLE:
                                error_msg += " (pycaw library not available)"
                            elif not self.com_initialized:
                                error_msg += " (COM initialization failed)"
                            else:
                                error_msg += " (Unable to access audio devices)"
                            print(error_msg)
                            break
                    elif self.check_count == 1:
                        # Log once during startup if there are issues
                        if not PYCAW_AVAILABLE:
                            print("AudioMonitor: pycaw not available, volume monitoring will not work")
                        elif not self.com_initialized:
                            print("AudioMonitor: COM not initialized, volume monitoring will not work")

                # Woken early by the callback, or by stop().
                self._wake.wait(self.POLL_SECONDS)
                self._wake.clear()
        except Exception as e:
            print(f"Error in AudioMonitor: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._unregister_callback()
            # COM cleanup is handled automatically by com_fix module

    # ------------------------------------------------------------------ #
    # The cached endpoint and Windows' own notification
    # ------------------------------------------------------------------ #
    def _endpoint_volume(self):
        """The default device's IAudioEndpointVolume, re-acquired rarely."""
        if (self._endpoint is not None
                and self._endpoint_polls < self.REACQUIRE_EVERY):
            self._endpoint_polls += 1
            return self._endpoint
        self._unregister_callback()
        self._endpoint = None
        devices = AudioUtilities.GetSpeakers()
        if devices is None:
            return None
        volume = devices.EndpointVolume
        if volume is None:
            return None
        self._endpoint = volume
        self._endpoint_polls = 0
        self._register_callback(volume)
        return volume

    def _register_callback(self, volume):
        """Ask Windows to wake the loop when the volume or mute changes."""
        try:
            from pycaw.callbacks import AudioEndpointVolumeCallback
        except Exception as e:
            print(f"AudioMonitor: volume notifications unavailable: {e}")
            return
        wake = self._wake

        class _Waker(AudioEndpointVolumeCallback):
            def on_notify(self, new_volume, new_mute, event_context,
                          channels, channel_volumes):
                wake.set()

        try:
            callback = _Waker()
            volume.RegisterControlChangeNotify(callback)
            # Windows holds this object; so do we, until it is unregistered.
            self._callback = callback
        except Exception as e:
            print(f"AudioMonitor: could not register for volume changes: {e}")

    def _unregister_callback(self):
        callback, endpoint = self._callback, self._endpoint
        self._callback = None
        if callback is not None and endpoint is not None:
            try:
                endpoint.UnregisterControlChangeNotify(callback)
            except Exception:
                pass

    def announce_volume_change(self, volume):
        """Announce volume change based on current settings"""
        if self.announce_mode in ['sound', 'both']:
            play_sound('system/volume.ogg')

        if self.announce_mode in ['speech', 'both']:
            _speak_positional(_("Volume: {}%").format(volume), pitch_offset=10)

    def get_volume_percentage_safe(self):
        """The volume, or -1. Never raises.

        This used to start a THREAD per read, with a one-second timeout, to
        survive a device enumeration that hung. The read is now one method
        call on a cached interface; the enumeration happens every
        ``REACQUIRE_EVERY`` polls on this thread, which is nobody's GUI.
        """
        try:
            value = self.get_volume_percentage()
        except Exception:
            return -1
        return -1 if value is None else value

    def get_volume_percentage(self):
        try:
            if platform.system() == 'Windows':
                return self.get_volume_windows()
            elif platform.system() == 'Darwin':
                return self.get_volume_mac()
            else:
                return self.get_volume_linux()
        except Exception as e:
            return -1

    @com_safe
    def get_volume_windows(self):
        try:
            # Check if pycaw is available first
            if not PYCAW_AVAILABLE:
                if self.check_count == 1 and self.last_error_message != "pycaw":
                    print("AudioMonitor: pycaw library not available - install with: pip install pycaw")
                    self.last_error_message = "pycaw"
                return -1

            # Check if COM is initialized properly
            if not self.com_initialized:
                if self.check_count == 1 and self.last_error_message != "com":
                    print("AudioMonitor: COM not initialized")
                    self.last_error_message = "com"
                return -1

            # The default device's endpoint, cached (see _endpoint_volume):
            # AudioUtilities.GetSpeakers() is a device enumeration and
            # EndpointVolume an interface activation - 13 ms together.
            volume = self._endpoint_volume()
            if volume is None:
                if self.check_count == 1 and self.last_error_message != "devices":
                    print("AudioMonitor: No audio output devices found")
                    self.last_error_message = "devices"
                return -1

            # Read the volume level; a read that fails (the device went
            # away) forgets the endpoint so the next poll asks for it again.
            try:
                level = volume.GetMasterVolumeLevelScalar()
            except Exception:
                self._unregister_callback()
                self._endpoint = None
                raise
            if level is None:
                if self.check_count == 1 and self.last_error_message != "level":
                    print("AudioMonitor: Cannot read volume level")
                    self.last_error_message = "level"
                return -1

            return int(level * 100)
        except (ImportError, OSError, ValueError, AttributeError, TypeError) as e:
            # Return -1 for any COM-related errors
            if self.check_count == 1 and self.last_error_message != str(type(e).__name__):
                print(f"AudioMonitor: COM error - {type(e).__name__}: {e}")
                self.last_error_message = str(type(e).__name__)
            return -1
        except Exception as e:
            # Catch any other unexpected errors
            if self.last_error_message != str(type(e).__name__):
                print(f"AudioMonitor: Unexpected error in get_volume_windows - {type(e).__name__}: {e}")
                self.last_error_message = str(type(e).__name__)
            return -1

    def get_volume_mac(self):
        try:
            result = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"],
                                    capture_output=True, text=True, check=True)
            return int(result.stdout.strip())
        except (FileNotFoundError, subprocess.CalledProcessError, ValueError) as e:
            return -1

    def get_volume_linux(self):
        import re
        if _LINUX_VOLUME_TOOL == 'alsaaudio':
            try:
                import alsaaudio
                mixer = alsaaudio.Mixer()
                return int(mixer.getvolume()[0])
            except Exception:
                pass
        if _LINUX_VOLUME_TOOL in ('alsaaudio', 'pactl'):
            try:
                result = subprocess.run(
                    ['pactl', 'get-sink-volume', '@DEFAULT_SINK@'],
                    capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0:
                    match = re.search(r'(\d+)%', result.stdout)
                    if match:
                        return int(match.group(1))
            except Exception:
                pass
        if _LINUX_VOLUME_TOOL in ('alsaaudio', 'pactl', 'amixer'):
            try:
                result = subprocess.run(
                    ['amixer', 'sget', 'Master'],
                    capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0:
                    match = re.search(r'\[(\d+)%\]', result.stdout)
                    if match:
                        return int(match.group(1))
            except Exception:
                pass
        return -1

    def stop(self):
        self.running = False
        wake = getattr(self, '_wake', None)
        if wake is not None:
            wake.set()

    def __del__(self):
        """Ensure cleanup on object destruction"""
        self.stop()

class NetworkMonitor(threading.Thread):
    """Monitor network connections on Windows and announce when connected to a new network"""

    def __init__(self):
        super().__init__()
        self.daemon = True
        self.running = True
        self.previous_ssid = None
        self.previous_wifi_state = None
        self.previous_interfaces = set()

    def _get_wifi_status(self):
        """Return (state, ssid) for the WiFi interface, or (None, None) if unavailable.

        Windows' own WLAN API first (16 ms, no process, no language);
        ``netsh`` - 159 ms and a console process a call - only where that
        cannot be asked.
        """
        try:
            from src.system import wlan
            state, ssid = wlan.wireless_state()
            if state is not None:
                return state, ssid
            if wlan.interfaces() == []:
                return None, None
        except Exception:
            pass
        return self._get_wifi_status_netsh()

    def _get_wifi_status_netsh(self):
        try:
            result = subprocess.run(
                ['netsh', 'wlan', 'show', 'interfaces'],
                capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=5,
                **get_subprocess_kwargs()
            )
            state = None
            ssid = None
            for line in result.stdout.splitlines():
                line = line.strip()
                # "SSID" line but NOT "BSSID" line
                if ':' in line:
                    key, _, val = line.partition(':')
                    key = key.strip()
                    val = val.strip()
                    if key.upper() == 'STATE' and val:
                        state = val.lower()
                    elif key.upper() == 'SSID' and val:
                        ssid = val
            return state, ssid
        except Exception:
            pass
        return None, None

    def _get_active_ethernet(self):
        """Return set of active non-WiFi interfaces that have an IPv4 address"""
        active = set()
        if not psutil:
            return active
        try:
            stats = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()
            wifi_names = {'wi-fi', 'wifi', 'wireless', 'wlan'}
            for iface, stat in stats.items():
                if not stat.isup:
                    continue
                iface_lower = iface.lower()
                if any(w in iface_lower for w in wifi_names):
                    continue  # handled by WiFi monitor
                if iface in addrs:
                    for addr in addrs[iface]:
                        if getattr(addr, 'family', None) == 2:  # AF_INET
                            if not addr.address.startswith('127.') and addr.address != '0.0.0.0':
                                active.add(iface)
                                break
        except Exception:
            pass
        return active

    def _init_state(self):
        self.previous_wifi_state, self.previous_ssid = self._get_wifi_status()
        self.previous_interfaces = self._get_active_ethernet()

    WIFI_CONNECTING_STATES = {'connecting', 'associating', 'discovering', 'authenticating'}

    #: Seconds between checks when Windows is telling us about changes (the
    #: WLAN notification and the address-table event below): the check is
    #: then only a safety net for an event that never came.
    WATCHED_POLL = 10.0
    #: Seconds between checks where neither event could be registered. It
    #: was 1 s of ``netsh`` (159 ms) plus two psutil walks (33 ms) - about
    #: a fifth of a processor core, for the life of the program.
    FALLBACK_POLL = 2.0
    #: A moment for the addresses to settle after an event, so one cable
    #: is not announced as two changes.
    SETTLE = 0.3

    def _check_once(self):
        """One comparison of the network with what it was; never raises."""
        try:
            # --- WiFi ---
            current_wifi_state, current_ssid = self._get_wifi_status()
            if current_wifi_state in self.WIFI_CONNECTING_STATES and self.previous_wifi_state not in self.WIFI_CONNECTING_STATES:
                self.on_connecting()
            self.previous_wifi_state = current_wifi_state
            if current_ssid != self.previous_ssid:
                if current_ssid:
                    self.on_connected(current_ssid)
                elif self.previous_ssid:
                    self.on_disconnected(self.previous_ssid)
            self.previous_ssid = current_ssid
            # --- Ethernet / other interfaces ---
            current_interfaces = self._get_active_ethernet()
            for iface in current_interfaces - self.previous_interfaces:
                self.on_connected(iface)
            for iface in self.previous_interfaces - current_interfaces:
                self.on_disconnected(iface)
            self.previous_interfaces = current_interfaces
        except Exception as e:
            print(f"NetworkMonitor error: {e}")

    def run(self):
        self._wake = threading.Event()
        # Wait for system to settle before monitoring
        if self._wake.wait(15):
            return
        self._init_state()

        # Told, rather than asking: a WLAN connection event from wlanapi and
        # an IPv4 address-table change from iphlpapi both wake the loop.
        watched = False
        addresses = None
        try:
            from src.system import wlan, net_events
            watched = wlan.watch(self._wake.set)
            addresses = net_events.AddressChange(self._wake)
            if addresses.available:
                watched = True
        except Exception as e:
            print(f"NetworkMonitor: polling only ({e})")

        try:
            while self.running:
                period = self.WATCHED_POLL if watched else self.FALLBACK_POLL
                woken = self._wake.wait(period)
                self._wake.clear()
                if not self.running:
                    break
                if woken:
                    time.sleep(self.SETTLE)
                self._check_once()
        finally:
            try:
                from src.system import wlan
                wlan.unwatch()
            except Exception:
                pass
            if addresses is not None:
                addresses.close()

    def on_connecting(self):
        play_sound('system/network_connecting.ogg')

    def on_connected(self, name):
        play_sound('system/network_connect.ogg')
        _speak_positional(_("Connected to {}").format(name), position=0.8)

    def on_disconnected(self, name):
        play_sound('system/network_disconnect.ogg')
        _speak_positional(_("Disconnected from {}").format(name), position=-0.8, pitch_offset=-10)

    def stop(self):
        self.running = False
        wake = getattr(self, '_wake', None)
        if wake is not None:
            wake.set()


# Global system monitor instance
_system_monitor = None

def initialize_system_monitor():
    """Initialize and start the system monitor"""
    global _system_monitor
    try:
        if _system_monitor is None:
            _system_monitor = SystemMonitor()
            _system_monitor.start()
    except Exception as e:
        print(f"Error initializing system monitor: {e}")
        import traceback
        traceback.print_exc()
        # Don't crash the program, just log the error

def stop_system_monitor():
    """Stop the system monitor"""
    global _system_monitor
    if _system_monitor:
        _system_monitor.stop()
        _system_monitor = None

def restart_system_monitor():
    """Restart the system monitor (useful after settings changes)"""
    stop_system_monitor()
    initialize_system_monitor()