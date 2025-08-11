# -*- coding: utf-8 -*-
import asyncio
import json
import os
import pickle
import threading
import time
import wx
import requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from sound import play_sound
from translation import set_language
from settings import get_setting
from titan_im_config import (
    initialize_config, load_titan_im_config, save_titan_im_config
)

# Initialize translation
_ = set_language(get_setting('language', 'pl'))

# Initialize configuration
initialize_config()

class MessengerClient:
    def __init__(self):
        self.driver = None
        self.is_connected = False
        self.message_callbacks = []
        self.status_callbacks = []
        self.typing_callbacks = []
        self.user_data = None
        self.conversations = {}
        self.current_conversation = None
        self.monitoring_thread = None
        self.cookies_file = os.path.join(os.path.dirname(__file__), 'messenger_cookies.pkl')
        self.last_message_count = {}
        self.driver_options = None
        
    def add_message_callback(self, callback):
        """Add callback for new messages"""
        self.message_callbacks.append(callback)
    
    def add_status_callback(self, callback):
        """Add callback for user status changes"""
        self.status_callbacks.append(callback)
    
    def add_typing_callback(self, callback):
        """Add callback for typing indicators"""
        self.typing_callbacks.append(callback)
    
    def detect_available_browsers(self):
        """Detect which browsers are available on the system"""
        available_browsers = []
        
        print("Wykrywanie przeglądarek...")
        
        # Check for Chrome
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        ]
        for path in chrome_paths:
            if os.path.exists(path):
                available_browsers.append("chrome")
                print(f"✓ Chrome znaleziony: {path}")
                break
        else:
            print("✗ Chrome nie znaleziony")
            
        # Check for Firefox
        firefox_paths = [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"
        ]
        for path in firefox_paths:
            if os.path.exists(path):
                available_browsers.append("firefox")
                print(f"✓ Firefox znaleziony: {path}")
                break
        else:
            print("✗ Firefox nie znaleziony")
            
        # Check for Edge
        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Windows\SystemApps\Microsoft.MicrosoftEdge_8wekyb3d8bbwe\MicrosoftEdge.exe"  # Legacy Edge
        ]
        for path in edge_paths:
            if os.path.exists(path):
                available_browsers.append("edge")
                print(f"✓ Edge znaleziony: {path}")
                break
        else:
            print("✗ Edge nie znaleziony")
        
        print(f"Dostępne przeglądarki: {available_browsers}")
        return available_browsers
    
    def setup_chrome_driver(self):
        """Setup Chrome WebDriver"""
        try:
            chrome_options = ChromeOptions()
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-web-security')
            chrome_options.add_argument('--allow-running-insecure-content')
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            
            # Enable persistent session
            profile_dir = os.path.join(os.path.dirname(__file__), 'messenger_profile_chrome')
            os.makedirs(profile_dir, exist_ok=True)
            chrome_options.add_argument(f'--user-data-dir={profile_dir}')
            
            service = ChromeService(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            return True
        except Exception as e:
            print(f"Błąd Chrome WebDriver: {e}")
            return False
    
    def setup_firefox_driver(self):
        """Setup Firefox WebDriver"""
        try:
            firefox_options = FirefoxOptions()
            firefox_options.add_argument('--disable-blink-features=AutomationControlled')
            firefox_options.set_preference("dom.webdriver.enabled", False)
            firefox_options.set_preference('useAutomationExtension', False)
            firefox_options.set_preference("general.useragent.override", 
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0")
            
            # Enable persistent profile
            profile_dir = os.path.join(os.path.dirname(__file__), 'messenger_profile_firefox')
            os.makedirs(profile_dir, exist_ok=True)
            
            service = FirefoxService(GeckoDriverManager().install())
            self.driver = webdriver.Firefox(service=service, options=firefox_options)
            return True
        except Exception as e:
            print(f"Błąd Firefox WebDriver: {e}")
            return False
    
    def setup_edge_driver(self):
        """Setup Edge WebDriver"""
        try:
            edge_options = EdgeOptions()
            edge_options.add_argument('--no-sandbox')
            edge_options.add_argument('--disable-dev-shm-usage')
            edge_options.add_argument('--disable-gpu')
            edge_options.add_argument('--disable-extensions')
            edge_options.add_argument('--disable-blink-features=AutomationControlled')
            edge_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            edge_options.add_experimental_option('useAutomationExtension', False)
            edge_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0")
            
            # Try without persistent profile first (Edge can be finicky with profiles)
            try:
                service = EdgeService(EdgeChromiumDriverManager().install())
                self.driver = webdriver.Edge(service=service, options=edge_options)
                self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                return True
            except Exception as profile_error:
                print(f"Edge failed without profile: {profile_error}")
                
                # Try with simpler options
                edge_options = EdgeOptions()
                edge_options.add_argument('--disable-blink-features=AutomationControlled')
                edge_options.add_experimental_option("excludeSwitches", ["enable-automation"])
                
                service = EdgeService(EdgeChromiumDriverManager().install())
                self.driver = webdriver.Edge(service=service, options=edge_options)
                return True
                
        except Exception as e:
            print(f"Błąd Edge WebDriver: {e}")
            print(f"Edge error details: {str(e)}")
            
            # Try system Edge if webdriver-manager fails
            try:
                print("Trying system Edge driver...")
                edge_options = EdgeOptions()
                edge_options.add_argument('--disable-blink-features=AutomationControlled')
                
                # Try to use system Edge driver
                self.driver = webdriver.Edge(options=edge_options)
                return True
            except Exception as system_error:
                print(f"System Edge also failed: {system_error}")
                return False
    
    def setup_driver(self):
        """Setup WebDriver with automatic browser detection"""
        available_browsers = self.detect_available_browsers()
        
        if not available_browsers:
            wx.MessageBox(
                _("No supported browser found!\n"
                  "Please install one of: Chrome, Firefox, or Edge."),
                _("Browser Error"),
                wx.OK | wx.ICON_ERROR
            )
            return False
        
        # Try browsers in order of preference
        browser_methods = {
            'chrome': self.setup_chrome_driver,
            'firefox': self.setup_firefox_driver, 
            'edge': self.setup_edge_driver
        }
        
        # Let user choose if multiple browsers available
        if len(available_browsers) > 1:
            choices = []
            choice_map = {}
            
            if 'chrome' in available_browsers:
                choices.append("Google Chrome")
                choice_map["Google Chrome"] = 'chrome'
            if 'firefox' in available_browsers:
                choices.append("Mozilla Firefox")
                choice_map["Mozilla Firefox"] = 'firefox'
            if 'edge' in available_browsers:
                choices.append("Microsoft Edge")
                choice_map["Microsoft Edge"] = 'edge'
                
            dlg = wx.SingleChoiceDialog(
                None,
                _("Multiple browsers detected. Choose one for Messenger:"),
                _("Browser Selection"),
                choices
            )
            
            if dlg.ShowModal() == wx.ID_OK:
                selected_browser = choice_map[dlg.GetStringSelection()]
                dlg.Destroy()
            else:
                dlg.Destroy()
                return False
        else:
            selected_browser = available_browsers[0]
        
        print(f"Using browser: {selected_browser}")
        
        # Try to setup selected browser
        print(f"Próba uruchomienia: {selected_browser}")
        try:
            success = browser_methods[selected_browser]()
            if success:
                print(f"✓ Pomyślnie uruchomiono {selected_browser}")
                return True
        except Exception as e:
            print(f"✗ Błąd {selected_browser}: {e}")
        
        # If selected browser failed, try others
        for browser in available_browsers:
            if browser != selected_browser:
                try:
                    print(f"Próba fallback: {browser}")
                    success = browser_methods[browser]()
                    if success:
                        print(f"✓ Fallback sukces: {browser}")
                        return True
                except Exception as e:
                    print(f"✗ Fallback błąd {browser}: {e}")
                    continue
        
        # If all failed, show detailed error
        wx.MessageBox(
            _("Failed to start any browser!\n\n"
              "Possible solutions:\n"
              "1. Update your browser to the latest version\n"
              "2. Run as administrator\n" 
              "3. Install Chrome, Firefox, or newer Edge\n"
              "4. Check antivirus settings"),
            _("Browser Startup Error"),
            wx.OK | wx.ICON_ERROR
        )
        return False
    
    def save_cookies(self):
        """Save cookies to file for persistent login"""
        try:
            if self.driver:
                cookies = self.driver.get_cookies()
                with open(self.cookies_file, 'wb') as f:
                    pickle.dump(cookies, f)
                print("Cookies zapisane pomyślnie")
        except Exception as e:
            print(f"Błąd podczas zapisywania cookies: {e}")
    
    def load_cookies(self):
        """Load cookies from file"""
        try:
            if os.path.exists(self.cookies_file):
                with open(self.cookies_file, 'rb') as f:
                    cookies = pickle.load(f)
                
                # Navigate to Facebook first
                self.driver.get("https://www.facebook.com")
                time.sleep(2)
                
                # Add cookies
                for cookie in cookies:
                    try:
                        self.driver.add_cookie(cookie)
                    except Exception as e:
                        print(f"Nie można dodać cookie: {e}")
                
                print("Cookies załadowane pomyślnie")
                return True
        except Exception as e:
            print(f"Błąd podczas ładowania cookies: {e}")
        
        return False
    
    def start_connection(self, email=None, password=None):
        """Start Messenger connection"""
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            return False
        
        self.monitoring_thread = threading.Thread(
            target=self._run_messenger_client,
            args=(email, password),
            daemon=True
        )
        self.monitoring_thread.start()
        return True
    
    def _run_messenger_client(self, email, password):
        """Run Messenger client in separate thread"""
        try:
            if not self.setup_driver():
                wx.CallAfter(self._notify_error, "Nie można uruchomić przeglądarki Chrome")
                return
            
            # Try to load existing cookies
            cookies_loaded = self.load_cookies()
            
            # Navigate to Messenger
            self.driver.get("https://www.messenger.com")
            time.sleep(3)
            
            # Check if already logged in
            if not self._is_logged_in():
                if not cookies_loaded and email and password:
                    # Login with credentials
                    success = self._login_with_credentials(email, password)
                    if not success:
                        wx.CallAfter(self._notify_error, "Logowanie nieudane")
                        return
                else:
                    # Need manual login
                    wx.CallAfter(self._notify_manual_login)
                    # Wait for manual login
                    max_wait = 300  # 5 minutes
                    while max_wait > 0 and not self._is_logged_in():
                        time.sleep(1)
                        max_wait -= 1
                    
                    if not self._is_logged_in():
                        wx.CallAfter(self._notify_error, "Timeout podczas oczekiwania na logowanie")
                        return
            
            # Save cookies after successful login
            self.save_cookies()
            
            # Get user info
            self.user_data = self._get_user_info()
            self.is_connected = True
            
            # Load conversations
            self._load_conversations()
            
            # Notify success
            wx.CallAfter(self._notify_connection_success)
            
            # Start monitoring for new messages
            self._monitor_messages()
            
        except Exception as e:
            print(f"Błąd Messenger client: {e}")
            wx.CallAfter(self._notify_error, f"Błąd połączenia: {e}")
        finally:
            if self.driver:
                self.driver.quit()
            self.is_connected = False
    
    def _is_logged_in(self):
        """Check if user is logged in to Messenger"""
        try:
            # Check for presence of conversations or chat list
            WebDriverWait(self.driver, 5).until(
                EC.any_of(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="conversation"]')),
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[role="main"]')),
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="mwchat-window"]'))
                )
            )
            return True
        except TimeoutException:
            return False
    
    def _login_with_credentials(self, email, password):
        """Login with email and password"""
        try:
            # Navigate to Facebook login if not already there
            if "facebook.com" not in self.driver.current_url:
                self.driver.get("https://www.facebook.com")
                time.sleep(2)
            
            # Find and fill email field
            email_field = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "email"))
            )
            email_field.clear()
            email_field.send_keys(email)
            
            # Find and fill password field
            password_field = self.driver.find_element(By.ID, "pass")
            password_field.clear()
            password_field.send_keys(password)
            
            # Click login button
            login_button = self.driver.find_element(By.NAME, "login")
            login_button.click()
            
            # Wait for login to complete
            time.sleep(5)
            
            # Navigate back to Messenger
            self.driver.get("https://www.messenger.com")
            time.sleep(3)
            
            return self._is_logged_in()
            
        except Exception as e:
            print(f"Błąd podczas logowania: {e}")
            return False
    
    def _get_user_info(self):
        """Get current user information"""
        try:
            # Try to get user name from Messenger interface
            user_name = "Messenger User"
            try:
                # Look for user profile elements
                profile_elements = self.driver.find_elements(By.CSS_SELECTOR, '[role="button"][aria-label*="profile"]')
                if profile_elements:
                    user_name = profile_elements[0].get_attribute('aria-label').replace(' profile', '')
            except:
                pass
            
            return {
                'username': user_name,
                'platform': 'Facebook Messenger'
            }
        except Exception as e:
            print(f"Błąd podczas pobierania danych użytkownika: {e}")
            return {'username': 'Messenger User', 'platform': 'Facebook Messenger'}
    
    def _load_conversations(self):
        """Load available conversations"""
        try:
            # Wait for conversations to load
            time.sleep(3)
            
            # Find conversation elements
            conversation_elements = self.driver.find_elements(By.CSS_SELECTOR, '[data-testid="conversation"]')
            
            conversations = {}
            for i, conv_elem in enumerate(conversation_elements[:20]):  # Limit to first 20
                try:
                    # Get conversation name
                    name_elem = conv_elem.find_element(By.CSS_SELECTOR, '[role="link"]')
                    conv_name = name_elem.get_attribute('aria-label') or f"Conversation {i+1}"
                    
                    # Get conversation ID or index
                    conv_id = conv_elem.get_attribute('id') or str(i)
                    
                    conversations[conv_id] = {
                        'name': conv_name,
                        'element': conv_elem,
                        'id': conv_id
                    }
                except Exception as e:
                    print(f"Błąd podczas parsowania konwersacji: {e}")
                    continue
            
            self.conversations = conversations
            
            # Notify about loaded conversations
            for callback in self.status_callbacks:
                try:
                    wx.CallAfter(callback, 'conversations_loaded', list(conversations.values()))
                except:
                    pass
                    
        except Exception as e:
            print(f"Błąd podczas ładowania konwersacji: {e}")
    
    def _monitor_messages(self):
        """Monitor for new messages"""
        while self.is_connected and self.driver:
            try:
                # Check for new messages in current conversation
                if self.current_conversation:
                    self._check_new_messages()
                
                # Check for new conversation notifications
                self._check_conversation_notifications()
                
                time.sleep(2)  # Check every 2 seconds
                
            except Exception as e:
                print(f"Błąd podczas monitorowania wiadomości: {e}")
                time.sleep(5)  # Wait longer on error
    
    def _check_new_messages(self):
        """Check for new messages in current conversation"""
        try:
            # Find message elements
            message_elements = self.driver.find_elements(By.CSS_SELECTOR, '[data-testid="message_text"]')
            
            current_count = len(message_elements)
            conv_id = self.current_conversation['id']
            last_count = self.last_message_count.get(conv_id, 0)
            
            if current_count > last_count:
                # New messages detected
                new_messages = message_elements[last_count:]
                
                for msg_elem in new_messages:
                    try:
                        message_text = msg_elem.text
                        sender_name = self._get_message_sender(msg_elem)
                        
                        # Create message data
                        message_data = {
                            'type': 'new_message',
                            'sender_username': sender_name,
                            'message': message_text,
                            'timestamp': datetime.now().isoformat(),
                            'conversation': self.current_conversation['name'],
                            'platform': 'Facebook Messenger'
                        }
                        
                        # Play sound and announce with TTS
                        play_sound('titannet/new_message.ogg')
                        
                        # TTS announcement
                        import accessible_output3.outputs.auto
                        speaker = accessible_output3.outputs.auto.Auto()
                        announcement = _("New Messenger message from {}: {}").format(
                            sender_name, message_text
                        )
                        speaker.speak(announcement)
                        
                        # Notify callbacks
                        for callback in self.message_callbacks:
                            try:
                                wx.CallAfter(callback, message_data)
                            except:
                                pass
                                
                    except Exception as e:
                        print(f"Błąd podczas przetwarzania wiadomości: {e}")
                
                self.last_message_count[conv_id] = current_count
                
        except Exception as e:
            print(f"Błąd podczas sprawdzania nowych wiadomości: {e}")
    
    def _get_message_sender(self, message_element):
        """Get sender name from message element"""
        try:
            # Try to find sender info near the message
            parent = message_element.find_element(By.XPATH, '..')
            sender_elements = parent.find_elements(By.CSS_SELECTOR, '[role="button"]')
            
            for elem in sender_elements:
                aria_label = elem.get_attribute('aria-label')
                if aria_label and 'profile' not in aria_label.lower():
                    return aria_label
            
            return "Unknown"
        except:
            return "Unknown"
    
    def _check_conversation_notifications(self):
        """Check for notifications in conversation list"""
        try:
            # Look for unread message indicators
            notification_elements = self.driver.find_elements(By.CSS_SELECTOR, '[data-testid="unread_count"]')
            
            for notif in notification_elements:
                if notif.is_displayed() and notif.text:
                    # New notification found
                    play_sound('titannet/new_message.ogg')
                    break
                    
        except Exception as e:
            print(f"Błąd podczas sprawdzania powiadomień: {e}")
    
    def send_message(self, conversation_name, message):
        """Send message to conversation"""
        if not self.is_connected or not self.driver:
            return False
        
        try:
            # Find and select conversation
            if not self._select_conversation(conversation_name):
                return False
            
            # Find message input field
            message_input = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, '[contenteditable="true"][role="textbox"]'))
            )
            
            # Clear and send message
            message_input.clear()
            message_input.send_keys(message)
            
            # Find and click send button
            send_button = self.driver.find_element(By.CSS_SELECTOR, '[data-testid="send"]')
            send_button.click()
            
            # Play send sound
            play_sound('titannet/message_send.ogg')
            
            # Notify callbacks
            message_data = {
                'type': 'message_sent',
                'recipient': conversation_name,
                'message': message,
                'status': 'sent',
                'timestamp': datetime.now().isoformat(),
                'platform': 'Facebook Messenger'
            }
            
            for callback in self.message_callbacks:
                try:
                    wx.CallAfter(callback, message_data)
                except:
                    pass
            
            return True
            
        except Exception as e:
            print(f"Błąd podczas wysyłania wiadomości: {e}")
            return False
    
    def _select_conversation(self, conversation_name):
        """Select conversation by name"""
        try:
            for conv_id, conv_data in self.conversations.items():
                if conv_data['name'] == conversation_name:
                    conv_data['element'].click()
                    self.current_conversation = conv_data
                    time.sleep(2)  # Wait for conversation to load
                    return True
            
            # If not found in loaded conversations, try to search
            return self._search_and_select_conversation(conversation_name)
            
        except Exception as e:
            print(f"Błąd podczas wybierania konwersacji: {e}")
            return False
    
    def _search_and_select_conversation(self, conversation_name):
        """Search for and select conversation"""
        try:
            # Find search box
            search_elements = self.driver.find_elements(By.CSS_SELECTOR, '[placeholder*="Search"], [placeholder*="Szukaj"]')
            
            if search_elements:
                search_box = search_elements[0]
                search_box.clear()
                search_box.send_keys(conversation_name)
                time.sleep(2)
                
                # Click on first result
                search_results = self.driver.find_elements(By.CSS_SELECTOR, '[role="option"], [data-testid="conversation"]')
                if search_results:
                    search_results[0].click()
                    time.sleep(2)
                    return True
            
            return False
            
        except Exception as e:
            print(f"Błąd podczas wyszukiwania konwersacji: {e}")
            return False
    
    def get_conversations(self):
        """Get list of available conversations"""
        return list(self.conversations.values())
    
    def _notify_connection_success(self):
        """Notify about successful connection"""
        print(_("Connected to Facebook Messenger as {}").format(self.user_data['username']))
        
        # Use TTS to announce successful connection
        import accessible_output3.outputs.auto
        speaker = accessible_output3.outputs.auto.Auto()
        speaker.speak(_("Connected to Facebook Messenger as {}").format(self.user_data['username']))
        
        # Play welcome sound
        def play_delayed_welcome():
            time.sleep(2)
            play_sound('titannet/welcome to IM.ogg')
        
        threading.Thread(target=play_delayed_welcome, daemon=True).start()
        
        for callback in self.status_callbacks:
            try:
                callback('connection_success', self.user_data)
            except:
                pass
    
    def _notify_error(self, error_message):
        """Notify about errors"""
        play_sound('error')
        print(f"Messenger error: {error_message}")
        wx.MessageBox(error_message, _("Messenger Error"), wx.OK | wx.ICON_ERROR)
    
    def _notify_manual_login(self):
        """Notify user to login manually"""
        wx.MessageBox(
            _("Please log in to Facebook Messenger in the opened browser window.\n"
              "The connection will continue automatically after successful login."),
            _("Manual Login Required"),
            wx.OK | wx.ICON_INFORMATION
        )
    
    def disconnect(self):
        """Disconnect from Messenger"""
        self.is_connected = False
        if self.driver:
            try:
                self.save_cookies()  # Save cookies before closing
                self.driver.quit()
            except:
                pass
        
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.monitoring_thread.join(timeout=2)
        
        play_sound('titannet/bye.ogg')
        print(_("Disconnected from Facebook Messenger"))

# Global client instance
messenger_client = MessengerClient()

def connect_to_messenger(email=None, password=None):
    """Connect to Facebook Messenger"""
    success = messenger_client.start_connection(email, password)
    return messenger_client if success else None

def disconnect_from_messenger():
    """Disconnect from Facebook Messenger"""
    messenger_client.disconnect()

def send_message(conversation_name, message):
    """Send message through Messenger"""
    return messenger_client.send_message(conversation_name, message)

def get_conversations():
    """Get list of conversations"""
    return messenger_client.get_conversations()

def add_message_callback(callback):
    """Add message callback"""
    return messenger_client.add_message_callback(callback)

def is_connected():
    """Check if connected to Messenger"""
    return messenger_client.is_connected

def get_user_data():
    """Get current user data"""
    return messenger_client.user_data

def add_status_callback(callback):
    """Add status callback"""
    return messenger_client.add_status_callback(callback)