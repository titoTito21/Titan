# Create Statusbar Applet Wizard

Interactive wizard to create a new statusbar applet for TCE Launcher.

## What are Statusbar Applets?

Statusbar applets are small plugins located in `data/statusbar_applets/` that display dynamic information in the status bar across all interface modes (GUI, IUI, Klango). They are loaded by `StatusbarAppletManager` (`src/titan_core/statusbar_applet_manager.py`). Examples: system information (CPU/RAM/Disk), clock, network status.

## Process:

1. **Ask for Applet Details:**
   - Applet name in English
   - Applet name in Polish
   - Applet ID (unique identifier, lowercase, for directory name)
   - Description (Polish and English)
   - Update interval in seconds (default: 5)
   - What data to display in the statusbar
   - Whether it needs an activation dialog (optional detail view)

2. **Create Applet Structure:**
   - Create directory: `data/statusbar_applets/{applet_id}/`
   - Create main file: `data/statusbar_applets/{applet_id}/main.py`
   - Create metadata file: `data/statusbar_applets/{applet_id}/applet.json`

3. **Create `applet.json`:**
   ```json
   {
       "name": "{English name}",
       "name_pl": "{Polish name}",
       "name_en": "{English name}",
       "description": "{English description}",
       "description_pl": "{Polish description}",
       "description_en": "{English description}",
       "version": "1.0.0",
       "author": "TCE Launcher",
       "update_interval": {seconds}
   }
   ```

4. **Generate Applet Template (`main.py`):**
   ```python
   """
   {Applet Name} Statusbar Applet

   {Description}
   """

   import os
   import sys

   # Add TCE root to path
   APPLET_DIR = os.path.dirname(os.path.abspath(__file__))
   TCE_ROOT = os.path.abspath(os.path.join(APPLET_DIR, '..', '..', '..'))
   if TCE_ROOT not in sys.path:
       sys.path.insert(0, TCE_ROOT)

   from src.titan_core.translation import set_language
   from src.settings.settings import get_setting

   # Initialize translations
   _ = set_language(get_setting('language', 'pl'))


   def get_statusbar_item_info():
       """
       Return applet metadata.

       Returns:
           dict: Applet info with name and update_interval
       """
       return {
           "name": _("{Applet Name}"),
           "update_interval": {seconds}  # Update every N seconds
       }


   def get_statusbar_item_text():
       """
       Return the text to display in the status bar.

       This function is called periodically (every update_interval seconds).
       Keep it fast — it has a 2-second timeout enforced by StatusbarAppletManager.

       Returns:
           str: Text to display in the statusbar
       """
       try:
           # Add your status bar text logic here
           value = "..."  # Replace with actual data

           return _("{Applet Name}: {value}").format(value=value)
       except Exception as e:
           print(f"Error getting {applet_id} information: {e}")
           return _("{Applet Name}: Error")


   def on_statusbar_item_activate(parent_frame=None):
       """
       Optional: Handle activation when user selects this statusbar item.

       Called when user double-clicks or activates the statusbar item.

       Args:
           parent_frame: wx.Frame for GUI dialogs (None for console/invisible mode)
       """
       try:
           if parent_frame:
               # GUI mode — show detailed dialog
               import wx

               # Build your detailed message here
               message = _("Detailed {Applet Name} information:\n\n")
               message += "..."  # Add details

               wx.MessageBox(
                   message,
                   _("{Applet Name}"),
                   wx.OK | wx.ICON_INFORMATION,
                   parent_frame
               )
           else:
               # Console/invisible mode — print info
               print(_("{Applet Name} - detailed view not available in console mode"))

       except Exception as e:
           print(f"Error showing {applet_id} details: {e}")
           import traceback
           traceback.print_exc()
   ```

5. **Verify Installation:**
   - Restart TCE Launcher
   - The applet text should appear in the statusbar
   - Double-click or activate the statusbar item to test the activation dialog

## Key Notes from StatusbarAppletManager:

- Applet text is cached with a **2-second timeout** — `get_statusbar_item_text()` MUST return fast
- If timeout is exceeded, "Error: Timeout" is shown in the statusbar
- `on_statusbar_item_activate()` is optional — omit it if no action needed
- `applet.json` `update_interval` sets how often the cache is refreshed
- Both `applet.json` and `main.py` are required for an applet to load
- Display name priority: `get_statusbar_item_info()['name']` > `applet.json` locale name

