# -*- coding: utf-8 -*-
import os
import threading
import time
import platform
import subprocess
import accessible_output3.outputs.auto
from sound import play_sound, initialize_sound
from settings import get_setting
from translation import set_language
from com_fix import com_safe, init_com_safe

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

# Speaker initialization moved to avoid TTS conflicts
speaker = None

def get_safe_system_speaker():
    """Get speaker instance safely with proper error handling"""
    global speaker
    if speaker is None:
        try:
            speaker = accessible_output3.outputs.auto.Auto()
        except Exception as e:
            print(f"Error initializing system monitor speaker: {e}")
            return None
    return speaker

# Attempt to import psutil for battery monitoring
try:
    import psutil
except ImportError:
    psutil = None
    print("psutil not found, battery monitoring will be disabled.")

# Attempt to import pycaw for Windows volume monitoring
try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    PYCAW_AVAILABLE = True
except ImportError:
    PYCAW_AVAILABLE = False
    print("pycaw not found, Windows volume monitoring will be disabled.")

# Sound system will be initialized by main.py
pygame = None

# Initialize pygame mixer for interruptible sound on Windows
if platform.system() == 'Windows':
    try:
        import pygame
        pygame.mixer.init()
    except (ImportError, pygame.error) as e:
        print(f"Pygame not found or failed to initialize, sound interruption for volume change will not be available: {e}")
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

            # Start AudioMonitor based on volume monitor setting (only if pycaw available on Windows)
            try:
                volume_monitor_mode = get_setting('volume_monitor', 'sound', section='system_monitor')
                if volume_monitor_mode != 'none':
                    if platform.system() != 'Windows' or PYCAW_AVAILABLE:
                        audio_monitor = AudioMonitor(volume_monitor_mode)
                        audio_monitor.start()
                        self.monitors.append(audio_monitor)
                    else:
                        print("Volume monitoring disabled on Windows - pycaw not available")
            except Exception as e:
                print(f"Error starting AudioMonitor: {e}")
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
        safe_speaker = get_safe_system_speaker()
        if safe_speaker:
            safe_speaker.speak(_("Connected to power adapter, battery level is {}%").format(percentage))

    def on_charger_disconnect(self, percentage):
        self.charged_notification_sent = False
        play_sound('system/charger_disconnect.ogg')
        safe_speaker = get_safe_system_speaker()
        if safe_speaker:
            safe_speaker.speak(_("Power adapter disconnected, battery level is {}%").format(percentage))

    def on_battery_charging(self, percentage):
        safe_speaker = get_safe_system_speaker()
        if safe_speaker:
            safe_speaker.speak(_("Charging battery, battery level {}%").format(percentage))

    def on_battery_charged(self):
        safe_speaker = get_safe_system_speaker()
        if safe_speaker:
            safe_speaker.speak(_("Battery is fully charged"))

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
            self.max_consecutive_errors = 10  # Stop after 10 consecutive errors
            self.previous_volume = self.get_volume_percentage_safe()
        except Exception as e:
            print(f"Error in AudioMonitor.__init__: {e}")
            import traceback
            traceback.print_exc()
            self.daemon = True
            self.running = False  # Don't run if initialization failed
            self.announce_mode = announce_mode
            self.com_initialized = False
            self.consecutive_errors = 0
            self.max_consecutive_errors = 10
            self.previous_volume = -1

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
                current_volume = self.get_volume_percentage_safe()
                
                if current_volume != -1:
                    self.consecutive_errors = 0  # Reset error counter on success
                    if current_volume != self.previous_volume:
                        self.announce_volume_change(current_volume)
                        self.previous_volume = current_volume
                else:
                    self.consecutive_errors += 1
                    if self.consecutive_errors >= self.max_consecutive_errors:
                        print("AudioMonitor: Too many consecutive errors, stopping monitor")
                        break
                        
                time.sleep(0.1)  # Increased sleep time to reduce CPU usage
        except Exception as e:
            print(f"Error in AudioMonitor: {e}")
        finally:
            # COM cleanup is handled automatically by com_fix module
            pass

    def announce_volume_change(self, volume):
        """Announce volume change based on current settings"""
        if self.announce_mode in ['sound', 'both']:
            play_sound('system/volume.ogg')
        
        if self.announce_mode in ['speech', 'both']:
            safe_speaker = get_safe_system_speaker()
            if safe_speaker:
                safe_speaker.speak(_("Volume: {}%").format(volume), interrupt=True)

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
                return -1
                
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL

            # Check if COM is initialized properly
            if not self.com_initialized:
                return -1

            devices = AudioUtilities.GetSpeakers()
            if devices is None:
                return -1
                
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            if interface is None:
                return -1
                
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            if volume is None:
                return -1
                
            level = volume.GetMasterVolumeLevelScalar()
            if level is None:
                return -1
                
            return int(level * 100)
        except (ImportError, OSError, ValueError, AttributeError, TypeError) as e:
            # Return -1 for any COM-related errors
            return -1
        except Exception as e:
            # Catch any other unexpected errors
            print(f"Unexpected error in get_volume_windows: {e}")
            return -1

    def get_volume_mac(self):
        try:
            result = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"],
                                    capture_output=True, text=True, check=True)
            return int(result.stdout.strip())
        except (FileNotFoundError, subprocess.CalledProcessError, ValueError) as e:
            return -1

    def get_volume_linux(self):
        try:
            import alsaaudio
            mixer = alsaaudio.Mixer()
            return mixer.getvolume()[0]
        except (ImportError, alsaaudio.ALSAAudioError) as e:
            return -1

    def stop(self):
        self.running = False
        
    def __del__(self):
        """Ensure cleanup on object destruction"""
        self.stop()

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