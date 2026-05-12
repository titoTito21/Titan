#!/usr/bin/env python3

import wx
import sys
import os
import re
import threading
import time
import platform
import subprocess
import tempfile
from src.titan_core.translation import _, set_language, language_code
from src.titan_core.sound import play_sound
from src.titan_core.skin_manager import apply_skin_to_window
from src.platform_utils import IS_WINDOWS, IS_LINUX, IS_MACOS, get_subprocess_kwargs
import concurrent.futures

try:
    import pywifi
    from pywifi import const
    PYWIFI_AVAILABLE = True
except ImportError:
    PYWIFI_AVAILABLE = False


def _xml_escape(value):
    """Escape characters that have meaning in XML attribute/text content."""
    return (str(value)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&apos;'))


def _show_skinned_message(message, caption, style=wx.OK | wx.ICON_INFORMATION, parent=None):
    dlg = wx.MessageDialog(parent, message, caption, style)
    try:
        apply_skin_to_window(dlg)
    except Exception:
        pass
    result = dlg.ShowModal()
    dlg.Destroy()
    return result

class NetworkManager:
    def __init__(self):
        self.wifi = None
        self.interface = None
        self.current_networks = []
        self.connected_network = None
        self.wifi_enabled = False
        self.last_scan_time = 0
        self.cached_networks = []
        self.cache_duration = 10  # Cache results for 10 seconds
        
        if PYWIFI_AVAILABLE:
            try:
                self.wifi = pywifi.PyWiFi()
                interfaces = self.wifi.interfaces()
                if interfaces:
                    self.interface = interfaces[0]
                    # Test interface access before marking as enabled
                    try:
                        self.interface.status()  # Test if interface is accessible
                        self.wifi_enabled = True
                        print(f"WiFi interface initialized: {self.interface.name()}")
                    except Exception as e:
                        print(f"WiFi interface not accessible: {e}")
                        self.wifi_enabled = False
                else:
                    print("No WiFi interfaces found")
                    self.wifi_enabled = False
            except Exception as e:
                print(f"Error initializing WiFi: {e}")
                self.wifi_enabled = False
        else:
            print("PyWiFi library not available")
            self.wifi_enabled = False
    
    def scan_networks(self, force_scan=False):
        """Scan for available WiFi networks with caching and timeout"""
        if not self.wifi_enabled or not self.interface:
            return []
        
        current_time = time.time()
        
        # Return cached results if recent enough and not forcing scan
        if not force_scan and self.cached_networks and (current_time - self.last_scan_time) < self.cache_duration:
            print("Using cached WiFi networks")
            return self.cached_networks
        
        print("Performing fresh WiFi scan...")
        
        try:
            # Check if interface is still valid before scanning
            if not self.interface:
                print("WiFi interface not available")
                return self.cached_networks if self.cached_networks else []
            
            # Check interface status before scanning
            try:
                status = self.interface.status()
                print(f"WiFi interface status: {status}")
            except Exception as e:
                print(f"Cannot check interface status: {e}")
                return self.cached_networks if self.cached_networks else []
            
            # Initiate scan with timeout protection
            scan_start_time = time.time()
            self.interface.scan()
            print("WiFi scan initiated...")
            
            # Optimized polling - check results with timeout
            scan_results = []
            start_time = time.time()
            timeout = 8.0  # Max 8 seconds wait
            poll_interval = 0.3  # Check every 300ms
            max_polls = int(timeout / poll_interval)
            poll_count = 0
            
            while time.time() < start_time + timeout and poll_count < max_polls:
                try:
                    scan_results = self.interface.scan_results()
                    if scan_results:
                        print(f"Scan completed in {time.time() - scan_start_time:.1f} seconds")
                        break
                except Exception as e:
                    print(f"Error getting scan results: {e}")
                    break
                    
                time.sleep(poll_interval)
                poll_count += 1
                
                # Adaptive polling interval
                if poll_count > 10:  # After 3 seconds, slow down polling
                    poll_interval = 0.5
            
            if not scan_results:
                print("WiFi scan timeout - no results")
                return self.cached_networks if self.cached_networks else []
            
            networks = []
            for network in scan_results:
                if network.ssid:  # Skip networks without SSID
                    network_info = {
                        'ssid': network.ssid,
                        'signal': network.signal,
                        'encrypted': len(network.akm) > 0,
                        'connected': False
                    }
                    networks.append(network_info)
            
            # Sort by signal strength
            networks.sort(key=lambda x: x['signal'], reverse=True)
            
            # Update cache
            self.current_networks = networks
            self.cached_networks = networks
            self.last_scan_time = current_time
            
            # Check if any network is currently connected
            self.update_connection_status()
            
            print(f"Found {len(networks)} WiFi networks")
            return networks
            
        except Exception as e:
            print(f"Error scanning networks: {e}")
            # Return cached results if available
            return self.cached_networks if self.cached_networks else []
    
    def _get_windows_connected_ssid(self):
        """Return the SSID of the currently associated WiFi network on Windows, or None."""
        try:
            result = subprocess.run(
                ['netsh', 'wlan', 'show', 'interfaces'],
                capture_output=True, text=True, timeout=5, **get_subprocess_kwargs()
            )
            if result.returncode != 0:
                return None
            state_connected = False
            ssid = None
            for line in result.stdout.split('\n'):
                stripped = line.strip()
                if stripped.lower().startswith('state'):
                    state_connected = 'connected' in stripped.lower() and 'disconnect' not in stripped.lower()
                if re.match(r'^\s*SSID\s*:', line) and 'BSSID' not in line:
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        ssid = parts[1].strip() or None
            return ssid if state_connected else None
        except Exception as e:
            print(f"netsh show interfaces failed: {e}")
            return None

    def _get_linux_connected_ssid(self):
        """Return the SSID of the currently associated WiFi network on Linux via nmcli or iwgetid."""
        # Try nmcli first
        try:
            out = subprocess.check_output(
                ['nmcli', '-t', '-f', 'ACTIVE,SSID', 'dev', 'wifi'],
                text=True, stderr=subprocess.DEVNULL, timeout=5
            )
            for line in out.strip().split('\n'):
                parts = line.split(':', 1)
                if len(parts) == 2 and parts[0] == 'yes':
                    return parts[1] or None
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass
        # Try iwgetid fallback
        try:
            out = subprocess.check_output(['iwgetid', '-r'], text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
            return out or None
        except Exception:
            return None

    def _get_macos_connected_ssid(self):
        """Return the SSID of the currently associated WiFi network on macOS via airport tool."""
        try:
            out = subprocess.check_output(
                ['/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport', '-I'],
                text=True, stderr=subprocess.DEVNULL, timeout=5
            )
            for line in out.split('\n'):
                line = line.strip()
                if line.startswith('SSID:'):
                    return line.split(':', 1)[1].strip() or None
            return None
        except Exception:
            return None

    def update_connection_status(self):
        """Update connection status of networks. Uses OS-native tools for accuracy."""
        try:
            for network in self.current_networks:
                network['connected'] = False
            self.connected_network = None

            connected_ssid = None
            if IS_WINDOWS:
                connected_ssid = self._get_windows_connected_ssid()
            elif IS_LINUX:
                connected_ssid = self._get_linux_connected_ssid()
            elif IS_MACOS:
                connected_ssid = self._get_macos_connected_ssid()

            if not connected_ssid and self.interface:
                try:
                    if self.interface.status() == const.IFACE_CONNECTED:
                        profiles = self.interface.network_profiles() or []
                        for profile in profiles:
                            if getattr(profile, 'ssid', None):
                                connected_ssid = profile.ssid
                                break
                except Exception:
                    pass

            if connected_ssid:
                self.connected_network = connected_ssid
                for network in self.current_networks:
                    if network.get('ssid') == connected_ssid:
                        network['connected'] = True
                        print(f"Found connected network: {connected_ssid}")
                        break
        except Exception as e:
            print(f"Error updating connection status: {e}")
            for network in self.current_networks:
                network['connected'] = False

    def _build_windows_wifi_profile_xml(self, ssid, password, security_type='WPA2PSK'):
        """Build a Windows WLAN profile XML for the given SSID/security."""
        safe_ssid = _xml_escape(ssid)
        if password is None:
            security_block = (
                '            <authEncryption>'
                '                <authentication>open</authentication>'
                '                <encryption>none</encryption>'
                '                <useOneX>false</useOneX>'
                '            </authEncryption>'
            )
        else:
            safe_pwd = _xml_escape(password)
            encryption = 'AES' if security_type in ('WPA2PSK', 'WPA3SAE') else 'TKIP'
            security_block = (
                f'            <authEncryption>'
                f'                <authentication>{security_type}</authentication>'
                f'                <encryption>{encryption}</encryption>'
                f'                <useOneX>false</useOneX>'
                f'            </authEncryption>'
                f'            <sharedKey>'
                f'                <keyType>passPhrase</keyType>'
                f'                <protected>false</protected>'
                f'                <keyMaterial>{safe_pwd}</keyMaterial>'
                f'            </sharedKey>'
            )
        return (
            '<?xml version="1.0"?>'
            '<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">'
            f'    <name>{safe_ssid}</name>'
            '    <SSIDConfig>'
            '        <SSID>'
            f'            <name>{safe_ssid}</name>'
            '        </SSID>'
            '    </SSIDConfig>'
            '    <connectionType>ESS</connectionType>'
            '    <connectionMode>auto</connectionMode>'
            '    <MSM>'
            '        <security>'
            f'{security_block}'
            '        </security>'
            '    </MSM>'
            '</WLANProfile>'
        )

    def _connect_windows_netsh(self, ssid, password, target_network):
        """Connect on Windows via netsh - writes profile XML, adds it, then connects."""
        is_encrypted = bool(target_network and target_network.get('encrypted'))
        security_types = []
        if is_encrypted and password:
            security_types = ['WPA2PSK', 'WPAPSK']
        elif not is_encrypted:
            security_types = [None]
        else:
            return False

        for sec in security_types:
            profile_path = None
            try:
                xml = self._build_windows_wifi_profile_xml(ssid, password if sec else None, sec or 'WPA2PSK')
                with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False, encoding='utf-8') as f:
                    f.write(xml)
                    profile_path = f.name

                add = subprocess.run(
                    ['netsh', 'wlan', 'add', 'profile', f'filename={profile_path}', 'user=current'],
                    capture_output=True, text=True, timeout=10, **get_subprocess_kwargs()
                )
                if add.returncode != 0:
                    print(f"netsh add profile ({sec}) failed: {add.stdout} {add.stderr}")
                    continue

                conn = subprocess.run(
                    ['netsh', 'wlan', 'connect', f'name={ssid}', f'ssid={ssid}'],
                    capture_output=True, text=True, timeout=10, **get_subprocess_kwargs()
                )
                if conn.returncode != 0:
                    print(f"netsh connect ({sec}) failed: {conn.stdout} {conn.stderr}")
                    continue

                # Poll up to 20s for association
                for _ in range(40):
                    time.sleep(0.5)
                    current = self._get_windows_connected_ssid()
                    if current == ssid:
                        self.connected_network = ssid
                        return True
            except Exception as e:
                print(f"netsh connect attempt ({sec}) raised: {e}")
            finally:
                if profile_path:
                    try:
                        os.unlink(profile_path)
                    except Exception:
                        pass
        return False

    def _connect_pywifi(self, ssid, password, target_network):
        """Fallback connect via pywifi profile - used when OS-native tools aren't available."""
        if not self.interface:
            return False
        is_encrypted = bool(target_network and target_network.get('encrypted'))

        try:
            self.interface.disconnect()
            time.sleep(1.0)
        except Exception:
            pass

        try:
            profile = pywifi.Profile()
            profile.ssid = ssid
            profile.auth = const.AUTH_ALG_OPEN
            if is_encrypted and password:
                profile.akm.append(const.AKM_TYPE_WPA2PSK)
                profile.cipher = const.CIPHER_TYPE_CCMP
                profile.key = password
            else:
                profile.akm.append(const.AKM_TYPE_NONE)
                profile.cipher = const.CIPHER_TYPE_NONE

            try:
                self.interface.remove_all_network_profiles()
            except Exception:
                pass
            tmp_profile = self.interface.add_network_profile(profile)
            self.interface.connect(tmp_profile)

            # Poll up to 20s for IFACE_CONNECTED
            for _ in range(40):
                time.sleep(0.5)
                if self.interface.status() == const.IFACE_CONNECTED:
                    self.connected_network = ssid
                    return True
            return False
        except Exception as e:
            print(f"pywifi connect error: {e}")
            return False

    def _connect_linux_nmcli(self, ssid, password, target_network):
        """Connect on Linux via nmcli - works whether or not the network was scanned."""
        is_encrypted = bool(target_network and target_network.get('encrypted'))
        cmd = ['nmcli', 'device', 'wifi', 'connect', ssid]
        if is_encrypted and password:
            cmd += ['password', password]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                # Verify association
                for _ in range(20):
                    time.sleep(0.5)
                    if self._get_linux_connected_ssid() == ssid:
                        self.connected_network = ssid
                        return True
                return False
            print(f"nmcli connect failed: {result.stdout} {result.stderr}")
            return False
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            print(f"nmcli connect raised: {e}")
            return False

    def _connect_macos_networksetup(self, ssid, password, target_network):
        """Connect on macOS via networksetup -setairportnetwork."""
        # Discover Wi-Fi device name
        iface_name = None
        try:
            out = subprocess.check_output(
                ['networksetup', '-listallhardwareports'],
                text=True, timeout=5
            )
            in_wifi = False
            for line in out.split('\n'):
                if line.startswith('Hardware Port:') and 'Wi-Fi' in line:
                    in_wifi = True
                elif in_wifi and line.startswith('Device:'):
                    iface_name = line.split(':', 1)[1].strip()
                    break
        except Exception as e:
            print(f"networksetup discovery failed: {e}")
            return False
        if not iface_name:
            return False

        cmd = ['networksetup', '-setairportnetwork', iface_name, ssid]
        if password:
            cmd.append(password)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and 'failed' not in (result.stdout + result.stderr).lower():
                for _ in range(20):
                    time.sleep(0.5)
                    if self._get_macos_connected_ssid() == ssid:
                        self.connected_network = ssid
                        return True
                return False
            print(f"networksetup connect failed: {result.stdout} {result.stderr}")
            return False
        except Exception as e:
            print(f"networksetup connect raised: {e}")
            return False

    def connect_to_network(self, ssid, password=None):
        """Connect to a WiFi network. Uses OS-native tools first, pywifi as fallback."""
        if not self.wifi_enabled:
            return False
        if not ssid:
            return False

        target_network = next((n for n in self.current_networks if n.get('ssid') == ssid), None)

        if IS_WINDOWS:
            if self._connect_windows_netsh(ssid, password, target_network):
                return True
            print("Windows netsh connect failed - falling back to pywifi")
        elif IS_LINUX:
            if self._connect_linux_nmcli(ssid, password, target_network):
                return True
            print("Linux nmcli connect failed - falling back to pywifi")
        elif IS_MACOS:
            if self._connect_macos_networksetup(ssid, password, target_network):
                return True
            print("macOS networksetup connect failed - falling back to pywifi")

        return self._connect_pywifi(ssid, password, target_network)

    def disconnect(self):
        """Disconnect from current network. Uses OS-native tools then pywifi fallback."""
        try:
            if IS_WINDOWS:
                try:
                    result = subprocess.run(
                        ['netsh', 'wlan', 'disconnect'],
                        capture_output=True, text=True, timeout=5, **get_subprocess_kwargs()
                    )
                    if result.returncode == 0:
                        self.connected_network = None
                        return True
                except Exception as e:
                    print(f"netsh disconnect failed: {e}")
            elif IS_LINUX:
                # Find the active wifi connection name and bring it down
                try:
                    out = subprocess.check_output(
                        ['nmcli', '-t', '-f', 'NAME,TYPE', 'connection', 'show', '--active'],
                        text=True, stderr=subprocess.DEVNULL, timeout=5
                    )
                    for line in out.strip().split('\n'):
                        parts = line.split(':')
                        if len(parts) >= 2 and 'wireless' in parts[1]:
                            subprocess.run(
                                ['nmcli', 'connection', 'down', parts[0]],
                                capture_output=True, text=True, timeout=5
                            )
                    self.connected_network = None
                    return True
                except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
                    print(f"nmcli disconnect failed: {e}")
            elif IS_MACOS:
                iface_name = None
                try:
                    out = subprocess.check_output(
                        ['networksetup', '-listallhardwareports'], text=True, timeout=5
                    )
                    in_wifi = False
                    for line in out.split('\n'):
                        if line.startswith('Hardware Port:') and 'Wi-Fi' in line:
                            in_wifi = True
                        elif in_wifi and line.startswith('Device:'):
                            iface_name = line.split(':', 1)[1].strip()
                            break
                except Exception:
                    pass
                if iface_name:
                    try:
                        subprocess.run(
                            ['/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport',
                             iface_name, '-z'],
                            capture_output=True, text=True, timeout=5
                        )
                        self.connected_network = None
                        return True
                    except Exception as e:
                        print(f"airport disassociate failed: {e}")

            # pywifi fallback
            if self.interface:
                self.interface.disconnect()
                self.connected_network = None
                return True
            return False
        except Exception as e:
            print(f"Error disconnecting: {e}")
            return False

    def toggle_wifi(self, enable):
        """Enable or disable the WiFi radio. On Windows uses netsh (no admin
        needed for connect/disconnect). 'Off' = disconnect from current network;
        'On' = re-enable scanning. True hardware radio toggle on Windows
        requires admin rights, so we use a soft toggle that matches user intent.
        """
        try:
            if IS_WINDOWS:
                if enable:
                    # Best-effort re-enable scanning
                    try:
                        if self.interface:
                            self.interface.scan()
                    except Exception:
                        pass
                    self.wifi_enabled = True
                    return True
                else:
                    # Soft "off" - disconnect from any associated network
                    try:
                        subprocess.run(
                            ['netsh', 'wlan', 'disconnect'],
                            capture_output=True, text=True, timeout=5, **get_subprocess_kwargs()
                        )
                    except Exception as e:
                        print(f"netsh disconnect failed: {e}")
                    self.connected_network = None
                    self.wifi_enabled = False
                    return True

            if IS_LINUX:
                cmd = ['nmcli', 'radio', 'wifi', 'on' if enable else 'off']
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        self.wifi_enabled = enable
                        return True
                except (subprocess.CalledProcessError, FileNotFoundError) as e:
                    print(f"nmcli radio toggle failed: {e}")
                # rfkill fallback
                try:
                    action = 'unblock' if enable else 'block'
                    subprocess.run(['rfkill', action, 'wifi'], capture_output=True, text=True, timeout=5)
                    self.wifi_enabled = enable
                    return True
                except (subprocess.CalledProcessError, FileNotFoundError) as e:
                    print(f"rfkill toggle failed: {e}")

            if IS_MACOS:
                iface_name = None
                try:
                    out = subprocess.check_output(
                        ['networksetup', '-listallhardwareports'],
                        text=True, timeout=5
                    )
                    in_wifi = False
                    for line in out.split('\n'):
                        if line.startswith('Hardware Port:') and 'Wi-Fi' in line:
                            in_wifi = True
                        elif in_wifi and line.startswith('Device:'):
                            iface_name = line.split(':', 1)[1].strip()
                            break
                except Exception as e:
                    print(f"networksetup discovery failed: {e}")
                if iface_name:
                    try:
                        subprocess.run(
                            ['networksetup', '-setairportpower', iface_name, 'on' if enable else 'off'],
                            capture_output=True, text=True, timeout=5
                        )
                        self.wifi_enabled = enable
                        return True
                    except Exception as e:
                        print(f"networksetup setairportpower failed: {e}")

            # Last-resort soft toggle
            self.wifi_enabled = enable
            return enable
        except Exception as e:
            print(f"toggle_wifi error: {e}")
            self.wifi_enabled = enable
            return enable

class WiFiPasswordDialog(wx.Dialog):
    def __init__(self, parent, network_name):
        super().__init__(parent, title=_("Connect to WiFi Network"))
        self.network_name = network_name
        self.password = ""

        play_sound('ui/statusbar.ogg')

        self.setup_ui()
    
    def setup_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Network name label
        network_label = wx.StaticText(self, label=_("Network: {}").format(self.network_name))
        sizer.Add(network_label, 0, wx.ALL, 10)
        
        # Password label and input
        password_label = wx.StaticText(self, label=_("Enter WiFi network password:"))
        sizer.Add(password_label, 0, wx.ALL, 10)
        
        self.password_ctrl = wx.TextCtrl(self, style=wx.TE_PASSWORD | wx.TE_PROCESS_ENTER)
        sizer.Add(self.password_ctrl, 0, wx.EXPAND | wx.ALL, 10)
        
        # Remember password checkbox
        self.remember_checkbox = wx.CheckBox(self, label=_("Connect automatically"))
        sizer.Add(self.remember_checkbox, 0, wx.ALL, 10)
        
        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        connect_btn = wx.Button(self, wx.ID_OK, _("Connect"))
        cancel_btn = wx.Button(self, wx.ID_CANCEL, _("Cancel"))
        
        button_sizer.Add(connect_btn, 0, wx.ALL, 5)
        button_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        
        sizer.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        self.SetSizer(sizer)
        self.Fit()
        
        # Set focus to password field
        self.password_ctrl.SetFocus()
        
        # Bind events
        connect_btn.Bind(wx.EVT_BUTTON, self.on_connect)
        self.password_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_connect)
    
    def on_connect(self, event):
        self.password = self.password_ctrl.GetValue()
        if self.password:
            self.EndModal(wx.ID_OK)
        else:
            _show_skinned_message(_("Please enter a password"), _("Error"), wx.OK | wx.ICON_ERROR)