## Performance Rules:

1. **Keep `get_statusbar_item_text()` fast** — under 2 seconds total
2. **Cache expensive data** — don't re-read files on every call
3. **Handle exceptions gracefully** — always return a string, never raise
4. **Use `interval=0.1`** for CPU sampling (not blocking `interval=1`)

## Reference Example:

See `data/statusbar_applets/system_information/main.py`:
- Uses `psutil` for CPU/RAM/disk
- `get_statusbar_item_text()` returns formatted string
- `on_statusbar_item_activate()` opens detailed wx.MessageBox
- Uses `set_language()` for translated output

## Reference Structure:

```
data/statusbar_applets/{applet_id}/
├── applet.json     # Metadata (name, description, update_interval)
└── main.py         # Implementation with required functions
```

## Required Functions:

Statusbar applets MUST define:
- `get_statusbar_item_info()` — Return dict with `name` and `update_interval` (required)
- `get_statusbar_item_text()` — Return status bar text string (required)

Statusbar applets CAN define (optional):
- `on_statusbar_item_activate(parent_frame=None)` — Handle user activation

## Complete Code Examples

Below are three complete, runnable statusbar applet examples. Each includes both `applet.json` and `main.py` ready to copy into `data/statusbar_applets/{applet_id}/`.

---

### Example 1: Clock Applet

Shows current time (HH:MM) in the statusbar. On activation, displays the full date, time, and day of week.

**`data/statusbar_applets/clock/applet.json`**

```json
{
    "name": "Clock",
    "name_pl": "Zegar",
    "name_en": "Clock",
    "description": "Displays current time in the statusbar",
    "description_pl": "Wyswietla aktualny czas na pasku stanu",
    "description_en": "Displays current time in the statusbar",
    "version": "1.0.0",
    "author": "TCE Launcher",
    "update_interval": 30
}
```

**`data/statusbar_applets/clock/main.py`**

```python
"""
Clock Statusbar Applet

Displays the current time in the statusbar.
On activation, shows the full date, time, and day of the week.
"""

import os
import sys
from datetime import datetime

# Add TCE root to path
APPLET_DIR = os.path.dirname(os.path.abspath(__file__))
TCE_ROOT = os.path.abspath(os.path.join(APPLET_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

from src.titan_core.translation import set_language
from src.settings.settings import get_setting

# Initialize translations
_ = set_language(get_setting('language', 'pl'))


def get_statusbar_item_info():
    """
    Return applet metadata.

    Returns:
        dict: Applet info with name and update_interval
    """
    return {
        "name": _("Clock"),
        "update_interval": 30
    }


def get_statusbar_item_text():
    """
    Return the current time as HH:MM for the statusbar.

    Returns:
        str: Current time formatted as HH:MM
    """
    try:
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        return time_str
    except Exception as e:
        print(f"Error getting clock information: {e}")
        return _("Clock: Error")


def on_statusbar_item_activate(parent_frame=None):
    """
    Show full date, time, and day of week on activation.

    Args:
        parent_frame: wx.Frame for GUI dialogs (None for console/invisible mode)
    """
    try:
        now = datetime.now()

        days_en = {
            0: "Monday", 1: "Tuesday", 2: "Wednesday",
            3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday"
        }
        day_name = days_en.get(now.weekday(), "Unknown")

        full_date = now.strftime("%Y-%m-%d")
        full_time = now.strftime("%H:%M:%S")

        message = _("Date: {date}\nTime: {time}\nDay of week: {day}").format(
            date=full_date,
            time=full_time,
            day=day_name
        )

        if parent_frame:
            import wx
            wx.MessageBox(
                message,
                _("Clock"),
                wx.OK | wx.ICON_INFORMATION,
                parent_frame
            )
        else:
            print(message)

    except Exception as e:
        print(f"Error showing clock details: {e}")
        import traceback
        traceback.print_exc()
```

---

### Example 2: Battery Status Applet

Shows battery percentage and charging status. Gracefully handles desktop PCs with no battery.

**`data/statusbar_applets/battery/applet.json`**

