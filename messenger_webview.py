# -*- coding: utf-8 -*-
"""
Facebook Messenger WebView integration for Titan IM
Uses wx.html2.WebView instead of Selenium for better performance and accessibility
"""

import wx
import wx.html2
import wx.lib.dialogs
import threading
import time
import os
import platform
from sound import play_sound
from translation import set_language
from settings import get_setting, SETTINGS_FILE_PATH
import accessible_output3.outputs.auto

# Initialize translation
_ = set_language(get_setting('language', 'pl'))

# TTS speaker
speaker = accessible_output3.outputs.auto.Auto()

def get_messenger_cookies_dir():
    """Get the directory for storing Messenger cookies and user data - same as Titan config"""
    # Use the same base directory as settings.ini
    titan_config_dir = os.path.dirname(SETTINGS_FILE_PATH)
    cookies_dir = os.path.join(titan_config_dir, 'IM COOKIES', 'Messenger')
    
    # Create directory if it doesn't exist
    os.makedirs(cookies_dir, exist_ok=True)
    
    return cookies_dir

def get_messenger_user_data_dir():
    """Get the user data directory for WebView2"""
    cookies_dir = get_messenger_cookies_dir()
    user_data_dir = os.path.join(cookies_dir, 'WebView2_UserData')
    
    # Create directory if it doesn't exist
    os.makedirs(user_data_dir, exist_ok=True)
    
    return user_data_dir

def clear_messenger_cookies():
    """Clear all stored Messenger cookies and user data"""
    try:
        import shutil
        cookies_dir = get_messenger_cookies_dir()
        
        if os.path.exists(cookies_dir):
            shutil.rmtree(cookies_dir)
            os.makedirs(cookies_dir, exist_ok=True)
            return True
    except Exception as e:
        print(f"Error clearing cookies: {e}")
        return False
    
    return False