class WiFiGUIPanel(wx.Panel):
    def __init__(self, parent, network_manager):
        super().__init__(parent)
        self.network_manager = network_manager
        self.setup_ui()
        
        # Don't auto-scan - let user click refresh when ready
        # This prevents hanging during GUI creation
        self.show_initial_message()
    
    def show_initial_message(self):
        """Show initial message instead of auto-scanning"""
        # Add helpful message to network list
        index = self.network_list.InsertItem(0, _("Click 'Refresh' to scan for WiFi networks"))
        self.network_list.SetItem(index, 1, "")
        self.network_list.SetItem(index, 2, _("Ready"))
        self.network_list.SetItem(index, 3, "")
        
        print("WiFi GUI ready - waiting for user to click Refresh")
    
    def show_scanning_message(self):
        """Show scanning message during network scan"""
        self.network_list.DeleteAllItems()
        index = self.network_list.InsertItem(0, _("Scanning WiFi networks..."))
        self.network_list.SetItem(index, 1, "")
        self.network_list.SetItem(index, 2, _("Please wait"))
        self.network_list.SetItem(index, 3, "")
        
        print("Showing scanning message to user")
    
    def initial_scan(self):
        """Perform initial network scan after GUI is ready (now optional)"""
        # This method is kept for compatibility but not called automatically
        wx.CallLater(500, self.refresh_networks, False)  # Use cache if available
    
    def setup_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # WiFi toggle
        self.wifi_toggle = wx.CheckBox(self, label=_("WiFi"))
        self.wifi_toggle.SetValue(self.network_manager.wifi_enabled)
        self.wifi_toggle.Bind(wx.EVT_CHECKBOX, self.on_wifi_toggle)
        sizer.Add(self.wifi_toggle, 0, wx.ALL, 10)
        
        # Network list
        self.network_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.network_list.InsertColumn(0, _("Network Name"), width=200)
        self.network_list.InsertColumn(1, _("Signal"), width=80)
        self.network_list.InsertColumn(2, _("Security"), width=80)
        self.network_list.InsertColumn(3, _("Status"), width=80)
        
        sizer.Add(self.network_list, 1, wx.EXPAND | wx.ALL, 10)
        
        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.refresh_btn = wx.Button(self, label=_("Refresh"))
        self.connect_btn = wx.Button(self, label=_("Connect"))
        self.disconnect_btn = wx.Button(self, label=_("Disconnect"))
        
        button_sizer.Add(self.refresh_btn, 0, wx.ALL, 5)
        button_sizer.Add(self.connect_btn, 0, wx.ALL, 5)
        button_sizer.Add(self.disconnect_btn, 0, wx.ALL, 5)
        
        sizer.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        self.SetSizer(sizer)
        
        # Bind events
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        self.connect_btn.Bind(wx.EVT_BUTTON, self.on_connect)
        self.disconnect_btn.Bind(wx.EVT_BUTTON, self.on_disconnect)
        self.network_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_network_selected)
        
        # Enable/disable controls based on WiFi status
        self.update_controls()
    
    def on_wifi_toggle(self, event):
        enabled = self.wifi_toggle.GetValue()
        self.network_manager.toggle_wifi(enabled)
        self.update_controls()
        
        if enabled:
            self.refresh_networks(force_scan=False)  # Use cache on WiFi enable for faster startup
    
    def update_controls(self):
        enabled = self.network_manager.wifi_enabled
        self.network_list.Enable(enabled)
        self.refresh_btn.Enable(enabled)
        self.connect_btn.Enable(enabled)
        self.disconnect_btn.Enable(enabled)
    
    def on_refresh(self, event):
        # Show scanning message immediately
        self.show_scanning_message()
        self.refresh_networks()
    
    def refresh_networks(self, force_scan=True):
        if not self.network_manager.wifi_enabled:
            self.update_network_list([])
            return
        
        # Show loading only for forced scans
        loading_dialog = None
        if force_scan:
            try:
                wx.BeginBusyCursor()
                loading_dialog = wx.ProgressDialog(
                    _("WiFi Scanner"),
                    _("Scanning for networks..."),
                    maximum=100,
                    parent=self,
                    style=wx.PD_AUTO_HIDE | wx.PD_APP_MODAL | wx.PD_CAN_ABORT
                )
                loading_dialog.Update(25)
            except:
                pass  # Ignore if cursor is already busy
        
        def scan_with_timeout():
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(self.network_manager.scan_networks, force_scan)
                    
                    if loading_dialog:
                        try:
                            wx.CallAfter(loading_dialog.Update, 50, _("Processing results..."))
                        except Exception as e:
                            print(f"Error updating loading dialog: {e}")
                    
                    try:
                        # 15 second timeout for network scanning
                        networks = future.result(timeout=15.0)
                        
                        if loading_dialog:
                            try:
                                wx.CallAfter(loading_dialog.Update, 100, _("Complete!"))
                            except Exception as e:
                                print(f"Error updating loading dialog completion: {e}")
                        
                        try:
                            wx.CallAfter(self.update_network_list, networks)
                        except Exception as e:
                            print(f"Error calling update_network_list: {e}")
                        
                    except concurrent.futures.TimeoutError:
                        print("WiFi scan timed out")
                        try:
                            wx.CallAfter(self.show_timeout_message)
                        except Exception as e:
                            print(f"Error showing timeout message: {e}")
                        try:
                            wx.CallAfter(self.update_network_list, [])
                        except Exception as e:
                            print(f"Error updating network list after timeout: {e}")
                        
            except Exception as e:
                print(f"Error in scan thread: {e}")
                try:
                    wx.CallAfter(self.show_error_message, str(e))
                except Exception as e2:
                    print(f"Error showing error message: {e2}")
                try:
                    wx.CallAfter(self.update_network_list, [])
                except Exception as e2:
                    print(f"Error updating network list after error: {e2}")
            finally:
                if force_scan:
                    try:
                        wx.CallAfter(wx.EndBusyCursor)
                    except Exception as e:
                        print(f"Error ending busy cursor: {e}")
                if loading_dialog:
                    try:
                        wx.CallAfter(loading_dialog.Destroy)
                    except Exception as e:
                        print(f"Error destroying loading dialog: {e}")
        
        thread = threading.Thread(target=scan_with_timeout, daemon=True)
        thread.start()
    
    def show_timeout_message(self):
        """Show timeout message to user"""
        _show_skinned_message(
            _("WiFi scan timed out. This may happen if your WiFi adapter is busy or there are many networks nearby. Please try again."),
            _("Scan Timeout"),
            wx.OK | wx.ICON_WARNING
        )
    
    def show_error_message(self, error):
        """Show error message to user"""
        _show_skinned_message(
            _("WiFi scan failed: {}").format(error),
            _("Scan Error"),
            wx.OK | wx.ICON_ERROR
        )
    
    def update_network_list(self, networks):
        try:
            self.network_list.DeleteAllItems()
            
            for i, network in enumerate(networks):
                index = self.network_list.InsertItem(i, network['ssid'])
                self.network_list.SetItem(index, 1, f"{network['signal']} dBm")
                self.network_list.SetItem(index, 2, _("Secured") if network['encrypted'] else _("Open"))
                self.network_list.SetItem(index, 3, _("Connected") if network.get('connected') else "")
                
                # Play sound for connected network
                if network.get('connected'):
                    play_sound('ui/X.ogg')
                    
            # Update status text and show results
            if networks:
                print(f"Updated network list with {len(networks)} networks")
                # Show success feedback briefly
                wx.CallLater(100, lambda: print(f"Scan complete: Found {len(networks)} networks"))
            else:
                print("No networks found or scan failed")
                # Show "no networks" message
                index = self.network_list.InsertItem(0, _("No WiFi networks found"))
                self.network_list.SetItem(index, 1, "")
                self.network_list.SetItem(index, 2, _("Try refreshing"))
                self.network_list.SetItem(index, 3, "")
                
        except Exception as e:
            print(f"Error updating network list: {e}")
    
    def on_network_selected(self, event):
        play_sound('core/FOCUS.ogg')
        # Play x.ogg if selected network is connected
        selection = event.GetIndex()
        if 0 <= selection < len(self.network_manager.current_networks):
            network = self.network_manager.current_networks[selection]
            if network.get('connected'):
                play_sound('ui/X.ogg')
    
    def on_connect(self, event):
        selection = self.network_list.GetFirstSelected()
        if selection == -1:
            _show_skinned_message(_("Please select a network"), _("Error"), wx.OK | wx.ICON_ERROR)
            return
        
        network = self.network_manager.current_networks[selection]
        ssid = network['ssid']
        
        # Check if network requires password
        if network['encrypted']:
            dialog = WiFiPasswordDialog(self, ssid)
            if dialog.ShowModal() == wx.ID_OK:
                password = dialog.password
                self.connect_to_network(ssid, password)
            dialog.Destroy()
        else:
            self.connect_to_network(ssid)
    
    def connect_to_network(self, ssid, password=None):
        # Show connection dialog
        connecting_dialog = wx.ProgressDialog(
            _("WiFi Connection"),
            _("Connecting to {}...").format(ssid),
            maximum=100,
            parent=self,
            style=wx.PD_AUTO_HIDE | wx.PD_APP_MODAL | wx.PD_CAN_ABORT
        )
        
        def connect_with_timeout():
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    try:
                        connecting_dialog.Update(25, _("Authenticating..."))
                    except Exception as e:
                        print(f"Error updating connecting dialog: {e}")
                    
                    future = executor.submit(self.network_manager.connect_to_network, ssid, password)
                    
                    try:
                        connecting_dialog.Update(50, _("Establishing connection..."))
                    except Exception as e:
                        print(f"Error updating connecting dialog progress: {e}")
                    
                    try:
                        # 30 second timeout for connection
                        success = future.result(timeout=30.0)
                        
                        try:
                            connecting_dialog.Update(100, _("Connected!") if success else _("Failed!"))
                        except Exception as e:
                            print(f"Error updating connecting dialog result: {e}")
                        
                        try:
                            wx.CallAfter(self.on_connect_result, success, ssid)
                        except Exception as e:
                            print(f"Error calling on_connect_result: {e}")
                        
                    except concurrent.futures.TimeoutError:
                        print(f"Connection to {ssid} timed out")
                        try:
                            wx.CallAfter(self.on_connect_timeout, ssid)
                        except Exception as e:
                            print(f"Error calling on_connect_timeout: {e}")
                        
            except Exception as e:
                print(f"Error in connect thread: {e}")
                try:
                    wx.CallAfter(self.on_connect_result, False, ssid)
                except Exception as e2:
                    print(f"Error calling on_connect_result after error: {e2}")
            finally:
                try:
                    wx.CallAfter(connecting_dialog.Destroy)
                except Exception as e:
                    print(f"Error destroying connecting dialog: {e}")
        
        threading.Thread(target=connect_with_timeout, daemon=True).start()
    
    def on_connect_timeout(self, ssid):
        """Handle connection timeout"""
        _show_skinned_message(
            _("Connection to {} timed out. Please check your password and try again.").format(ssid),
            _("Connection Timeout"),
            wx.OK | wx.ICON_WARNING
        )
    
    def on_connect_result(self, success, ssid):
        if success:
            _show_skinned_message(_("Connected to {}").format(ssid), _("Success"), wx.OK | wx.ICON_INFORMATION)
            play_sound('ui/X.ogg')  # Connected sound
            self.refresh_networks(force_scan=False)  # Quick refresh
        else:
            _show_skinned_message(_("Failed to connect to {}").format(ssid), _("Error"), wx.OK | wx.ICON_ERROR)
    
    def on_disconnect(self, event):
        success = self.network_manager.disconnect()
        if success:
            _show_skinned_message(_("Disconnected from network"), _("Success"), wx.OK | wx.ICON_INFORMATION)
            self.refresh_networks()
        else:
            _show_skinned_message(_("Failed to disconnect"), _("Error"), wx.OK | wx.ICON_ERROR)