```json
{
    "name": "Battery",
    "name_pl": "Bateria",
    "name_en": "Battery",
    "description": "Displays battery percentage and charging status",
    "description_pl": "Wyswietla poziom baterii i stan ladowania",
    "description_en": "Displays battery percentage and charging status",
    "version": "1.0.0",
    "author": "TCE Launcher",
    "update_interval": 60
}
```

**`data/statusbar_applets/battery/main.py`**

```python
"""
Battery Status Statusbar Applet

Displays battery percentage and charging status in the statusbar.
On activation, shows detailed battery information including time remaining.
Gracefully handles desktop PCs without a battery.
"""

import os
import sys

# Add TCE root to path
APPLET_DIR = os.path.dirname(os.path.abspath(__file__))
TCE_ROOT = os.path.abspath(os.path.join(APPLET_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

from src.titan_core.translation import set_language
from src.settings.settings import get_setting

# Initialize translations
_ = set_language(get_setting('language', 'pl'))

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def get_statusbar_item_info():
    """
    Return applet metadata.

    Returns:
        dict: Applet info with name and update_interval
    """
    return {
        "name": _("Battery"),
        "update_interval": 60
    }


def _get_battery():
    """
    Safely retrieve battery info.

    Returns:
        psutil battery named tuple or None if unavailable
    """
    if not HAS_PSUTIL:
        return None
    try:
        return psutil.sensors_battery()
    except Exception:
        return None


def get_statusbar_item_text():
    """
    Return battery percentage and charging indicator for the statusbar.

    Returns:
        str: Battery status text (e.g. "Battery: 75% [Charging]" or "No battery")
    """
    try:
        battery = _get_battery()
        if battery is None:
            return _("Battery: N/A")

        percent = int(battery.percent)
        if battery.power_plugged:
            status = _("Charging")
        else:
            status = _("Discharging")

        return _("Battery: {percent}% [{status}]").format(
            percent=percent,
            status=status
        )
    except Exception as e:
        print(f"Error getting battery information: {e}")
        return _("Battery: Error")


def on_statusbar_item_activate(parent_frame=None):
    """
    Show detailed battery information on activation.

    Args:
        parent_frame: wx.Frame for GUI dialogs (None for console/invisible mode)
    """
    try:
        battery = _get_battery()

        if battery is None:
            message = _("No battery detected. This may be a desktop PC or psutil is not installed.")
        else:
            percent = int(battery.percent)
            plugged = _("Yes") if battery.power_plugged else _("No")

            if battery.secsleft == psutil.POWER_TIME_UNLIMITED:
                time_remaining = _("Unlimited (plugged in)")
            elif battery.secsleft == psutil.POWER_TIME_UNKNOWN:
                time_remaining = _("Unknown")
            else:
                hours = battery.secsleft // 3600
                minutes = (battery.secsleft % 3600) // 60
                time_remaining = _("{hours}h {minutes}m").format(
                    hours=hours,
                    minutes=minutes
                )

            message = _("Battery level: {percent}%\n"
                        "Plugged in: {plugged}\n"
                        "Time remaining: {time_remaining}").format(
                percent=percent,
                plugged=plugged,
                time_remaining=time_remaining
            )

        if parent_frame:
            import wx
            wx.MessageBox(
                message,
                _("Battery Status"),
                wx.OK | wx.ICON_INFORMATION,
                parent_frame
            )
        else:
            print(message)

    except Exception as e:
        print(f"Error showing battery details: {e}")
        import traceback
        traceback.print_exc()
```

---

### Example 3: Network Status Applet

Shows current network connection type and IP address. On activation, lists all network interfaces.

**`data/statusbar_applets/network_status/applet.json`**

```json
{
    "name": "Network Status",
    "name_pl": "Status sieci",
    "name_en": "Network Status",
    "description": "Displays current network connection and IP address",
    "description_pl": "Wyswietla aktualne polaczenie sieciowe i adres IP",
    "description_en": "Displays current network connection and IP address",
    "version": "1.0.0",
    "author": "TCE Launcher",
    "update_interval": 10
}
```

**`data/statusbar_applets/network_status/main.py`**

