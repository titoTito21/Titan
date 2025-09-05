# -*- coding: utf-8 -*-
"""
WhatsApp Web integration for Titan IM
Uses wx.html2.WebView instead of Selenium for better performance and accessibility
Based on Messenger WebView implementation
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

def get_whatsapp_cookies_dir():
    """Get the directory for storing WhatsApp cookies and user data - same as Titan config"""
    # Use the same base directory as settings.ini
    titan_config_dir = os.path.dirname(SETTINGS_FILE_PATH)
    cookies_dir = os.path.join(titan_config_dir, 'IM COOKIES', 'WhatsApp')
    
    # Create directory if it doesn't exist
    os.makedirs(cookies_dir, exist_ok=True)
    
    return cookies_dir

def get_whatsapp_user_data_dir():
    """Get the user data directory for WebView2"""
    cookies_dir = get_whatsapp_cookies_dir()
    user_data_dir = os.path.join(cookies_dir, 'WebView2_UserData')
    
    # Create directory if it doesn't exist
    os.makedirs(user_data_dir, exist_ok=True)
    
    return user_data_dir

def clear_whatsapp_cookies():
    """Clear all stored WhatsApp cookies and user data"""
    try:
        import shutil
        cookies_dir = get_whatsapp_cookies_dir()
        
        if os.path.exists(cookies_dir):
            shutil.rmtree(cookies_dir)
            os.makedirs(cookies_dir, exist_ok=True)
            return True
    except Exception as e:
        print(f"Error clearing WhatsApp cookies: {e}")
        return False
    
    return False

def is_webview_available():
    """Check if WebView2 is available on the system"""
    if platform.system() != 'Windows':
        return False
    
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

class WhatsAppWebViewFrame(wx.Frame):
    def __init__(self, parent=None):
        super().__init__(parent, title=_("WhatsApp Web - Titan IM"), size=(1000, 700))
        
        self.whatsapp_loaded = False
        self.whatsapp_logged_in = False
        self.message_callbacks = []
        self.status_callbacks = []
        self.notification_timer = None
        self.typing_timer = None
        self.last_typing_user = None
        self.last_title = ""
        self.last_message_count = 0
        self.last_activity_check = 0
        
        # Notification anti-spam mechanism
        self.last_notification_time = 0
        self.last_notification_count = 0
        self.notification_cooldown = 5.0  # 5 seconds cooldown between notifications
        
        # Chat list monitoring for new chats
        self.last_chat_count = 0
        
        self.setup_ui()
        self.setup_notification_monitoring()
        self.Centre()
        
        # Load WhatsApp Web
        wx.CallAfter(self.load_whatsapp)
    
    def setup_notification_monitoring(self):
        """Setup notification monitoring"""
        self.last_title = ""
        self.last_notification_count = 0
    
    def setup_ui(self):
        """Setup the user interface"""
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Menu bar
        self.setup_menubar()
        
        # Status bar
        self.CreateStatusBar()
        self.SetStatusText(_("Ładowanie WhatsApp Web..."))
        
        # WebView
        try:
            self.webview = wx.html2.WebView.New(panel)
            
            # Set user data folder for persistent sessions
            user_data_dir = get_whatsapp_user_data_dir()
            print(f"WhatsApp WebView user data dir: {user_data_dir}")
            
            main_sizer.Add(self.webview, 1, wx.EXPAND)
            
            # Bind WebView events
            self.Bind(wx.html2.EVT_WEBVIEW_LOADED, self.on_webview_loaded, self.webview)
            self.Bind(wx.html2.EVT_WEBVIEW_TITLE_CHANGED, self.on_title_changed, self.webview)
            self.Bind(wx.html2.EVT_WEBVIEW_ERROR, self.on_webview_error, self.webview)
            
            # Bind keyboard events
            self.webview.Bind(wx.EVT_CHAR_HOOK, self.on_webview_key)
            
        except Exception as e:
            error_text = wx.StaticText(panel, label=f"WebView error: {e}")
            main_sizer.Add(error_text, 1, wx.EXPAND | wx.ALL, 10)
        
        panel.SetSizer(main_sizer)
        
        # Bind window events
        self.Bind(wx.EVT_CLOSE, self.on_close)
    
    def setup_menubar(self):
        """Setup menu bar with WhatsApp options"""
        menubar = wx.MenuBar()
        
        # WhatsApp menu
        whatsapp_menu = wx.Menu()
        
        refresh_item = whatsapp_menu.Append(wx.ID_ANY, _("Odśwież\tF5"), _("Odśwież stronę"))
        self.Bind(wx.EVT_MENU, self.on_refresh, refresh_item)
        
        whatsapp_menu.AppendSeparator()
        
        clear_cookies_item = whatsapp_menu.Append(wx.ID_ANY, _("Wyczyść dane sesji"), _("Wyczyść cookies i dane"))
        self.Bind(wx.EVT_MENU, self.on_clear_cookies, clear_cookies_item)
        
        whatsapp_menu.AppendSeparator()
        
        close_item = whatsapp_menu.Append(wx.ID_EXIT, _("Zamknij\tAlt+F4"), _("Zamknij okno"))
        self.Bind(wx.EVT_MENU, self.on_close, close_item)
        
        menubar.Append(whatsapp_menu, _("WhatsApp"))
        
        # Settings menu
        settings_menu = wx.Menu()
        
        self.notifications_item = settings_menu.AppendCheckItem(wx.ID_ANY, _("Powiadomienia"), _("Włącz powiadomienia o nowych wiadomościach"))
        self.notifications_item.Check(True)  # Default enabled
        
        self.tts_item = settings_menu.AppendCheckItem(wx.ID_ANY, _("Mowa (TTS)"), _("Włącz powiadomienia głosowe"))
        self.tts_item.Check(True)  # Default enabled
        
        menubar.Append(settings_menu, _("Ustawienia"))
        
        # Help menu
        help_menu = wx.Menu()
        
        about_item = help_menu.Append(wx.ID_ABOUT, _("O programie"), _("Informacje o WhatsApp Web dla Titan IM"))
        self.Bind(wx.EVT_MENU, self.on_about, about_item)
        
        menubar.Append(help_menu, _("Pomoc"))
        
        self.SetMenuBar(menubar)
    
    def load_whatsapp(self):
        """Load WhatsApp Web"""
        if not hasattr(self, 'webview'):
            return
        
        try:
            # Play connecting sound like in Telegram/Messenger
            play_sound('connecting.ogg')
            print("🔗 Connecting to WhatsApp Web...")
            
            # TTS announcement if available
            try:
                import accessible_output3.outputs.auto
                speaker = accessible_output3.outputs.auto.Auto()
                speaker.speak(_("Connecting to WhatsApp Web"))
            except:
                pass
            
            # Load WhatsApp Web
            self.webview.LoadURL("https://web.whatsapp.com")
            self.SetStatusText(_("Ładowanie WhatsApp Web..."))
            
        except Exception as e:
            print(f"Error loading WhatsApp Web: {e}")
            self.SetStatusText(_("Błąd ładowania WhatsApp Web"))
    
    def on_webview_loaded(self, event):
        """Handle WebView loaded event"""
        url = event.GetURL()
        print(f"WhatsApp WebView loaded: {url}")
        
        if "web.whatsapp.com" in url:
            self.whatsapp_loaded = True
            self.SetStatusText(_("WhatsApp Web załadowany"))
            
            # Check if user is already logged in
            wx.CallLater(3000, self.check_login_status)
    
    def check_login_status(self):
        """Check if user is logged in to WhatsApp"""
        if not hasattr(self, 'webview') or not self.webview:
            return
        
        try:
            login_check_script = """
            (function() {
                try {
                    // Enhanced WhatsApp Web login detection (2024/2025)
                    
                    // Check for QR code (not logged in)
                    const qrSelectors = [
                        'canvas[aria-label*="scan"]',
                        '[data-testid="qr-code"]', 
                        'div[data-testid="intro-md-beta-logo-container"]',
                        'canvas[role="img"]',
                        '[data-testid="qr-canvas"]',
                        'div[data-testid="landing-wrapper"]'
                    ];
                    
                    for (let selector of qrSelectors) {
                        const qrCode = document.querySelector(selector);
                        if (qrCode && qrCode.offsetWidth > 0) {
                            return { loggedIn: false, hasQR: true };
                        }
                    }
                    
                    // Check for main chat interface (logged in)
                    const chatSelectors = [
                        '[data-testid="chat-list"]',
                        'div[aria-label*="Chat list"]',
                        '#pane-side',
                        'div[data-testid="contact-list-container"]',
                        '[data-testid="chatlist-header"]',
                        'div[role="application"] div[role="grid"]'
                    ];
                    
                    for (let selector of chatSelectors) {
                        const chatList = document.querySelector(selector);
                        if (chatList && chatList.offsetWidth > 0) {
                            return { loggedIn: true, hasQR: false };
                        }
                    }
                    
                    // Check for loading indicators
                    const loadingIndicators = document.querySelectorAll('[data-testid*="loading"], .landing-main, div[class*="landing"]');
                    if (loadingIndicators.length > 0) {
                        return { loggedIn: false, hasQR: false, loading: true };
                    }
                    
                    // Default loading state
                    return { loggedIn: false, hasQR: false, loading: true };
                } catch (e) {
                    return { error: e.toString() };
                }
            })();
            """
            
            result_str = self.webview.RunScript(login_check_script)
            if result_str:
                import json
                try:
                    # Handle WebView returning tuple (success, result) instead of just result
                    if isinstance(result_str, tuple) and len(result_str) >= 2:
                        success, actual_result = result_str
                        if success:
                            result_str = actual_result
                        else:
                            print(f"WhatsApp login check script failed: {actual_result}")
                            wx.CallLater(5000, self.check_login_status)
                            return
                    
                    result = json.loads(result_str)
                    if result.get('loggedIn'):
                        self.on_login_success()
                    elif result.get('hasQR'):
                        self.SetStatusText(_("Zeskanuj kod QR, aby zalogować się do WhatsApp"))
                        # Check again in 5 seconds
                        wx.CallLater(5000, self.check_login_status)
                    elif result.get('loading'):
                        self.SetStatusText(_("Ładowanie WhatsApp Web..."))
                        # Check again in 3 seconds
                        wx.CallLater(3000, self.check_login_status)
                    else:
                        # Check again in 5 seconds
                        wx.CallLater(5000, self.check_login_status)
                except json.JSONDecodeError as e:
                    print(f"JSON decode error in WhatsApp login check: {e}, result: {result_str}")
                    # Check again in 5 seconds
                    wx.CallLater(5000, self.check_login_status)
        except Exception as e:
            print(f"Error checking WhatsApp login status: {e}")
            wx.CallLater(5000, self.check_login_status)
    
    def on_login_success(self):
        """Handle successful login to WhatsApp"""
        if self.whatsapp_logged_in:
            return  # Already handled
        
        self.whatsapp_logged_in = True
        self.SetStatusText(_("Połączono z WhatsApp"))
        
        print("✓ WhatsApp login successful")
        play_sound('titannet/titannet_success.ogg')
        
        # Also play welcome sound
        wx.CallLater(1500, lambda: play_sound('titannet/welcome to IM.ogg'))
        
        # Notify status callbacks about successful login
        for callback in self.status_callbacks:
            try:
                wx.CallAfter(callback, 'logged_in', {"platform": "WhatsApp Web"})
            except Exception as e:
                print(f"Error calling WhatsApp status callback: {e}")
        
        # Start enhanced monitoring for messages and typing
        self.start_enhanced_monitoring()
        
        # Setup message sent monitoring
        self.setup_message_sent_monitoring()
        
        # Setup typing detection
        self.start_typing_monitoring()
        
        # Setup voice call monitoring
        wx.CallLater(5000, self.setup_voice_call_monitoring)
    
    def start_enhanced_monitoring(self):
        """Start monitoring for new message notifications"""
        if self.notification_timer:
            self.notification_timer.Stop()
        
        self.notification_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.check_notifications, self.notification_timer)
        self.notification_timer.Start(5000)  # Check every 5 seconds (reduced frequency)
    
    def start_typing_monitoring(self):
        """Start monitoring for typing indicators - same as Messenger"""
        if self.typing_timer:
            self.typing_timer.Stop()
        
        self.typing_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.check_typing_activity, self.typing_timer)
        self.typing_timer.Start(1500)  # Check every 1.5 seconds like Messenger
    
    def check_typing_activity(self, event):
        """Check for typing indicators - same as Messenger implementation"""
        if not hasattr(self, 'webview') or not self.webview or not self.whatsapp_logged_in:
            return
            
        try:
            # Check for typing indicators with comprehensive selectors
            typing_script = """
            (function() {
                try {
                    var result = {
                        typing: false,
                        typingUser: '',
                        debug: {}
                    };
                    
                    // WhatsApp typing indicators - multiple selector approaches
                    var typingSelectors = [
                        '[aria-label*="typing"]',
                        '[data-testid*="typing"]', 
                        '[aria-label*="is typing"]',
                        '[aria-label*="pisze"]',
                        '[aria-label*="schreibt"]',
                        '[aria-label*="est en train d"]',
                        '.typing-indicator',
                        '[role="status"]',
                        '[data-testid="typing-indicator"]',
                        'div[class*="typing"]',
                        'span[class*="typing"]'
                    ];
                    
                    var typingIndicators = [];
                    typingSelectors.forEach(selector => {
                        try {
                            var elements = document.querySelectorAll(selector);
                            typingIndicators = typingIndicators.concat(Array.from(elements));
                        } catch (e) {
                            // Skip problematic selectors
                        }
                    });
                    
                    // Check if any typing indicators are visible and active
                    for (var i = 0; i < typingIndicators.length; i++) {
                        var elem = typingIndicators[i];
                        
                        // Must be visible
                        if (elem.offsetWidth === 0 || elem.offsetHeight === 0) {
                            continue;
                        }
                        
                        var text = elem.textContent || elem.getAttribute('aria-label') || '';
                        var lowercaseText = text.toLowerCase();
                        
                        if (lowercaseText.includes('typing') || 
                            lowercaseText.includes('pisze') || 
                            lowercaseText.includes('schreibt') ||
                            lowercaseText.includes('est en train')) {
                            
                            result.typing = true;
                            
                            // Extract username from typing text
                            var userName = text.replace(/is typing|pisze|schreibt|est en train d/gi, '').trim();
                            if (userName.length > 0 && userName.length < 50) {
                                result.typingUser = userName;
                            } else {
                                result.typingUser = 'Someone';
                            }
                            
                            console.log('TITAN: WhatsApp typing detected:', text);
                            break;
                        }
                    }
                    
                    // Alternative approach: Look for typing animations or status text
                    if (!result.typing) {
                        var statusElements = document.querySelectorAll(
                            '[data-testid="msg-time"], ' +
                            '[data-testid="last-seen"], ' +
                            'span[dir="auto"][class*="status"], ' +
                            'div[class*="typing"]'
                        );
                        
                        statusElements.forEach(elem => {
                            if (elem.offsetWidth > 0) {
                                var statusText = (elem.textContent || '').toLowerCase();
                                if (statusText.includes('typing') || statusText.includes('pisze')) {
                                    result.typing = true;
                                    result.typingUser = 'Contact';
                                    console.log('TITAN: WhatsApp typing detected via status:', statusText);
                                }
                            }
                        });
                    }
                    
                    result.debug.typingIndicators = typingIndicators.length;
                    result.debug.timestamp = new Date().toISOString();
                    
                    return JSON.stringify(result);
                    
                } catch (error) {
                    console.error('TITAN: WhatsApp typing check error:', error);
                    return JSON.stringify({typing: false, typingUser: '', error: error.toString()});
                }
            })();
            """
            
            result_str = self.webview.RunScript(typing_script)
            if result_str:
                import json
                import time
                try:
                    # Handle WebView returning tuple
                    if isinstance(result_str, tuple) and len(result_str) >= 2:
                        success, actual_result = result_str
                        if success:
                            result_str = actual_result
                        else:
                            return
                    
                    if isinstance(result_str, str):
                        result = json.loads(result_str)
                    else:
                        return
                    
                    # Handle typing indicators - same logic as Messenger
                    if result.get('typing') and self.notifications_item.IsChecked():
                        typing_user = result.get('typingUser', 'Someone')
                        
                        # Only play typing sound if different user or enough time passed
                        if (not self.last_typing_user or 
                            self.last_typing_user != typing_user or 
                            not hasattr(self, 'last_typing_time') or
                            time.time() - self.last_typing_time > 3):
                            
                            print(f"🔤 WhatsApp TYPING DETECTED: {typing_user}")
                            
                            # Play typing sound like in Telegram/Messenger
                            play_sound('titannet/typing.ogg')
                            print("✓ WhatsApp typing sound played - typing.ogg")
                            
                            # TTS announcement
                            if self.tts_item.IsChecked():
                                try:
                                    from stereo_speech import get_stereo_speech
                                    stereo_speech = get_stereo_speech()
                                    
                                    if stereo_speech and stereo_speech.is_stereo_enabled():
                                        if typing_user and typing_user != 'Someone':
                                            message = _("{} is typing").format(typing_user)
                                        else:
                                            message = _("Someone is typing")
                                        
                                        # Use stereo speech with neutral position and slight pitch change
                                        stereo_speech.speak(message, position=0.0, pitch_offset=1, use_fallback=False)
                                    else:
                                        import accessible_output3.outputs.auto
                                        speaker = accessible_output3.outputs.auto.Auto()
                                        if typing_user and typing_user != 'Someone':
                                            speaker.speak(_("{} is typing").format(typing_user))
                                        else:
                                            speaker.speak(_("Someone is typing"))
                                except ImportError:
                                    import accessible_output3.outputs.auto
                                    speaker = accessible_output3.outputs.auto.Auto()
                                    if typing_user and typing_user != 'Someone':
                                        speaker.speak(_("{} is typing").format(typing_user))
                                    else:
                                        speaker.speak(_("Someone is typing"))
                            
                            self.last_typing_user = typing_user
                            self.last_typing_time = time.time()
                    
                except json.JSONDecodeError as e:
                    print(f"JSON decode error in WhatsApp typing check: {e}")
                    
        except Exception as e:
            print(f"Error checking WhatsApp typing activity: {e}")
    
    def check_new_chats(self):
        """Check for new chats appearing - same as Telegram"""
        if not hasattr(self, 'webview') or not self.webview or not self.whatsapp_logged_in:
            return
        
        try:
            # Count current number of chats
            chat_count_script = """
            (function() {
                try {
                    const chatSelectors = [
                        '[data-testid="chat-list"] div[role="listitem"]',
                        'div[aria-label*="Chat list"] div[role="listitem"]',
                        '[data-testid="contact-list-container"] div[role="listitem"]',
                        '[data-testid="cell-frame-container"]'
                    ];
                    
                    let totalChats = 0;
                    
                    for (let selector of chatSelectors) {
                        const chats = document.querySelectorAll(selector);
                        if (chats.length > 0) {
                            totalChats = chats.length;
                            break; // Use first successful selector
                        }
                    }
                    
                    return totalChats;
                } catch (e) {
                    return 0;
                }
            })();
            """
            
            result = self.webview.RunScript(chat_count_script)
            
            # Handle WebView returning tuple
            if isinstance(result, tuple) and len(result) >= 2:
                success, actual_result = result
                if success:
                    result = actual_result
                else:
                    result = 0
            
            current_chat_count = int(result) if result and str(result).isdigit() else 0
            
            # Check if chat count increased (new chat)
            if self.last_chat_count > 0 and current_chat_count > self.last_chat_count:
                new_chats = current_chat_count - self.last_chat_count
                print(f"✓ WhatsApp: {new_chats} new chat(s) detected!")
                
                if self.notifications_item.IsChecked():
                    # Play new chat sound like in Telegram
                    play_sound('titannet/new_chat.ogg')
                    
                    # TTS announcement
                    if self.tts_item.IsChecked():
                        try:
                            from stereo_speech import get_stereo_speech
                            stereo_speech = get_stereo_speech()
                            
                            if stereo_speech.is_stereo_enabled():
                                if new_chats == 1:
                                    notification_text = _("New WhatsApp chat")
                                else:
                                    notification_text = _("New WhatsApp chats: {}").format(new_chats)
                                
                                # Use stereo speech for new chat notification
                                stereo_speech.speak(notification_text, position=0.0, pitch_offset=2, use_fallback=False)
                            else:
                                import accessible_output3.outputs.auto
                                speaker = accessible_output3.outputs.auto.Auto()
                                if new_chats == 1:
                                    speaker.speak(_("New WhatsApp chat"))
                                else:
                                    speaker.speak(_("New WhatsApp chats: {}").format(new_chats))
                        except ImportError:
                            import accessible_output3.outputs.auto
                            speaker = accessible_output3.outputs.auto.Auto()
                            if new_chats == 1:
                                speaker.speak(_("New WhatsApp chat"))
                            else:
                                speaker.speak(_("New WhatsApp chats: {}").format(new_chats))
            
            self.last_chat_count = current_chat_count
            
        except Exception as e:
            print(f"Error checking new WhatsApp chats: {e}")
    
    def check_notifications(self, event):
        """Check for new notifications with detailed message info"""
        if not hasattr(self, 'webview') or not self.webview or not self.whatsapp_logged_in:
            return
        
        try:
            # Enhanced notification detection with message details
            detailed_notification_script = """
            (function() {
                try {
                    console.log('TITAN: Starting WhatsApp detailed notification check...');
                    
                    var result = {
                        totalCount: 0,
                        newMessages: []
                    };
                    
                    // Find all chat items with unread messages
                    const chatSelectors = [
                        '[data-testid="chat-list"] div[role="listitem"]',
                        'div[aria-label*="Chat list"] div[role="listitem"]',
                        '[data-testid="contact-list-container"] div[role="listitem"]',
                        '[data-testid="cell-frame-container"]'
                    ];
                    
                    for (let chatSelector of chatSelectors) {
                        const chatItems = document.querySelectorAll(chatSelector);
                        
                        if (chatItems.length > 0) {
                            chatItems.forEach((chatItem, index) => {
                                try {
                                    // Check if this chat has unread messages
                                    const unreadBadge = chatItem.querySelector(
                                        '[data-testid="unread-count"], ' +
                                        'span[data-testid*="unread"], ' +
                                        '[aria-label*="unread"], ' +
                                        'div[class*="unread"]'
                                    );
                                    
                                    if (unreadBadge && unreadBadge.offsetWidth > 0) {
                                        // Get sender name
                                        let senderName = '';
                                        const nameSelectors = [
                                            '[data-testid="conversation-title"] span',
                                            'span[title][dir="auto"]',
                                            'div[data-testid*="cell"] span[title]',
                                            'span[aria-label]'
                                        ];
                                        
                                        for (let nameSelector of nameSelectors) {
                                            const nameEl = chatItem.querySelector(nameSelector);
                                            if (nameEl && (nameEl.textContent.trim() || nameEl.title)) {
                                                senderName = nameEl.textContent.trim() || nameEl.title;
                                                break;
                                            }
                                        }
                                        
                                        // Get last message preview
                                        let messagePreview = '';
                                        const msgSelectors = [
                                            '[data-testid="last-msg"] span[dir="auto"]',
                                            'div[data-testid*="cell"] span:last-child',
                                            'div:last-child span[dir="auto"]',
                                            'span[dir="auto"]:not([title])'
                                        ];
                                        
                                        for (let msgSelector of msgSelectors) {
                                            const msgEl = chatItem.querySelector(msgSelector);
                                            if (msgEl && msgEl.textContent.trim() && 
                                                msgEl.textContent.trim() !== senderName) {
                                                messagePreview = msgEl.textContent.trim();
                                                break;
                                            }
                                        }
                                        
                                        // Get unread count
                                        let unreadCount = 1;
                                        const unreadText = unreadBadge.textContent.trim();
                                        if (unreadText && !isNaN(unreadText)) {
                                            unreadCount = parseInt(unreadText);
                                        }
                                        
                                        if (senderName) {
                                            result.newMessages.push({
                                                sender: senderName,
                                                message: messagePreview || 'New message',
                                                count: unreadCount
                                            });
                                            result.totalCount += unreadCount;
                                        }
                                    }
                                } catch (err) {
                                    console.log('TITAN: Error processing chat item:', err);
                                }
                            });
                            
                            // If we found messages, break from selector loop
                            if (result.newMessages.length > 0) {
                                break;
                            }
                        }
                    }
                    
                    console.log('TITAN: WhatsApp notification result:', result);
                    return JSON.stringify(result);
                    
                } catch (e) {
                    console.error('TITAN: WhatsApp notification error:', e);
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
                    
                    total_count = notification_data.get('totalCount', 0)
                    new_messages = notification_data.get('newMessages', [])
                    
                    # Trigger detailed notifications if we have new messages
                    if total_count > 0 and new_messages:
                        self.on_detailed_notification(new_messages, total_count)
                    
                except Exception as e:
                    print(f"WhatsApp notification parsing error: {e}")
            
            # Also check for new chats
            self.check_new_chats()
                
        except Exception as e:
            print(f"WhatsApp notification check error: {e}")
    
    def on_detailed_notification(self, messages, total_count):
        """Handle detailed notification with sender and message info"""
        if not self.notifications_item.IsChecked() or not self.whatsapp_logged_in:
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
        
        print(f"✓ WhatsApp detailed notification: {total_count} messages from {len(messages)} chats")
        
        # Play notification sound
        play_sound('titannet/new_message.ogg')
        
        # Execute notification script
        self._execute_notification_script(total_count)
        
        # Enhanced TTS with sender and message details
        if self.tts_item.IsChecked():
            try:
                from stereo_speech import get_stereo_speech
                stereo_speech = get_stereo_speech()
                
                # Create detailed notification text
                if len(messages) == 1:
                    msg = messages[0]
                    notification_text = _("WhatsApp message from {}: {}").format(msg['sender'], msg['message'][:50])
                elif len(messages) <= 3:
                    # Announce first few messages individually
                    for msg in messages[:3]:
                        notification_text = _("WhatsApp message from {}: {}").format(msg['sender'], msg['message'][:30])
                        
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
                    notification_text = _("WhatsApp: {} new messages from {} contacts").format(total_count, len(messages))
                
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
                    notification_text = _("WhatsApp message from {}: {}").format(msg['sender'], msg['message'][:50])
                else:
                    notification_text = _("WhatsApp: {} new messages").format(total_count)
                speaker.speak(notification_text)
                print(f"✓ Fallback TTS: {notification_text}")
        
        # Flash taskbar
        try:
            if hasattr(self, 'RequestUserAttention'):
                self.RequestUserAttention()
        except:
            pass
    
    def on_notification_detected(self, title, count=None):
        """Handle detected notification with anti-spam protection and full script functionality"""
        if not self.notifications_item.IsChecked() or not self.whatsapp_logged_in:
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
        
        print(f"✓ WhatsApp notification: {count or 'new message'}")
        
        # Play notification sound like in Telegram/Messenger
        play_sound('titannet/new_message.ogg')
        
        # Execute WhatsApp notification script
        self._execute_notification_script(count)
        
        # TTS announcement (mowa stereo) - exactly like Telegram/Messenger
        if self.tts_item.IsChecked():
            # Check if stereo speech is enabled (same as Telegram/Messenger)
            try:
                from stereo_speech import get_stereo_speech
                stereo_speech = get_stereo_speech()
                
                if stereo_speech.is_stereo_enabled():
                    # Use stereo speech with higher tone for notification (same style as Telegram)
                    if count and count > 1:
                        notification_text = _("New messages from WhatsApp: {}").format(count)
                    else:
                        notification_text = _("New message from WhatsApp")
                    
                    # Speak with higher pitch (faster/higher tone) - same as Telegram
                    stereo_speech.speak(notification_text, position=0.0, pitch_offset=3, use_fallback=False)
                    print(f"✓ Stereo TTS notification: {notification_text}")
                else:
                    # Fallback to accessible_output3 if stereo speech is disabled
                    if count and count > 1:
                        message = _("WhatsApp: {} new messages").format(count)
                    else:
                        message = _("WhatsApp: new message")
                    
                    import accessible_output3.outputs.auto
                    speaker = accessible_output3.outputs.auto.Auto()
                    speaker.speak(message)
                    print(f"✓ Fallback TTS notification: {message}")
            except ImportError:
                # If stereo_speech is not available, use standard TTS
                if count and count > 1:
                    message = _("WhatsApp: {} new messages").format(count)
                else:
                    message = _("WhatsApp: new message")
                
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
    
    def setup_message_sent_monitoring(self):
        """Setup monitoring for sent messages - same as Messenger"""
        if not hasattr(self, 'webview') or not self.webview:
            return
        
        try:
            # Enhanced WhatsApp Web message send monitoring script
            setup_script = """
            (function() {
                if (window.titanWhatsAppSetup) {
                    return; // Already setup
                }
                
                console.log('TITAN: Setting up WhatsApp message send monitoring...');
                
                // Monitor Enter key presses in text inputs
                document.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' && !e.shiftKey && e.target.matches('[contenteditable="true"], textarea, input')) {
                        // Check if this is the WhatsApp message input
                        const inputSelectors = [
                            '[data-testid="compose-box-input"]',
                            'div[contenteditable="true"][data-tab="10"]',
                            '[data-testid="msg-input"]',
                            'div[role="textbox"][contenteditable="true"]'
                        ];
                        
                        for (let selector of inputSelectors) {
                            if (e.target.matches(selector) || e.target.closest(selector)) {
                                console.log('TITAN: WhatsApp Enter key send detected!');
                                window.titanWhatsAppMessageSent = true;
                                setTimeout(() => window.titanWhatsAppMessageSent = false, 3000);
                                break;
                            }
                        }
                    }
                }, true);
                
                // Monitor clicks on send buttons
                document.addEventListener('click', function(e) {
                    const sendSelectors = [
                        '[data-testid="send"]',
                        '[data-testid="compose-btn-send"]',
                        'button[aria-label*="Send"]',
                        'button[aria-label*="Wyślij"]',
                        'span[data-testid="send"] button'
                    ];
                    
                    for (let selector of sendSelectors) {
                        if (e.target.matches(selector) || e.target.closest(selector)) {
                            console.log('TITAN: WhatsApp send button clicked!');
                            window.titanWhatsAppMessageSent = true;
                            setTimeout(() => window.titanWhatsAppMessageSent = false, 3000);
                            break;
                        }
                    }
                }, true);
                
                // Also monitor for any SVG icons in buttons (WhatsApp uses SVG for send button)
                document.addEventListener('click', function(e) {
                    const button = e.target.closest('button');
                    if (button && button.querySelector('svg')) {
                        // Check if this looks like a send button area
                        const messageArea = button.closest('[data-testid*="compose"], [data-testid*="footer"]');
                        if (messageArea) {
                            console.log('TITAN: WhatsApp SVG button (likely send) clicked!');
                            window.titanWhatsAppMessageSent = true;
                            setTimeout(() => window.titanWhatsAppMessageSent = false, 3000);
                        }
                    }
                }, true);
                
                window.titanWhatsAppSetup = true;
                console.log('TITAN: WhatsApp message send monitoring setup complete!');
            })();
            """
            
            result = self.webview.RunScript(setup_script)
            print("✓ WhatsApp message send monitoring script injected")
            
            # Start monitoring timer for sent messages
            if not hasattr(self, 'send_monitor_timer'):
                self.send_monitor_timer = wx.Timer(self)
                self.Bind(wx.EVT_TIMER, self.check_message_sent, self.send_monitor_timer)
                self.send_monitor_timer.Start(1000)  # Check every 1 second
            
        except Exception as e:
            print(f"Error setting up WhatsApp message send monitoring: {e}")
    
    def check_message_sent(self, event):
        """Check if user sent a message - same as Messenger"""
        if not hasattr(self, 'webview') or not self.webview or not self.whatsapp_logged_in:
            return
        
        try:
            # Check if message was sent
            check_script = """
            (function() {
                var result = {
                    messageSent: !!window.titanWhatsAppMessageSent,
                    setup: !!window.titanWhatsAppSetup
                };
                
                if (result.messageSent) {
                    window.titanWhatsAppMessageSent = false; // Clear flag
                }
                
                return JSON.stringify(result);
            })();
            """
            
            result_str = self.webview.RunScript(check_script)
            if result_str:
                import json
                try:
                    # Handle WebView returning tuple
                    if isinstance(result_str, tuple) and len(result_str) >= 2:
                        success, actual_result = result_str
                        if success:
                            result_str = actual_result
                        else:
                            return
                    
                    # Check if result_str is already parsed or needs parsing
                    if isinstance(result_str, str):
                        result = json.loads(result_str)
                    elif isinstance(result_str, dict):
                        result = result_str
                    else:
                        # If it's an int or other type, create a dict
                        result = {'messageSent': False, 'setup': bool(result_str)}
                    
                    if result.get('messageSent'):
                        print("🚀 WhatsApp MESSAGE SENT DETECTED! Playing sound...")
                        
                        if self.notifications_item.IsChecked():
                            # Play message send sound like in Telegram/Messenger
                            play_sound('titannet/message_send.ogg')
                            print("✓ WhatsApp message sent - played message_send.ogg")
                            
                            # TTS for sent message (optional)
                            if self.tts_item.IsChecked():
                                try:
                                    from stereo_speech import get_stereo_speech
                                    stereo_speech = get_stereo_speech()
                                    
                                    if stereo_speech.is_stereo_enabled():
                                        # Use stereo speech for sent confirmation with lower pitch
                                        stereo_speech.speak(_("Message sent"), position=0.0, pitch_offset=-2, use_fallback=False)
                                    else:
                                        import accessible_output3.outputs.auto
                                        speaker = accessible_output3.outputs.auto.Auto()
                                        speaker.speak(_("Message sent"))
                                except ImportError:
                                    import accessible_output3.outputs.auto
                                    speaker = accessible_output3.outputs.auto.Auto()
                                    speaker.speak(_("Message sent"))
                
                except json.JSONDecodeError as e:
                    print(f"JSON decode error in WhatsApp message sent check: {e}")
                    
        except Exception as e:
            print(f"Error checking WhatsApp message sent: {e}")
    
    def get_chat_list(self):
        """Get list of active conversations from WhatsApp Web - same as Messenger"""
        if not hasattr(self, 'webview') or not self.webview:
            return []
        
        # Only get chat list if user is logged in
        if not self.whatsapp_logged_in:
            print("get_chat_list: User not logged in yet")
            return []
        
        try:
            chat_list_script = """
            (function() {
                try {
                    console.log('TITAN: Starting WhatsApp chat list extraction...');
                    
                    // Enhanced selectors for current WhatsApp Web (2024/2025)
                    const chatSelectors = [
                        // Main conversation list containers
                        '[data-testid="chat-list"] div[role="listitem"]',
                        'div[aria-label*="Chat list"] div[role="listitem"]',
                        'div[aria-label*="Lista czatów"] div[role="listitem"]',
                        '[data-testid="contact-list-container"] div[role="listitem"]',
                        'div[id="pane-side"] div[role="listitem"]',
                        
                        // Alternative containers
                        '[data-testid="cell-frame-container"]',
                        'div[aria-label*="Chat list"] > div > div',
                        'div[role="main"] div[role="listitem"]',
                        
                        // Fallback selectors
                        'div[aria-label*="Chat list"] li',
                        'div[role="navigation"] li',
                        'div[id="pane-side"] li'
                    ];
                    
                    let conversations = [];
                    
                    for (let selector of chatSelectors) {
                        const chatElements = document.querySelectorAll(selector);
                        console.log(`TITAN: Trying selector "${selector}" - found ${chatElements.length} elements`);
                        
                        if (chatElements.length > 0) {
                            chatElements.forEach((element, index) => {
                                try {
                                    // Enhanced name extraction for current WhatsApp
                                    let name = '';
                                    const nameSelectors = [
                                        // Current WhatsApp name selectors (2024/2025)
                                        '[data-testid="conversation-title"] span',
                                        'span[title][dir="auto"]',
                                        'div[data-testid*="cell"] span[title]',
                                        'span[aria-label]',
                                        'div[role="heading"] span',
                                        
                                        // Fallback selectors
                                        'h3', 'span[dir="auto"]', '[data-testid="contact_name"]',
                                        'div[title]', 'strong', 'span[title]',
                                        'div:first-child span'
                                    ];
                                    
                                    for (let nameSelector of nameSelectors) {
                                        const nameEl = element.querySelector(nameSelector);
                                        if (nameEl && (nameEl.textContent.trim() || nameEl.title)) {
                                            name = nameEl.textContent.trim() || nameEl.title;
                                            break;
                                        }
                                    }
                                    
                                    // Enhanced last message extraction
                                    let lastMessage = '';
                                    const msgSelectors = [
                                        // Current WhatsApp message preview selectors
                                        '[data-testid="last-msg"] span[dir="auto"]',
                                        'div[data-testid*="cell"] span:last-child',
                                        'div:last-child span[dir="auto"]',
                                        'span[dir="auto"]:not([title])',
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
                                        if (msgEl && msgEl.textContent.trim() && 
                                            msgEl.textContent.trim() !== name) {
                                            lastMessage = msgEl.textContent.trim();
                                            break;
                                        }
                                    }
                                    
                                    // Check for unread status
                                    let unread = 0;
                                    const unreadSelectors = [
                                        '[data-testid="unread-count"]',
                                        'span[data-testid*="unread"]',
                                        '[aria-label*="unread message"]',
                                        'div[class*="unread"] span'
                                    ];
                                    
                                    for (let unreadSelector of unreadSelectors) {
                                        const unreadEl = element.querySelector(unreadSelector);
                                        if (unreadEl) {
                                            const unreadText = unreadEl.textContent.trim();
                                            if (unreadText && !isNaN(unreadText)) {
                                                unread = parseInt(unreadText);
                                                break;
                                            } else if (unreadEl.offsetWidth > 0) {
                                                unread = 1; // Visual indicator exists
                                                break;
                                            }
                                        }
                                    }
                                    
                                    // Only add if we have a name
                                    if (name && name.length > 0) {
                                        const conversation = {
                                            id: `whatsapp_${index}_${name.replace(/[^a-zA-Z0-9]/g, '_')}`,
                                            name: name,
                                            lastMessage: lastMessage || 'No preview available',
                                            unread: unread,
                                            platform: 'WhatsApp',
                                            type: 'whatsapp',
                                            timestamp: new Date().toLocaleTimeString()
                                        };
                                        
                                        conversations.push(conversation);
                                        console.log(`TITAN: Added WhatsApp conversation: ${name} (unread: ${unread})`);
                                    }
                                } catch (err) {
                                    console.log(`TITAN: Error processing WhatsApp chat element ${index}:`, err);
                                }
                            });
                            
                            // If we found conversations with this selector, break
                            if (conversations.length > 0) {
                                console.log(`TITAN: Successfully extracted ${conversations.length} WhatsApp conversations`);
                                break;
                            }
                        }
                    }
                    
                    return JSON.stringify({
                        success: true,
                        conversations: conversations,
                        totalFound: conversations.length,
                        timestamp: new Date().toISOString()
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
                    # Handle WebView returning tuple (success, result) instead of just result
                    if isinstance(result_str, tuple) and len(result_str) >= 2:
                        success, actual_result = result_str
                        if success:
                            result_str = actual_result
                        else:
                            print(f"WhatsApp chat list script failed: {actual_result}")
                            return []
                    
                    result = json.loads(result_str)
                    if result.get('success'):
                        return result.get('conversations', [])
                    else:
                        print(f"WhatsApp chat list extraction failed: {result.get('error')}")
                        return []
                except json.JSONDecodeError:
                    print(f"Failed to parse WhatsApp chat list result: {result_str}")
                    return []
            
        except Exception as e:
            print(f"Error getting WhatsApp chat list: {e}")
        
        return []
    
    def send_message_to_chat(self, chat_name, message):
        """Send message to specific WhatsApp chat - same as Messenger"""
        if not hasattr(self, 'webview') or not self.webview or not self.whatsapp_logged_in:
            print("Cannot send WhatsApp message: not connected")
            return False
        
        try:
            # JavaScript to find chat and send message
            send_message_script = f"""
            (function() {{
                try {{
                    console.log('TITAN: Attempting to send WhatsApp message to: {chat_name}');
                    
                    // First, find the chat in the list
                    const chatSelectors = [
                        '[data-testid="chat-list"] div[role="listitem"]',
                        'div[aria-label*="Chat list"] div[role="listitem"]',
                        '[data-testid="contact-list-container"] div[role="listitem"]',
                        '[data-testid="cell-frame-container"]'
                    ];
                    
                    let targetChat = null;
                    
                    for (let selector of chatSelectors) {{
                        const chats = document.querySelectorAll(selector);
                        for (let chat of chats) {{
                            const nameSelectors = [
                                '[data-testid="conversation-title"] span',
                                'span[title][dir="auto"]',
                                'span[aria-label]',
                                'span[title]'
                            ];
                            
                            for (let nameSelector of nameSelectors) {{
                                const nameEl = chat.querySelector(nameSelector);
                                if (nameEl) {{
                                    const chatName = nameEl.textContent.trim() || nameEl.title || '';
                                    if (chatName.toLowerCase().includes('{chat_name}'.toLowerCase()) || 
                                        '{chat_name}'.toLowerCase().includes(chatName.toLowerCase())) {{
                                        targetChat = chat;
                                        console.log('TITAN: Found WhatsApp target chat:', chatName);
                                        break;
                                    }}
                                }}
                            }}
                            if (targetChat) break;
                        }}
                        if (targetChat) break;
                    }}
                    
                    if (!targetChat) {{
                        console.log('TITAN: WhatsApp chat not found: {chat_name}');
                        return JSON.stringify({{
                            success: false,
                            error: 'Chat not found: {chat_name}',
                            step: 'chat_search'
                        }});
                    }}
                    
                    // Click on the chat to open it
                    targetChat.click();
                    console.log('TITAN: Clicked on WhatsApp chat');
                    
                    // Wait a moment for chat to load
                    setTimeout(() => {{
                        try {{
                            // Find message input
                            const inputSelectors = [
                                '[data-testid="compose-box-input"]',
                                'div[contenteditable="true"][data-tab="10"]',
                                '[data-testid="msg-input"]',
                                'div[role="textbox"][contenteditable="true"]',
                                'div[contenteditable="true"][spellcheck="true"]'
                            ];
                            
                            let messageInput = null;
                            for (let selector of inputSelectors) {{
                                messageInput = document.querySelector(selector);
                                if (messageInput) {{
                                    console.log('TITAN: Found WhatsApp message input with selector:', selector);
                                    break;
                                }}
                            }}
                            
                            if (!messageInput) {{
                                console.log('TITAN: WhatsApp message input not found');
                                return;
                            }}
                            
                            // Focus and type message
                            messageInput.focus();
                            messageInput.textContent = '{message}';
                            
                            // Trigger input events
                            const inputEvent = new Event('input', {{ bubbles: true }});
                            messageInput.dispatchEvent(inputEvent);
                            
                            // Find and click send button
                            setTimeout(() => {{
                                const sendSelectors = [
                                    '[data-testid="send"]',
                                    '[data-testid="compose-btn-send"]',
                                    'button[aria-label*="Send"]',
                                    'button[aria-label*="Wyślij"]',
                                    'span[data-testid="send"] button'
                                ];
                                
                                let sendButton = null;
                                for (let selector of sendSelectors) {{
                                    sendButton = document.querySelector(selector);
                                    if (sendButton && sendButton.offsetWidth > 0) {{
                                        console.log('TITAN: Found WhatsApp send button with selector:', selector);
                                        break;
                                    }}
                                }}
                                
                                if (sendButton) {{
                                    sendButton.click();
                                    console.log('TITAN: WhatsApp message sent successfully');
                                }} else {{
                                    // Try pressing Enter as fallback
                                    const enterEvent = new KeyboardEvent('keydown', {{
                                        key: 'Enter',
                                        code: 'Enter',
                                        keyCode: 13,
                                        bubbles: true
                                    }});
                                    messageInput.dispatchEvent(enterEvent);
                                    console.log('TITAN: Tried Enter key for WhatsApp message');
                                }}
                            }}, 500);
                            
                        }} catch (error) {{
                            console.log('TITAN: Error in WhatsApp message sending:', error);
                        }}
                    }}, 1000);
                    
                    return JSON.stringify({{
                        success: true,
                        message: 'WhatsApp message sending initiated',
                        chat: '{chat_name}'
                    }});
                    
                }} catch (error) {{
                    console.error('TITAN: WhatsApp send message error:', error);
                    return JSON.stringify({{
                        success: false,
                        error: error.toString(),
                        step: 'general_error'
                    }});
                }}
            }})();
            """
            
            result_str = self.webview.RunScript(send_message_script)
            if result_str:
                import json
                try:
                    # Handle WebView returning tuple (success, result) instead of just result
                    if isinstance(result_str, tuple) and len(result_str) >= 2:
                        success, actual_result = result_str
                        if success:
                            result_str = actual_result
                        else:
                            print(f"WhatsApp send message script failed: {actual_result}")
                            return False
                    
                    result = json.loads(result_str)
                    return result.get('success', False)
                except json.JSONDecodeError:
                    print(f"Failed to parse WhatsApp send message result: {result_str}")
                    return False
        
        except Exception as e:
            print(f"Error sending WhatsApp message: {e}")
            return False
        
        return False
    
    def setup_voice_call_monitoring(self):
        """Setup voice call detection for WhatsApp Web - same as Messenger"""
        if not hasattr(self, 'webview') or not self.webview or not self.whatsapp_logged_in:
            # Retry in 3 seconds if not logged in yet
            wx.CallLater(3000, self.setup_voice_call_monitoring)
            return
        
        print("Setting up WhatsApp voice call monitoring...")
        
        # Inject enhanced WebRTC and DOM monitoring JavaScript for WhatsApp
        webrtc_script = """
        (function() {
            console.log('TITAN: Setting up WhatsApp voice call monitoring...');
            
            if (window.titanWhatsAppVoiceSetup) {
                console.log('WhatsApp voice monitoring already setup');
                return;
            }
            
            // Initialize call state
            window.titanCallState = window.titanCallState || {
                isCallActive: false,
                callType: 'unknown',
                callStartTime: null,
                peerConnection: null,
                callUIVisible: false
            };
            
            // Override WebRTC APIs for WhatsApp
            const originalRTCPeerConnection = window.RTCPeerConnection || window.webkitRTCPeerConnection;
            
            if (originalRTCPeerConnection) {
                window.RTCPeerConnection = function(...args) {
                    console.log('TITAN: WhatsApp RTCPeerConnection created');
                    const pc = new originalRTCPeerConnection(...args);
                    window.titanCallState.peerConnection = pc;
                    
                    pc.addEventListener('connectionstatechange', () => {
                        const state = pc.connectionState;
                        console.log('TITAN: WhatsApp connection state:', state);
                        
                        if (state === 'connected') {
                            window.titanCallState.isCallActive = true;
                            window.titanCallConnected = true;
                            console.log('TITAN: WhatsApp call connected');
                        } else if (state === 'disconnected' || state === 'failed' || state === 'closed') {
                            window.titanCallState.isCallActive = false;
                            window.titanCallEnded = true;
                            console.log('TITAN: WhatsApp call ended');
                        }
                    });
                    
                    return pc;
                };
                
                // Copy static methods
                Object.setPrototypeOf(window.RTCPeerConnection, originalRTCPeerConnection);
                Object.defineProperty(window.RTCPeerConnection, 'prototype', {
                    value: originalRTCPeerConnection.prototype
                });
            }
            
            // Monitor WhatsApp call UI elements
            const observer = new MutationObserver(function(mutations) {
                mutations.forEach(function(mutation) {
                    mutation.addedNodes.forEach(function(node) {
                        if (node.nodeType === 1) {
                            // WhatsApp call UI selectors
                            const callSelectors = [
                                '[data-testid*="call"]',
                                '[aria-label*="Call"]',
                                '[aria-label*="End call"]',
                                '[aria-label*="Mute"]',
                                '[aria-label*="Video"]',
                                'div[class*="call"]'
                            ];
                            
                            let callUIFound = false;
                            
                            callSelectors.forEach(selector => {
                                if (node.matches && node.matches(selector)) {
                                    console.log('TITAN: WhatsApp call UI detected:', selector);
                                    callUIFound = true;
                                } else if (node.querySelector && node.querySelector(selector)) {
                                    console.log('TITAN: WhatsApp call UI found in subtree:', selector);
                                    callUIFound = true;
                                }
                            });
                            
                            if (callUIFound) {
                                window.titanCallState.callUIVisible = true;
                                window.titanCallUIAppeared = true;
                                
                                // Determine call type by checking button labels
                                const endButton = document.querySelector('[aria-label*="End call"]');
                                if (endButton) {
                                    window.titanOutgoingCall = true;
                                    console.log('TITAN: WhatsApp outgoing call detected');
                                } else {
                                    window.titanIncomingCall = true;
                                    console.log('TITAN: WhatsApp incoming call detected');
                                }
                            }
                        }
                    });
                    
                    mutation.removedNodes.forEach(function(node) {
                        if (node.nodeType === 1) {
                            const wasCallUI = node.className && (
                                node.className.includes('call') || 
                                node.className.includes('voice') ||
                                node.querySelector('[data-testid*="call"]')
                            );
                            
                            if (wasCallUI) {
                                console.log('TITAN: WhatsApp call UI disappeared');
                                window.titanCallState.callUIVisible = false;
                                window.titanCallUIDisappeared = true;
                            }
                        }
                    });
                });
            });
            
            observer.observe(document.body, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['class', 'aria-label', 'data-testid']
            });
            
            window.titanWhatsAppVoiceSetup = true;
            window.titanVoiceObserver = observer;
            console.log('TITAN: WhatsApp voice call monitoring setup complete!');
            
        })();
        """
        
        try:
            result = self.webview.RunScript(webrtc_script)
            print("✓ WhatsApp voice call monitoring script injected")
            
            # Start voice call monitoring timer
            if not hasattr(self, 'voice_timer'):
                self.voice_timer = wx.Timer(self)
                self.Bind(wx.EVT_TIMER, self.check_voice_call_status, self.voice_timer)
                self.voice_timer.Start(2000)  # Check every 2 seconds
                
        except Exception as e:
            print(f"Voice setup error: {e}")
    
    def check_voice_call_status(self, event=None):
        """Check for voice call status changes"""
        if not hasattr(self, 'webview') or not self.webview or not self.whatsapp_logged_in:
            return
        
        try:
            call_check_script = """
            (function() {
                if (!window.titanWhatsAppVoiceSetup) return JSON.stringify({status: 'not_setup'});
                
                var result = {
                    isCallActive: window.titanCallState ? window.titanCallState.isCallActive : false,
                    incomingCall: !!window.titanIncomingCall,
                    outgoingCall: !!window.titanOutgoingCall,
                    callConnected: !!window.titanCallConnected,
                    callEnded: !!window.titanCallEnded,
                    callUIAppeared: !!window.titanCallUIAppeared,
                    callUIDisappeared: !!window.titanCallUIDisappeared,
                    callUIVisible: window.titanCallState ? window.titanCallState.callUIVisible : false
                };
                
                // Clear one-time flags
                window.titanIncomingCall = false;
                window.titanOutgoingCall = false;
                window.titanCallConnected = false;
                window.titanCallEnded = false;
                window.titanCallUIAppeared = false;
                window.titanCallUIDisappeared = false;
                
                return JSON.stringify(result);
            })();
            """
            
            result_str = self.webview.RunScript(call_check_script)
            if result_str:
                import json
                try:
                    # Handle WebView returning tuple
                    if isinstance(result_str, tuple) and len(result_str) >= 2:
                        success, actual_result = result_str
                        if success:
                            result_str = actual_result
                        else:
                            return
                    
                    if isinstance(result_str, str):
                        result = json.loads(result_str)
                    else:
                        return
                    
                    # Handle incoming call
                    if result.get('incomingCall'):
                        self.on_incoming_call()
                    
                    # Handle outgoing call
                    if result.get('outgoingCall'):
                        self.on_outgoing_call()
                    
                    # Handle call connected
                    if result.get('callConnected'):
                        self.on_call_connected()
                    
                    # Handle call ended
                    if result.get('callEnded') or result.get('callUIDisappeared'):
                        self.on_call_ended()
                
                except json.JSONDecodeError as e:
                    print(f"Voice call check JSON error: {e}")
                    
        except Exception as e:
            if "'int' object has no attribute 'get'" not in str(e):
                print(f"Voice call check error: {e}")
    
    def on_incoming_call(self):
        """Handle incoming WhatsApp call"""
        print("📞 WhatsApp incoming call detected")
        
        # Play incoming call sound
        if self.notifications_item.IsChecked():
            play_sound('titannet/ring_in.ogg')
            print("✓ Incoming WhatsApp call - played ring_in.ogg")
        
        if self.tts_item.IsChecked():
            try:
                import accessible_output3.outputs.auto
                speaker = accessible_output3.outputs.auto.Auto()
                speaker.speak(_("Incoming WhatsApp call"))
            except:
                pass
    
    def on_outgoing_call(self):
        """Handle outgoing WhatsApp call"""
        print("📞 WhatsApp outgoing call detected")
        
        # Play outgoing call sound
        if self.notifications_item.IsChecked():
            play_sound('titannet/ring_out.ogg')
            print("✓ Outgoing WhatsApp call - played ring_out.ogg")
        
        if self.tts_item.IsChecked():
            try:
                import accessible_output3.outputs.auto
                speaker = accessible_output3.outputs.auto.Auto()
                speaker.speak(_("WhatsApp call connecting"))
            except:
                pass
    
    def on_call_connected(self):
        """Handle WhatsApp call connected"""
        print("✅ WhatsApp call connected")
        
        # Play call success sound
        if self.notifications_item.IsChecked():
            play_sound('titannet/callsuccess.ogg')
            print("✓ WhatsApp call connected - played callsuccess.ogg")
        
        if self.tts_item.IsChecked():
            try:
                import accessible_output3.outputs.auto
                speaker = accessible_output3.outputs.auto.Auto()
                speaker.speak(_("WhatsApp call connected"))
            except:
                pass
    
    def on_call_ended(self):
        """Handle WhatsApp call ended"""
        print("📞 WhatsApp call ended")
        
        # Play call end sound
        if self.notifications_item.IsChecked():
            play_sound('titannet/bye.ogg')
            print("✓ WhatsApp call ended - played bye.ogg")
        
        if self.tts_item.IsChecked():
            try:
                import accessible_output3.outputs.auto
                speaker = accessible_output3.outputs.auto.Auto()
                speaker.speak(_("WhatsApp call ended"))
            except:
                pass
    
    def _execute_notification_script(self, count=None):
        """Execute JavaScript to interact with WhatsApp Web - same as Messenger"""
        if not hasattr(self, 'webview') or not self.webview:
            return
        
        try:
            # Enhanced WhatsApp Web interaction script (same pattern as Messenger)
            whatsapp_script = f"""
            (function() {{
                console.log('TITAN: WhatsApp Web notification script started');
                
                try {{
                    // Mark messages as seen/read (same as Messenger functionality)
                    const unreadChats = document.querySelectorAll(
                        '[data-testid="cell-frame-container"][aria-label*="unread"], ' +
                        '[data-testid*="unread"], ' +
                        'div[data-testid="chat-list"] > div[class*="unread"], ' +
                        'div[aria-label*="unread message"]'
                    );
                    
                    console.log(`TITAN: Found ${{unreadChats.length}} unread WhatsApp chats`);
                    
                    // Auto-scroll to latest messages (same as Messenger)
                    const chatArea = document.querySelector('[data-testid="conversation-panel-messages"]');
                    if (chatArea) {{
                        chatArea.scrollTop = chatArea.scrollHeight;
                        console.log('TITAN: Auto-scrolled to latest WhatsApp messages');
                    }}
                    
                    // Focus chat input for accessibility (same as Messenger)
                    const chatInput = document.querySelector(
                        '[data-testid="compose-box-input"], ' +
                        'div[contenteditable="true"][data-tab="10"], ' +
                        '[data-testid="msg-input"], ' +
                        'div[role="textbox"][contenteditable="true"]'
                    );
                    
                    if (chatInput && document.activeElement !== chatInput) {{
                        setTimeout(() => {{
                            try {{
                                chatInput.focus();
                                console.log('TITAN: Focused WhatsApp chat input');
                            }} catch (e) {{
                                console.log('TITAN: Could not focus WhatsApp chat input:', e);
                            }}
                        }}, 500);
                    }}
                    
                    // Accessibility improvements (same as Messenger)
                    const messageElements = document.querySelectorAll('[data-testid="msg-container"]');
                    console.log(`TITAN: Found ${{messageElements.length}} WhatsApp message elements`);
                    
                    // Add keyboard shortcuts info (same as Messenger pattern)
                    if (!document.querySelector('#titan-whatsapp-shortcuts')) {{
                        const shortcutInfo = document.createElement('div');
                        shortcutInfo.id = 'titan-whatsapp-shortcuts';
                        shortcutInfo.style.cssText = 'position: fixed; top: -1000px; left: -1000px; opacity: 0;';
                        shortcutInfo.setAttribute('aria-hidden', 'true');
                        shortcutInfo.textContent = 'Titan IM WhatsApp shortcuts: F5=Refresh, Ctrl+Shift+I=DevTools, Tab=Navigate';
                        document.body.appendChild(shortcutInfo);
                    }}
                    
                    return {{
                        success: true,
                        unreadCount: unreadChats.length,
                        messagesFound: messageElements.length,
                        chatInputFound: !!chatInput,
                        timestamp: new Date().toISOString()
                    }};
                    
                }} catch (error) {{
                    console.error('TITAN: WhatsApp script error:', error);
                    return {{
                        success: false,
                        error: error.toString(),
                        timestamp: new Date().toISOString()
                    }};
                }}
            }})();
            """
            
            # Execute the script
            result = self.webview.RunScript(whatsapp_script)
            if result:
                print(f"✓ WhatsApp notification script executed: {result}")
            
        except Exception as e:
            print(f"Error executing WhatsApp notification script: {e}")
    
    def on_title_changed(self, event):
        """Handle title change"""
        title = event.GetString()
        
        # Check for new message notifications in title and update window title like Telegram/Messenger
        if "(" in title and ")" in title:
            import re
            match = re.search(r'\((\d+)\)', title)
            if match:
                count = int(match.group(1))
                if count > 0:
                    # Show unread count in window title like Telegram/Messenger
                    self.SetTitle(f"[{count}] WhatsApp Web - Titan IM")
                    
                    # Trigger notification if enabled
                    if self.notifications_item.IsChecked():
                        self.on_notification_detected(title, count)
                else:
                    # No unread messages
                    self.SetTitle("WhatsApp Web - Titan IM")
            else:
                self.SetTitle(f"{title} - Titan IM")
        else:
            # No unread count in title
            self.SetTitle(f"{title} - Titan IM")
    
    def on_webview_error(self, event):
        """Handle WebView errors"""
        url = event.GetURL()
        error = event.GetString()
        
        print(f"WhatsApp WebView error loading {url}: {error}")
        self.SetStatusText(_("Błąd ładowania strony"))
        
        # Play error sound
        play_sound('error.ogg')
        
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
            # Developer tools shortcut
            pass
        else:
            event.Skip()
    
    def on_refresh(self, event):
        """Refresh WhatsApp Web"""
        if hasattr(self, 'webview') and self.webview:
            self.webview.Reload()
            self.SetStatusText(_("Odświeżanie WhatsApp Web..."))
            self.whatsapp_logged_in = False
            wx.CallLater(3000, self.check_login_status)
    
    def on_clear_cookies(self, event):
        """Clear WhatsApp cookies and session data"""
        dialog = wx.MessageDialog(
            self,
            _("Czy na pewno chcesz wyczyścić wszystkie dane sesji WhatsApp?\nBędziesz musiał zalogować się ponownie."),
            _("Wyczyść dane sesji"),
            wx.YES_NO | wx.ICON_QUESTION
        )
        
        if dialog.ShowModal() == wx.ID_YES:
            if clear_whatsapp_cookies():
                wx.MessageBox(_("Dane sesji zostały wyczyszczone.\nOdśwież stronę, aby zalogować się ponownie."), 
                             _("Sukces"), wx.OK | wx.ICON_INFORMATION)
                self.on_refresh(None)
            else:
                wx.MessageBox(_("Nie udało się wyczyścić danych sesji."), 
                             _("Błąd"), wx.OK | wx.ICON_ERROR)
        
        dialog.Destroy()
    
    def on_about(self, event):
        """Show about dialog"""
        info = wx.adv.AboutDialogInfo()
        info.SetName("WhatsApp Web - Titan IM")
        info.SetVersion("1.0")
        info.SetDescription(_("Integracja WhatsApp Web z systemem Titan IM.\nUmożliwia korzystanie z WhatsApp w ramach TCE Launcher."))
        info.SetWebSite("https://github.com/dawidpieper/Titanium-Community-Edition", "Titan Community Edition")
        info.AddDeveloper("Titan IM Team")
        
        wx.adv.AboutBox(info)
    
    def add_message_callback(self, callback):
        """Add callback for message events"""
        self.message_callbacks.append(callback)
    
    def add_status_callback(self, callback):
        """Add callback for status events"""
        self.status_callbacks.append(callback)
    
    def on_close(self, event):
        """Handle window close safely - same as Messenger"""
        print("✓ WhatsApp WebView disconnecting...")
        
        # Play disconnect sound
        try:
            play_sound('titannet/bye.ogg')
            print("✓ WhatsApp WebView disconnect sound played")
        except:
            pass
        
        # Stop all timers safely
        try:
            self.whatsapp_logged_in = False
            
            if hasattr(self, 'notification_timer') and self.notification_timer:
                self.notification_timer.Stop()
                self.notification_timer = None
                
            if hasattr(self, 'send_monitor_timer') and self.send_monitor_timer:
                self.send_monitor_timer.Stop()
                self.send_monitor_timer = None
                
            if hasattr(self, 'voice_timer') and self.voice_timer:
                self.voice_timer.Stop()
                self.voice_timer = None
                
            if hasattr(self, 'typing_timer') and self.typing_timer:
                self.typing_timer.Stop()
                self.typing_timer = None
                
        except Exception as e:
            print(f"Error stopping WhatsApp timers: {e}")
        
        # Safe WebView cleanup
        try:
            if hasattr(self, 'webview') and self.webview:
                # Clear JavaScript state
                try:
                    self.webview.RunScript("window.titanWhatsAppMessageSent = false; window.titanWhatsAppSetup = false; window.titanWhatsAppVoiceSetup = false;")
                except:
                    pass
                
                # Stop WebView
                try:
                    self.webview.Stop()
                except:
                    pass
                    
        except Exception as e:
            print(f"Error cleaning up WhatsApp WebView: {e}")
        
        # Notify status callbacks about disconnection
        try:
            for callback in self.status_callbacks:
                try:
                    wx.CallAfter(callback, 'disconnected', None)
                except:
                    pass
        except Exception as e:
            print(f"Error notifying WhatsApp callbacks: {e}")
        
        # TTS announcement
        try:
            import accessible_output3.outputs.auto
            speaker = accessible_output3.outputs.auto.Auto()
            speaker.speak(_("Disconnected from WhatsApp Web"))
        except:
            pass
        
        print("✓ WhatsApp WebView disconnected")
        
        # Safe window destroy
        try:
            self.Destroy()
        except Exception as e:
            print(f"Error destroying WhatsApp window: {e}")

# Module-level instance tracking (same pattern as Messenger)
_whatsapp_instance = None

def get_whatsapp_instance():
    """Get the current WhatsApp WebView instance"""
    global _whatsapp_instance
    if _whatsapp_instance and not _whatsapp_instance.IsBeingDeleted():
        return _whatsapp_instance
    return None

def show_whatsapp_webview(parent=None):
    """Show WhatsApp WebView window"""
    global _whatsapp_instance
    
    # Check if instance already exists
    if _whatsapp_instance and not _whatsapp_instance.IsBeingDeleted():
        _whatsapp_instance.Raise()
        _whatsapp_instance.Show()
        return _whatsapp_instance
    
    try:
        _whatsapp_instance = WhatsAppWebViewFrame(parent)
        _whatsapp_instance.Show()
        return _whatsapp_instance
        
    except Exception as e:
        print(f"Error creating WhatsApp WebView: {e}")
        if wx.GetApp():  # Only show MessageBox if wx.App exists
            wx.MessageBox(
                _("Nie można uruchomić WhatsApp WebView.\n"
                  "Sprawdź czy WebView2 jest zainstalowany.\n"
                  "Błąd: {}").format(str(e)),
                _("Błąd WhatsApp WebView"),
                wx.OK | wx.ICON_ERROR
            )
        return None

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
        frame = show_whatsapp_webview()
        if frame:
            app.MainLoop()