def _iui_announce_widget_type():
    """Return True when the IUI 'announce_widget_type' option is on. Safe import."""
    try:
        from src.settings.settings import get_setting
        return get_setting('announce_widget_type', 'False', section='invisible_interface').lower() == 'true'
    except Exception as e:
        print(f"WiFiPanel: unable to read announce_widget_type setting: {e}")
        return False


def _prompt_wifi_password(ssid):
    """Show a modal wx password dialog for the given SSID. Returns the password string or None."""
    result = {'password': None}

    def _do_show():
        try:
            dlg = WiFiPasswordDialog(None, ssid)
            try:
                apply_skin_to_window(dlg)
            except Exception:
                pass
            try:
                if dlg.ShowModal() == wx.ID_OK:
                    result['password'] = dlg.password
            finally:
                dlg.Destroy()
        except Exception as e:
            print(f"Error showing WiFi password dialog: {e}")

    try:
        if wx.IsMainThread():
            _do_show()
        else:
            evt = threading.Event()

            def _wrapper():
                try:
                    _do_show()
                finally:
                    evt.set()

            wx.CallAfter(_wrapper)
            # Wait for the dialog to close; cap the wait so we never deadlock
            evt.wait(timeout=120)
    except Exception as e:
        print(f"Error scheduling WiFi password dialog: {e}")

    return result['password']


