"""
System Information Statusbar Applet

Displays system CPU, RAM, and disk usage in the status bar.
"""

import psutil
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
        "name": _("System Information"),
        "update_interval": 5  # Update every 5 seconds
    }


def get_statusbar_item_text():
    """
    Return status bar text with system information.

    Returns:
        str: Formatted text with CPU, RAM, and disk usage
    """
    try:
        # CPU usage (quick sample)
        cpu_percent = psutil.cpu_percent(interval=0.1)

        # RAM usage
        memory = psutil.virtual_memory()
        ram_percent = memory.percent

        # Disk usage (root drive)
        try:
            # Windows: C:\, Linux/Mac: /
            import platform
            if platform.system() == "Windows":
                disk = psutil.disk_usage('C:\\')
            else:
                disk = psutil.disk_usage('/')
            disk_percent = disk.percent
        except:
            disk_percent = 0

        return _("CPU: {cpu}%, RAM: {ram}%, Disk: {disk}%").format(
            cpu=int(cpu_percent),
            ram=int(ram_percent),
            disk=int(disk_percent)
        )
    except Exception as e:
        print(f"Error getting system information: {e}")
        return _("System Information: Error")


def on_statusbar_item_activate(parent_frame=None):
    """
    Optional: Open detailed system information window.

    Args:
        parent_frame: Parent wx.Frame for GUI dialogs (None for console mode)
    """
    try:
        if parent_frame:
            # GUI mode - show detailed dialog
            import wx

            # Get detailed system information
            cpu_percent = psutil.cpu_percent(interval=0.5)
            cpu_count = psutil.cpu_count()

            memory = psutil.virtual_memory()
            ram_percent = memory.percent
            ram_total_gb = memory.total / (1024 ** 3)
            ram_used_gb = memory.used / (1024 ** 3)
            ram_available_gb = memory.available / (1024 ** 3)

            # Disk info
            import platform
            if platform.system() == "Windows":
                disk = psutil.disk_usage('C:\\')
            else:
                disk = psutil.disk_usage('/')
            disk_percent = disk.percent
            disk_total_gb = disk.total / (1024 ** 3)
            disk_used_gb = disk.used / (1024 ** 3)
            disk_free_gb = disk.free / (1024 ** 3)

            # Format message
            message = _("Detailed System Information:\n\n" +
                       "CPU:\n" +
                       "  Usage: {cpu_percent}%\n" +
                       "  Cores: {cpu_count}\n\n" +
                       "RAM:\n" +
                       "  Usage: {ram_percent}%\n" +
                       "  Total: {ram_total:.1f} GB\n" +
                       "  Used: {ram_used:.1f} GB\n" +
                       "  Available: {ram_available:.1f} GB\n\n" +
                       "Disk:\n" +
                       "  Usage: {disk_percent}%\n" +
                       "  Total: {disk_total:.1f} GB\n" +
                       "  Used: {disk_used:.1f} GB\n" +
                       "  Free: {disk_free:.1f} GB").format(
                cpu_percent=int(cpu_percent),
                cpu_count=cpu_count,
                ram_percent=int(ram_percent),
                ram_total=ram_total_gb,
                ram_used=ram_used_gb,
                ram_available=ram_available_gb,
                disk_percent=int(disk_percent),
                disk_total=disk_total_gb,
                disk_used=disk_used_gb,
                disk_free=disk_free_gb
            )

            wx.MessageBox(
                message,
                _("System Information"),
                wx.OK | wx.ICON_INFORMATION,
                parent_frame
            )
        else:
            # Console mode - just print
            print(_("System Information - detailed view not available in console mode"))

    except Exception as e:
        print(f"Error showing system information details: {e}")
        import traceback
        traceback.print_exc()
