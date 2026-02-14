# -*- coding: utf-8 -*-
import asyncio
import threading
import time
import os
from datetime import datetime
import wx
import logging
from telethon import TelegramClient as TelethonClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneNumberInvalidError
from telethon.tl.types import PeerUser, PeerChat, PeerChannel
from src.titan_core.sound import play_sound
from src.titan_core.translation import set_language
from src.settings.settings import get_setting
from src.settings.titan_im_config import (
    initialize_config, get_telegram_credentials, set_telegram_credentials,
    get_telegram_config, save_telegram_config, load_titan_im_config
)
from src.network import telegram_voice

# Initialize translation
_ = set_language(get_setting('language', 'pl'))

# Initialize configuration
initialize_config()

# Load Telegram API credentials from secure config
def get_api_credentials():
    """Get API credentials from config or use defaults"""
    api_id, api_hash, _ = get_telegram_credentials()
    if api_id and api_hash:
        return api_id, api_hash
    else:
        # Use default credentials if not configured
        return 25330754, 'cb7ba1e93ccbc0576ca1e344a0fe8ae0'

API_ID, API_HASH = get_api_credentials()

# Session file path
SESSION_FILE = os.path.join(os.path.dirname(__file__), 'telegram_session')

class TelegramClient:
    def __init__(self):
        self.client = None
        self.is_connected = False
        self.message_callbacks = []
        self.status_callbacks = []
        self.typing_callbacks = []
        self.call_callbacks = []
        self.current_incoming_call = None  # Store incoming call data for proper answering
        self.user_data = None
        self.chat_users = {}  # Store chat participants
        self.dialogs = []  # Store all dialogs/chats
        self.current_chat = None
        self.event_loop = None
        self.connection_thread = None
        
    def add_message_callback(self, callback):
        """Add callback for new messages"""
        self.message_callbacks.append(callback)
    
    def add_status_callback(self, callback):
        """Add callback for user status changes"""
        self.status_callbacks.append(callback)
    
    def add_typing_callback(self, callback):
        """Add callback for typing indicators"""
        self.typing_callbacks.append(callback)
    
    def add_call_callback(self, callback):
        """Add callback for call events"""
        self.call_callbacks.append(callback)
    
    def start_connection(self, phone_number, password=None):
        """Start Telegram client connection"""
        if self.connection_thread and self.connection_thread.is_alive():
            return False
        
        self.connection_thread = threading.Thread(
            target=self._run_telegram_client,
            args=(phone_number, password),
            daemon=True
        )
        self.connection_thread.start()
        return True
    
    def _run_telegram_client(self, phone_number, password):
        """Run Telegram client in event loop"""
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)
        
        try:
            self.event_loop.run_until_complete(
                self._connect_telegram(phone_number, password)
            )
        except Exception as e:
            print(f"Telegram client error: {e}")
            wx.CallAfter(self._notify_error, f"{_('Connection error')}: {e}")
        finally:
            if self.event_loop:
                self.event_loop.close()
    
    async def _connect_telegram(self, phone_number, password):
        """Connect to Telegram"""
        try:
            # Create Telegram client
            self.client = TelethonClient(SESSION_FILE, API_ID, API_HASH)
            
            # Connect to Telegram
            await self.client.connect()
            
            # Check if already logged in
            if not await self.client.is_user_authorized():
                # Send code request
                await self.client.send_code_request(phone_number)
                
                # Get code from user
                code = await self._get_verification_code()
                if not code:
                    return
                
                try:
                    # Sign in with code
                    await self.client.sign_in(phone_number, code)
                except SessionPasswordNeededError:
                    # 2FA is enabled, need password
                    if not password:
                        password = await self._get_2fa_password()
                        if not password:
                            return
                    await self.client.sign_in(password=password)
            
            # Get user info
            me = await self.client.get_me()
            self.user_data = {
                'id': me.id,
                'username': me.username or f"{me.first_name} {me.last_name or ''}".strip(),
                'first_name': me.first_name,
                'last_name': me.last_name,
                'phone': me.phone
            }
            
            # Set up event handlers
            self.client.add_event_handler(self._handle_new_message, events.NewMessage)
            self.client.add_event_handler(self._handle_user_update, events.UserUpdate)
            self.client.add_event_handler(self._handle_call_update, events.Raw)
            
            self.is_connected = True
            
            # Save successful login configuration
            set_telegram_credentials(API_ID, API_HASH, phone_number)
            
            # Load dialogs (chats)
            await self._load_dialogs()
            
            # Initialize voice client
            telegram_voice.initialize_voice_client(self.client)
            
            # Notify success
            wx.CallAfter(self._notify_connection_success)
            
            # Keep connection alive
            await self.client.run_until_disconnected()
            
        except PhoneNumberInvalidError:
            wx.CallAfter(self._notify_error, _("Invalid phone number"))
        except PhoneCodeInvalidError:
            wx.CallAfter(self._notify_error, _("Invalid verification code"))
        except Exception as e:
            wx.CallAfter(self._notify_error, f"{_('Login error')}: {e}")
    
    async def _get_verification_code(self):
        """Get verification code from user"""
        code = None
        
        def get_code():
            nonlocal code
            dlg = wx.TextEntryDialog(None, 
                _("Enter the verification code received by SMS or Telegram:"), 
                _("Verification code"))
            if dlg.ShowModal() == wx.ID_OK:
                code = dlg.GetValue()
            dlg.Destroy()
        
        wx.CallAfter(get_code)
        
        # Wait for code
        while code is None:
            await asyncio.sleep(0.1)
        
        return code
    
    async def _get_2fa_password(self):
        """Get 2FA password from user"""
        password = None
        
        def get_password():
            nonlocal password
            dlg = wx.PasswordEntryDialog(None,
                _("Enter two-factor authentication password:"),
                _("2FA Password"))
            if dlg.ShowModal() == wx.ID_OK:
                password = dlg.GetValue()
            dlg.Destroy()
        
        wx.CallAfter(get_password)
        
        # Wait for password
        while password is None:
            await asyncio.sleep(0.1)
        
        return password
    
    async def _load_dialogs(self):
        """Load all dialogs/chats"""
        try:
            dialogs = []
            async for dialog in self.client.iter_dialogs():
                dialog_info = {
                    'id': dialog.id,
                    'title': dialog.title,
                    'name': dialog.name,
                    'is_user': dialog.is_user,
                    'is_group': dialog.is_group,
                    'is_channel': dialog.is_channel,
                    'entity': dialog.entity
                }
                dialogs.append(dialog_info)
                
                # Store users for easy access
                if dialog.is_user and dialog.entity.username:
                    self.chat_users[dialog.entity.username] = dialog_info
            
            self.dialogs = dialogs
            
            # Notify about loaded dialogs
            for callback in self.status_callbacks:
                try:
                    wx.CallAfter(callback, 'dialogs_loaded', dialogs)
                except:
                    pass
                    
        except Exception as e:
            print(f"Error loading dialogs: {e}")
    
    async def _handle_new_message(self, event):
        """Handle incoming messages"""
        try:
            message = event.message
            sender = await message.get_sender()
            msg_text = message.text or ''

            # Check for TCE voice call markers BEFORE normal message processing
            if msg_text and isinstance(message.peer_id, PeerUser):
                call_info = telegram_voice.parse_call_message(msg_text)
                if call_info:
                    sender_name = getattr(sender, 'first_name', None) or getattr(sender, 'username', None) or _('Unknown')
                    sender_id = sender.id if sender else None

                    if call_info['type'] == 'call_request':
                        # Incoming TCE voice call
                        group_id = call_info['group_id']
                        caller_name = call_info.get('caller_name', sender_name)
                        print(f"Incoming TCE voice call from {caller_name} (group: {group_id})")

                        # Show incoming call dialog on main thread
                        def show_tce_call_dialog():
                            try:
                                from src.network import telegram_windows
                                app = wx.GetApp()
                                if app:
                                    parent = app.GetTopWindow()
                                    if parent:
                                        if hasattr(parent, 'IsIconized') and parent.IsIconized():
                                            parent.Iconize(False)
                                        parent.Raise()
                                        parent.RequestUserAttention()

                                    call_data = {
                                        'caller_name': caller_name,
                                        'caller_id': sender_id,
                                        'group_id': group_id,
                                        'type': 'tce_call'
                                    }
                                    telegram_windows.show_incoming_call_dialog(
                                        parent, caller_name, call_data
                                    )
                            except Exception as dialog_err:
                                print(f"Error showing TCE call dialog: {dialog_err}")
                                import traceback
                                traceback.print_exc()

                        wx.CallAfter(show_tce_call_dialog)

                    elif call_info['type'] == 'call_end':
                        # Other side ended the call
                        print(f"TCE call ended by remote side (group: {call_info['group_id']})")
                        if telegram_voice.is_call_active():
                            telegram_voice.end_voice_call()

                    # Don't process call markers as regular messages
                    return

            # Create message data
            message_data = {
                'type': 'new_message',
                'id': message.id,
                'sender_id': sender.id if sender else None,
                'sender_username': getattr(sender, 'username', None) or getattr(sender, 'first_name', _('Unknown')),
                'message': msg_text,
                'timestamp': message.date.isoformat(),
                'chat_id': message.peer_id,
                'is_private': isinstance(message.peer_id, PeerUser),
                'is_group': isinstance(message.peer_id, PeerChat),
                'is_channel': isinstance(message.peer_id, PeerChannel)
            }

            # Play sound and announce message with TTS
            play_sound('titannet/new_message.ogg')

            # Get group/chat information for group messages
            chat_name = None
            if message_data['is_group'] or message_data['is_channel']:
                # Try to get the chat name from our dialogs
                chat_id = message.peer_id.chat_id if hasattr(message.peer_id, 'chat_id') else message.peer_id.channel_id
                for dialog in self.dialogs:
                    if dialog['id'] == chat_id or str(dialog['id']).endswith(str(chat_id)):
                        chat_name = dialog['name'] or dialog['title']
                        break
                if not chat_name:
                    chat_name = "Unknown Group"

            # Announce message with TTS (translatable)
            # Check if stereo speech is enabled
            try:
                from src.titan_core.stereo_speech import get_stereo_speech
                stereo_speech = get_stereo_speech()
            except ImportError:
                stereo_speech = None

            if stereo_speech and stereo_speech.is_stereo_enabled():
                # Use stereo speech with higher tone for notification and slower for message content
                if message_data['is_group'] or message_data['is_channel']:
                    notification_text = _("New group message from {}, {}").format(
                        chat_name,
                        message_data['sender_username']
                    )
                    message_content = message_data['message']
                else:
                    notification_text = _("New message from {}").format(
                        message_data['sender_username']
                    )
                    message_content = message_data['message']

                stereo_speech.speak(notification_text, position=0.0, pitch_offset=3, use_fallback=False)

                import time
                time.sleep(0.3)

                if message_content:
                    stereo_speech.speak(message_content, position=0.0, pitch_offset=-2, use_fallback=False)
            else:
                # Fallback to accessible_output3
                import accessible_output3.outputs.auto
                speaker = accessible_output3.outputs.auto.Auto()

                if message_data['is_group'] or message_data['is_channel']:
                    announcement = _("New group message from {}, {}, {}").format(
                        chat_name,
                        message_data['sender_username'],
                        message_data['message']
                    )
                else:
                    announcement = _("Message from: {}, {}").format(
                        message_data['sender_username'],
                        message_data['message']
                    )

                speaker.speak(announcement)

            # Add group name to message data for GUI display
            if message_data['is_group'] or message_data['is_channel']:
                message_data['group_name'] = chat_name

            for callback in self.message_callbacks:
                try:
                    wx.CallAfter(callback, message_data)
                except:
                    pass

        except Exception as e:
            print(f"Error handling message: {e}")
    
    async def _handle_user_update(self, event):
        """Handle user status updates"""
        try:
            # This could be typing indicators, online status, etc.
            for callback in self.typing_callbacks:
                try:
                    wx.CallAfter(callback, {'type': 'user_typing', 'user_id': getattr(event, 'user_id', None)})
                except:
                    pass
        except Exception as e:
            print(f"Error handling user update: {e}")
    
    async def _handle_call_update(self, event):
        """Handle native Telegram call updates (signaling only)."""
        try:
            from telethon.tl.types import UpdatePhoneCall

            if not isinstance(event, UpdatePhoneCall):
                return

            phone_call = event.phone_call
            call_type = getattr(phone_call, '_', None)
            if not call_type:
                return

            if call_type == 'phoneCallRequested':
                # Incoming native Telegram call
                caller_id = phone_call.admin_id
                print(f"Incoming native call from user ID: {caller_id}")

                self.current_incoming_call = {
                    'caller_id': caller_id,
                    'call_object': phone_call,
                    'call_id': phone_call.id,
                    'type': 'native_call'
                }

                # Find caller name
                caller_name = f"User {caller_id}"
                try:
                    for dialog in self.dialogs:
                        if hasattr(dialog['entity'], 'id') and dialog['entity'].id == caller_id:
                            caller_name = dialog['name'] or dialog['title']
                            break
                except Exception:
                    pass

                # Show incoming call dialog
                def show_native_call_dialog():
                    try:
                        from src.network import telegram_windows
                        app = wx.GetApp()
                        parent = app.GetTopWindow() if app else None
                        if parent:
                            if hasattr(parent, 'IsIconized') and parent.IsIconized():
                                parent.Iconize(False)
                            parent.Raise()
                            parent.RequestUserAttention()
                        telegram_windows.show_incoming_call_dialog(
                            parent, caller_name, self.current_incoming_call
                        )
                    except Exception as e:
                        print(f"Error showing native call dialog: {e}")
                        import traceback
                        traceback.print_exc()

                wx.CallAfter(show_native_call_dialog)
                play_sound('titannet/ring_in.ogg')

                for callback in self.call_callbacks:
                    try:
                        wx.CallAfter(callback, 'incoming_call', {
                            'caller_id': caller_id,
                            'caller_name': caller_name,
                            'call_id': phone_call.id,
                            'call_object': phone_call
                        })
                    except Exception:
                        pass

            elif call_type == 'phoneCallAccepted':
                # Our outgoing native call was accepted - complete DH exchange
                print("Native call accepted - completing DH exchange")
                if telegram_voice.telegram_voice_client and telegram_voice.telegram_voice_client.dh_params:
                    try:
                        from telethon.tl.functions.phone import ConfirmCallRequest
                        from telethon.tl.types import InputPhoneCall
                        import hashlib

                        dh = telegram_voice.telegram_voice_client.dh_params
                        if 'g_a' in dh:
                            g_a_bytes = dh['g_a'].to_bytes(256, byteorder='big')
                            p = dh['p']
                            a = dh['a']
                            g_b_int = int.from_bytes(phone_call.g_b, byteorder='little')
                            shared_key = pow(g_b_int, a, p)
                            shared_bytes = shared_key.to_bytes((shared_key.bit_length() + 7) // 8, byteorder='big')
                            fingerprint = int.from_bytes(
                                hashlib.sha1(shared_bytes).digest()[-8:],
                                byteorder='little', signed=True
                            )

                            input_call = InputPhoneCall(id=phone_call.id, access_hash=phone_call.access_hash)

                            def do_confirm():
                                try:
                                    if self.event_loop and self.event_loop.is_running():
                                        future = asyncio.run_coroutine_threadsafe(
                                            self.client(ConfirmCallRequest(
                                                peer=input_call,
                                                g_a=g_a_bytes,
                                                key_fingerprint=fingerprint,
                                                protocol=dh['protocol']
                                            )),
                                            self.event_loop
                                        )
                                        result = future.result(timeout=10)
                                        if hasattr(result, 'phone_call') and telegram_voice.telegram_voice_client:
                                            telegram_voice.telegram_voice_client.current_call_object = result.phone_call
                                except Exception as e:
                                    print(f"DH confirm failed: {e}")

                            import threading
                            threading.Thread(target=do_confirm, daemon=True).start()

                    except Exception as e:
                        print(f"DH exchange failed: {e}")

                play_sound('titannet/callsuccess.ogg')

                for callback in self.call_callbacks:
                    try:
                        wx.CallAfter(callback, 'call_connected', {'call_id': phone_call.id})
                    except Exception:
                        pass

            elif call_type == 'phoneCallWaiting':
                # Outgoing call is ringing
                play_sound('titannet/ring_out.ogg')

            elif call_type == 'phoneCall':
                # Call fully established
                play_sound('titannet/callsuccess.ogg')
                if telegram_voice.telegram_voice_client:
                    telegram_voice.telegram_voice_client.current_call_object = phone_call

                for callback in self.call_callbacks:
                    try:
                        wx.CallAfter(callback, 'call_active', {'call_id': phone_call.id})
                    except Exception:
                        pass

            elif call_type == 'phoneCallDiscarded':
                # Call ended
                reason = getattr(phone_call, 'reason', None)
                print(f"Native call discarded (reason: {reason})")
                play_sound('titannet/bye.ogg')

                if telegram_voice.telegram_voice_client:
                    # Only end if the voice client still thinks it's a native call
                    vc = telegram_voice.telegram_voice_client
                    if vc.current_call_object and not vc.current_group_id:
                        telegram_voice.end_voice_call()

                self.current_incoming_call = None

                for callback in self.call_callbacks:
                    try:
                        wx.CallAfter(callback, 'call_ended', {})
                    except Exception:
                        pass

        except Exception as e:
            print(f"Error handling call update: {e}")
            import traceback
            traceback.print_exc()
    
    def _notify_connection_success(self):
        """Notify about successful connection"""
        print(_("Connected to Telegram as {}").format(self.user_data['username']))
        
        # Use TTS to announce successful connection
        import accessible_output3.outputs.auto
        speaker = accessible_output3.outputs.auto.Auto()
        speaker.speak(_("Connected to Telegram as {}").format(self.user_data['username']))
        
        # Welcome sound is played by GUI, not here
        # def play_delayed_welcome():
        #     time.sleep(2)
        #     play_sound('titannet/welcome to IM.ogg')
        #
        # threading.Thread(target=play_delayed_welcome, daemon=True).start()

        for callback in self.status_callbacks:
            try:
                callback('connection_success', self.user_data)
            except:
                pass
    
    def _notify_error(self, error_message):
        """Notify about errors"""
        play_sound('core/error.ogg')
        print(f"Telegram error: {error_message}")
        wx.MessageBox(error_message, _("Telegram Error"), wx.OK | wx.ICON_ERROR)
    
    def send_message(self, recipient, message):
        """Send message to recipient"""
        if not self.is_connected or not self.client:
            return False
        
        def send_async():
            try:
                if self.event_loop:
                    asyncio.run_coroutine_threadsafe(
                        self._send_message_async(recipient, message),
                        self.event_loop
                    )
            except Exception as e:
                print(f"Error sending message: {e}")
        
        thread = threading.Thread(target=send_async, daemon=True)
        thread.start()
        return True
    
    async def _send_message_async(self, recipient, message):
        """Send message asynchronously"""
        try:
            # Find recipient entity
            entity = None
            
            # Try to find by username
            if recipient in self.chat_users:
                entity = self.chat_users[recipient]['entity']
            else:
                # Try to find in dialogs
                for dialog in self.dialogs:
                    if dialog['name'] == recipient or dialog['title'] == recipient:
                        entity = dialog['entity']
                        break
            
            if not entity:
                # Try to resolve username
                try:
                    entity = await self.client.get_entity(recipient)
                except:
                    print(f"Could not find recipient: {recipient}")
                    return False
            
            # Send message
            await self.client.send_message(entity, message)
            
            # Play sound and notify
            play_sound('titannet/message_send.ogg')
            
            # Notify callbacks
            message_data = {
                'type': 'message_sent',
                'recipient': recipient,
                'message': message,
                'status': 'sent',
                'timestamp': datetime.now().isoformat()
            }
            
            for callback in self.message_callbacks:
                try:
                    wx.CallAfter(callback, message_data)
                except:
                    pass
            
            return True
            
        except Exception as e:
            print(f"Error sending message: {e}")
            return False
    
    def send_typing_indicator(self, recipient, is_typing=True):
        """Send typing indicator"""
        # Telethon supports typing indicators
        if not self.is_connected or not self.client:
            return False
        
        def send_typing_async():
            try:
                if self.event_loop:
                    asyncio.run_coroutine_threadsafe(
                        self._send_typing_async(recipient, is_typing),
                        self.event_loop
                    )
            except Exception as e:
                print(f"Error sending typing indicator: {e}")
        
        thread = threading.Thread(target=send_typing_async, daemon=True)
        thread.start()
        return True
    
    async def _send_typing_async(self, recipient, is_typing):
        """Send typing indicator asynchronously"""
        try:
            # Find recipient entity (same logic as in send message)
            entity = None
            if recipient in self.chat_users:
                entity = self.chat_users[recipient]['entity']
            else:
                for dialog in self.dialogs:
                    if dialog['name'] == recipient or dialog['title'] == recipient:
                        entity = dialog['entity']
                        break
            
            if entity and is_typing:
                await self.client.send_read_acknowledge(entity)
                # Note: Telethon automatically sends typing indicators when you're composing
                
        except Exception as e:
            print(f"Error sending typing indicator: {e}")
    
    def get_chat_history(self, with_user):
        """Get chat history with specific user"""
        if not self.is_connected or not self.client:
            return False
        
        def get_history_async():
            try:
                if self.event_loop:
                    asyncio.run_coroutine_threadsafe(
                        self._get_chat_history_async(with_user),
                        self.event_loop
                    )
            except Exception as e:
                print(f"Error getting chat history: {e}")
        
        thread = threading.Thread(target=get_history_async, daemon=True)
        thread.start()
        return True
    
    async def _get_chat_history_async(self, with_user):
        """Get chat history asynchronously"""
        try:
            # Find entity
            entity = None
            if with_user in self.chat_users:
                entity = self.chat_users[with_user]['entity']
            else:
                for dialog in self.dialogs:
                    if dialog['name'] == with_user or dialog['title'] == with_user:
                        entity = dialog['entity']
                        break
            
            if not entity:
                return
            
            # Get message history
            messages = []
            async for message in self.client.iter_messages(entity, limit=50):
                sender = await message.get_sender()
                msg_data = {
                    'id': message.id,
                    'sender_username': getattr(sender, 'username', None) or getattr(sender, 'first_name', _('Unknown')),
                    'message': message.text or '',
                    'timestamp': message.date.isoformat()
                }
                messages.append(msg_data)
            
            # Reverse to get chronological order
            messages.reverse()
            
            # Notify callbacks
            history_data = {
                'type': 'chat_history',
                'with_user': with_user,
                'messages': messages
            }
            
            for callback in self.message_callbacks:
                try:
                    wx.CallAfter(callback, history_data)
                except:
                    pass
                    
        except Exception as e:
            print(f"Error getting chat history: {e}")
    
    def get_online_users(self):
        """Legacy method - redirects to get_contacts for backward compatibility"""
        return self.get_contacts()
    
    def get_contacts(self):
        """Get list of private contacts"""
        contacts_list = []
        for dialog in self.dialogs:
            if dialog['is_user']:  # Only show private chats/users
                contacts_list.append({
                    'id': dialog['id'],
                    'username': dialog['name'] or dialog['title'],
                    'type': 'contact'
                })
        return contacts_list
    
    def get_group_chats(self):
        """Get list of group chats and channels"""
        groups_list = []
        for dialog in self.dialogs:
            if dialog['is_group'] or dialog['is_channel']:  # Groups and channels
                groups_list.append({
                    'id': dialog['id'],
                    'name': dialog['name'] or dialog['title'],
                    'title': dialog['title'],
                    'is_group': dialog['is_group'],
                    'is_channel': dialog['is_channel'],
                    'type': 'group'
                })
        return groups_list
    
    def send_group_message(self, group_name, message):
        """Send message to a group chat"""
        if not self.is_connected or not self.client:
            return False
        
        def send_group_async():
            try:
                if self.event_loop:
                    future = asyncio.run_coroutine_threadsafe(
                        self._send_group_message_async(group_name, message),
                        self.event_loop
                    )
                    return future.result(timeout=10)
            except Exception as e:
                print(f"Error sending group message: {e}")
                return False
        
        thread = threading.Thread(target=send_group_async, daemon=True)
        thread.start()
        return True
    
    async def _send_group_message_async(self, group_name, message):
        """Send group message asynchronously"""
        try:
            # Find group entity
            group_entity = None
            for dialog in self.dialogs:
                if (dialog['is_group'] or dialog['is_channel']) and \
                   (dialog['name'] == group_name or dialog['title'] == group_name):
                    group_entity = dialog['entity']
                    break
            
            if not group_entity:
                print(f"Group '{group_name}' not found")
                return False
            
            # Send message to group
            await self.client.send_message(group_entity, message)
            print(f"Group message sent to '{group_name}': {message}")
            
            # Play send sound
            play_sound('titannet/message_send.ogg')
            
            return True
            
        except Exception as e:
            print(f"Error sending group message: {e}")
            return False
    
    def get_group_chat_history(self, group_name):
        """Get group chat history"""
        if not self.is_connected or not self.client:
            return False
        
        def get_group_history_async():
            try:
                if self.event_loop:
                    asyncio.run_coroutine_threadsafe(
                        self._get_group_chat_history_async(group_name),
                        self.event_loop
                    )
            except Exception as e:
                print(f"Error getting group chat history: {e}")
        
        thread = threading.Thread(target=get_group_history_async, daemon=True)
        thread.start()
        return True
    
    async def _get_group_chat_history_async(self, group_name):
        """Get group chat history asynchronously"""
        try:
            # Find group entity
            group_entity = None
            for dialog in self.dialogs:
                if (dialog['is_group'] or dialog['is_channel']) and \
                   (dialog['name'] == group_name or dialog['title'] == group_name):
                    group_entity = dialog['entity']
                    break
            
            if not group_entity:
                return
            
            # Get message history
            messages = []
            async for message in self.client.iter_messages(group_entity, limit=50):
                sender = await message.get_sender()
                msg_data = {
                    'sender_username': sender.username if sender else 'Unknown',
                    'message': message.text,
                    'timestamp': message.date.isoformat()
                }
                messages.append(msg_data)
            
            # Sort messages chronologically
            messages.reverse()
            
            # Send to callbacks
            history_data = {
                'type': 'group_chat_history',
                'group_name': group_name,
                'messages': messages
            }
            
            for callback in self.message_callbacks:
                try:
                    wx.CallAfter(callback, history_data)
                except:
                    pass
                    
        except Exception as e:
            print(f"Error getting group chat history: {e}")
    
    def disconnect(self):
        """Disconnect from Telegram safely"""
        print(_("Disconnecting from Telegram..."))
        
        # Set disconnected state immediately to prevent new operations
        self.is_connected = False
        self.logged_in = False
        
        try:
            # Stop any ongoing operations first
            if hasattr(self, 'update_timer') and self.update_timer:
                try:
                    self.update_timer.Stop()
                except:
                    pass
            
            # Disconnect client safely
            if self.client:
                try:
                    if self.event_loop and self.event_loop.is_running():
                        # If event loop is still running, schedule disconnect
                        future = asyncio.run_coroutine_threadsafe(
                            self._safe_disconnect(),
                            self.event_loop
                        )
                        # Wait max 3 seconds for disconnect
                        future.result(timeout=3)
                    else:
                        # Event loop stopped, force close
                        print(_("Event loop stopped, forcing client cleanup"))
                except Exception as e:
                    print(f"Error during client disconnect: {e}")
                finally:
                    # Clear client reference
                    self.client = None
            
            # Stop event loop safely
            if self.event_loop and self.event_loop.is_running():
                try:
                    self.event_loop.call_soon_threadsafe(self.event_loop.stop)
                except:
                    pass
            
            # Wait for thread to finish, but don't block forever
            if self.connection_thread and self.connection_thread.is_alive():
                print(_("Waiting for connection thread to finish..."))
                self.connection_thread.join(timeout=5)
                
                if self.connection_thread.is_alive():
                    print(_("Warning: Connection thread did not stop cleanly"))
                else:
                    print(_("Connection thread stopped"))
            
            # Reset state
            self.connection_thread = None
            self.event_loop = None
            self.chat_users = {}
            self.dialogs = []
            
            # Play disconnect sound
            play_sound('titannet/bye.ogg')
            print(_("Successfully disconnected from Telegram"))
            
        except Exception as e:
            print(f"Error during disconnect: {e}")
            # Still play sound and mark as disconnected even if there were errors
            play_sound('titannet/bye.ogg')
            print(_("Disconnected from Telegram (with errors)"))
    
    async def _safe_disconnect(self):
        """Safe async disconnect helper"""
        try:
            if self.client and hasattr(self.client, 'disconnect'):
                await self.client.disconnect()
                print(_("Telegram client disconnected"))
        except Exception as e:
            print(f"Error in async disconnect: {e}")

# Global client instance
telegram_client = TelegramClient()

def create_account(phone_number, password=None):
    """Start login process (replaces account creation)"""
    return {"status": "success", "message": _("Start login by providing phone number")}

def login(phone_number, password=None):
    """Login with phone number"""
    if not phone_number:
        return {"status": "error", "message": _("Phone number is required")}
    return {"status": "success", "message": _("Preparing connection to Telegram...")}

def connect_to_server(phone_number, password=None, username=None):
    """Connect to Telegram"""
    success = telegram_client.start_connection(phone_number, password)
    return telegram_client if success else None

def disconnect_from_server():
    """Disconnect from Telegram"""
    telegram_client.disconnect()

def send_message(recipient, message):
    """Send message through Telegram"""
    return telegram_client.send_message(recipient, message)

def get_online_users():
    """Get list of chat users/dialogs - legacy for backward compatibility"""
    return telegram_client.get_online_users()

def get_contacts():
    """Get list of private contacts"""
    return telegram_client.get_contacts()

def get_group_chats():
    """Get list of group chats and channels"""
    return telegram_client.get_group_chats()

def send_group_message(group_name, message):
    """Send message to group chat"""
    return telegram_client.send_group_message(group_name, message)

def get_group_chat_history(group_name):
    """Get group chat history"""
    return telegram_client.get_group_chat_history(group_name)

def get_chat_history(with_user):
    """Get chat history with user"""
    return telegram_client.get_chat_history(with_user)

def add_message_callback(callback):
    """Add message callback"""
    return telegram_client.add_message_callback(callback)

def is_connected():
    """Check if connected to Telegram"""
    return telegram_client.is_connected

def get_user_data():
    """Get current user data"""
    return telegram_client.user_data

def get_last_phone_number():
    """Get last used phone number from config"""
    _, _, last_phone = get_telegram_credentials()
    return last_phone

def get_auto_connect_enabled():
    """Check if auto connect is enabled"""
    config = get_telegram_config()
    return config.get('auto_connect', False)

def start_voice_call(recipient):
    """Start voice call with recipient"""
    if not telegram_client.is_connected:
        return False
    
    return telegram_voice.start_voice_call(recipient)

def answer_voice_call():
    """Answer incoming voice call"""
    if not telegram_client.is_connected:
        return False
    
    # Pass the stored incoming call data to answer_voice_call
    call_data = telegram_client.current_incoming_call if telegram_client.current_incoming_call else {}
    print(f"Answering call with data: {call_data}")
    
    return telegram_voice.answer_voice_call(call_data)

def end_voice_call():
    """End current voice call"""
    return telegram_voice.end_voice_call()

def join_voice_call(group_id):
    """Join an existing voice call group (for receiving TCE calls)"""
    return telegram_voice.join_voice_call(group_id)

def toggle_mute():
    """Toggle microphone mute during voice call"""
    return telegram_voice.toggle_mute()

def is_call_active():
    """Check if voice call is active"""
    return telegram_voice.is_call_active()

def get_call_status():
    """Get current call status"""
    return telegram_voice.get_call_status()

def add_call_callback(callback):
    """Add callback for call events"""
    telegram_voice.add_call_callback(callback)

def is_voice_calls_available():
    """Check if voice calls are available"""
    return telegram_voice.is_voice_calls_available()