class WiFiPanel:
    """WiFi Panel for Invisible UI - works like volume panel.

    Two virtual controls: 'wifi_toggle' (checkbox) and 'networks' (list).
    The initial network scan runs in a background thread so opening the
    panel never blocks the IUI thread.
    """

    def __init__(self, speak_func):
        self.speak_func = speak_func
        self.network_manager = NetworkManager()
        self.networks = []
        self.current_network_index = 0
        self.wifi_enabled = self.network_manager.wifi_enabled
        self.scanning_in_progress = False
        # Always start on WiFi toggle until the first scan completes — networks list is empty here.
        self.current_control = "wifi_toggle"

        # Kick the first scan off in the background so opening the panel is instant.
        if self.wifi_enabled:
            self.refresh_networks(force_scan=False, threaded=True)

    def speak(self, text, interrupt=True):
        """Safely speak text using the provided speak function"""
        try:
            if self.speak_func and callable(self.speak_func):
                self.speak_func(text)
            else:
                print(f"WiFi Panel speak: {text}")
        except Exception as e:
            print(f"Error in WiFi Panel speak: {e}")
            print(f"WiFi Panel speak fallback: {text}")

    def refresh_networks(self, force_scan=False, threaded=False):
        """Refresh network list - optionally in background thread."""
        if not self.wifi_enabled:
            self.networks = []
            return

        if threaded and not self.scanning_in_progress:
            self.scanning_in_progress = True

            def background_scan():
                try:
                    if not getattr(self, 'network_manager', None):
                        print("WiFiPanel: network_manager not initialized")
                        return
                    try:
                        networks = self.network_manager.scan_networks(force_scan=force_scan) or []
                    except Exception as e:
                        print(f"WiFiPanel: error scanning networks: {e}")
                        networks = []
                    try:
                        self.network_manager.update_connection_status()
                    except Exception as e:
                        print(f"WiFiPanel: error updating connection status: {e}")
                    self.networks = networks
                    try:
                        if networks:
                            self.speak(_("Found {} networks").format(len(networks)))
                        else:
                            self.speak(_("No WiFi networks found"))
                    except Exception as e:
                        print(f"WiFiPanel: error speaking scan result: {e}")
                except Exception as e:
                    print(f"WiFiPanel: error in background scan: {e}")
                finally:
                    self.scanning_in_progress = False

            scan_thread = threading.Thread(target=background_scan, daemon=True)
            scan_thread.start()
            self.speak(_("Scanning networks in background..."))
        else:
            try:
                if not getattr(self, 'network_manager', None):
                    self.networks = []
                    return
                self.networks = self.network_manager.scan_networks(force_scan=force_scan) or []
                self.network_manager.update_connection_status()
            except Exception as e:
                print(f"WiFiPanel: error in synchronous network scan: {e}")
                self.networks = []

    def _format_network_label(self, network, announce_widget_type):
        ssid = network.get('ssid', _("Unknown"))
        status = f" - {_('Connected')}" if network.get('connected') else ""
        security = _("Secured") if network.get('encrypted', False) else _("Open")
        if announce_widget_type:
            return f"{ssid} - {security}{status}, {_('list item')}"
        return f"{ssid} - {security}{status}"

    def get_current_element(self):
        """Get description of current element. Honors IUI announce_widget_type."""
        announce_widget_type = _iui_announce_widget_type()

        if self.current_control == "wifi_toggle":
            status_text = _("Checked") if self.wifi_enabled else _("Unchecked")
            if announce_widget_type:
                return f"{_('WiFi')}, {_('checkbox')}: {status_text}"
            return f"{_('WiFi')}: {status_text}"

        if self.current_control == "networks":
            if self.scanning_in_progress and not self.networks:
                return _("Scanning for WiFi networks...")
            if self.networks and 0 <= self.current_network_index < len(self.networks):
                return self._format_network_label(self.networks[self.current_network_index], announce_widget_type)
            return _("No WiFi networks available")

        return _("WiFi Manager")

    def navigate(self, direction):
        """Navigate within the WiFi panel - up/down for lists, left/right for controls."""
        if direction == "up":
            if self.current_control == "networks":
                if self.networks and self.current_network_index > 0:
                    self.current_network_index -= 1
                    if self.networks[self.current_network_index].get('connected'):
                        play_sound('ui/X.ogg')
                    return (True, 1, 2)
                return (False, 1, 2)
            return (False, 0, 2)

        if direction == "down":
            if self.current_control == "networks":
                if self.networks and self.current_network_index < len(self.networks) - 1:
                    self.current_network_index += 1
                    if self.networks[self.current_network_index].get('connected'):
                        play_sound('ui/X.ogg')
                    return (True, 1, 2)
                return (False, 1, 2)
            return (False, 0, 2)

        if direction == "left":
            if self.current_control != "wifi_toggle":
                self.current_control = "wifi_toggle"
                return (True, 0, 2)
            return (False, 0, 2)

        if direction == "right":
            if self.current_control != "networks":
                self.current_control = "networks"
                if self.networks:
                    self.current_network_index = 0
                    if self.networks[0].get('connected'):
                        play_sound('ui/X.ogg')
                return (True, 1, 2)
            return (False, 1, 2)

        return (False, 0, 2)

    def activate_current_element(self):
        """Activate current element (connect to network or toggle WiFi)."""
        if self.current_control == "wifi_toggle":
            self.wifi_enabled = not self.wifi_enabled
            self.network_manager.toggle_wifi(self.wifi_enabled)
            play_sound('core/SELECT.ogg')
            announce_widget_type = _iui_announce_widget_type()
            status = _("Checked") if self.wifi_enabled else _("Unchecked")
            if announce_widget_type:
                self.speak(f"{_('WiFi')}, {_('checkbox')}: {status}")
            else:
                self.speak(f"{_('WiFi')}: {status}")
            if self.wifi_enabled:
                self.refresh_networks(force_scan=True, threaded=True)
            else:
                self.networks = []
            return

        if self.current_control == "networks":
            if self.networks and 0 <= self.current_network_index < len(self.networks):
                self._connect_to_network(self.networks[self.current_network_index])

    def _connect_to_network(self, network):
        """Connect to a network. For encrypted networks, prompts for password via wx dialog."""
        ssid = network.get('ssid', '')
        if not ssid:
            self.speak(_("Cannot connect: missing network name"))
            return

        if network.get('connected'):
            self.speak(_("Already connected to {}").format(ssid))
            return

        password = None
        if network.get('encrypted', False):
            self.speak(_("Network {} requires a password").format(ssid))
            play_sound('ui/statusbar.ogg')
            password = _prompt_wifi_password(ssid)
            if not password:
                self.speak(_("Connection cancelled"))
                return

        self.speak(_("Connecting to {}...").format(ssid))

        def background_connect():
            try:
                success = self.network_manager.connect_to_network(ssid, password)
                if success:
                    self.speak(_("Connected to {}").format(ssid))
                    play_sound('ui/X.ogg')
                    self.refresh_networks(force_scan=True, threaded=True)
                else:
                    self.speak(_("Failed to connect to {}").format(ssid))
                    play_sound('core/error.ogg')
            except Exception as e:
                print(f"WiFiPanel: error connecting in background: {e}")
                self.speak(_("Connection error"))
                play_sound('core/error.ogg')

        connect_thread = threading.Thread(target=background_connect, daemon=True)
        connect_thread.start()

    def handle_titan_enter(self):
        """Handle Titan+Enter key - refresh networks in background."""
        if self.scanning_in_progress:
            self.speak(_("Scan already in progress"))
        else:
            self.refresh_networks(force_scan=True, threaded=True)
            play_sound('core/SELECT.ogg')

