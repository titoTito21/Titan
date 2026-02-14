"""Titan IM Sound API for external modules.

Provides unified sound interface so all external IM modules
use the same TitanNet/Titan IM sounds regardless of developer.
Covers all sounds used by built-in integrations (Telegram, EltenLink, Titan-Net).

Usage in external module init.py:
    def open(parent_frame):
        # 'sounds' is automatically injected by the module manager
        import sys
        module = sys.modules[__name__]
        sounds = getattr(module, 'sounds', None)
        if sounds:
            sounds.welcome()
            sounds.notify("Connected!", 'success')
"""

from src.titan_core.sound import play_sound


# TTS functions - imported lazily to avoid circular imports
_speak_titannet = None
_speak_notification = None


def _ensure_tts():
    """Lazily import TTS functions from titan_net_gui."""
    global _speak_titannet, _speak_notification
    if _speak_titannet is None:
        try:
            from src.network.titan_net_gui import speak_titannet, speak_notification
            _speak_titannet = speak_titannet
            _speak_notification = speak_notification
        except ImportError:
            # Fallback: try accessible_output3 directly
            try:
                import accessible_output3.outputs.auto
                _speaker = accessible_output3.outputs.auto.Auto()
                _speak_titannet = lambda text, **kw: _speaker.output(text)
                _speak_notification = lambda text, **kw: _speaker.output(text)
            except Exception:
                _speak_titannet = lambda text, **kw: None
                _speak_notification = lambda text, **kw: None


