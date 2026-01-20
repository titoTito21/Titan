#!/usr/bin/env python3
"""
WiFi Safe Wrapper - Ultimate protection against WiFi GUI hanging
"""

import wx
import threading
import time
import signal
import os
import sys
from src.titan_core.translation import _

# Global circuit breaker
_wifi_gui_active = False
_wifi_gui_failed_count = 0
_last_failure_time = 0
FAILURE_COOLDOWN = 30  # 30 seconds cooldown after failure

def is_wifi_gui_safe():
    """Check if WiFi GUI is safe to open based on failure history"""
    global _wifi_gui_failed_count, _last_failure_time
    
    current_time = time.time()
    
    # Reset failure count after cooldown period
    if current_time - _last_failure_time > FAILURE_COOLDOWN:
        _wifi_gui_failed_count = 0
    
    # Block if too many recent failures
    if _wifi_gui_failed_count >= 3:
        return False
        
    return True

def record_wifi_failure():
    """Record a WiFi GUI failure"""
    global _wifi_gui_failed_count, _last_failure_time
    _wifi_gui_failed_count += 1
    _last_failure_time = time.time()
    print(f"WiFi GUI failure recorded. Count: {_wifi_gui_failed_count}")

def safe_show_wifi_gui(parent=None):
    """Safely show WiFi GUI with ultimate timeout protection"""
    global _wifi_gui_active
    
    # Check circuit breaker
    if not is_wifi_gui_safe():
        wx.MessageBox(
            _("WiFi interface has failed multiple times recently.\n"
              "Please wait 30 seconds before trying again, or use system WiFi settings.\n\n"
              "Windows WiFi: Win+I → Network & Internet → WiFi"),
            _("WiFi Protection Active"),
            wx.OK | wx.ICON_WARNING
        )
        return None
    
    # Check if already active
    if _wifi_gui_active:
        wx.MessageBox(
            _("WiFi interface is already being opened. Please wait."),
            _("WiFi Already Loading"),
            wx.OK | wx.ICON_INFORMATION
        )
        return None
    
    print("Starting ULTRA-SAFE WiFi GUI opening process...")
    _wifi_gui_active = True
    
    # Create watchdog timer - will forcibly terminate the attempt
    watchdog_triggered = [False]
    
    def watchdog_timeout():
        if not watchdog_triggered[0]:
            watchdog_triggered[0] = True
            print("WATCHDOG TIMEOUT: WiFi GUI attempt terminated!")
            record_wifi_failure()
            
            # Emergency message
            try:
                wx.CallAfter(show_watchdog_message)
            except:
                print("Could not show watchdog message")
    
    def show_watchdog_message():
        global _wifi_gui_active
        _wifi_gui_active = False
        try:
            wx.MessageBox(
                _("WiFi interface loading was forcibly stopped.\n\n"
                  "This prevents your computer from freezing.\n"
                  "Please use Windows WiFi settings instead:\n\n"
                  "Press Win+I → Network & Internet → WiFi"),
                _("WiFi Safety Protection"),
                wx.OK | wx.ICON_ERROR
            )
        except:
            pass
    
    # Start watchdog with 5 second timeout
    watchdog = threading.Timer(5.0, watchdog_timeout)
    watchdog.daemon = True
    watchdog.start()
    
    try:
        # Import and call WiFi GUI in a very controlled way
        import tce_system_net
        
        # Show immediate feedback
        progress = wx.ProgressDialog(
            _("Network Settings"),
            _("Loading WiFi interface (5s timeout)..."),
            maximum=100,
            parent=parent,
            style=wx.PD_AUTO_HIDE | wx.PD_APP_MODAL
        )
        
        result = [None]
        exception_occurred = [False]
        
        def wifi_thread():
            try:
                result[0] = tce_system_net.show_wifi_gui(parent)
            except Exception as e:
                exception_occurred[0] = True
                print(f"Exception in WiFi thread: {e}")
        
        # Start thread
        thread = threading.Thread(target=wifi_thread, daemon=True)
        thread.start()
        
        # Wait with progress updates
        for i in range(50):
            if watchdog_triggered[0]:
                break
            if not thread.is_alive():
                break
            
            progress.Update(i * 2, f"Loading... ({i/10:.1f}s)")
            time.sleep(0.1)
        
        # Cancel watchdog if successful
        if not watchdog_triggered[0] and not thread.is_alive():
            watchdog.cancel()
            progress.Update(100, _("Ready!"))
            wx.CallLater(200, progress.Destroy)
            
            if exception_occurred[0]:
                record_wifi_failure()
            
            _wifi_gui_active = False
            return result[0]
        else:
            # Timeout occurred
            progress.Destroy()
            if not watchdog_triggered[0]:
                watchdog.cancel()
                record_wifi_failure()
            
            _wifi_gui_active = False
            return None
            
    except Exception as e:
        watchdog.cancel()
        _wifi_gui_active = False
        record_wifi_failure()
        
        print(f"Critical error in safe WiFi wrapper: {e}")
        try:
            wx.MessageBox(
                _("Critical error loading WiFi interface: {}").format(str(e)),
                _("WiFi Error"),
                wx.OK | wx.ICON_ERROR
            )
        except:
            pass
        return None

def get_wifi_status_message():
    """Get current WiFi protection status message"""
    global _wifi_gui_failed_count, _last_failure_time
    
    if _wifi_gui_failed_count == 0:
        return "WiFi interface: Ready"
    
    time_since_failure = time.time() - _last_failure_time
    cooldown_remaining = max(0, FAILURE_COOLDOWN - time_since_failure)
    
    if cooldown_remaining > 0:
        return f"WiFi interface: Cooling down ({cooldown_remaining:.0f}s remaining)"
    else:
        return "WiFi interface: Ready (recovered)"