class WiFiInvisibleUI:
    def __init__(self, network_manager, announce_widget_type=False, titan_ui_mode=False):
        try:
            self.network_manager = network_manager
            self.networks = []
            self.current_index = 0
            self.wifi_enabled = True
            self.is_expanded = False
            self.announce_widget_type = announce_widget_type
            self.is_on_wifi_toggle = False  # Track if we're on the WiFi checkbox
            self.titan_ui_mode = titan_ui_mode  # Track if we're in Titan UI mode
            self.listener = None
        except Exception as e:
            print(f"Error initializing WiFiInvisibleUI: {e}")
            # Set default values
            self.network_manager = None
            self.networks = []
            self.current_index = 0
            self.wifi_enabled = False
            self.is_expanded = False
            self.announce_widget_type = False
            self.is_on_wifi_toggle = False
            self.titan_ui_mode = False
            self.listener = None
        
    def show_wifi_interface(self):
        """Show WiFi interface for invisible UI with keyboard navigation"""
        try:
            play_sound('focus_expanded.ogg')
        except Exception as e:
            print(f"Error playing sound: {e}")
        
        if not self.network_manager:
            print("Error: network_manager not available")
            return
        self.is_expanded = True
        
        # Get networks
        self.refresh_networks()
        
        if self.announce_widget_type:
            print(_("WiFi Manager: Widget"))
        else:
            print(_("WiFi Manager"))
        print("=============")
        print(f"Current networks: {len(self.networks)}")
        
        # Start keyboard listener
        self.start_keyboard_listener()
        
        # Show initial state
        self.update_display()
        
        return self
    
    def refresh_networks(self):
        """Refresh network list"""
        try:
            if not self.network_manager:
                print("Error: network_manager not available")
                self.networks = []
                return
                
            self.networks = self.network_manager.scan_networks()
            if self.networks is None:
                self.networks = []
            if self.networks and len(self.networks) > 0:
                self.current_index = 0
            else:
                self.current_index = 0
        except Exception as e:
            print(f"Error refreshing networks: {e}")
            self.networks = []
            self.current_index = 0
        
    def start_keyboard_listener(self):
        """Start keyboard listener for navigation"""
        import sys as _sys
        if _sys.platform == 'darwin':
            print("WiFi keyboard listener: not supported on macOS (no keyboard module)")
            return
        try:
            import keyboard
        except Exception as e:
            print(f"Error importing keyboard: {e}")
            return

        def on_key_event(event):
            """Handle keyboard events using keyboard library"""
            try:
                if event.event_type != 'down':  # Only handle key down events
                    return

                key_name = event.name

                # In Titan UI mode, use direct key navigation (no modifiers)
                if self.titan_ui_mode:
                    if key_name == 'up':
                        self.move_up()
                    elif key_name == 'down':
                        self.move_down()
                    elif key_name == 'right':
                        self.move_right()
                    elif key_name == 'left':
                        self.move_left()
                    elif key_name in ['enter', 'space']:
                        self.activate_current()
                    elif key_name in ['esc', 'backspace']:
                        self.close_interface()
                    elif key_name == 'r':
                        self.refresh_networks()
                        self.update_display()
                # In normal mode, use traditional navigation
                else:
                    if key_name == 'up':
                        self.move_up()
                    elif key_name == 'down':
                        self.move_down()
                    elif key_name == 'right':
                        self.move_right()
                    elif key_name == 'left':
                        self.move_left()
                    elif key_name == 'enter':
                        self.activate_current()
                    elif key_name == 'esc':
                        self.close_interface()
                    elif key_name == 'r':
                        self.refresh_networks()
                        self.update_display()
            except Exception as e:
                print(f"Error handling key press: {e}")

        # Only start listener if not in Titan UI mode (in Titan UI, keys are handled by main system)
        if not self.titan_ui_mode:
            try:
                # Use keyboard.hook to listen for key events without blocking
                keyboard.hook(on_key_event, suppress=False)
                self.listener = True  # Mark that listener is active
            except Exception as e:
                print(f"Error starting keyboard listener: {e}")
                self.listener = None
        
        print("\nNavigation:")
        if self.titan_ui_mode:
            print("- Up/Down: Navigate networks (Titan UI mode)")
            print("- Right/Left: Move to WiFi toggle")
            print("- Enter/Space: Connect/Toggle WiFi")
            print("- R: Refresh networks")
            print("- Escape/Backspace: Exit")
        else:
            print("- Up/Down: Navigate networks")
            print("- Right/Left: Move to WiFi toggle")
            print("- Enter: Connect/Toggle WiFi")
            print("- R: Refresh networks")
            print("- Escape: Exit")
    
    def update_display(self):
        """Update the display with current state"""
        print(f"\nWiFi networks list ({len(self.networks)} networks)")
        
        if self.networks:
            for i, network in enumerate(self.networks):
                status = " - Connected" if network.get('connected') else ""
                security = "Secured" if network['encrypted'] else "Open"
                prefix = "> " if i == self.current_index and not self.is_on_wifi_toggle else "  "
                print(f"{prefix}{network['ssid']} - Signal: {network['signal']} dBm - {security}{status}")
        else:
            print("No WiFi networks found")
        
        # Show WiFi toggle
        from src.settings.settings import get_setting
        announce_widget_type = get_setting('announce_widget_type', 'False', section='invisible_interface').lower() == 'true'
        toggle_prefix = "> " if self.is_on_wifi_toggle else "  "
        toggle_status = "Checked" if self.wifi_enabled else "Unchecked"
        if announce_widget_type:
            print(f"{toggle_prefix}WiFi, checkbox: {toggle_status}")
        else:
            print(f"{toggle_prefix}WiFi: {toggle_status}")
        
        # Announce current selection
        if self.is_on_wifi_toggle:
            status_text = "Checked" if self.wifi_enabled else "Unchecked"
            if announce_widget_type:
                print(f"WiFi, checkbox: {status_text}")
            else:
                print(f"WiFi: {status_text}")
        elif self.networks:
            self.announce_current_network()
    
    def navigation_loop(self):
        """Handle keyboard navigation"""
        print(f"\nWiFi networks list ({len(self.networks)} networks)")
        
        if self.networks:
            for i, network in enumerate(self.networks):
                status = "Connected" if network.get('connected') else ""
                security = "Secured" if network['encrypted'] else "Open"
                prefix = "> " if i == self.current_index else "  "
                print(f"{prefix}{network['ssid']} - Signal: {network['signal']} dBm - {security} {status}")
                
                if network.get('connected'):
                    play_sound('ui/X.ogg')
            
            print(f"\nCurrent selection: {self.networks[self.current_index]['ssid']}")
            self.announce_current_network()
        else:
            print("No WiFi networks found")
            
        wifi_status = "List: WiFi networks" if self.networks else "List: No networks"
        print(wifi_status)
        print("WiFi: Checkbox: Checked" if self.wifi_enabled else "WiFi: Checkbox: Unchecked")
        
        # Simulate basic navigation for testing
        print("\nPress Ctrl+C to exit...")
    
    def move_up(self):
        """Move selection up"""
        if self.is_on_wifi_toggle:
            # Move from WiFi toggle to last network
            if self.networks:
                self.is_on_wifi_toggle = False
                self.current_index = len(self.networks) - 1
                play_sound('focus.ogg')
                self.announce_current_network()
        elif self.networks and self.current_index > 0:
            self.current_index -= 1
            play_sound('focus.ogg')
            self.announce_current_network()
        elif self.current_index == 0:
            # Move to WiFi toggle
            self.is_on_wifi_toggle = True
            play_sound('focus.ogg')
            from src.settings.settings import get_setting
            announce_widget_type = get_setting('announce_widget_type', 'False', section='invisible_interface').lower() == 'true'
            status = "Checked" if self.wifi_enabled else "Unchecked"
            if announce_widget_type:
                print(f"WiFi, checkbox: {status}")
            else:
                print(f"WiFi: {status}")
    
    def move_down(self):
        """Move selection down"""
        if self.is_on_wifi_toggle:
            # Move from WiFi toggle to first network
            if self.networks:
                self.is_on_wifi_toggle = False
                self.current_index = 0
                play_sound('focus.ogg')
                self.announce_current_network()
        elif self.networks and self.current_index < len(self.networks) - 1:
            self.current_index += 1
            play_sound('focus.ogg')
            self.announce_current_network()
        elif self.networks and self.current_index == len(self.networks) - 1:
            # Move to WiFi toggle
            self.is_on_wifi_toggle = True
            play_sound('focus.ogg')
            from src.settings.settings import get_setting
            announce_widget_type = get_setting('announce_widget_type', 'False', section='invisible_interface').lower() == 'true'
            status = "Checked" if self.wifi_enabled else "Unchecked"
            if announce_widget_type:
                print(f"WiFi, checkbox: {status}")
            else:
                print(f"WiFi: {status}")
    
    def move_right(self):
        """Move to WiFi toggle from network list"""
        if not self.is_on_wifi_toggle:
            self.is_on_wifi_toggle = True
            play_sound('focus.ogg')
            from src.settings.settings import get_setting
            announce_widget_type = get_setting('announce_widget_type', 'False', section='invisible_interface').lower() == 'true'
            status = "Checked" if self.wifi_enabled else "Unchecked"
            if announce_widget_type:
                print(f"WiFi, checkbox: {status}")
            else:
                print(f"WiFi: {status}")
    
    def move_left(self):
        """Move from WiFi toggle to network list"""
        if self.is_on_wifi_toggle and self.networks:
            self.is_on_wifi_toggle = False
            play_sound('focus.ogg')
            self.announce_current_network()
    
    def activate_current(self):
        """Activate current selection (connect to network or toggle WiFi)"""
        if self.is_on_wifi_toggle:
            # Toggle WiFi
            self.wifi_enabled = not self.wifi_enabled
            self.network_manager.toggle_wifi(self.wifi_enabled)
            play_sound('core/SELECT.ogg')
            from src.settings.settings import get_setting
            announce_widget_type = get_setting('announce_widget_type', 'False', section='invisible_interface').lower() == 'true'
            status = "Checked" if self.wifi_enabled else "Unchecked"
            if announce_widget_type:
                print(f"WiFi, checkbox: {status}")
            else:
                print(f"WiFi: {status}")
            
            if self.wifi_enabled:
                print("Scanning for networks...")
                self.refresh_networks()
                self.update_display()
        else:
            # Connect to selected network
            self.connect_to_current_network()
    
    def announce_current_network(self):
        """Announce current network details"""
        if not self.networks or self.current_index >= len(self.networks):
            return
        
        network = self.networks[self.current_index]
        status = f" - {_('Connected')}" if network.get('connected') else ""
        security = _("Secured") if network['encrypted'] else _("Open")
        from src.settings.settings import get_setting
        announce_widget_type = get_setting('announce_widget_type', 'False', section='invisible_interface').lower() == 'true'
        if announce_widget_type:
            print(f"{network['ssid']} - {security}{status}, {_('list item')}")
        else:
            print(f"{network['ssid']} - {security}{status}")
        
        # Play x.ogg sound for connected network during navigation
        if network.get('connected'):
            play_sound('x.ogg')
    
    def connect_to_current_network(self):
        """Connect to currently selected network"""
        if not self.networks or self.current_index >= len(self.networks):
            return
        
        network = self.networks[self.current_index]
        ssid = network['ssid']
        
        # Check if already connected
        if network.get('connected'):
            print(_("Already connected to {}").format(ssid))
            return
        
        if network['encrypted']:
            play_sound('statusbar.ogg')
            print(_("Enter WiFi network password for {}:").format(ssid))
            try:
                password = input(_("Password: "))
                if password:
                    print(_("Connecting to network..."))
                    success = self.network_manager.connect_to_network(ssid, password)
                else:
                    print(_("Password required"))
                    return
            except KeyboardInterrupt:
                print(_("\nConnection cancelled"))
                return
        else:
            print(_("Connecting to {}...").format(ssid))
            success = self.network_manager.connect_to_network(ssid)
        
        if success:
            print(_("Connected to {}").format(ssid))
            play_sound('x.ogg')
            self.refresh_networks()
            self.update_display()
        else:
            print(_("Failed to connect to {}").format(ssid))
            play_sound('error.ogg')
    
    def close_interface(self):
        """Close WiFi interface"""
        try:
            if self.listener:
                try:
                    # Unhook keyboard events
                    import keyboard
                    keyboard.unhook_all()
                except Exception as e:
                    print(f"Error stopping keyboard listener: {e}")
                self.listener = None

            try:
                play_sound('focus_collapsed.ogg')
            except Exception as e:
                print(f"Error playing sound: {e}")

            self.is_expanded = False
            print(_("WiFi manager closed"))
        except Exception as e:
            print(f"Error closing interface: {e}")
    
    # Methods required for IUI widget compatibility
    def navigate(self, direction):
        """Navigate in the specified direction (for IUI widget compatibility)"""
        if direction == 'up':
            self.move_up()
        elif direction == 'down':
            self.move_down()
        elif direction == 'left':
            self.move_left()
        elif direction == 'right':
            self.move_right()
        return True
    
    def activate_current_element(self):
        """Activate current element (for IUI widget compatibility)"""
        self.activate_current()
    
    def get_current_element(self):
        """Get description of current element (for IUI widget compatibility)"""
        from src.settings.settings import get_setting
        announce_widget_type = get_setting('announce_widget_type', 'False', section='invisible_interface').lower() == 'true'
        
        if self.is_on_wifi_toggle:
            status_text = _("Checked") if self.wifi_enabled else _("Unchecked")
            if announce_widget_type:
                return f"{_('WiFi')}, {_('checkbox')}: {status_text}"
            else:
                return f"{_('WiFi')}: {status_text}"
        elif self.networks and self.current_index < len(self.networks):
            network = self.networks[self.current_index]
            status = f" - {_('Connected')}" if network.get('connected') else ""
            security = _("Secured") if network['encrypted'] else _("Open")
            if announce_widget_type:
                return f"{network['ssid']} - {security}{status}, {_('list item')}"
            else:
                return f"{network['ssid']} - {security}{status}"
        else:
            return _("No WiFi networks available")
    
    def handle_titan_enter(self):
        """Handle Titan+Enter key (for IUI widget compatibility)"""
        # For WiFi manager, Titan+Enter can refresh the networks
        print(_("Refreshing WiFi networks..."))
        self.refresh_networks()
        self.update_display()
        return _("Networks refreshed")
    
    def set_border(self):
        """Set widget border (for IUI widget compatibility)"""
        # WiFi manager doesn't need visual border, but method needed for compatibility
        pass

