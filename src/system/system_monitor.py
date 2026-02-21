# -*- coding: utf-8 -*-
import os
import threading
import time
import platform
import subprocess
try:
    import accessible_output3.outputs.auto as _ao3_mod
    _ao3_mod_available = True
except Exception:
    _ao3_mod_available = False
from src.titan_core.sound import play_sound, initialize_sound
from src.settings.settings import get_setting
from src.titan_core.translation import set_language
from src.system.com_fix import com_safe, init_com_safe
from src.titan_core.stereo_speech import get_stereo_speech

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

# Speaker initialization moved to avoid TTS conflicts
_speaker = None
_stereo_speech = get_stereo_speech()

def _get_speaker():
    """Get ao3 speaker instance, initializing lazily."""
    global _speaker
    if _speaker is None and _ao3_mod_available:
        try:
            _speaker = _ao3_mod.Auto()
        except Exception as e:
            print(f"Error initializing system monitor speaker: {e}")
    return _speaker

def _speak(message, interrupt=False):
    """Speak using Titan TTS: stereo_speech when enabled, ao3 otherwise, with cross-fallback."""
    stereo_enabled = get_setting('stereo_speech', 'False', 'invisible_interface').lower() in ['true', '1']
    if stereo_enabled and _stereo_speech:
        try:
            _stereo_speech.speak_async(message, use_fallback=True)
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
            if _stereo_speech:
                try:
                    _stereo_speech.speak_async(message, use_fallback=True)
                except Exception as stereo_e:
                    print(f"All TTS methods failed: ao3={ao3_e}, stereo={stereo_e}")


def _speak_positional(message, position=0.0, pitch_offset=0):
    """Speak with stereo position and pitch using stereo_speech, fallback to _speak."""
    if _stereo_speech:
        try:
            _stereo_speech.speak_async(message, position=position, pitch_offset=pitch_offset, use_fallback=True)
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

# Attempt to import pycaw for Windows volume monitoring
try:
    from pycaw.pycaw import AudioUtilities
    PYCAW_AVAILABLE = True
except ImportError:
    PYCAW_AVAILABLE = False
    print("pycaw not found, Windows volume monitoring will be disabled.")

# Check for Linux volume tools (pactl for PulseAudio/PipeWire, amixer for ALSA)
_LINUX_VOLUME_TOOL = None
if platform.system() == 'Linux':
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

            # Start ChargerMonitor if enabled and available
            try:
                if (get_setting('monitor_charger', True, section='system_monitor') and
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
                        get_setting('monitor_network', True, section='system_monitor')):
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
            self.previous_status = None
            self.previous_percentage = None

    def run(self):
        while self.running:
            try:
                battery = psutil.sensors_battery()
                if battery:
                    current_status = battery.power_plugged
                    current_percentage = battery.percent

                    # Check for charger connection/disconnection
                    if self.previous_status is not None and current_status != self.previous_status:
                        if current_status:
                            self.on_charger_connect(current_percentage)
                        else:
                            self.on_charger_disconnect(current_percentage)
                        self.previous_status = current_status

                    # Check for battery level changes during charging
                    battery_announce_interval = get_setting('battery_announce_interval', '10%', section='system_monitor')
                    if (current_status and current_percentage != self.previous_percentage and 
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
                    if current_status and current_percentage == 100 and not self.charged_notification_sent:
                        self.on_battery_charged()
                        self.charged_notification_sent = True
                    elif not current_status:
                        self.charged_notification_sent = False

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

    def run(self):
        if platform.system() == 'Windows':
            try:
                # Use safe COM initialization
                init_com_safe()
                self.com_initialized = True
            except Exception as e:
                print(f"Failed to initialize COM library: {e}")
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

                time.sleep(0.2)  # Increased sleep time to reduce CPU usage
        except Exception as e:
            print(f"Error in AudioMonitor: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # COM cleanup is handled automatically by com_fix module
            pass

    def announce_volume_change(self, volume):
        """Announce volume change based on current settings"""
        if self.announce_mode in ['sound', 'both']:
            play_sound('system/volume.ogg')

        if self.announce_mode in ['speech', 'both']:
            _speak_positional(_("Volume: {}%").format(volume), pitch_offset=10)

    def get_volume_percentage_safe(self):
        """Safe version of get_volume_percentage with timeout protection"""
        if platform.system() != 'Windows':
            return self.get_volume_percentage()
            
        # Use threading for timeout on Windows
        import queue
        result_queue = queue.Queue()
        
        def get_volume_thread():
            try:
                result = self.get_volume_percentage()
                result_queue.put(result)
            except Exception as e:
                result_queue.put(-1)
        
        thread = threading.Thread(target=get_volume_thread, daemon=True)
        thread.start()
        
        try:
            # Wait for result with timeout
            return result_queue.get(timeout=1.0)  # 1 second timeout
        except queue.Empty:
            # Timeout occurred
            return -1

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

            # Use the correct pycaw API: AudioUtilities.GetSpeakers() returns an AudioDevice object
            # In newer pycaw versions, we can directly access EndpointVolume property
            devices = AudioUtilities.GetSpeakers()
            if devices is None:
                if self.check_count == 1 and self.last_error_message != "devices":
                    print("AudioMonitor: No audio output devices found")
                    self.last_error_message = "devices"
                return -1

            # Get the volume controller directly from the AudioDevice
            # This is the new pycaw API (version 20251023+)
            # EndpointVolume is a property, not a method
            volume = devices.EndpointVolume
            if volume is None:
                if self.check_count == 1 and self.last_error_message != "endpoint_volume":
                    print("AudioMonitor: Cannot access EndpointVolume")
                    self.last_error_message = "endpoint_volume"
                return -1

            # Read the volume level
            level = volume.GetMasterVolumeLevelScalar()
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
        self.previous_interfaces = set()

    def _get_wifi_ssid(self):
        """Return current WiFi SSID via netsh, or None if not connected"""
        try:
            result = subprocess.run(
                ['netsh', 'wlan', 'show', 'interfaces'],
                capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=5
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                # "SSID" line but NOT "BSSID" line
                if ':' in line:
                    key, _, val = line.partition(':')
                    key = key.strip()
                    val = val.strip()
                    if key.upper() == 'SSID' and val:
                        return val
        except Exception:
            pass
        return None

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
        self.previous_ssid = self._get_wifi_ssid()
        self.previous_interfaces = self._get_active_ethernet()

    def run(self):
        # Wait for system to settle before monitoring
        time.sleep(15)
        self._init_state()
        while self.running:
            try:
                # --- WiFi ---
                current_ssid = self._get_wifi_ssid()
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
            time.sleep(5)

    def on_connected(self, name):
        play_sound('system/network_connect.ogg')
        _speak_positional(_("Connected to {}").format(name), position=0.8)

    def on_disconnected(self, name):
        _speak_positional(_("Disconnected from {}").format(name), position=-0.8, pitch_offset=-10)

    def stop(self):
        self.running = False


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