```python
"""
Network Status Statusbar Applet

Displays current network connection type and IP address in the statusbar.
On activation, shows all network interfaces with their addresses.
"""

import os
import sys
import socket

# Add TCE root to path
APPLET_DIR = os.path.dirname(os.path.abspath(__file__))
TCE_ROOT = os.path.abspath(os.path.join(APPLET_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

from src.titan_core.translation import set_language
from src.settings.settings import get_setting

# Initialize translations
_ = set_language(get_setting('language', 'pl'))

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def get_statusbar_item_info():
    """
    Return applet metadata.

    Returns:
        dict: Applet info with name and update_interval
    """
    return {
        "name": _("Network"),
        "update_interval": 10
    }


def _get_local_ip():
    """
    Get the primary local IP address by connecting to an external host.

    Returns:
        str: Local IP address or "N/A" if unavailable
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "N/A"


def _get_connection_type():
    """
    Determine the active network connection type (Wi-Fi, Ethernet, or Disconnected).

    Returns:
        str: Connection type name
    """
    if not HAS_PSUTIL:
        return _("Unknown")

    try:
        stats = psutil.net_if_stats()
        for iface_name, iface_stats in stats.items():
            if not iface_stats.isup:
                continue
            if iface_name.startswith("lo") or iface_name == "Loopback Pseudo-Interface 1":
                continue

            name_lower = iface_name.lower()
            if "wi-fi" in name_lower or "wlan" in name_lower or "wireless" in name_lower:
                return _("Wi-Fi")
            elif "ethernet" in name_lower or "eth" in name_lower:
                return _("Ethernet")

        # Check if any non-loopback interface is up
        for iface_name, iface_stats in stats.items():
            if iface_stats.isup and not iface_name.startswith("lo") and iface_name != "Loopback Pseudo-Interface 1":
                return _("Connected")

        return _("Disconnected")
    except Exception:
        return _("Unknown")


def get_statusbar_item_text():
    """
    Return network connection type and IP for the statusbar.

    Returns:
        str: Network status text (e.g. "Net: Wi-Fi 192.168.1.10")
    """
    try:
        conn_type = _get_connection_type()
        ip = _get_local_ip()

        if ip == "N/A":
            return _("Net: {type} (no IP)").format(type=conn_type)

        return _("Net: {type} {ip}").format(type=conn_type, ip=ip)
    except Exception as e:
        print(f"Error getting network information: {e}")
        return _("Net: Error")


def on_statusbar_item_activate(parent_frame=None):
    """
    Show all network interfaces and their addresses on activation.

    Args:
        parent_frame: wx.Frame for GUI dialogs (None for console/invisible mode)
    """
    try:
        lines = []
        lines.append(_("Network Interfaces:"))
        lines.append("")

        if HAS_PSUTIL:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()

            for iface_name in sorted(addrs.keys()):
                iface_stats = stats.get(iface_name)
                status = _("Up") if iface_stats and iface_stats.isup else _("Down")
                speed = iface_stats.speed if iface_stats else 0

                lines.append(_("{name} [{status}]").format(
                    name=iface_name,
                    status=status
                ))

                if speed > 0:
                    lines.append(_("  Speed: {speed} Mbps").format(speed=speed))

                for addr in addrs[iface_name]:
                    if addr.family == socket.AF_INET:
                        lines.append(_("  IPv4: {address}").format(address=addr.address))
                    elif addr.family == socket.AF_INET6:
                        lines.append(_("  IPv6: {address}").format(address=addr.address))

                lines.append("")
        else:
            ip = _get_local_ip()
            hostname = socket.gethostname()
            lines.append(_("Hostname: {hostname}").format(hostname=hostname))
            lines.append(_("Local IP: {ip}").format(ip=ip))
            lines.append("")
            lines.append(_("Install psutil for detailed interface information."))

        message = "\n".join(lines)

        if parent_frame:
            import wx
            wx.MessageBox(
                message,
                _("Network Status"),
                wx.OK | wx.ICON_INFORMATION,
                parent_frame
            )
        else:
            print(message)

    except Exception as e:
        print(f"Error showing network details: {e}")
        import traceback
        traceback.print_exc()
```

---

## Action:

Ask the user for applet details and create a complete, working statusbar applet following the current TCE standard.