def show_wifi_gui(parent=None):
    """Show WiFi GUI interface with timeout protection"""
    if not PYWIFI_AVAILABLE:
        _show_skinned_message(_("WiFi functionality requires pywifi library.\nInstall with: pip install pywifi"), 
                     _("Error"), wx.OK | wx.ICON_ERROR)
        return None
    
    # Show loading dialog immediately
    loading_dialog = wx.ProgressDialog(
        _("WiFi Manager"),
        _("Initializing WiFi interface..."),
        maximum=100,
        parent=parent,
        style=wx.PD_AUTO_HIDE | wx.PD_APP_MODAL | wx.PD_CAN_ABORT
    )
    
    try:
        loading_dialog.Update(25, _("Creating network manager..."))
        
        # Initialize network manager with timeout in background thread
        def init_network_manager():
            return NetworkManager()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(init_network_manager)
            
            # Wait with timeout
            try:
                network_manager = future.result(timeout=10.0)  # 10 second timeout
            except concurrent.futures.TimeoutError:
                loading_dialog.Destroy()
                _show_skinned_message(_("WiFi initialization timed out. Please try again."), 
                             _("Timeout Error"), wx.OK | wx.ICON_ERROR)
                return None
        
        loading_dialog.Update(50, _("Checking WiFi interfaces..."))
        
        if not network_manager.wifi_enabled:
            loading_dialog.Destroy()
            _show_skinned_message(_("No WiFi interfaces available or WiFi initialization failed."), 
                         _("WiFi Error"), wx.OK | wx.ICON_WARNING)
            return None
        
        loading_dialog.Update(75, _("Creating GUI interface..."))
        print("Creating WiFi GUI frame...")
        
        frame = wx.Frame(parent, title=_("WiFi Manager"), size=(600, 400))
        panel = WiFiGUIPanel(frame, network_manager)
        
        loading_dialog.Update(100, _("Ready!"))
        wx.CallLater(500, loading_dialog.Destroy)  # Close loading dialog after short delay
        
        frame.Show()
        print("WiFi GUI frame created and shown")
        return frame
        
    except Exception as e:
        loading_dialog.Destroy()
        print(f"Error creating WiFi GUI: {e}")
        import traceback
        traceback.print_exc()
        try:
            _show_skinned_message(_("Error creating WiFi interface:\n{}").format(str(e)), 
                         _("Error"), wx.OK | wx.ICON_ERROR)
        except:
            print("Could not show error dialog")
        return None

def show_wifi_invisible_ui(announce_widget_type=False, titan_ui_mode=False):
    """Show WiFi invisible UI interface"""
    network_manager = NetworkManager()
    
    if not PYWIFI_AVAILABLE:
        print("WiFi functionality requires pywifi library.")
        print("Install with: pip install pywifi")
        return None
    
    wifi_ui = WiFiInvisibleUI(network_manager, announce_widget_type, titan_ui_mode)
    return wifi_ui.show_wifi_interface()

if __name__ == "__main__":
    # Test the WiFi interfaces
    if len(sys.argv) > 1 and sys.argv[1] == "gui":
        app = wx.App()
        show_wifi_gui()
        app.MainLoop()
    else:
        show_wifi_invisible_ui()