class TitanIMSoundAPI:
    """Unified sound API for external Titan IM modules.

    All methods are safe to call - they silently fail if sound system
    is not initialized. Module developers don't need to handle errors.

    Sound categories match built-in IM integrations:
    - Telegram GUI (src/network/telegram_gui.py)
    - EltenLink GUI (src/eltenlink_client/elten_gui.py)
    - Titan-Net GUI (src/network/titan_net_gui.py)
    """

    # =========================================================================
    # MESSAGE SOUNDS
    # =========================================================================

    def new_message(self):
        """New message received.
        Used by: Telegram, EltenLink, Titan-Net"""
        play_sound('titannet/new_message.ogg')

    def message_sent(self):
        """Message sent successfully.
        Used by: EltenLink, Titan-Net"""
        play_sound('titannet/message_send.ogg')

    def chat_message(self):
        """Chat message event (in active chat).
        Used by: Telegram, EltenLink, Titan-Net"""
        play_sound('titannet/chat_message.ogg')

    def typing(self):
        """User is typing indicator."""
        play_sound('titannet/typing.ogg')

    # =========================================================================
    # CHAT / ROOM SOUNDS
    # =========================================================================

    def new_chat(self):
        """New chat or room opened.
        Used by: EltenLink, Titan-Net"""
        play_sound('titannet/new_chat.ogg')

    def new_replies(self):
        """New replies available (forum, thread).
        Used by: EltenLink, Titan-Net"""
        play_sound('titannet/newreplies.ogg')

    # =========================================================================
    # USER PRESENCE SOUNDS
    # =========================================================================

    def user_online(self):
        """User came online.
        Used by: EltenLink, Titan-Net"""
        play_sound('titannet/online.ogg')

    def user_offline(self):
        """User went offline.
        Used by: EltenLink, Titan-Net"""
        play_sound('titannet/offline.ogg')

    def status_changed(self):
        """User status changed."""
        play_sound('titannet/new_status.ogg')

    def account_created(self):
        """New account created."""
        play_sound('titannet/account_created.ogg')

    # =========================================================================
    # CALL / VOICE SOUNDS
    # =========================================================================

    def call_connected(self):
        """Voice call connected successfully.
        Used by: Titan-Net"""
        play_sound('titannet/callsuccess.ogg')

    def ring_incoming(self):
        """Incoming call ringing."""
        play_sound('titannet/ring_in.ogg')

    def ring_outgoing(self):
        """Outgoing call ringing."""
        play_sound('titannet/ring_out.ogg')

    def walkie_talkie_start(self):
        """Walkie-talkie / push-to-talk mode activated."""
        play_sound('titannet/walkietalkie.ogg')

    def walkie_talkie_end(self):
        """Walkie-talkie / push-to-talk mode deactivated."""
        play_sound('titannet/walkietalkieend.ogg')

    def recording_start(self):
        """Voice recording started.
        Used by: Titan-Net (broadcast recording)"""
        play_sound('ai/ui1.ogg')

    def recording_stop(self):
        """Voice recording stopped.
        Used by: Titan-Net (broadcast recording)"""
        play_sound('ai/ui2.ogg')

    # =========================================================================
    # FILE SOUNDS
    # =========================================================================

    def file_received(self):
        """New file received."""
        play_sound('titannet/new_file.ogg')

    def file_success(self):
        """File operation completed successfully.
        Used by: Titan-Net"""
        play_sound('titannet/file_success.ogg')

    def file_error(self):
        """File operation failed."""
        play_sound('titannet/file_error.ogg')

    # =========================================================================
    # GENERAL NOTIFICATION SOUNDS
    # =========================================================================

    def notification(self):
        """General notification.
        Used by: EltenLink, Titan-Net"""
        play_sound('titannet/titannet-notification.ogg')

    def success(self):
        """Success notification sound.
        Used by: EltenLink (notification_settings)"""
        play_sound('titannet/titannet_success.ogg')

    def error(self):
        """Error notification sound.
        Used by: Telegram, EltenLink, Titan-Net"""
        play_sound('core/error.ogg')

    def welcome(self):
        """Welcome sound - play when module opens.
        Used by: Telegram, EltenLink, Titan-Net"""
        play_sound('titannet/welcome to IM.ogg')

    def goodbye(self):
        """Goodbye sound - play when module closes / disconnected.
        Used by: EltenLink, Titan-Net"""
        play_sound('titannet/bye.ogg')

    def birthday(self):
        """Birthday notification.
        Used by: EltenLink (whats_new_categories)"""
        play_sound('titannet/birthday.ogg')

    def new_feed_post(self):
        """New feed post.
        Used by: EltenLink (whats_new_categories)"""
        play_sound('titannet/new_feedpost.ogg')

    def announcement(self):
        """Announcement start."""
        play_sound('titannet/ogloszenie.ogg')

    def announcement_ended(self):
        """Announcement ended."""
        play_sound('titannet/ogloszenie_ended.ogg')

    def announcement_status_changed(self):
        """Announcement status changed."""
        play_sound('titannet/ogloszenie_changestatus.ogg')

    def moderation(self):
        """Moderation alert / broadcast received.
        Used by: Titan-Net"""
        play_sound('titannet/moderation.ogg')

    def motd(self):
        """Message of the day."""
        play_sound('titannet/motd.ogg')

    def iui(self):
        """IUI (Invisible UI) related notification."""
        play_sound('titannet/iui.ogg')

    def app_update(self):
        """Application/package update notification.
        Used by: Titan-Net (package pending/approved)"""
        play_sound('apprepo/appupdate.ogg')

    # =========================================================================
    # UI SOUNDS - CORE
    # =========================================================================

    def focus(self, pan=None):
        """Focus change sound.
        Used by: Telegram, EltenLink, Titan-Net"""
        play_sound('core/FOCUS.ogg', pan=pan)

    def select(self):
        """Selection / action confirmed sound.
        Used by: Telegram, EltenLink, Titan-Net"""
        play_sound('core/SELECT.ogg')

    def click(self):
        """Simple click sound."""
        play_sound('core/click.ogg')

    # =========================================================================
    # UI SOUNDS - DIALOGS & WINDOWS
    # =========================================================================

    def dialog_open(self):
        """Dialog opened sound.
        Used by: EltenLink, Titan-Net"""
        play_sound('ui/dialog.ogg')

    def dialog_close(self):
        """Dialog closed sound."""
        play_sound('ui/dialogclose.ogg')

    def window_open(self):
        """Window opened sound.
        Used by: Titan-Net"""
        play_sound('ui/uiopen.ogg')

    def window_close(self):
        """Window closed sound."""
        play_sound('ui/uiclose.ogg')

    def popup(self):
        """Popup window opened.
        Used by: Telegram"""
        play_sound('ui/popup.ogg')

    def popup_close(self):
        """Popup window closed."""
        play_sound('ui/popupclose.ogg')

    def msg_box(self):
        """Message box opened."""
        play_sound('ui/msg.ogg')

    def msg_box_close(self):
        """Message box closed."""
        play_sound('ui/msgclose.ogg')

    # =========================================================================
    # UI SOUNDS - CONTEXT MENU
    # =========================================================================

    def context_menu(self):
        """Context menu opened.
        Used by: EltenLink"""
        play_sound('ui/contextmenu.ogg')

    def context_menu_close(self):
        """Context menu closed.
        Used by: EltenLink"""
        play_sound('ui/contextmenuclose.ogg')

    # =========================================================================
    # UI SOUNDS - LISTS & NAVIGATION
    # =========================================================================

    def end_of_list(self):
        """End of list reached.
        Used by: Telegram, EltenLink, Titan-Net"""
        play_sound('ui/endoflist.ogg')

    def section_change(self):
        """Section/tab changed."""
        play_sound('ui/sectionchange.ogg')

    def switch_category(self):
        """Category switched."""
        play_sound('ui/switch_category.ogg')

    def switch_list(self):
        """List switched."""
        play_sound('ui/switch_list.ogg')

    def focus_collapsed(self):
        """Tree node collapsed."""
        play_sound('ui/focus_collabsed.ogg')

    def focus_expanded(self):
        """Tree node expanded."""
        play_sound('ui/focus_expanded.ogg')

    # =========================================================================
    # UI SOUNDS - NOTIFICATIONS & INFO
    # =========================================================================

    def notify_sound(self):
        """Notification sound (without TTS).
        Used by: EltenLink (info notification_settings)"""
        play_sound('ui/notify.ogg')

    def tip(self):
        """Tooltip / hint sound."""
        play_sound('ui/tip.ogg')

    # =========================================================================
    # UI SOUNDS - WINDOW STATE
    # =========================================================================

    def minimize(self):
        """Window minimized."""
        play_sound('ui/minimalize.ogg')

    def restore(self):
        """Window restored from minimized."""
        play_sound('ui/normalize.ogg')

    # =========================================================================
    # SYSTEM SOUNDS
    # =========================================================================

    def connecting(self):
        """Connection in progress.
        Used by: Titan-Net"""
        play_sound('system/connecting.ogg')

    # =========================================================================
    # TTS (TEXT-TO-SPEECH)
    # =========================================================================

    def speak(self, text, position=0.0, pitch_offset=0):
        """Speak text using TTS with stereo positioning.

        Args:
            text: Text to speak
            position: -1.0 (left) to 1.0 (right), 0.0 (center)
            pitch_offset: -10 to +10, higher = more important
        """
        _ensure_tts()
        if _speak_titannet:
            _speak_titannet(text, position=position, pitch_offset=pitch_offset)

    def notify(self, text, notification_type='info', play_sound_effect=True):
        """Speak notification with appropriate sound and positioning.

        Respects TCE settings (stereo, pitch). Sound + TTS combined.
        Notification types with their stereo positioning:
            - 'error': right side (0.7), pitch +5
            - 'banned': far right (0.9), pitch +8
            - 'warning': slightly right (0.4), pitch +3
            - 'success': center (0.0), pitch 0
            - 'info': slightly left (-0.3), pitch -2

        Args:
            text: Text to speak
            notification_type: 'error', 'success', 'info', 'warning', 'banned'
            play_sound_effect: Whether to play the sound effect (default True)
        """
        _ensure_tts()
        if _speak_notification:
            _speak_notification(text, notification_type=notification_type,
                                play_sound_effect=play_sound_effect)

    # =========================================================================
    # DIRECT ACCESS
    # =========================================================================

    def play(self, sound_file, pan=None):
        """Play any sound file by relative path (e.g. 'titannet/new_message.ogg').

        Uses the current sound theme with fallback to default theme.

        Args:
            sound_file: Relative path within sfx/ directory
            pan: Optional stereo pan 0.0 (left) to 1.0 (right)
        """
        play_sound(sound_file, pan=pan)