class MessengerWebViewFrame(wx.Frame):
    def __init__(self, parent=None):
        super().__init__(parent, title=_("Facebook Messenger - Titan IM"), size=(1000, 700))
        
        self.messenger_loaded = False
        self.messenger_logged_in = False
        self.message_callbacks = []
        self.status_callbacks = []
        self.notification_timer = None
        self.typing_timer = None
        self.last_typing_user = None
        self.last_message_count = 0
        self.last_activity_check = 0
        
        # Notification anti-spam mechanism
        self.last_notification_time = 0
        self.last_notification_count = 0
        self.notification_cooldown = 5.0  # 5 seconds cooldown between notifications
        
        # Voice call state
        self.is_call_active = False
        self.current_call_user = None
        self.call_start_time = None
        self.call_type = None  # 'incoming' or 'outgoing'
        self.call_callbacks = []
        
        self.setup_ui()
        self.setup_notification_monitoring()
        self.Centre()
        
        # Don't play welcome sound yet - wait until logged in
        
        # Load Messenger
        wx.CallAfter(self.load_messenger)
    
    def setup_ui(self):
        """Setup the user interface"""
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Toolbar
        toolbar = wx.Panel(panel)
        toolbar_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Navigation buttons
        self.back_btn = wx.Button(toolbar, label=_("Wstecz"))
        self.forward_btn = wx.Button(toolbar, label=_("Dalej"))
        self.refresh_btn = wx.Button(toolbar, label=_("Refresh"))
        self.home_btn = wx.Button(toolbar, label=_("Messenger"))
        
        # Bind toolbar events
        self.back_btn.Bind(wx.EVT_BUTTON, self.on_back)
        self.forward_btn.Bind(wx.EVT_BUTTON, self.on_forward)
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        self.home_btn.Bind(wx.EVT_BUTTON, self.on_home)
        
        # URL display (read-only)
        self.url_display = wx.TextCtrl(toolbar, style=wx.TE_READONLY)
        self.url_display.SetValue("https://www.messenger.com")
        
        toolbar_sizer.Add(self.back_btn, 0, wx.ALL, 5)
        toolbar_sizer.Add(self.forward_btn, 0, wx.ALL, 5)
        toolbar_sizer.Add(self.refresh_btn, 0, wx.ALL, 5)
        toolbar_sizer.Add(self.home_btn, 0, wx.ALL, 5)
        toolbar_sizer.Add(self.url_display, 1, wx.ALL | wx.EXPAND, 5)
        
        toolbar.SetSizer(toolbar_sizer)
        main_sizer.Add(toolbar, 0, wx.EXPAND)
        
        # WebView
        try:
            # Configure WebView with custom user data directory
            user_data_dir = get_messenger_user_data_dir()
            print(f"Using WebView user data directory: {user_data_dir}")
            
            # Create WebView with custom backend options if supported
            try:
                # Configure WebView2 with media permissions
                self.configure_webview2_environment()
                
                # Try to create WebView with custom user data directory
                if hasattr(wx.html2.WebView, 'NewWithBackend'):
                    # For newer versions of wxPython that support backend configuration
                    backend = wx.html2.WebViewBackendEdge
                    self.webview = wx.html2.WebView.NewWithBackend(panel, backend=backend)
                else:
                    # Standard WebView creation
                    self.webview = wx.html2.WebView.New(panel)
            except:
                # Fallback to standard WebView
                self.webview = wx.html2.WebView.New(panel)
            
            if self.webview:
                # Enable developer tools
                self.webview.EnableAccessToDevTools(True)
                
                # Configure WebView2 permissions for media access
                self.setup_webview_permissions()
                
                # Try to set user data folder for WebView2 (if supported)
                try:
                    # This is experimental - WebView2 user data configuration
                    if hasattr(self.webview, 'SetUserDataFolder'):
                        self.webview.SetUserDataFolder(user_data_dir)
                        print(f"✓ Set WebView user data folder: {user_data_dir}")
                    elif hasattr(self.webview, 'SetUserDataDirectory'):
                        self.webview.SetUserDataDirectory(user_data_dir)  
                        print(f"✓ Set WebView user data directory: {user_data_dir}")
                except Exception as e:
                    print(f"Note: Could not set custom user data directory: {e}")
                    print("Using default WebView2 user data location")
                
                # Bind WebView events
                self.webview.Bind(wx.html2.EVT_WEBVIEW_NAVIGATING, self.on_navigating)
                self.webview.Bind(wx.html2.EVT_WEBVIEW_LOADED, self.on_page_loaded)
                self.webview.Bind(wx.html2.EVT_WEBVIEW_TITLE_CHANGED, self.on_title_changed)
                self.webview.Bind(wx.html2.EVT_WEBVIEW_ERROR, self.on_webview_error)
                
                # Key bindings for accessibility
                self.webview.Bind(wx.EVT_CHAR_HOOK, self.on_webview_key)
                
                main_sizer.Add(self.webview, 1, wx.EXPAND)
            else:
                self.show_webview_error()
                return
                
        except Exception as e:
            print(f"WebView initialization error: {e}")
            self.show_webview_error()
            return
        
        panel.SetSizer(main_sizer)
        
        # Status bar
        self.CreateStatusBar()
        self.SetStatusText(_("Loading Facebook Messenger..."))
        
        # Bind close event
        self.Bind(wx.EVT_CLOSE, self.on_close)
        
        # Create menu bar after all methods are defined
        wx.CallAfter(self.create_menu_bar)
        wx.CallAfter(self.complete_voice_menu)
    
    def show_webview_error(self):
        """Show error when WebView is not available"""
        error_panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        error_text = wx.StaticText(error_panel, label=_(
            "WebView is not available on this system.\n\n"
            "Possible solutions:\n"
            "• Zaktualizuj wxPython: pip install -U wxPython\n"
            "• Zainstaluj Microsoft Edge WebView2 Runtime\n"
            "• Check if your system supports WebView2"
        ))
        
        close_btn = wx.Button(error_panel, wx.ID_CLOSE, _("Zamknij"))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        
        sizer.Add(error_text, 1, wx.ALL | wx.CENTER, 20)
        sizer.Add(close_btn, 0, wx.ALL | wx.CENTER, 10)
        
        error_panel.SetSizer(sizer)
        
        # Speak error
        speaker.speak(_("WebView is not available"))
    
    def create_menu_bar(self):
        """Create menu bar"""
        menubar = wx.MenuBar()
        
        # Messenger menu
        messenger_menu = wx.Menu()
        
        refresh_item = messenger_menu.Append(wx.ID_ANY, _("Refresh\tF5"), _("Refresh Messenger page"))
        messenger_menu.AppendSeparator()
        
        zoom_in_item = messenger_menu.Append(wx.ID_ANY, _("Zoom In\tCtrl++"), _("Zoom in page"))
        zoom_out_item = messenger_menu.Append(wx.ID_ANY, _("Zoom Out\tCtrl+-"), _("Zoom out page"))
        zoom_reset_item = messenger_menu.Append(wx.ID_ANY, _("Reset Zoom\tCtrl+0"), _("Reset zoom level"))
        
        messenger_menu.AppendSeparator()
        
        devtools_item = messenger_menu.Append(wx.ID_ANY, _("Developer Tools\tF12"), _("Open developer tools"))
        
        messenger_menu.AppendSeparator()
        
        # Cookie management
        cookies_menu = wx.Menu()
        show_cookies_dir_item = cookies_menu.Append(wx.ID_ANY, _("Pokaż folder cookies"), _("Otwórz folder z danymi użytkownika"))
        clear_cookies_item = cookies_menu.Append(wx.ID_ANY, _("Wyczyść cookies"), _("Usuń wszystkie zapisane dane logowania"))
        
        messenger_menu.AppendSubMenu(cookies_menu, _("Zarządzanie cookies"))
        
        messenger_menu.AppendSeparator()
        
        close_item = messenger_menu.Append(wx.ID_EXIT, _("Zamknij\tAlt+F4"), _("Zamknij Messenger"))
        
        # Bind menu events
        self.Bind(wx.EVT_MENU, self.on_refresh, refresh_item)
        self.Bind(wx.EVT_MENU, self.on_zoom_in, zoom_in_item)
        self.Bind(wx.EVT_MENU, self.on_zoom_out, zoom_out_item)
        self.Bind(wx.EVT_MENU, self.on_zoom_reset, zoom_reset_item)
        self.Bind(wx.EVT_MENU, self.on_dev_tools, devtools_item)
        self.Bind(wx.EVT_MENU, self.on_show_cookies_dir, show_cookies_dir_item)
        self.Bind(wx.EVT_MENU, self.on_clear_cookies, clear_cookies_item)
        self.Bind(wx.EVT_MENU, self.on_close, close_item)
        
        menubar.Append(messenger_menu, _("Messenger"))
        
        # View menu
        view_menu = wx.Menu()
        
        self.notifications_item = view_menu.AppendCheckItem(wx.ID_ANY, _("Powiadomienia dźwiękowe"), _("Włącz powiadomienia dźwiękowe"))
        self.notifications_item.Check(True)
        
        self.tts_item = view_menu.AppendCheckItem(wx.ID_ANY, _("Odczytywanie TTS"), _("Włącz odczytywanie przez TTS"))
        self.tts_item.Check(True)
        
        view_menu.AppendSeparator()
        
        focus_chat_item = view_menu.Append(wx.ID_ANY, _("Fokus na czat\tCtrl+M"), _("Ustaw fokus na obszar czatu"))
        
        self.Bind(wx.EVT_MENU, self.on_focus_chat, focus_chat_item)
        
        menubar.Append(view_menu, _("Widok"))
        
        # Voice calls menu
        voice_menu = wx.Menu()
        
        self.voice_enabled_item = voice_menu.AppendCheckItem(wx.ID_ANY, _("Włącz połączenia głosowe"), _("Włącz obsługę połączeń głosowych"))
        self.voice_enabled_item.Check(True)
        
        voice_menu.AppendSeparator()
        
        self.call_status_item = voice_menu.Append(wx.ID_ANY, _("Status połączenia"), _("Pokaż status aktualnego połączenia"))
        self.call_status_item.Enable(False)
        
        end_call_item = voice_menu.Append(wx.ID_ANY, _("Zakończ połączenie\tCtrl+E"), _("Zakończ aktywne połączenie głosowe"))
        
        self.Bind(wx.EVT_MENU, self.on_show_call_status, self.call_status_item)
        self.Bind(wx.EVT_MENU, self.on_end_call, end_call_item)
        
        # Test and debug items will be added after all methods are defined
        voice_menu.AppendSeparator()
        
        # Store menu reference for later
        self.voice_menu = voice_menu
        
        menubar.Append(voice_menu, _("Połączenia"))
        
        self.SetMenuBar(menubar)
    
    def complete_voice_menu(self):
        """Complete voice menu with test and debug items after all methods are defined"""
        if not hasattr(self, 'voice_menu'):
            return
        
        try:
            test_incoming_item = self.voice_menu.Append(wx.ID_ANY, _("Test dźwięku przychodzącego"), _("Przetestuj dźwięk przychodzącego połączenia"))
            test_outgoing_item = self.voice_menu.Append(wx.ID_ANY, _("Test dźwięku wychodzącego"), _("Przetestuj dźwięk wychodzącego połączenia"))
            test_connected_item = self.voice_menu.Append(wx.ID_ANY, _("Test dźwięku nawiązania"), _("Przetestuj dźwięk nawiązanego połączenia"))
            test_ended_item = self.voice_menu.Append(wx.ID_ANY, _("Test dźwięku zakończenia"), _("Przetestuj dźwięk zakończenia połączenia"))
            
            debug_voice_item = self.voice_menu.Append(wx.ID_ANY, _("Debug połączeń głosowych"), _("Pokaż informacje debug o połączeniach"))
            
            self.Bind(wx.EVT_MENU, self.on_test_incoming_sound, test_incoming_item)
            self.Bind(wx.EVT_MENU, self.on_test_outgoing_sound, test_outgoing_item)
            self.Bind(wx.EVT_MENU, self.on_test_connected_sound, test_connected_item)
            self.Bind(wx.EVT_MENU, self.on_test_ended_sound, test_ended_item)
            self.Bind(wx.EVT_MENU, self.on_debug_voice, debug_voice_item)
            
            print("✓ Voice menu completed with test and debug items")
            
        except Exception as e:
            print(f"Error completing voice menu: {e}")
    
    def setup_webview_permissions(self):
        """Setup WebView2 permissions for camera and microphone access"""
        try:
            print("Setting up WebView2 media permissions...")
            
            # Method 1: Try to configure via WebView2 environment settings
            # This might not be directly available in wx.html2.WebView, but we can try
            if hasattr(self.webview, 'GetCoreWebView2'):
                try:
                    core = self.webview.GetCoreWebView2()
                    if core and hasattr(core, 'Settings'):
                        settings = core.Settings
                        if hasattr(settings, 'IsGeneralAutofillEnabled'):
                            # This indicates we have WebView2 settings access
                            print("✓ WebView2 core settings accessible")
                            
                            # Try to set media permissions
                            if hasattr(settings, 'AreDefaultScriptDialogsEnabled'):
                                settings.AreDefaultScriptDialogsEnabled = True
                            if hasattr(settings, 'AreWebMessageEnabled'):
                                settings.AreWebMessageEnabled = True
                                
                except Exception as settings_error:
                    print(f"WebView2 settings method failed: {settings_error}")
            
            # Method 2: JavaScript-based permission handling
            wx.CallLater(3000, self.setup_javascript_permissions)
            
            print("✓ WebView2 permissions setup initiated")
            
        except Exception as e:
            print(f"WebView2 permissions setup error: {e}")
    
    def setup_javascript_permissions(self):
        """Setup JavaScript-based permission handling"""
        if not hasattr(self, 'webview') or not self.webview:
            return
            
        try:
            # Inject JavaScript to handle permissions
            permission_script = """
            (function() {
                console.log('TITAN: Setting up media permissions...');
                
                // Store original permissions API
                const originalQuery = navigator.permissions ? navigator.permissions.query : null;
                
                // Override permissions query to grant media permissions
                if (navigator.permissions) {
                    navigator.permissions.query = function(permissionDesc) {
                        console.log('TITAN: Permission requested:', permissionDesc);
                        
                        // Auto-grant camera and microphone permissions
                        if (permissionDesc.name === 'camera' || 
                            permissionDesc.name === 'microphone' ||
                            permissionDesc.name === 'audiocapture' ||
                            permissionDesc.name === 'videocapture') {
                            
                            console.log('TITAN: Auto-granting media permission:', permissionDesc.name);
                            
                            return Promise.resolve({
                                state: 'granted',
                                onchange: null
                            });
                        }
                        
                        // Use original query for other permissions
                        if (originalQuery) {
                            return originalQuery.call(this, permissionDesc);
                        }
                        
                        // Default fallback
                        return Promise.resolve({
                            state: 'granted',
                            onchange: null
                        });
                    };
                }
                
                // Override getUserMedia to ensure it works
                if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
                    const originalGetUserMedia = navigator.mediaDevices.getUserMedia;
                    
                    navigator.mediaDevices.getUserMedia = function(constraints) {
                        console.log('TITAN: getUserMedia called with constraints:', constraints);
                        
                        // Ensure the request goes through
                        return originalGetUserMedia.call(this, constraints)
                            .then(stream => {
                                console.log('TITAN: Media stream obtained successfully:', stream);
                                return stream;
                            })
                            .catch(error => {
                                console.error('TITAN: getUserMedia failed:', error);
                                
                                // Try to provide helpful error info
                                if (error.name === 'NotAllowedError') {
                                    console.error('TITAN: Media access denied - check browser permissions');
                                } else if (error.name === 'NotFoundError') {
                                    console.error('TITAN: No media devices found');
                                } else if (error.name === 'NotReadableError') {
                                    console.error('TITAN: Media device in use by another application');
                                }
                                
                                throw error;
                            });
                    };
                }
                
                // Set a flag to indicate permissions are configured
                window.titanMediaPermissionsConfigured = true;
                console.log('TITAN: Media permissions configuration complete');
                
            })();
            """
            
            result = self.webview.RunScript(permission_script)
            print("✓ JavaScript media permissions script injected")
            
        except Exception as e:
            print(f"JavaScript permissions setup error: {e}")
    
    def configure_webview2_environment(self):
        """Configure WebView2 environment variables and settings"""
        try:
            print("Configuring WebView2 environment...")
            
            # Set environment variables for WebView2 to allow media access
            import os
            
            # These might help with permissions
            os.environ.setdefault('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', 
                '--allow-running-insecure-content '
                '--disable-web-security '
                '--use-fake-ui-for-media-stream '
                '--use-fake-device-for-media-stream '
                '--allow-file-access-from-files '
                '--disable-features=VizDisplayCompositor '
                '--enable-media-stream '
                '--enable-usermedia-screen-capturing'
            )
            
            # User data directory with permissions
            user_data_dir = get_messenger_user_data_dir()
            
            # Create preferences file for automatic media permissions
            preferences_dir = os.path.join(user_data_dir, 'Default')
            os.makedirs(preferences_dir, exist_ok=True)
            
            preferences_file = os.path.join(preferences_dir, 'Preferences')
            
            # WebView2 preferences for media permissions
            preferences = {
                "profile": {
                    "content_settings": {
                        "exceptions": {
                            "media_stream_mic": {
                                "https://www.messenger.com:443,*": {
                                    "last_modified": "13347000000000000",
                                    "setting": 1
                                }
                            },
                            "media_stream_camera": {
                                "https://www.messenger.com:443,*": {
                                    "last_modified": "13347000000000000", 
                                    "setting": 1
                                }
                            }
                        }
                    },
                    "default_content_setting_values": {
                        "media_stream_mic": 1,
                        "media_stream_camera": 1
                    }
                }
            }
            
            # Write preferences only if file doesn't exist to avoid overriding user settings
            if not os.path.exists(preferences_file):
                try:
                    import json
                    with open(preferences_file, 'w', encoding='utf-8') as f:
                        json.dump(preferences, f, indent=2)
                    print(f"✓ Created WebView2 preferences with media permissions: {preferences_file}")
                except Exception as pref_error:
                    print(f"Could not create preferences file: {pref_error}")
            else:
                print(f"✓ WebView2 preferences file already exists: {preferences_file}")
                
            print("✓ WebView2 environment configured for media access")
            
        except Exception as e:
            print(f"WebView2 environment configuration error: {e}")
    
    def check_media_permissions(self):
        """Check if media permissions are working"""
        if not hasattr(self, 'webview') or not self.webview:
            return
            
        try:
            permission_check_script = """
            (function() {
                var result = {
                    hasGetUserMedia: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
                    hasPermissionsAPI: !!navigator.permissions,
                    titanConfigured: !!window.titanMediaPermissionsConfigured,
                    userAgent: navigator.userAgent,
                    mediaDevices: !!navigator.mediaDevices,
                    protocol: window.location.protocol
                };
                
                // Test permission check for microphone
                if (navigator.permissions) {
                    navigator.permissions.query({name: 'microphone'})
                        .then(permissionStatus => {
                            console.log('TITAN: Microphone permission status:', permissionStatus.state);
                            result.micPermission = permissionStatus.state;
                        })
                        .catch(err => {
                            console.log('TITAN: Microphone permission query failed:', err);
                            result.micPermissionError = err.message;
                        });
                        
                    navigator.permissions.query({name: 'camera'})
                        .then(permissionStatus => {
                            console.log('TITAN: Camera permission status:', permissionStatus.state);
                            result.cameraPermission = permissionStatus.state;
                        })
                        .catch(err => {
                            console.log('TITAN: Camera permission query failed:', err);
                            result.cameraPermissionError = err.message;
                        });
                }
                
                // Test getUserMedia availability
                if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
                    console.log('TITAN: getUserMedia is available');
                    result.getUserMediaAvailable = true;
                } else {
                    console.log('TITAN: getUserMedia is NOT available');
                    result.getUserMediaAvailable = false;
                }
                
                console.log('TITAN: Media permissions check result:', result);
                return JSON.stringify(result);
            })();
            """
            
            result_str = self.webview.RunScript(permission_check_script)
            if result_str:
                import json
                
                # Handle WebView returning tuple
                if isinstance(result_str, tuple) and len(result_str) >= 2:
                    success, actual_result = result_str
                    if success:
                        result_str = actual_result
                    else:
                        print("❌ Media permission check script failed")
                        return
                
                result = json.loads(result_str)
                
                print(f"📱 Media capabilities check:")
                print(f"  - getUserMedia available: {result.get('getUserMediaAvailable', False)}")
                print(f"  - Permissions API: {result.get('hasPermissionsAPI', False)}")
                print(f"  - Titan configured: {result.get('titanConfigured', False)}")
                print(f"  - Protocol: {result.get('protocol', 'unknown')}")
                print(f"  - MediaDevices: {result.get('mediaDevices', False)}")
                
                if result.get('micPermission'):
                    print(f"  - Microphone: {result['micPermission']}")
                if result.get('cameraPermission'):
                    print(f"  - Camera: {result['cameraPermission']}")
                    
                if result.get('protocol') != 'https:':
                    print("⚠️  WARNING: Not using HTTPS - media access may be restricted")
                    
                if not result.get('getUserMediaAvailable'):
                    print("❌ getUserMedia not available - voice calls will not work")
                else:
                    print("✅ Media APIs appear to be available")
                    
        except Exception as e:
            print(f"Media permission check error: {e}")
    
    def load_messenger(self):
        """Load Facebook Messenger"""
        if hasattr(self, 'webview') and self.webview:
            # Play connecting sound like in Telegram
            play_sound('system/connecting.ogg')
            print("Connecting to Messenger...")
            
            # TTS announcement if available
            if hasattr(self, 'tts_item') and self.tts_item and self.tts_item.IsChecked():
                speaker.speak(_("Łączenie z Messenger"))
            else:
                # Fallback TTS if menu not ready yet
                speaker.speak(_("Łączenie z Messenger"))
            
            self.webview.LoadURL("https://www.messenger.com")
    
    def on_navigating(self, event):
        """Handle page navigation start"""
        url = event.GetURL()
        self.url_display.SetValue(url)
        self.SetStatusText(_("Ładowanie..."))
        
        
        # TTS announcement
        if hasattr(self, 'tts_item') and self.tts_item and self.tts_item.IsChecked():
            speaker.speak(_("Ładowanie strony"))
    
    def on_page_loaded(self, event):
        """Handle page loaded"""
        self.SetStatusText(_("Strona załadowana"))
        self.messenger_loaded = True
        
        # Play connection success sound like in Telegram
        play_sound('titannet/titannet_success.ogg')
        
        # Get page title
        title = self.webview.GetCurrentTitle()
        if title:
            self.SetTitle(f"{title} - Titan IM")
            
            # TTS announcement
            if hasattr(self, 'tts_item') and self.tts_item and self.tts_item.IsChecked():
                speaker.speak(_("Załadowano {}").format(title))
        
        # Set focus to webview
        self.webview.SetFocus()
        
        # Initialize notification monitoring after loading
        if "messenger.com" in self.webview.GetCurrentURL():
            self.start_notification_monitoring()
            # Check if user is already logged in
            wx.CallLater(3000, self.check_login_status)
            # Setup media permissions
            wx.CallLater(4000, self.setup_javascript_permissions)
            # Setup voice call monitoring
            wx.CallLater(5000, self.setup_voice_call_monitoring)
            # Check media permissions
            wx.CallLater(6000, self.check_media_permissions)
    
    def on_title_changed(self, event):
        """Handle title change"""
        title = event.GetString()
        
        # Check for new message notifications in title and update window title like Telegram
        if "(" in title and ")" in title:
            import re
            match = re.search(r'\((\d+)\)', title)
            if match:
                count = int(match.group(1))
                if count > 0:
                    # Show unread count in window title like Telegram
                    self.SetTitle(f"[{count}] Facebook Messenger - Titan IM")
                    
                    # Trigger notification if enabled
                    if self.notifications_item.IsChecked():
                        self.on_notification_detected(title, count)
                else:
                    # No unread messages
                    self.SetTitle("Facebook Messenger - Titan IM")
            else:
                self.SetTitle(f"{title} - Titan IM")
        else:
            # No unread count in title
            self.SetTitle(f"{title} - Titan IM")
    
    def on_webview_error(self, event):
        """Handle WebView errors"""
        url = event.GetURL()
        error = event.GetString()
        
        print(f"WebView error loading {url}: {error}")
        self.SetStatusText(_("Błąd ładowania strony"))

        # Play error sound
        play_sound('core/error.ogg')

        # TTS error announcement
        if self.tts_item.IsChecked():
            speaker.speak(_("Błąd ładowania strony"))
    
    def on_webview_key(self, event):
        """Handle keyboard events in WebView"""
        keycode = event.GetKeyCode()
        ctrl_down = event.ControlDown()
        
        # Handle custom shortcuts
        if keycode == wx.WXK_F5:
            self.on_refresh(event)
        elif keycode == wx.WXK_F12:
            self.on_dev_tools(event)
        elif ctrl_down and keycode == ord('M'):
            self.on_focus_chat(event)
        elif ctrl_down and keycode == ord('='):  # Ctrl++
            self.on_zoom_in(event)
        elif ctrl_down and keycode == ord('-'):  # Ctrl+-
            self.on_zoom_out(event)
        elif ctrl_down and keycode == ord('0'):  # Ctrl+0
            self.on_zoom_reset(event)
        elif ctrl_down and keycode == ord('E'):  # Ctrl+E
            self.on_end_call(event)
        else:
            event.Skip()  # Let WebView handle other keys
    
    # Toolbar event handlers
    def on_back(self, event):
        """Go back"""
        if hasattr(self, 'webview') and self.webview and self.webview.CanGoBack():
            self.webview.GoBack()
    
    def on_forward(self, event):
        """Go forward"""
        if hasattr(self, 'webview') and self.webview and self.webview.CanGoForward():
            self.webview.GoForward()
    
    def on_refresh(self, event):
        """Refresh page"""
        if hasattr(self, 'webview') and self.webview:
            print("🔄 Refreshing Messenger...")
            
            if hasattr(self, 'tts_item') and self.tts_item and self.tts_item.IsChecked():
                speaker.speak(_("Odświeżanie"))
            
            self.webview.Reload()
    
    def on_home(self, event):
        """Go to Messenger home"""
        if hasattr(self, 'webview') and self.webview:
            print("🏠 Going to Messenger home...")
            
            if hasattr(self, 'tts_item') and self.tts_item and self.tts_item.IsChecked():
                speaker.speak(_("Powrót do strony głównej"))
            
            self.webview.LoadURL("https://www.messenger.com")
    
    # Menu event handlers
    def on_zoom_in(self, event):
        """Zoom in"""
        if hasattr(self, 'webview') and self.webview:
            try:
                self.webview.SetZoomType(wx.html2.WEBVIEW_ZOOM_TYPE_LAYOUT)
                current_zoom = self.webview.GetZoomFactor()
                self.webview.SetZoomFactor(min(current_zoom + 0.1, 3.0))
            except:
                pass
    
    def on_zoom_out(self, event):
        """Zoom out"""
        if hasattr(self, 'webview') and self.webview:
            try:
                self.webview.SetZoomType(wx.html2.WEBVIEW_ZOOM_TYPE_LAYOUT)
                current_zoom = self.webview.GetZoomFactor()
                self.webview.SetZoomFactor(max(current_zoom - 0.1, 0.5))
            except:
                pass
    
    def on_zoom_reset(self, event):
        """Reset zoom"""
        if hasattr(self, 'webview') and self.webview:
            try:
                self.webview.SetZoomFactor(1.0)
            except:
                pass
    
    def on_dev_tools(self, event):
        """Open developer tools"""
        if hasattr(self, 'webview') and self.webview:
            try:
                # Try to run script to open dev tools
                self.webview.RunScript("console.log('Developer tools accessed from Titan IM');")
                # Note: Actual dev tools opening depends on WebView2 implementation
            except:
                wx.MessageBox(
                    _("Narzędzia deweloperskie mogą nie być dostępne w tej wersji WebView."),
                    _("Informacja"),
                    wx.OK | wx.ICON_INFORMATION
                )
    
    def check_login_status(self):
        """Check if user is logged in and play welcome sound"""
        if not hasattr(self, 'webview') or not self.webview or self.messenger_logged_in:
            return
        
        try:
            # Check for logged-in indicators with debug
            login_check_script = """
            (function() {
                console.log('=== TITAN IM LOGIN CHECK ===');
                
                // Look for various logged-in indicators
                var chatElements = document.querySelectorAll('[data-testid="conversation"], [role="main"], [aria-label*="Chat"], [aria-label*="Rozmowy"]');
                var loginElements = document.querySelectorAll('[type="email"], [type="password"], [name="email"], [name="pass"], [placeholder*="Email"], [placeholder*="Password"]');
                var messengerElements = document.querySelectorAll('[data-testid*="message"], [role="textbox"], [aria-label*="Message"]');
                var sendButtons = document.querySelectorAll('[data-testid="send"], [aria-label*="Send"], [aria-label*="Wyślij"]');
                
                console.log('Chat elements found:', chatElements.length);
                console.log('Login elements found:', loginElements.length); 
                console.log('Message elements found:', messengerElements.length);
                console.log('Send buttons found:', sendButtons.length);
                console.log('Current URL:', window.location.href);
                console.log('Page title:', document.title);
                
                // More comprehensive login detection
                var isLoggedIn = false;
                var reason = '';
                
                // Method 1: Look for messenger interface elements
                if (sendButtons.length > 0 || messengerElements.length > 0) {
                    isLoggedIn = true;
                    reason = 'found_messenger_interface';
                }
                // Method 2: URL check - logged in users are usually redirected
                else if (window.location.href.includes('/t/') || 
                         window.location.pathname !== '/' && 
                         !window.location.href.includes('login')) {
                    isLoggedIn = true;
                    reason = 'url_indicates_logged_in';
                }
                // Method 3: No login forms visible
                else if (loginElements.length === 0 && chatElements.length > 0) {
                    isLoggedIn = true;
                    reason = 'no_login_forms';
                }
                // Method 4: Title check
                else if (document.title.includes('Messenger') && 
                         !document.title.includes('Log') && 
                         loginElements.length === 0) {
                    isLoggedIn = true;
                    reason = 'title_indicates_messenger';
                }
                
                var result = {
                    status: isLoggedIn ? 'logged_in' : 'not_logged_in',
                    reason: reason,
                    chatElements: chatElements.length,
                    loginElements: loginElements.length,
                    messengerElements: messengerElements.length,
                    sendButtons: sendButtons.length,
                    url: window.location.href,
                    title: document.title
                };
                
                console.log('Login status result:', result);
                return JSON.stringify(result);
            })();
            """
            
            result_str = self.webview.RunScript(login_check_script)
            print(f"Login check raw result: {result_str}")
            
            if result_str:
                try:
                    import json
                    
                    # Handle WebView returning tuple (success, result) instead of just result
                    if isinstance(result_str, tuple) and len(result_str) >= 2:
                        success, actual_result = result_str
                        if success:
                            result_str = actual_result
                        else:
                            print(f"WebView script failed: {actual_result}")
                            return
                    
                    result = json.loads(result_str)
                    
                    print(f"Login detection: {result}")
                    
                    if result.get('status') == 'logged_in' and not self.messenger_logged_in:
                        self.messenger_logged_in = True
                        
                        print(f"✓ Messenger login successful! Reason: {result.get('reason')}")
                        
                        # Play welcome sound like in Telegram - but only now after login!
                        print("Playing welcome sound...")
                        play_sound('titannet/welcome to IM.ogg')
                        
                        # TTS announcement
                        if hasattr(self, 'tts_item') and self.tts_item.IsChecked():
                            speaker.speak(_("Połączono z Facebook Messenger"))
                        
                        # Update status
                        self.SetStatusText(_("Połączono z Messenger"))
                        
                        # Notify status callbacks about successful login
                        for callback in self.status_callbacks:
                            try:
                                wx.CallAfter(callback, 'logged_in', {"platform": "Facebook Messenger Web"})
                            except Exception as e:
                                print(f"Error calling status callback: {e}")
                        
                        # Start enhanced monitoring for typing and messages
                        self.start_enhanced_monitoring()
                        
                    elif result.get('status') == 'not_logged_in':
                        print(f"Not logged in yet. Debug: {result}")
                        # Keep checking periodically
                        wx.CallLater(3000, self.check_login_status)  # Check more frequently
                        
                except Exception as e:
                    print(f"Login result parsing error: {e}")
                    print(f"Raw result was: {result_str}")
            else:
                print("No result from login check script")
                wx.CallLater(3000, self.check_login_status)
                
        except Exception as e:
            print(f"Login check error: {e}")
            # Keep checking
            wx.CallLater(3000, self.check_login_status)
    
    def start_enhanced_monitoring(self):
        """Start enhanced monitoring for typing, message sending, etc."""
        if not hasattr(self, 'enhanced_timer'):
            self.enhanced_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self.check_activity, self.enhanced_timer)
            
        self.enhanced_timer.Start(1500)  # Check every 1.5 seconds for typing/activity
        
        # Also add simple fallback detection
        self.setup_simple_detection()
    
    def check_activity(self, event):
        """Check for typing indicators and message sending activity"""
        if not hasattr(self, 'webview') or not self.webview or not self.messenger_logged_in:
            return
            
        try:
            # Check for typing indicators and user activity with comprehensive debug
            activity_script = """
            (function() {
                // Initialize global state if needed
                if (!window.titanMessengerState) {
                    window.titanMessengerState = {
                        lastMessageCount: 0,
                        sendMonitored: false,
                        lastSendTime: 0,
                        debugMode: true
                    };
                }
                
                var state = window.titanMessengerState;
                var result = {
                    typing: false,
                    typingUser: '',
                    messageSent: false,
                    newMessage: false,
                    messageCount: 0,
                    debug: {}
                };
                
                if (state.debugMode) {
                    console.log('=== TITAN IM ACTIVITY CHECK ===');
                }
                
                // Method 1: Check for typing indicators (multiple selectors)
                var typingSelectors = [
                    '[aria-label*="typing"]',
                    '[data-testid*="typing"]', 
                    '[aria-label*="is typing"]',
                    '[aria-label*="pisze"]',
                    '.typing-indicator',
                    '[role="status"]'
                ];
                
                var typingIndicators = [];
                typingSelectors.forEach(selector => {
                    var elements = document.querySelectorAll(selector);
                    typingIndicators = typingIndicators.concat(Array.from(elements));
                });
                
                if (typingIndicators.length > 0) {
                    result.typing = true;
                    for (var i = 0; i < typingIndicators.length; i++) {
                        var elem = typingIndicators[i];
                        var text = elem.textContent || elem.getAttribute('aria-label') || '';
                        if (text.toLowerCase().includes('typing') || text.toLowerCase().includes('pisze')) {
                            result.typingUser = text.replace(/is typing|pisze/gi, '').trim();
                            if (state.debugMode) {
                                console.log('TYPING detected:', text);
                            }
                            break;
                        }
                    }
                }
                
                // Method 2: Count messages with multiple selectors
                var messageSelectors = [
                    '[data-testid*="message"]',
                    '[role="gridcell"]',
                    '[data-testid="message_text"]',
                    '.message',
                    '[aria-label*="message"]'
                ];
                
                var allMessages = [];
                messageSelectors.forEach(selector => {
                    var elements = document.querySelectorAll(selector);
                    allMessages = allMessages.concat(Array.from(elements));
                });
                
                // Remove duplicates
                var uniqueMessages = [];
                allMessages.forEach(msg => {
                    if (!uniqueMessages.includes(msg)) {
                        uniqueMessages.push(msg);
                    }
                });
                
                result.messageCount = uniqueMessages.length;
                result.debug.messageElements = uniqueMessages.length;
                
                // Method 3: Enhanced send button monitoring
                var sendSelectors = [
                    '[data-testid="send"]',
                    '[aria-label*="Send"]',
                    '[aria-label*="Wyślij"]',
                    '[type="submit"]',
                    'button[type="submit"]',
                    '.send-button'
                ];
                
                var sendButtons = [];
                sendSelectors.forEach(selector => {
                    var elements = document.querySelectorAll(selector);
                    sendButtons = sendButtons.concat(Array.from(elements));
                });
                
                result.debug.sendButtons = sendButtons.length;
                
                if (sendButtons.length > 0 && !state.sendMonitored) {
                    if (state.debugMode) {
                        console.log('Setting up send button monitoring. Found', sendButtons.length, 'buttons');
                    }
                    
                    sendButtons.forEach((btn, index) => {
                        btn.addEventListener('click', function(e) {
                            console.log('SEND BUTTON CLICKED!', index);
                            state.lastSendTime = Date.now();
                            window.titanMessageSent = true;
                        }, true); // Use capture phase
                        
                        btn.addEventListener('mousedown', function(e) {
                            console.log('SEND BUTTON MOUSEDOWN!', index);
                            state.lastSendTime = Date.now();
                            window.titanMessageSent = true;
                        }, true);
                    });
                    
                    state.sendMonitored = true;
                }
                
                // Method 4: Alternative send detection - monitor Enter key in text inputs
                var textInputs = document.querySelectorAll('[contenteditable="true"], textarea, input[type="text"]');
                textInputs.forEach(input => {
                    if (!input.titanEnterMonitored) {
                        input.addEventListener('keydown', function(e) {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                console.log('ENTER KEY SEND!');
                                state.lastSendTime = Date.now();
                                window.titanMessageSent = true;
                            }
                        });
                        input.titanEnterMonitored = true;
                    }
                });
                
                // Check if message was recently sent
                if (window.titanMessageSent && (Date.now() - state.lastSendTime < 3000)) {
                    result.messageSent = true;
                    window.titanMessageSent = false; // Clear flag
                    if (state.debugMode) {
                        console.log('MESSAGE SENT DETECTED!');
                    }
                }
                
                // Method 5: Detect new messages by count change
                if (state.lastMessageCount > 0 && result.messageCount > state.lastMessageCount) {
                    result.newMessage = true;
                    if (state.debugMode) {
                        console.log('NEW MESSAGE detected. Count:', state.lastMessageCount, '->', result.messageCount);
                    }
                }
                
                state.lastMessageCount = result.messageCount;
                
                // Debug info
                result.debug.typingIndicators = typingIndicators.length;
                result.debug.textInputs = textInputs.length;
                result.debug.lastSendTime = state.lastSendTime;
                result.debug.timeSinceLastSend = Date.now() - state.lastSendTime;
                
                if (state.debugMode && (result.typing || result.messageSent || result.newMessage)) {
                    console.log('Activity result:', result);
                }
                
                return JSON.stringify(result);
            })();
            """
            
            result_str = self.webview.RunScript(activity_script)
            if result_str:
                try:
                    import json
                    
                    # Handle WebView returning tuple (success, result) instead of just result
                    if isinstance(result_str, tuple) and len(result_str) >= 2:
                        success, actual_result = result_str
                        if success:
                            result_str = actual_result
                        else:
                            print(f"Activity script failed: {actual_result}")
                            return
                    
                    result = json.loads(result_str)
                    
                    # Debug output every 10 checks to avoid spam
                    if not hasattr(self, 'debug_counter'):
                        self.debug_counter = 0
                    self.debug_counter += 1
                    
                    if self.debug_counter % 10 == 0 or result.get('typing') or result.get('messageSent') or result.get('newMessage'):
                        print(f"Activity check {self.debug_counter}: {result}")
                    
                    # Handle typing indicators
                    if result.get('typing') and self.notifications_item.IsChecked():
                        typing_user = result.get('typingUser', 'Ktoś')
                        
                        # Only play typing sound if different user or enough time passed
                        if (not self.last_typing_user or 
                            self.last_typing_user != typing_user or 
                            not hasattr(self, 'last_typing_time') or
                            time.time() - self.last_typing_time > 3):
                            
                            print(f"🔤 TYPING DETECTED: {typing_user}")
                            
                            # Play typing sound like in Telegram
                            play_sound('titannet/typing.ogg')
                            
                            # TTS announcement
                            if self.tts_item.IsChecked():
                                if typing_user and typing_user != 'Ktoś':
                                    speaker.speak(_("{} pisze").format(typing_user))
                                else:
                                    speaker.speak(_("Ktoś pisze"))
                            
                            self.last_typing_user = typing_user
                            self.last_typing_time = time.time()
                    
                    # Handle message sent by user
                    if result.get('messageSent'):
                        print(f"📤 MESSAGE SENT DETECTED! Playing sound...")
                        
                        if self.notifications_item.IsChecked():
                            # Play message send sound like in Telegram
                            play_sound('titannet/message_send.ogg')
                            
                            # TTS announcement with stereo speech like WhatsApp
                            if self.tts_item.IsChecked():
                                try:
                                    from stereo_speech import get_stereo_speech
                                    stereo_speech = get_stereo_speech()
                                    
                                    if stereo_speech.is_stereo_enabled():
                                        # Use stereo speech for sent confirmation with lower pitch
                                        stereo_speech.speak(_("Message sent"), position=0.0, pitch_offset=-2, use_fallback=False)
                                    else:
                                        speaker.speak(_("Message sent"))
                                except ImportError:
                                    speaker.speak(_("Message sent"))
                                
                            print("✓ Wiadomość wysłana - odtworzono dźwięk message_send.ogg")
                        else:
                            print("⚠️ Notifications disabled - no sound played")
                    
                    # Handle new messages using the newMessage flag from JS
                    if result.get('newMessage'):
                        print(f"📨 NEW MESSAGE DETECTED! Playing sound...")
                        
                        if self.notifications_item.IsChecked():
                            play_sound('titannet/new_message.ogg')
                            
                            if self.tts_item.IsChecked():
                                speaker.speak(_("Nowa wiadomość"))
                                
                            print("✓ Nowa wiadomość - odtworzono dźwięk new_message.ogg")
                        else:
                            print("⚠️ Notifications disabled - no sound played")
                
                except Exception as e:
                    if "Expecting value: line 1 column 1 (char 0)" not in str(e):
                        print(f"Activity parsing error: {e}")
                        print(f"Raw result was: {result_str}")
                    
        except Exception as e:
            print(f"Activity check error: {e}")
    
    def setup_simple_detection(self):
        """Setup simple fallback detection methods"""
        print("Setting up simple fallback detection...")
        
        # Add simple JavaScript that runs immediately when page changes
        simple_script = """
        (function() {
            console.log('TITAN: Setting up simple detection...');
            
            // Very simple - monitor document for any changes
            if (!window.titanSimpleSetup) {
                // Monitor any key presses in the document
                document.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' && e.target.matches('[contenteditable="true"], textarea, input')) {
                        console.log('TITAN: Enter key detected in text field!');
                        window.titanSimpleMessageSent = true;
                        setTimeout(() => window.titanSimpleMessageSent = false, 3000);
                    }
                }, true);
                
                // Monitor clicks on any buttons that might be send buttons  
                document.addEventListener('click', function(e) {
                    var target = e.target;
                    var button = target.closest('button, [role="button"]');
                    if (button) {
                        var text = button.textContent || button.getAttribute('aria-label') || '';
                        if (text.toLowerCase().includes('send') || 
                            text.toLowerCase().includes('wyślij') ||
                            button.querySelector('svg')) {  // Many send buttons have SVG icons
                            console.log('TITAN: Send button clicked!', text);
                            window.titanSimpleMessageSent = true;
                            setTimeout(() => window.titanSimpleMessageSent = false, 3000);
                        }
                    }
                }, true);
                
                window.titanSimpleSetup = true;
                console.log('TITAN: Simple detection setup complete');
            }
        })();
        """
        
        def run_simple_setup():
            try:
                result = self.webview.RunScript(simple_script)
                # We don't need to handle the result, just run the script
                print("Simple detection setup script executed")
            except Exception as e:
                print(f"Simple setup script error: {e}")
        
        try:
            wx.CallLater(2000, run_simple_setup)
        except:
            pass
        
        # Start simple polling timer
        if not hasattr(self, 'simple_timer'):
            self.simple_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self.check_simple_flags, self.simple_timer)
            self.simple_timer.Start(1000)  # Check every second
    
    def check_simple_flags(self, event):
        """Check simple detection flags"""
        if not hasattr(self, 'webview') or not self.webview or not self.messenger_logged_in:
            return
        
        try:
            # Check simple flags
            simple_check = """
            (function() {
                var result = {
                    messageSent: !!window.titanSimpleMessageSent,
                    setup: !!window.titanSimpleSetup
                };
                
                if (result.messageSent) {
                    window.titanSimpleMessageSent = false; // Clear flag
                }
                
                return JSON.stringify(result);
            })();
            """
            
            result_str = self.webview.RunScript(simple_check)
            if result_str:
                import json
                
                # Handle WebView returning tuple (success, result) instead of just result
                if isinstance(result_str, tuple) and len(result_str) >= 2:
                    success, actual_result = result_str
                    if success:
                        result_str = actual_result
                    else:
                        print(f"Simple check script failed: {actual_result}")
                        return
                
                result = json.loads(result_str)
                
                if result.get('messageSent'):
                    print("🚀 SIMPLE DETECTION: Message sent!")
                    
                    if self.notifications_item.IsChecked():
                        play_sound('titannet/message_send.ogg')
                        print("✓ Simple detection - played message_send.ogg")
                        
                        if self.tts_item.IsChecked():
                            try:
                                from stereo_speech import get_stereo_speech
                                stereo_speech = get_stereo_speech()
                                
                                if stereo_speech.is_stereo_enabled():
                                    # Use stereo speech for sent confirmation with lower pitch
                                    stereo_speech.speak(_("Message sent"), position=0.0, pitch_offset=-2, use_fallback=False)
                                else:
                                    speaker.speak(_("Message sent"))
                            except ImportError:
                                speaker.speak(_("Message sent"))
                
                if not result.get('setup'):
                    # Re-setup if needed
                    wx.CallLater(1000, self.setup_simple_detection)
            
        except Exception as e:
            if "Expecting value: line 1 column 1 (char 0)" not in str(e):
                print(f"Simple check error: {e}")
    
    def setup_voice_call_monitoring(self):
        """Setup voice call detection and WebRTC integration"""
        if not hasattr(self, 'webview') or not self.webview or not self.messenger_logged_in:
            # Retry in 3 seconds if not logged in yet
            wx.CallLater(3000, self.setup_voice_call_monitoring)
            return
        
        print("Setting up voice call monitoring...")
        
        # Inject enhanced WebRTC and DOM monitoring JavaScript
        webrtc_script = """
        (function() {
            console.log('TITAN IM: Setting up enhanced voice call monitoring...');
            
            if (window.titanVoiceSetup) {
                console.log('Voice monitoring already setup');
                return;
            }
            
            // Store original functions
            const originalRTCPeerConnection = window.RTCPeerConnection;
            const originalGetUserMedia = navigator.mediaDevices ? navigator.mediaDevices.getUserMedia : null;
            
            // Track active calls and media streams
            window.titanCallState = {
                isCallActive: false,
                callType: null,
                remoteUser: null,
                callStartTime: null,
                peerConnection: null,
                mediaStreams: [],
                callUIVisible: false
            };
            
            // Monitor getUserMedia calls (indicates call starting)
            if (originalGetUserMedia) {
                navigator.mediaDevices.getUserMedia = function(...args) {
                    console.log('TITAN: getUserMedia called!', args);
                    
                    // Check if requesting audio (voice call)
                    const constraints = args[0];
                    if (constraints && constraints.audio) {
                        console.log('TITAN: Audio stream requested - call starting!');
                        window.titanCallState.callType = 'outgoing';
                        window.titanOutgoingCall = true;
                    }
                    
                    return originalGetUserMedia.apply(this, args).then(stream => {
                        console.log('TITAN: Media stream obtained:', stream);
                        window.titanCallState.mediaStreams.push(stream);
                        
                        // Monitor stream ending
                        stream.getTracks().forEach(track => {
                            track.addEventListener('ended', () => {
                                console.log('TITAN: Media track ended');
                                window.titanCallEnded = true;
                            });
                        });
                        
                        return stream;
                    });
                };
            }
            
            // Override RTCPeerConnection
            window.RTCPeerConnection = function(...args) {
                console.log('TITAN: RTCPeerConnection created!', args);
                const pc = new originalRTCPeerConnection(...args);
                
                window.titanCallState.peerConnection = pc;
                
                // Monitor all state changes
                pc.addEventListener('connectionstatechange', function() {
                    console.log('TITAN: Connection state:', pc.connectionState);
                    
                    switch(pc.connectionState) {
                        case 'connecting':
                            console.log('TITAN: Call connecting...');
                            window.titanCallConnecting = true;
                            break;
                        case 'connected':
                            console.log('TITAN: Call connected!');
                            window.titanCallState.isCallActive = true;
                            window.titanCallState.callStartTime = Date.now();
                            window.titanCallConnected = true;
                            break;
                        case 'disconnected':
                        case 'failed':
                        case 'closed':
                            console.log('TITAN: Call ended!');
                            if (window.titanCallState.isCallActive) {
                                window.titanCallState.isCallActive = false;
                                window.titanCallEnded = true;
                            }
                            break;
                    }
                });
                
                // Monitor ICE state
                pc.addEventListener('iceconnectionstatechange', function() {
                    console.log('TITAN: ICE state:', pc.iceConnectionState);
                    if (pc.iceConnectionState === 'connected' || pc.iceConnectionState === 'completed') {
                        if (!window.titanCallState.isCallActive) {
                            console.log('TITAN: ICE connected - call active!');
                            window.titanCallConnected = true;
                        }
                    }
                });
                
                // Monitor tracks (incoming media)
                pc.addEventListener('track', function(event) {
                    console.log('TITAN: Remote track received!', event);
                    if (!window.titanCallState.callType) {
                        window.titanCallState.callType = 'incoming';
                        window.titanIncomingCall = true;
                    }
                });
                
                // Monitor offers/answers
                const originalCreateOffer = pc.createOffer;
                pc.createOffer = function(...args) {
                    console.log('TITAN: Creating offer - outgoing call!');
                    window.titanCallState.callType = 'outgoing';
                    window.titanOutgoingCall = true;
                    return originalCreateOffer.apply(this, args);
                };
                
                const originalCreateAnswer = pc.createAnswer;
                pc.createAnswer = function(...args) {
                    console.log('TITAN: Creating answer - incoming call!');
                    window.titanCallState.callType = 'incoming';
                    window.titanIncomingCall = true;
                    return originalCreateAnswer.apply(this, args);
                };
                
                const originalSetRemoteDescription = pc.setRemoteDescription;
                pc.setRemoteDescription = function(description) {
                    console.log('TITAN: Setting remote description:', description.type);
                    if (description.type === 'offer') {
                        console.log('TITAN: Received offer - incoming call!');
                        window.titanIncomingCall = true;
                    }
                    return originalSetRemoteDescription.apply(this, arguments);
                };
                
                return pc;
            };
            
            // Copy static methods and properties
            Object.setPrototypeOf(window.RTCPeerConnection, originalRTCPeerConnection);
            Object.getOwnPropertyNames(originalRTCPeerConnection).forEach(name => {
                if (typeof originalRTCPeerConnection[name] === 'function') {
                    window.RTCPeerConnection[name] = originalRTCPeerConnection[name];
                }
            });
            
            // Enhanced DOM monitoring for call UI
            const observer = new MutationObserver(function(mutations) {
                mutations.forEach(function(mutation) {
                    mutation.addedNodes.forEach(function(node) {
                        if (node.nodeType === 1) {
                            // More comprehensive call UI detection
                            const callSelectors = [
                                '[aria-label*="call"]',
                                '[aria-label*="Call"]', 
                                '[aria-label*="voice"]',
                                '[aria-label*="Voice"]',
                                '[data-testid*="call"]',
                                '[data-testid*="voice"]',
                                '[class*="call"]',
                                '[class*="voice"]',
                                '[class*="rtc"]',
                                '.video-call',
                                '.voice-call',
                                '.call-container',
                                '.call-ui',
                                '[role="dialog"][aria-label*="call"]'
                            ];
                            
                            let callUIFound = false;
                            callSelectors.forEach(selector => {
                                try {
                                    const elements = node.querySelectorAll ? node.querySelectorAll(selector) : [];
                                    if (elements.length > 0) {
                                        console.log('TITAN: Call UI detected with selector:', selector, elements.length);
                                        callUIFound = true;
                                    }
                                } catch (e) {
                                    // Ignore selector errors
                                }
                            });
                            
                            // Check if the node itself matches call UI patterns
                            if (node.className && typeof node.className === 'string') {
                                if (node.className.includes('call') || node.className.includes('voice') || node.className.includes('rtc')) {
                                    console.log('TITAN: Call UI node detected:', node.className);
                                    callUIFound = true;
                                }
                            }
                            
                            // Check aria-label
                            if (node.getAttribute) {
                                const ariaLabel = node.getAttribute('aria-label');
                                if (ariaLabel && (ariaLabel.toLowerCase().includes('call') || ariaLabel.toLowerCase().includes('voice'))) {
                                    console.log('TITAN: Call UI via aria-label:', ariaLabel);
                                    callUIFound = true;
                                }
                            }
                            
                            if (callUIFound && !window.titanCallState.callUIVisible) {
                                console.log('TITAN: Call UI appeared!');
                                window.titanCallState.callUIVisible = true;
                                window.titanCallUIAppeared = true;
                            }
                        }
                    });
                    
                    // Monitor removed nodes for call UI disappearing
                    mutation.removedNodes.forEach(function(node) {
                        if (node.nodeType === 1) {
                            if (node.className && typeof node.className === 'string') {
                                if (node.className.includes('call') || node.className.includes('voice')) {
                                    console.log('TITAN: Call UI disappeared:', node.className);
                                    window.titanCallState.callUIVisible = false;
                                    window.titanCallUIDisappeared = true;
                                }
                            }
                        }
                    });
                });
            });
            
            // Start observing with more comprehensive options
            observer.observe(document.body, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['class', 'aria-label', 'data-testid']
            });
            
            // Also monitor clicks on potential call buttons
            document.addEventListener('click', function(event) {
                const target = event.target;
                const button = target.closest('button, [role="button"], [tabindex="0"]');
                
                if (button) {
                    const text = button.textContent || button.getAttribute('aria-label') || '';
                    const className = button.className || '';
                    
                    // Check for call-related button clicks
                    if (text.toLowerCase().includes('call') || 
                        text.toLowerCase().includes('voice') ||
                        className.includes('call') ||
                        className.includes('voice')) {
                        
                        console.log('TITAN: Call button clicked!', text, className);
                        window.titanCallButtonClicked = true;
                        
                        // If no call type set yet, assume outgoing
                        if (!window.titanCallState.callType) {
                            window.titanCallState.callType = 'outgoing';
                            window.titanOutgoingCall = true;
                        }
                    }
                }
            }, true);
            
            // Periodic check for call UI elements (fallback)
            setInterval(function() {
                const callElements = document.querySelectorAll(
                    '[aria-label*="End call"], [aria-label*="Mute"], [aria-label*="Video"], ' +
                    '.call-ui, .video-call, .voice-call, [data-testid*="call"], ' +
                    '[class*="call-container"], [class*="rtc-"]'
                );
                
                if (callElements.length > 0 && !window.titanCallState.callUIVisible) {
                    console.log('TITAN: Call UI detected via periodic check:', callElements.length);
                    window.titanCallState.callUIVisible = true;
                    window.titanCallUIAppeared = true;
                }
            }, 3000);
            
            window.titanVoiceSetup = true;
            window.titanVoiceObserver = observer;
            console.log('TITAN: Enhanced voice call monitoring setup complete!');
            
        })();
        """
        
        try:
            result = self.webview.RunScript(webrtc_script)
            print("✓ Voice call monitoring script injected")
            
            # Start voice call monitoring timer
            if not hasattr(self, 'voice_timer'):
                self.voice_timer = wx.Timer(self)
                self.Bind(wx.EVT_TIMER, self.check_voice_call_status, self.voice_timer)
                self.voice_timer.Start(2000)  # Check every 2 seconds
                
        except Exception as e:
            print(f"Voice setup error: {e}")
    
    def check_voice_call_status(self, event):
        """Check for voice call status changes"""
        if not hasattr(self, 'webview') or not self.webview or not self.voice_enabled_item.IsChecked():
            return
        
        try:
            call_check_script = """
            (function() {
                if (!window.titanVoiceSetup) return JSON.stringify({status: 'not_setup'});
                
                var result = {
                    isCallActive: window.titanCallState ? window.titanCallState.isCallActive : false,
                    callType: window.titanCallState ? window.titanCallState.callType : null,
                    callUIVisible: window.titanCallState ? window.titanCallState.callUIVisible : false,
                    events: {
                        connecting: !!window.titanCallConnecting,
                        connected: !!window.titanCallConnected,
                        incoming: !!window.titanIncomingCall,
                        outgoing: !!window.titanOutgoingCall,
                        ended: !!window.titanCallEnded,
                        buttonClicked: !!window.titanCallButtonClicked,
                        uiAppeared: !!window.titanCallUIAppeared,
                        uiDisappeared: !!window.titanCallUIDisappeared
                    },
                    debug: {
                        mediaStreams: window.titanCallState ? window.titanCallState.mediaStreams.length : 0,
                        hasConnection: !!(window.titanCallState && window.titanCallState.peerConnection)
                    }
                };
                
                // Clear event flags
                window.titanCallConnecting = false;
                window.titanCallConnected = false;
                window.titanIncomingCall = false;
                window.titanOutgoingCall = false;
                window.titanCallEnded = false;
                window.titanCallButtonClicked = false;
                window.titanCallUIAppeared = false;
                window.titanCallUIDisappeared = false;
                
                return JSON.stringify(result);
            })();
            """
            
            result_str = self.webview.RunScript(call_check_script)
            if result_str:
                import json
                
                # Handle WebView returning tuple
                if isinstance(result_str, tuple) and len(result_str) >= 2:
                    success, actual_result = result_str
                    if success:
                        result_str = actual_result
                    else:
                        return
                
                result = json.loads(result_str)
                events = result.get('events', {})
                debug_info = result.get('debug', {})
                
                # Debug output every 20 checks to reduce spam
                if not hasattr(self, 'voice_debug_counter'):
                    self.voice_debug_counter = 0
                self.voice_debug_counter += 1
                
                if self.voice_debug_counter % 20 == 0 or any(events.values()):
                    print(f"Voice check {self.voice_debug_counter}: {result}")
                
                # Handle call button clicked (early detection)
                if events.get('buttonClicked') and not self.is_call_active:
                    print("🔘 CALL BUTTON CLICKED!")
                    self.on_call_connecting()
                
                # Handle call UI appeared (visual confirmation of call starting)
                if events.get('uiAppeared') and not self.is_call_active:
                    print("🖼️ CALL UI APPEARED!")
                    # If we don't know the call type yet, UI appearance might indicate start
                    if not result.get('callType'):
                        self.on_call_connecting()
                
                # Handle call connecting
                if events.get('connecting') and not self.is_call_active:
                    print("🔄 CALL CONNECTING...")
                    self.on_call_connecting()
                
                # Handle incoming call
                if events.get('incoming') and not self.is_call_active:
                    print("📞 INCOMING CALL DETECTED!")
                    self.on_incoming_call()
                
                # Handle outgoing call
                if events.get('outgoing') and not self.is_call_active:
                    print("📞 OUTGOING CALL DETECTED!")
                    self.on_outgoing_call()
                
                # Handle call connected
                if events.get('connected') and not self.is_call_active:
                    print("✅ CALL CONNECTED!")
                    self.on_call_connected(result.get('callType'))
                
                # Handle call ended
                if events.get('ended') and self.is_call_active:
                    print("📴 CALL ENDED!")
                    self.on_call_ended()
                
                # Handle call UI disappeared (possible call end)
                if events.get('uiDisappeared') and self.is_call_active:
                    print("🖼️ CALL UI DISAPPEARED!")
                    # Give it a moment in case it's just UI refresh, then check if call really ended
                    wx.CallLater(3000, self.check_call_ended_by_ui)
                
        except Exception as e:
            if "'int' object has no attribute 'get'" not in str(e) and "Expecting value: line 1 column 1 (char 0)" not in str(e):
                print(f"Voice call check error: {e}")
    
    def check_call_ended_by_ui(self):
        """Check if call really ended when UI disappeared"""
        if not self.is_call_active:
            return
        
        try:
            # Check if call UI is still gone and no WebRTC connection
            check_script = """
            (function() {
                if (!window.titanCallState) return JSON.stringify({ended: true});
                
                var callElements = document.querySelectorAll(
                    '[aria-label*="End call"], [aria-label*="Mute"], [class*="call-ui"]'
                );
                
                var hasActiveConnection = false;
                if (window.titanCallState.peerConnection) {
                    var state = window.titanCallState.peerConnection.connectionState;
                    hasActiveConnection = (state === 'connected' || state === 'connecting');
                }
                
                return JSON.stringify({
                    callUIElements: callElements.length,
                    hasActiveConnection: hasActiveConnection,
                    ended: callElements.length === 0 && !hasActiveConnection
                });
            })();
            """
            
            result_str = self.webview.RunScript(check_script)
            if result_str:
                import json
                
                # Handle WebView returning tuple
                if isinstance(result_str, tuple) and len(result_str) >= 2:
                    success, actual_result = result_str
                    if success:
                        result_str = actual_result
                    else:
                        return
                
                result = json.loads(result_str)
                
                if result.get('ended'):
                    print("🔚 Confirmed call ended by UI check")
                    self.on_call_ended()
                else:
                    print(f"🔄 Call still active - UI elements: {result.get('callUIElements')}, Connection: {result.get('hasActiveConnection')}")
        
        except Exception as e:
            print(f"Call end check error: {e}")
    
    def on_call_connecting(self):
        """Handle call connecting"""
        if self.notifications_item.IsChecked():
            # Don't play sound yet, wait for connection
            pass
        
        if self.tts_item.IsChecked():
            speaker.speak(_("Łączenie..."))
    
    def on_incoming_call(self):
        """Handle incoming call detected"""
        self.current_call_user = "Nieznany kontakt"
        self.call_type = 'incoming'
        
        # Play incoming call sound like in Telegram
        if self.notifications_item.IsChecked():
            play_sound('titannet/ring_in.ogg')
            print("✓ Incoming call - played ring_in.ogg")
        
        if self.tts_item.IsChecked():
            speaker.speak(_("Przychodzące połączenie"))
        
        # Notify callbacks
        self._notify_call_event('incoming_call', {
            'user': self.current_call_user,
            'type': 'incoming'
        })
    
    def on_outgoing_call(self):
        """Handle outgoing call detected"""
        self.current_call_user = "Kontakt"
        self.call_type = 'outgoing'
        
        # Play outgoing call sound like in Telegram
        if self.notifications_item.IsChecked():
            play_sound('titannet/ring_out.ogg')
            print("✓ Outgoing call - played ring_out.ogg")
        
        if self.tts_item.IsChecked():
            speaker.speak(_("Dzwonię..."))
        
        # Notify callbacks
        self._notify_call_event('outgoing_call', {
            'user': self.current_call_user,
            'type': 'outgoing'
        })
    
    def on_call_connected(self, call_type=None):
        """Handle call connected"""
        import datetime
        self.is_call_active = True
        self.call_start_time = datetime.datetime.now()
        if call_type:
            self.call_type = call_type
        
        # Play call success sound like in Telegram
        if self.notifications_item.IsChecked():
            play_sound('titannet/callsuccess.ogg')
            print("✓ Call connected - played callsuccess.ogg")
        
        if self.tts_item.IsChecked():
            speaker.speak(_("Połączenie nawiązane"))
        
        # Enable call status menu
        if hasattr(self, 'call_status_item'):
            self.call_status_item.Enable(True)
        
        # Update status bar
        self.SetStatusText(_("Aktywne połączenie głosowe"))
        
        # Notify callbacks
        self._notify_call_event('call_connected', {
            'user': self.current_call_user,
            'type': self.call_type,
            'start_time': self.call_start_time.isoformat() if self.call_start_time else None
        })
    
    def on_call_ended(self):
        """Handle call ended"""
        if not self.is_call_active:
            return
        
        # Calculate duration
        call_duration = None
        if self.call_start_time:
            import datetime
            call_duration = datetime.datetime.now() - self.call_start_time
        
        # Play call end sound like in Telegram
        if self.notifications_item.IsChecked():
            play_sound('titannet/bye.ogg')
            print("✓ Call ended - played bye.ogg")
        
        if self.tts_item.IsChecked():
            if call_duration:
                minutes = int(call_duration.total_seconds() // 60)
                seconds = int(call_duration.total_seconds() % 60)
                duration_text = f"{minutes} minut {seconds} sekund" if minutes > 0 else f"{seconds} sekund"
                speaker.speak(_("Połączenie zakończone. Czas trwania: {}").format(duration_text))
            else:
                speaker.speak(_("Połączenie zakończone"))
        
        # Disable call status menu
        if hasattr(self, 'call_status_item'):
            self.call_status_item.Enable(False)
        
        # Reset call state
        self.is_call_active = False
        old_user = self.current_call_user
        self.current_call_user = None
        self.call_start_time = None
        self.call_type = None
        
        # Update status bar
        self.SetStatusText(_("Połączenie zakończone"))
        
        # Notify callbacks
        self._notify_call_event('call_ended', {
            'user': old_user,
            'duration': call_duration.total_seconds() if call_duration else 0
        })
    
    def on_end_call(self, event):
        """Handle end call menu item"""
        if not self.is_call_active:
            wx.MessageBox(_("Brak aktywnego połączenia"), _("Informacja"), wx.OK | wx.ICON_INFORMATION)
            return
        
        # Try to end the call via JavaScript
        try:
            end_call_script = """
            (function() {
                console.log('TITAN: Attempting to end call...');
                
                if (window.titanCallState && window.titanCallState.peerConnection) {
                    try {
                        window.titanCallState.peerConnection.close();
                        console.log('TITAN: PeerConnection closed');
                        return 'success';
                    } catch (e) {
                        console.log('TITAN: Error closing PeerConnection:', e);
                        return 'error: ' + e.message;
                    }
                }
                
                // Also try to find and click end call button
                var endButtons = document.querySelectorAll('[aria-label*="End call"], [aria-label*="Zakończ"], [data-testid*="end"], [class*="end-call"]');
                if (endButtons.length > 0) {
                    endButtons[0].click();
                    console.log('TITAN: Clicked end call button');
                    return 'clicked_button';
                }
                
                return 'no_method_found';
            })();
            """
            
            result = self.webview.RunScript(end_call_script)
            print(f"End call result: {result}")
            
        except Exception as e:
            print(f"Error ending call: {e}")
        
        # Force end call state locally if WebRTC doesn't respond
        wx.CallLater(2000, self.force_end_call)
    
    def force_end_call(self):
        """Force end call if automatic detection doesn't work"""
        if self.is_call_active:
            print("Force ending call...")
            self.on_call_ended()
    
    def on_show_call_status(self, event):
        """Show call status dialog"""
        if not self.is_call_active:
            wx.MessageBox(_("Brak aktywnego połączenia"), _("Status połączenia"), wx.OK | wx.ICON_INFORMATION)
            return
        
        # Calculate duration
        duration_text = _("Nieznany")
        if self.call_start_time:
            import datetime
            duration = datetime.datetime.now() - self.call_start_time
            minutes = int(duration.total_seconds() // 60)
            seconds = int(duration.total_seconds() % 60)
            duration_text = f"{minutes:02d}:{seconds:02d}"
        
        status_text = _(
            "Status połączenia głosowego:\n\n"
            "Kontakt: {}\n"
            "Typ: {}\n"
            "Czas trwania: {}\n"
            "Status: Aktywne"
        ).format(
            self.current_call_user or _("Nieznany"),
            _("Przychodzące") if self.call_type == 'incoming' else _("Wychodzące"),
            duration_text
        )
        
        wx.MessageBox(status_text, _("Status połączenia"), wx.OK | wx.ICON_INFORMATION)
    
    def on_test_incoming_sound(self, event):
        """Test incoming call sound"""
        play_sound('titannet/ring_in.ogg')
        if self.tts_item.IsChecked():
            speaker.speak(_("Test dźwięku przychodzącego połączenia"))
    
    def on_test_outgoing_sound(self, event):
        """Test outgoing call sound"""
        play_sound('titannet/ring_out.ogg')
        if self.tts_item.IsChecked():
            speaker.speak(_("Test dźwięku wychodzącego połączenia"))
    
    def on_test_connected_sound(self, event):
        """Test connected call sound"""
        play_sound('titannet/callsuccess.ogg')
        if self.tts_item.IsChecked():
            speaker.speak(_("Test dźwięku nawiązania połączenia"))
    
    def on_test_ended_sound(self, event):
        """Test ended call sound"""
        play_sound('titannet/bye.ogg')
        if self.tts_item.IsChecked():
            speaker.speak(_("Test dźwięku zakończenia połączenia"))
    
    def on_debug_voice(self, event):
        """Show voice call debug information"""
        try:
            debug_script = """
            (function() {
                if (!window.titanVoiceSetup) {
                    return JSON.stringify({error: 'Voice monitoring not setup'});
                }
                
                var debug = {
                    setup: !!window.titanVoiceSetup,
                    hasRTCPeerConnection: !!window.RTCPeerConnection,
                    hasGetUserMedia: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
                    callState: window.titanCallState || {},
                    currentCallElements: document.querySelectorAll('[aria-label*="call"], [class*="call"], [data-testid*="call"]').length,
                    currentVoiceElements: document.querySelectorAll('[aria-label*="voice"], [class*="voice"]').length,
                    messengerElements: document.querySelectorAll('[data-testid], [aria-label]').length,
                    hasObserver: !!window.titanVoiceObserver
                };
                
                return JSON.stringify(debug, null, 2);
            })();
            """
            
            result_str = self.webview.RunScript(debug_script)
            if result_str:
                import json
                
                # Handle WebView returning tuple
                if isinstance(result_str, tuple) and len(result_str) >= 2:
                    success, actual_result = result_str
                    if success:
                        result_str = actual_result
                    else:
                        wx.MessageBox(_("Błąd pobierania informacji debug"), _("Debug"), wx.OK | wx.ICON_ERROR)
                        return
                
                debug_info = json.loads(result_str)
                
                debug_text = _("Informacje debug połączeń głosowych:\n\n")
                
                if debug_info.get('error'):
                    debug_text += f"❌ Błąd: {debug_info['error']}\n"
                else:
                    debug_text += f"✅ Monitoring skonfigurowany: {debug_info.get('setup', False)}\n"
                    debug_text += f"🔌 RTCPeerConnection dostępne: {debug_info.get('hasRTCPeerConnection', False)}\n"
                    debug_text += f"🎤 getUserMedia dostępne: {debug_info.get('hasGetUserMedia', False)}\n"
                    debug_text += f"👁️ Observer aktywny: {debug_info.get('hasObserver', False)}\n\n"
                    
                    call_state = debug_info.get('callState', {})
                    debug_text += f"📞 Stan połączenia:\n"
                    debug_text += f"  - Aktywne: {call_state.get('isCallActive', False)}\n"
                    debug_text += f"  - Typ: {call_state.get('callType', 'brak')}\n"
                    debug_text += f"  - UI widoczne: {call_state.get('callUIVisible', False)}\n"
                    debug_text += f"  - Strumienie: {len(call_state.get('mediaStreams', []))}\n\n"
                    
                    debug_text += f"🔍 Elementy DOM:\n"
                    debug_text += f"  - Elementy call: {debug_info.get('currentCallElements', 0)}\n"
                    debug_text += f"  - Elementy voice: {debug_info.get('currentVoiceElements', 0)}\n"
                    debug_text += f"  - Elementy Messenger: {debug_info.get('messengerElements', 0)}\n\n"
                    
                    debug_text += f"🎛️ Lokalne ustawienia:\n"
                    debug_text += f"  - Połączenia włączone: {self.voice_enabled_item.IsChecked()}\n"
                    debug_text += f"  - Powiadomienia: {self.notifications_item.IsChecked()}\n"
                    debug_text += f"  - TTS: {self.tts_item.IsChecked()}\n"
                    debug_text += f"  - Zalogowany: {self.messenger_logged_in}\n"
                    debug_text += f"  - Lokalne połączenie aktywne: {self.is_call_active}\n"
                
                # Show in scrollable dialog
                dlg = wx.lib.dialogs.ScrolledMessageDialog(
                    self, debug_text, _("Debug połączeń głosowych"), 
                    style=wx.OK | wx.ICON_INFORMATION
                )
                dlg.ShowModal()
                dlg.Destroy()
                
        except Exception as e:
            wx.MessageBox(
                _("Błąd pobierania informacji debug:\n{}").format(str(e)),
                _("Debug"),
                wx.OK | wx.ICON_ERROR
            )
    
    def add_call_callback(self, callback):
        """Add callback for call events"""
        self.call_callbacks.append(callback)
    
    def _notify_call_event(self, event_type, data):
        """Notify call callbacks"""
        for callback in self.call_callbacks:
            try:
                wx.CallAfter(callback, event_type, data)
            except Exception as e:
                print(f"Call callback error: {e}")
    
    def on_show_cookies_dir(self, event):
        """Open cookies directory in file manager"""
        try:
            cookies_dir = get_messenger_cookies_dir()
            
            if platform.system() == 'Windows':
                os.startfile(cookies_dir)
            elif platform.system() == 'Darwin':  # macOS
                os.system(f'open "{cookies_dir}"')
            else:  # Linux
                os.system(f'xdg-open "{cookies_dir}"')
                
            if self.tts_item.IsChecked():
                speaker.speak(_("Otwarto folder cookies"))
                
        except Exception as e:
            print(f"Error opening cookies directory: {e}")
            wx.MessageBox(
                _("Nie można otworzyć folderu cookies:\n{}").format(str(e)),
                _("Błąd"),
                wx.OK | wx.ICON_ERROR
            )
    
    def on_clear_cookies(self, event):
        """Clear all cookies and user data"""
        # Confirm action
        dlg = wx.MessageDialog(
            self,
            _("Czy na pewno chcesz usunąć wszystkie cookies i dane logowania?\n\n"
              "To spowoduje wylogowanie z Messenger i konieczność ponownego logowania."),
            _("Potwierdź usunięcie cookies"),
            wx.YES_NO | wx.ICON_QUESTION
        )
        
        if dlg.ShowModal() == wx.ID_YES:
            dlg.Destroy()
            
            try:
                # First navigate away from Messenger to release any file locks
                if hasattr(self, 'webview') and self.webview:
                    self.webview.LoadURL("about:blank")
                
                # Wait a moment for navigation to complete
                wx.CallLater(1000, self._perform_cookie_clear)
                
            except Exception as e:
                print(f"Error initiating cookie clear: {e}")
                wx.MessageBox(
                    _("Błąd podczas czyszczenia cookies:\n{}").format(str(e)),
                    _("Błąd"),
                    wx.OK | wx.ICON_ERROR
                )
        else:
            dlg.Destroy()
    
    def _perform_cookie_clear(self):
        """Actually perform the cookie clearing"""
        try:
            success = clear_messenger_cookies()
            
            if success:
                wx.MessageBox(
                    _("Cookies zostały usunięte pomyślnie.\n"
                      "Przeładuj stronę aby zastosować zmiany."),
                    _("Cookies usunięte"),
                    wx.OK | wx.ICON_INFORMATION
                )
                
                # Reload Messenger
                if hasattr(self, 'webview') and self.webview:
                    self.webview.LoadURL("https://www.messenger.com")
                
                if self.tts_item.IsChecked():
                    speaker.speak(_("Cookies usunięte"))
                    
            else:
                wx.MessageBox(
                    _("Nie można usunąć cookies.\n"
                      "Może być potrzebne zamknięcie wszystkich okien Messenger."),
                    _("Błąd"),
                    wx.OK | wx.ICON_ERROR
                )
                
        except Exception as e:
            print(f"Error clearing cookies: {e}")
            wx.MessageBox(
                _("Błąd podczas usuwania cookies:\n{}").format(str(e)),
                _("Błąd"),
                wx.OK | wx.ICON_ERROR
            )
    
    def on_focus_chat(self, event):
        """Set focus to chat area"""
        if hasattr(self, 'webview') and self.webview:
            # Try to focus on common Messenger input elements
            focus_script = """
            (function() {
                // Try to focus on message input
                var inputs = document.querySelectorAll('[contenteditable="true"], textarea, input[type="text"]');
                for (var i = 0; i < inputs.length; i++) {
                    if (inputs[i].offsetWidth > 0 && inputs[i].offsetHeight > 0) {
                        inputs[i].focus();
                        return true;
                    }
                }
                return false;
            })();
            """
            try:
                result = self.webview.RunScript(focus_script)
                # We don't need the result, just run the script
                if self.tts_item.IsChecked():
                    speaker.speak(_("Fokus na obszar czatu"))
            except:
                pass
    
    def setup_notification_monitoring(self):
        """Setup notification monitoring"""
        self.last_title = ""
        self.last_notification_count = 0
    
    def start_notification_monitoring(self):
        """Start monitoring for new message notifications"""
        if self.notification_timer:
            self.notification_timer.Stop()
        
        self.notification_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.check_notifications, self.notification_timer)
        self.notification_timer.Start(5000)  # Check every 5 seconds (reduced frequency)
    
    def check_notifications(self, event):
        """Check for new notifications by monitoring page changes (improved with anti-spam)"""
        if not hasattr(self, 'webview') or not self.webview or not self.messenger_logged_in:
            return
        
        try:
            current_count = 0
            
            # Method 1: Check title for unread count
            current_title = self.webview.GetCurrentTitle()
            if current_title and "(" in current_title and ")" in current_title:
                import re
                match = re.search(r'\((\d+)\)', current_title)
                if match:
                    current_count = int(match.group(1))
            
            # Method 2: Check DOM for notification badges (only if title didn't show count)
            if current_count == 0:
                # Check for visual notifications using JavaScript
                notification_script = """
                (function() {
                    try {
                        // Enhanced notification detection for current Messenger
                        var badges = document.querySelectorAll(
                            '[data-testid="unread_count"], ' +
                            '.notification, ' +
                            '[aria-label*="unread"], ' +
                            '[style*="background-color: rgb(0, 132, 255)"], ' +
                            'span[data-testid*="unread"], ' +
                            'div[data-testid*="unread"]'
                        );
                        
                        var count = 0;
                        for (var i = 0; i < badges.length; i++) {
                            if (badges[i].offsetWidth > 0 && badges[i].offsetHeight > 0) {
                                var text = badges[i].textContent || badges[i].innerText;
                                if (text && !isNaN(text)) {
                                    count += parseInt(text);
                                } else if (badges[i].offsetWidth > 0) {
                                    count += 1;
                                }
                            }
                        }
                        return count;
                    } catch (e) {
                        return 0;
                    }
                })();
                """
                
                try:
                    result = self.webview.RunScript(notification_script)
                    if isinstance(result, tuple) and len(result) >= 2:
                        success, actual_result = result
                        if success:
                            result = actual_result
                        else:
                            result = None
                    
                    if result and isinstance(result, (int, float)):
                        current_count = int(result)
                except:
                    pass  # Ignore JavaScript errors
            
            # Trigger notification if count increased (new messages)
            if current_count > 0:
                # Check for detailed message information
                self.check_detailed_notifications(current_count)
                
        except Exception as e:
            print(f"Notification check error: {e}")
    
    def check_detailed_notifications(self, total_count):
        """Check for detailed message notifications with sender info"""
        if not hasattr(self, 'webview') or not self.webview or not self.messenger_logged_in:
            return
        
        try:
            # Enhanced notification detection with message details for Messenger
            detailed_notification_script = """
            (function() {
                try {
                    console.log('TITAN: Starting Messenger detailed notification check...');
                    
                    var result = {
                        totalCount: 0,
                        newMessages: []
                    };
                    
                    // Find all chat items with unread messages in Messenger
                    const chatSelectors = [
                        'div[aria-label*="Conversations"] div[role="listitem"]',
                        'div[aria-label*="Chats"] div[role="listitem"]',
                        'div[aria-label*="Rozmowy"] div[role="listitem"]',
                        '[data-testid="mwthreadlist"] div[role="listitem"]',
                        'div[role="navigation"] div[role="listitem"]'
                    ];
                    
                    for (let chatSelector of chatSelectors) {
                        const chatItems = document.querySelectorAll(chatSelector);
                        
                        if (chatItems.length > 0) {
                            chatItems.forEach((chatItem, index) => {
                                try {
                                    // Check if this chat has unread indicator
                                    const unreadIndicators = [
                                        'div[class*="unread"]',
                                        '[aria-label*="unread"]',
                                        'span[data-testid*="unread"]',
                                        'div[data-testid*="unread"]',
                                        // Visual indicators (bold text, badges)
                                        'strong',
                                        'span[class*="badge"]',
                                        'div[class*="notification"]'
                                    ];
                                    
                                    let hasUnread = false;
                                    for (let selector of unreadIndicators) {
                                        const indicator = chatItem.querySelector(selector);
                                        if (indicator && indicator.offsetWidth > 0) {
                                            hasUnread = true;
                                            break;
                                        }
                                    }
                                    
                                    if (hasUnread) {
                                        // Get sender name
                                        let senderName = '';
                                        const nameSelectors = [
                                            'span[dir="auto"] strong',
                                            'div[data-testid*="thread"] span',
                                            'h3 span',
                                            'span[role="heading"]',
                                            'div[role="heading"] span',
                                            'h3',
                                            'span[dir="auto"]:first-child',
                                            'strong'
                                        ];
                                        
                                        for (let nameSelector of nameSelectors) {
                                            const nameEl = chatItem.querySelector(nameSelector);
                                            if (nameEl && nameEl.textContent.trim()) {
                                                senderName = nameEl.textContent.trim();
                                                break;
                                            }
                                        }
                                        
                                        // Get last message preview
                                        let messagePreview = '';
                                        const msgSelectors = [
                                            'div[data-testid*="thread"] span:last-child',
                                            'div:last-child span[dir="auto"]',
                                            'span[dir="auto"]:not(:first-child)',
                                            'div:nth-child(2) span[dir="auto"]',
                                            'span[dir="auto"]:last-child',
                                            'p:last-child'
                                        ];
                                        
                                        for (let msgSelector of msgSelectors) {
                                            const msgEl = chatItem.querySelector(msgSelector);
                                            if (msgEl && msgEl.textContent.trim() && 
                                                msgEl.textContent.trim() !== senderName &&
                                                !msgEl.textContent.includes('Active') &&
                                                !msgEl.textContent.includes('ago')) {
                                                messagePreview = msgEl.textContent.trim();
                                                break;
                                            }
                                        }
                                        
                                        if (senderName) {
                                            result.newMessages.push({
                                                sender: senderName,
                                                message: messagePreview || 'New message',
                                                count: 1
                                            });
                                            result.totalCount += 1;
                                        }
                                    }
                                } catch (err) {
                                    console.log('TITAN: Error processing Messenger chat item:', err);
                                }
                            });
                            
                            // If we found messages, break from selector loop
                            if (result.newMessages.length > 0) {
                                break;
                            }
                        }
                    }
                    
                    console.log('TITAN: Messenger notification result:', result);
                    return JSON.stringify(result);
                    
                } catch (e) {
                    console.error('TITAN: Messenger notification error:', e);
                    return JSON.stringify({totalCount: 0, newMessages: []});
                }
            })();
            """
            
            result_str = self.webview.RunScript(detailed_notification_script)
            if result_str:
                import json
                try:
                    # Handle WebView returning tuple
                    if isinstance(result_str, tuple) and len(result_str) >= 2:
                        success, actual_result = result_str
                        if success:
                            result_str = actual_result
                        else:
                            result_str = '{"totalCount": 0, "newMessages": []}'
                    
                    if isinstance(result_str, str):
                        notification_data = json.loads(result_str)
                    else:
                        notification_data = {"totalCount": 0, "newMessages": []}
                    
                    detected_count = notification_data.get('totalCount', 0)
                    new_messages = notification_data.get('newMessages', [])
                    
                    # Use the higher count (either detected or passed total_count)
                    final_count = max(detected_count, total_count)
                    
                    # Trigger detailed notifications if we have messages
                    if final_count > 0:
                        if new_messages:
                            self.on_detailed_messenger_notification(new_messages, final_count)
                        else:
                            # Fallback to simple notification
                            self.on_notification_detected("Messenger", final_count)
                    
                except Exception as e:
                    print(f"Messenger notification parsing error: {e}")
                    # Fallback to simple notification
                    self.on_notification_detected("Messenger", total_count)
            else:
                # Fallback to simple notification
                self.on_notification_detected("Messenger", total_count)
                
        except Exception as e:
            print(f"Messenger detailed notification error: {e}")
            # Fallback to simple notification
            self.on_notification_detected("Messenger", total_count)
    
    def on_detailed_messenger_notification(self, messages, total_count):
        """Handle detailed Messenger notification with sender and message info"""
        if not self.notifications_item.IsChecked() or not self.messenger_logged_in:
            return
        
        import time
        current_time = time.time()
        
        # Anti-spam protection
        if current_time - self.last_notification_time < self.notification_cooldown:
            return
        
        # Only notify if count actually increased
        if total_count <= self.last_notification_count:
            return
        
        self.last_notification_time = current_time
        self.last_notification_count = total_count
        
        print(f"✓ Messenger detailed notification: {total_count} messages from {len(messages)} chats")
        
        # Play notification sound
        play_sound('titannet/new_message.ogg')
        
        # Enhanced TTS with sender and message details
        if self.tts_item.IsChecked():
            try:
                from stereo_speech import get_stereo_speech
                stereo_speech = get_stereo_speech()
                
                # Create detailed notification text
                if len(messages) == 1:
                    msg = messages[0]
                    notification_text = _("Messenger message from {}: {}").format(msg['sender'], msg['message'][:50])
                elif len(messages) <= 3:
                    # Announce first few messages individually
                    for msg in messages[:3]:
                        notification_text = _("Messenger message from {}: {}").format(msg['sender'], msg['message'][:30])
                        
                        if stereo_speech and stereo_speech.is_stereo_enabled():
                            stereo_speech.speak(notification_text, position=0.0, pitch_offset=3, use_fallback=False)
                        else:
                            import accessible_output3.outputs.auto
                            speaker = accessible_output3.outputs.auto.Auto()
                            speaker.speak(notification_text)
                        
                        time.sleep(0.5)  # Brief pause between messages
                    return
                else:
                    # Too many messages, give summary
                    notification_text = _("Messenger: {} new messages from {} contacts").format(total_count, len(messages))
                
                if stereo_speech and stereo_speech.is_stereo_enabled():
                    stereo_speech.speak(notification_text, position=0.0, pitch_offset=3, use_fallback=False)
                    print(f"✓ Stereo TTS: {notification_text}")
                else:
                    import accessible_output3.outputs.auto
                    speaker = accessible_output3.outputs.auto.Auto()
                    speaker.speak(notification_text)
                    print(f"✓ Standard TTS: {notification_text}")
                    
            except ImportError:
                import accessible_output3.outputs.auto
                speaker = accessible_output3.outputs.auto.Auto()
                if len(messages) == 1:
                    msg = messages[0]
                    notification_text = _("Messenger message from {}: {}").format(msg['sender'], msg['message'][:50])
                else:
                    notification_text = _("Messenger: {} new messages").format(total_count)
                speaker.speak(notification_text)
                print(f"✓ Fallback TTS: {notification_text}")
        
        # Flash taskbar
        try:
            if hasattr(self, 'RequestUserAttention'):
                self.RequestUserAttention()
        except:
            pass
    
    def on_notification_detected(self, title, count=None):
        """Handle detected notification with anti-spam protection"""
        if not self.notifications_item.IsChecked() or not self.messenger_logged_in:
            return
        
        import time
        current_time = time.time()
        
        # Anti-spam protection - only allow notifications every X seconds
        if current_time - self.last_notification_time < self.notification_cooldown:
            return
            
        # Only notify if count actually increased (new messages)
        if count is not None and count <= self.last_notification_count:
            return
        
        self.last_notification_time = current_time
        if count is not None:
            self.last_notification_count = count
        
        print(f"✓ Messenger notification: {count or 'new message'}")
        
        # Play notification sound like in Telegram
        play_sound('titannet/new_message.ogg')
        
        # TTS announcement (mowa stereo) - exactly like Telegram
        if self.tts_item.IsChecked():
            # Check if stereo speech is enabled (same as Telegram)
            try:
                from stereo_speech import get_stereo_speech
                stereo_speech = get_stereo_speech()
                
                if stereo_speech.is_stereo_enabled():
                    # Use stereo speech with higher tone for notification (same style as Telegram)
                    if count and count > 1:
                        notification_text = _("New messages from Messenger: {}").format(count)
                    else:
                        notification_text = _("New message from Messenger")
                    
                    # Speak with higher pitch (faster/higher tone) - same as Telegram
                    stereo_speech.speak(notification_text, position=0.0, pitch_offset=3, use_fallback=False)
                    print(f"✓ Stereo TTS notification: {notification_text}")
                else:
                    # Fallback to accessible_output3 if stereo speech is disabled
                    if count and count > 1:
                        message = _("Messenger: {} new messages").format(count)
                    else:
                        message = _("Messenger: new message")
                    
                    import accessible_output3.outputs.auto
                    speaker = accessible_output3.outputs.auto.Auto()
                    speaker.speak(message)
                    print(f"✓ Fallback TTS notification: {message}")
            except ImportError:
                # If stereo_speech is not available, use standard TTS
                if count and count > 1:
                    message = _("Messenger: {} new messages").format(count)
                else:
                    message = _("Messenger: new message")
                
                import accessible_output3.outputs.auto
                speaker = accessible_output3.outputs.auto.Auto()
                speaker.speak(message)
                print(f"✓ Standard TTS notification: {message}")
        
        # Flash taskbar (Windows)
        try:
            if hasattr(self, 'RequestUserAttention'):
                self.RequestUserAttention()
        except:
            pass
    
    def add_message_callback(self, callback):
        """Add callback for message events"""
        self.message_callbacks.append(callback)
    
    def add_status_callback(self, callback):
        """Add callback for status events"""
        self.status_callbacks.append(callback)
    
    def get_chat_list(self):
        """Get list of active conversations from Messenger"""
        if not hasattr(self, 'webview') or not self.webview:
            return []
        
        # Only get chat list if user is logged in
        if not self.messenger_logged_in:
            print("get_chat_list: User not logged in yet")
            return []
        
        try:
            chat_list_script = """
            (function() {
                try {
                    console.log('TITAN: Starting chat list extraction...');
                    
                    // Enhanced selectors for current Messenger (2024/2025)
                    const chatSelectors = [
                        // Main conversation list containers
                        'div[aria-label*="Conversations"] div[role="listitem"]',
                        'div[aria-label*="Chats"] div[role="listitem"]', 
                        'div[aria-label*="Rozmowy"] div[role="listitem"]',
                        '[data-testid="mwthreadlist"] div[role="listitem"]',
                        'div[role="navigation"] div[role="listitem"]',
                        
                        // Alternative containers
                        '[data-testid="conversation"]',
                        'div[aria-label*="Conversations"] > div > div',
                        'div[role="main"] div[role="listitem"]',
                        
                        // Fallback selectors
                        'div[aria-label*="Conversations"] li',
                        'div[role="navigation"] li',
                        'div[aria-label="Chats"] li'
                    ];
                    
                    let conversations = [];
                    
                    for (let selector of chatSelectors) {
                        const chatElements = document.querySelectorAll(selector);
                        console.log(`TITAN: Trying selector "${selector}" - found ${chatElements.length} elements`);
                        
                        if (chatElements.length > 0) {
                            chatElements.forEach((element, index) => {
                                try {
                                    // Enhanced name extraction for current Messenger
                                    let name = '';
                                    const nameSelectors = [
                                        // Current Messenger name selectors (2024/2025)
                                        'span[dir="auto"] strong',
                                        'div[data-testid*="thread"] span',
                                        'h3 span',
                                        'span[role="heading"]',
                                        'div[role="heading"] span',
                                        
                                        // Fallback selectors
                                        'h3', 'span[dir="auto"]', '[data-testid="thread_name"]',
                                        'div[title]', 'strong', 'span[title]',
                                        'div:first-child span'
                                    ];
                                    
                                    for (let nameSelector of nameSelectors) {
                                        const nameEl = element.querySelector(nameSelector);
                                        if (nameEl && nameEl.textContent.trim()) {
                                            name = nameEl.textContent.trim();
                                            break;
                                        }
                                    }
                                    
                                    // Enhanced last message extraction
                                    let lastMessage = '';
                                    const msgSelectors = [
                                        // Current Messenger message preview selectors
                                        'div[data-testid*="thread"] span:last-child',
                                        'div:last-child span[dir="auto"]',
                                        'span[dir="auto"]:not(:first-child)',
                                        'div:nth-child(2) span[dir="auto"]',
                                        
                                        // Fallback selectors
                                        'span[dir="auto"]:last-child', 
                                        'p:last-child', 
                                        '.text-content', 
                                        '.message-snippet',
                                        'div > div:last-child span'
                                    ];
                                    
                                    for (let msgSelector of msgSelectors) {
                                        const msgEl = element.querySelector(msgSelector);
                                        if (msgEl && msgEl.textContent.trim() !== name) {
                                            lastMessage = msgEl.textContent.trim();
                                            break;
                                        }
                                    }
                                    
                                    // Enhanced unread indicator detection
                                    let unread = 0;
                                    const unreadSelectors = [
                                        // Current Messenger unread indicators
                                        'span[data-testid*="unread"]',
                                        'div[data-testid*="unread"]',
                                        'span[aria-label*="unread"]',
                                        'div[aria-label*="unread"]',
                                        'span[style*="background-color: rgb(0, 132, 255)"]',
                                        'div[style*="background-color: rgb(0, 132, 255)"]',
                                        
                                        // Fallback selectors
                                        '[data-testid="unread_count"]',
                                        '.unread-badge', 
                                        '.notification-badge',
                                        'span[style*="background"]',
                                        'div[style*="border-radius"][style*="background"]'
                                    ];
                                    
                                    for (let unreadSelector of unreadSelectors) {
                                        const unreadEl = element.querySelector(unreadSelector);
                                        if (unreadEl) {
                                            const unreadText = unreadEl.textContent.trim();
                                            unread = parseInt(unreadText) || 1;
                                            break;
                                        }
                                    }
                                    
                                    // Get timestamp if available
                                    let timestamp = '';
                                    const timeSelectors = [
                                        'time', '[data-testid="timestamp"]', '.timestamp',
                                        'span:last-child'
                                    ];
                                    
                                    for (let timeSelector of timeSelectors) {
                                        const timeEl = element.querySelector(timeSelector);
                                        if (timeEl && timeEl.textContent.match(/\\d/)) {
                                            timestamp = timeEl.textContent.trim();
                                            break;
                                        }
                                    }
                                    
                                    if (name && name.length > 0) {
                                        const conversation = {
                                            id: 'conv_' + index,
                                            name: name,
                                            lastMessage: lastMessage || '',
                                            timestamp: timestamp || '',
                                            unread: unread,
                                            element_index: index,
                                            selector_used: selector
                                        };
                                        
                                        conversations.push(conversation);
                                        console.log(`TITAN: Found conversation: ${name} (last: "${lastMessage}", unread: ${unread})`);
                                    }
                                } catch (e) {
                                    console.log('TITAN: Error parsing conversation element:', e);
                                }
                            });
                            
                            if (conversations.length > 0) {
                                console.log(`TITAN: Successfully found ${conversations.length} conversations with selector: ${selector}`);
                                break; // If we found conversations with this selector, stop
                            }
                        }
                    }
                    
                    console.log(`TITAN: Total conversations found: ${conversations.length}`);
                    
                    return JSON.stringify({
                        success: true,
                        conversations: conversations,
                        count: conversations.length
                    });
                    
                } catch (error) {
                    return JSON.stringify({
                        success: false,
                        error: error.toString(),
                        conversations: []
                    });
                }
            })();
            """
            
            result_str = self.webview.RunScript(chat_list_script)
            if result_str:
                import json
                try:
                    result = json.loads(result_str)
                    if result.get('success'):
                        return result.get('conversations', [])
                    else:
                        print(f"Chat list extraction failed: {result.get('error')}")
                        return []
                except json.JSONDecodeError:
                    print(f"Failed to parse chat list JSON: {result_str}")
                    return []
        
        except Exception as e:
            print(f"Error getting chat list: {e}")
            return []
        
        return []
    
    def send_message_to_chat(self, chat_name, message):
        """Send a message to specific chat"""
        if not hasattr(self, 'webview') or not self.webview:
            return False
        
        try:
            # Escape quotes and special characters in the message
            escaped_message = message.replace("'", "\\'").replace('"', '\\"').replace('\n', '\\n')
            escaped_chat_name = chat_name.replace("'", "\\'").replace('"', '\\"')
            
            send_message_script = f"""
            (function() {{
                try {{
                    console.log('TITAN: Starting message send to: {escaped_chat_name}');
                    
                    // Use same enhanced selectors as chat list extraction
                    const chatSelectors = [
                        'div[aria-label*="Conversations"] div[role="listitem"]',
                        'div[aria-label*="Chats"] div[role="listitem"]', 
                        'div[aria-label*="Rozmowy"] div[role="listitem"]',
                        '[data-testid="mwthreadlist"] div[role="listitem"]',
                        'div[role="navigation"] div[role="listitem"]',
                        '[data-testid="conversation"]',
                        'div[aria-label*="Conversations"] > div > div',
                        'div[role="main"] div[role="listitem"]',
                        'div[aria-label*="Conversations"] li',
                        'div[role="navigation"] li',
                        'div[aria-label="Chats"] li'
                    ];
                    
                    let chatFound = false;
                    let targetChat = '{escaped_chat_name}';
                    
                    for (let selector of chatSelectors) {{
                        const chatElements = document.querySelectorAll(selector);
                        console.log(`TITAN: Checking selector "${{selector}}" - found ${{chatElements.length}} elements`);
                        
                        for (let element of chatElements) {{
                            // Use enhanced name selectors matching get_chat_list
                            const nameSelectors = [
                                'span[dir="auto"] strong',
                                'div[data-testid*="thread"] span',
                                'h3 span',
                                'span[role="heading"]',
                                'div[role="heading"] span',
                                'h3', 'span[dir="auto"]', '[data-testid="thread_name"]',
                                'div[title]', 'strong', 'span[title]',
                                'div:first-child span'
                            ];
                            
                            for (let nameSelector of nameSelectors) {{
                                const nameEl = element.querySelector(nameSelector);
                                if (nameEl && nameEl.textContent.trim().includes(targetChat)) {{
                                    console.log(`TITAN: Found matching chat: ${{nameEl.textContent.trim()}}`);
                                    element.click();
                                    chatFound = true;
                                    break;
                                }}
                            }}
                            if (chatFound) break;
                        }}
                        if (chatFound) break;
                    }}
                    
                    if (!chatFound) {{
                        return JSON.stringify({{
                            success: false,
                            error: 'Chat not found: ' + targetChat
                        }});
                    }}
                    
                    // Wait a bit for chat to load, then find message input
                    setTimeout(() => {{
                        console.log('TITAN: Looking for message input field...');
                        
                        const messageInputSelectors = [
                            // Current Messenger message input selectors (2024/2025)
                            'div[aria-label*="Message"][contenteditable="true"]',
                            'div[aria-label*="Wiadomość"][contenteditable="true"]', 
                            'div[role="textbox"][contenteditable="true"]',
                            'div[data-testid*="message"][contenteditable="true"]',
                            '[data-testid="message-input"]',
                            
                            // Fallback selectors
                            'div[aria-label*="Message"]',
                            'div[contenteditable="true"]',
                            'div[role="textbox"]',
                            'textarea[placeholder*="message" i]',
                            'div[contenteditable="true"][style*="outline"]'
                        ];
                        
                        let messageInput = null;
                        for (let selector of messageInputSelectors) {{
                            messageInput = document.querySelector(selector);
                            if (messageInput) break;
                        }}
                        
                        if (messageInput) {{
                            // Focus on the input
                            messageInput.focus();
                            
                            // Set the message text
                            messageInput.innerHTML = '{escaped_message}';
                            
                            // Trigger input events
                            messageInput.dispatchEvent(new Event('input', {{bubbles: true}}));
                            messageInput.dispatchEvent(new Event('change', {{bubbles: true}}));
                            
                            // Try to find and click send button
                            setTimeout(() => {{
                                console.log('TITAN: Looking for send button...');
                                
                                const sendButtonSelectors = [
                                    // Current Messenger send button selectors (2024/2025)
                                    'div[aria-label*="Send"][role="button"]',
                                    'div[aria-label*="Wyślij"][role="button"]',
                                    'button[aria-label*="Send"]',
                                    'button[aria-label*="Wyślij"]',
                                    '[data-testid*="send"]',
                                    'div[role="button"][aria-label*="Send"]',
                                    
                                    // Fallback selectors
                                    'div[aria-label*="Send" i]',
                                    'button[aria-label*="Send" i]',
                                    '[data-testid="send-button"]',
                                    'div[role="button"][aria-label*="Send" i]',
                                    'svg[aria-label*="Send"]'
                                ];
                                
                                let sendButton = null;
                                for (let selector of sendButtonSelectors) {{
                                    sendButton = document.querySelector(selector);
                                    if (sendButton) {{
                                        console.log(`TITAN: Found send button with selector: ${{selector}}`);
                                        break;
                                    }}
                                }}
                                
                                if (sendButton) {{
                                    console.log('TITAN: Clicking send button...');
                                    sendButton.click();
                                    console.log('TITAN: Message sent successfully!');
                                }} else {{
                                    console.log('TITAN: Send button not found, trying Enter key...');
                                    // Fallback: try Enter key
                                    messageInput.dispatchEvent(new KeyboardEvent('keydown', {{
                                        key: 'Enter',
                                        code: 'Enter',
                                        keyCode: 13,
                                        which: 13,
                                        bubbles: true
                                    }}));
                                    console.log('TITAN: Enter key pressed as fallback');
                                }}
                            }}, 500);
                        }}
                    }}, 1000);
                    
                    return JSON.stringify({{
                        success: true,
                        message: 'Message sending initiated'
                    }});
                    
                }} catch (error) {{
                    return JSON.stringify({{
                        success: false,
                        error: error.toString()
                    }});
                }}
            }})();
            """
            
            result_str = self.webview.RunScript(send_message_script)
            if result_str:
                import json
                try:
                    result = json.loads(result_str)
                    return result.get('success', False)
                except json.JSONDecodeError:
                    print(f"Failed to parse send message result: {result_str}")
                    return False
        
        except Exception as e:
            print(f"Error sending message: {e}")
            return False
        
        return False
    
    def start_video_call_with_contact(self, chat_name):
        """Start video call with specific contact"""
        if not hasattr(self, 'webview') or not self.webview:
            return False
        
        try:
            # Escape quotes and special characters in the chat name
            escaped_chat_name = chat_name.replace("'", "\\'").replace('"', '\\"')
            
            start_call_script = f"""
            (function() {{
                try {{
                    console.log('TITAN: Starting video call with: {escaped_chat_name}');
                    
                    // Use same enhanced selectors as message sending
                    const chatSelectors = [
                        'div[aria-label*="Conversations"] div[role="listitem"]',
                        'div[aria-label*="Chats"] div[role="listitem"]', 
                        'div[aria-label*="Rozmowy"] div[role="listitem"]',
                        '[data-testid="mwthreadlist"] div[role="listitem"]',
                        'div[role="navigation"] div[role="listitem"]',
                        '[data-testid="conversation"]',
                        'div[aria-label*="Conversations"] > div > div',
                        'div[role="main"] div[role="listitem"]',
                        'div[aria-label*="Conversations"] li',
                        'div[role="navigation"] li',
                        'div[aria-label="Chats"] li'
                    ];
                    
                    let chatFound = false;
                    let targetChat = '{escaped_chat_name}';
                    
                    for (let selector of chatSelectors) {{
                        const chatElements = document.querySelectorAll(selector);
                        console.log(`TITAN: Checking selector "${{selector}}" - found ${{chatElements.length}} elements`);
                        
                        for (let element of chatElements) {{
                            // Use enhanced name selectors matching message sending
                            const nameSelectors = [
                                'span[dir="auto"] strong',
                                'div[data-testid*="thread"] span',
                                'h3 span',
                                'span[role="heading"]',
                                'div[role="heading"] span',
                                'h3', 'span[dir="auto"]', '[data-testid="thread_name"]',
                                'div[title]', 'strong', 'span[title]',
                                'div:first-child span'
                            ];
                            
                            for (let nameSelector of nameSelectors) {{
                                const nameEl = element.querySelector(nameSelector);
                                if (nameEl && nameEl.textContent.trim().includes(targetChat)) {{
                                    console.log(`TITAN: Found matching chat for video call: ${{nameEl.textContent.trim()}}`);
                                    element.click();
                                    chatFound = true;
                                    break;
                                }}
                            }}
                            if (chatFound) break;
                        }}
                        if (chatFound) break;
                    }}
                    
                    if (!chatFound) {{
                        console.log('TITAN: Chat not found:', targetChat);
                        return {{ success: false, error: 'Chat not found' }};
                    }}
                    
                    // Wait a moment for the chat to load
                    setTimeout(function() {{
                        try {{
                            console.log('TITAN: Looking for video call button...');
                            
                            // Enhanced video call button selectors (2024/2025)
                            const callButtonSelectors = [
                                // Current Messenger video call selectors
                                'div[aria-label*="Video call"][role="button"]',
                                'div[aria-label*="Start video call"][role="button"]',
                                'div[aria-label*="Rozmowa wideo"][role="button"]',
                                'button[aria-label*="Video call"]',
                                'button[aria-label*="Start video call"]',
                                '[data-testid*="video_call"]',
                                '[data-testid*="videocall"]',
                                
                                // Fallback selectors
                                '[aria-label*="Video call"]',
                                '[aria-label*="Start video call"]',
                                '[aria-label*="video"]',
                                'button[data-testid*="video"]',
                                'button[data-testid*="call"]',
                                '[class*="video-call"]',
                                '[class*="call-button"]',
                                '.x1i10hfl[aria-label*="call"]',
                                'svg[aria-label*="Video call"]'
                            ];
                            
                            let callButton = null;
                            for (let selector of callButtonSelectors) {{
                                const buttons = document.querySelectorAll(selector);
                                if (buttons.length > 0) {{
                                    console.log(`TITAN: Found ${{buttons.length}} potential video call buttons with selector: ${{selector}}`);
                                }}
                                
                                for (let button of buttons) {{
                                    const label = button.getAttribute('aria-label') || '';
                                    const text = button.textContent || '';
                                    if (label.toLowerCase().includes('video') || 
                                        label.toLowerCase().includes('call') ||
                                        text.toLowerCase().includes('video')) {{
                                        console.log(`TITAN: Found video call button: ${{label}} - ${{text}}`);
                                        callButton = button;
                                        break;
                                    }}
                                }}
                                if (callButton) break;
                            }}
                            
                            if (callButton) {{
                                console.log('TITAN: Found video call button, clicking...');
                                callButton.click();
                                
                                // Set call state
                                if (!window.titanCallState) {{
                                    window.titanCallState = {{ callType: 'outgoing', callUIVisible: false }};
                                }}
                                window.titanCallState.callType = 'outgoing';
                                window.titanOutgoingCall = true;
                                window.titanCallButtonClicked = true;
                                
                                return {{ success: true }};
                            }} else {{
                                console.log('TITAN: Video call button not found');
                                return {{ success: false, error: 'Video call button not found' }};
                            }}
                        }} catch (e) {{
                            console.log('TITAN: Error clicking video call button:', e);
                            return {{ success: false, error: e.message }};
                        }}
                    }}, 1000);
                    
                    // Return pending result
                    return {{ success: true, pending: true }};
                    
                }} catch (e) {{
                    console.log('TITAN: Error starting video call:', e);
                    return {{ success: false, error: e.message }};
                }}
            }})();
            """
            
            result_str = self.webview.RunScript(start_call_script)
            print(f"Start video call result: {result_str}")
            
            if result_str:
                try:
                    result = json.loads(result_str)
                    success = result.get('success', False)
                    
                    if success:
                        # Set current call user for monitoring
                        self.current_call_user = chat_name
                        print(f"✓ Video call initiated with {{chat_name}}")
                        return True
                    else:
                        print(f"Video call failed: {{result.get('error', 'Unknown error')}}")
                        return False
                except json.JSONDecodeError:
                    print(f"Failed to parse video call result: {result_str}")
                    # If we can't parse JSON, assume success if no obvious error
                    self.current_call_user = chat_name
                    return True
        
        except Exception as e:
            print(f"Error starting video call: {e}")
            return False
        
        return False
    
    def on_close(self, event):
        """Handle window close"""
        try:
            # End any active call first
            if self.is_call_active:
                print("Ending active call before closing...")
                self.on_call_ended()
            
            # Stop all timers
            if self.notification_timer:
                self.notification_timer.Stop()
                self.notification_timer = None
            if hasattr(self, 'enhanced_timer'):
                self.enhanced_timer.Stop()
                self.enhanced_timer = None
            if hasattr(self, 'simple_timer'):
                self.simple_timer.Stop()
                self.simple_timer = None
            if hasattr(self, 'voice_timer'):
                self.voice_timer.Stop()
                self.voice_timer = None
            
            # Clean up WebView resources
            if hasattr(self, 'webview') and self.webview:
                try:
                    # Unbind WebView events to prevent callbacks during cleanup
                    self.webview.Unbind(wx.html2.EVT_WEBVIEW_NAVIGATING)
                    self.webview.Unbind(wx.html2.EVT_WEBVIEW_LOADED)
                    self.webview.Unbind(wx.html2.EVT_WEBVIEW_TITLE_CHANGED)
                    self.webview.Unbind(wx.html2.EVT_WEBVIEW_ERROR)
                    self.webview.Unbind(wx.EVT_CHAR_HOOK)
                    
                    # Navigate to about:blank to stop any ongoing operations
                    self.webview.LoadURL("about:blank")
                    
                    # Destroy the WebView
                    self.webview.Destroy()
                    self.webview = None
                except Exception as e:
                    print(f"Error cleaning up WebView: {e}")
            
            # Play goodbye sound like in Telegram - only if was logged in
            if self.messenger_logged_in and not self.is_call_active:  # Don't play if call just ended
                play_sound('titannet/bye.ogg')
                print("✓ Zamykanie - odtworzono dźwięk bye.ogg")
            
            # TTS goodbye
            if hasattr(self, 'tts_item') and self.tts_item.IsChecked():
                if self.messenger_logged_in:
                    speaker.speak(_("Rozłączono z Messenger"))
                else:
                    speaker.speak(_("Zamykanie Messenger"))
            
            # Allow the event to be processed properly
            if event.CanVeto():
                event.Skip()
            else:
                # Use CallAfter to ensure proper cleanup order
                wx.CallAfter(self.Destroy)
                
        except Exception as e:
            print(f"Error during close: {e}")
            # Force close if something goes wrong
            wx.CallAfter(self.Destroy)

def show_messenger_webview(parent=None):
    """Show Messenger WebView window"""
    try:
        messenger_window = MessengerWebViewFrame(parent)
        set_messenger_instance(messenger_window)  # Set global instance for voice call integration
        messenger_window.Show()
        return messenger_window
    except Exception as e:
        print(f"Error creating Messenger WebView: {e}")
        if wx.GetApp():  # Only show MessageBox if wx.App exists
            wx.MessageBox(
                _("Nie można otworzyć Messenger WebView.\n"
                  "Sprawdź czy WebView2 jest zainstalowany."),
                _("Błąd"),
                wx.OK | wx.ICON_ERROR
            )
        return None

def is_webview_available():
    """Check if WebView is available on this system"""
    try:
        # Check if we already have a wx.App running
        current_app = wx.GetApp()
        if current_app:
            # Use existing app to test WebView
            test_frame = wx.Frame(None)
            try:
                test_webview = wx.html2.WebView.New(test_frame)
                test_frame.Destroy()
                return True
            except Exception:
                test_frame.Destroy()
                return False
        else:
            # Create temporary app for testing
            test_app = wx.App(False)
            test_frame = wx.Frame(None)
            try:
                test_webview = wx.html2.WebView.New(test_frame)
                test_frame.Destroy()
                test_app.Destroy()
                return True
            except Exception:
                test_frame.Destroy()
                test_app.Destroy()
                return False
    except Exception:
        return False

# Global messenger instance for voice call integration
_messenger_instance = None

def get_messenger_instance():
    """Get the global messenger instance"""
    return _messenger_instance

def set_messenger_instance(instance):
    """Set the global messenger instance"""
    global _messenger_instance
    _messenger_instance = instance

def is_messenger_call_active():
    """Check if messenger voice call is active"""
    instance = get_messenger_instance()
    return instance.is_call_active if instance else False

def get_messenger_call_status():
    """Get messenger call status"""
    instance = get_messenger_instance()
    if not instance or not instance.is_call_active:
        return {'active': False}
    
    call_duration = None
    if instance.call_start_time:
        import datetime
        call_duration = datetime.datetime.now() - instance.call_start_time
    
    return {
        'active': True,
        'user': instance.current_call_user or 'Unknown',
        'type': instance.call_type or 'unknown',
        'duration': call_duration.total_seconds() if call_duration else 0,
        'start_time': instance.call_start_time.isoformat() if instance.call_start_time else None
    }

def add_messenger_call_callback(callback):
    """Add callback for messenger call events"""
    instance = get_messenger_instance()
    if instance:
        instance.add_call_callback(callback)

def end_messenger_call():
    """End current messenger voice call"""
    instance = get_messenger_instance()
    if instance and instance.is_call_active:
        instance.on_end_call(None)
        return True
    return False

def get_messenger_chat_list():
    """Get list of chats from Messenger WebView"""
    instance = get_messenger_instance()
    if instance:
        return instance.get_chat_list()
    return []

def send_messenger_message(chat_name, message):
    """Send message to specific chat in Messenger WebView"""
    instance = get_messenger_instance()
    if instance:
        return instance.send_message_to_chat(chat_name, message)
    return False

def start_messenger_video_call(chat_name):
    """Start video call with specific contact in Messenger WebView"""
    instance = get_messenger_instance()
    if instance:
        return instance.start_video_call_with_contact(chat_name)
    return False

if __name__ == '__main__':
    app = wx.App()
    
    # Check WebView availability
    if not is_webview_available():
        wx.MessageBox(
            _("WebView nie jest dostępny na tym systemie.\n"
              "Zainstaluj Microsoft Edge WebView2 Runtime."),
            _("Błąd WebView"),
            wx.OK | wx.ICON_ERROR
        )
    else:
        frame = MessengerWebViewFrame()
        set_messenger_instance(frame)  # Set global instance
        frame.Show()
        app.MainLoop()