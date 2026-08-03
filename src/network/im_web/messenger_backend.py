# -*- coding: utf-8 -*-
"""Facebook Messenger as a Titan IM backend."""

from __future__ import annotations

from typing import Optional

from src.network.im_web.base import (
    IMBackend,
    CAP_ARCHIVE, CAP_ATTACHMENTS, CAP_DELETE, CAP_MESSAGE_REQUESTS,
    CAP_PARTICIPANTS, CAP_PRESENCE, CAP_REACTIONS, CAP_SEARCH,
    CAP_VIDEO_CALL, CAP_VOICE_CALL, CAP_VOICE_NOTES,
)
from src.network.im_web.js_messenger import build_messenger_agent


class MessengerWebBackend(IMBackend):
    SERVICE = 'messenger'
    SERVICE_LABEL = 'Messenger'
    URL = 'https://www.messenger.com/'
    BUFFER_CATEGORY = 'messenger'

    DEFAULT_CAPABILITIES = {
        CAP_ATTACHMENTS, CAP_SEARCH, CAP_ARCHIVE, CAP_VOICE_CALL,
        CAP_VIDEO_CALL, CAP_PRESENCE, CAP_PARTICIPANTS, CAP_REACTIONS,
        CAP_DELETE, CAP_MESSAGE_REQUESTS, CAP_VOICE_NOTES,
    }

    def build_agent_js(self) -> str:
        return build_messenger_agent()

    # ------------------------------------------------------------------ login
    def login_with_credentials(self, email: str, password: str, callback=None) -> None:
        """Fill Messenger's own login form from an accessible Titan dialog.

        A checkpoint, two-factor prompt or captcha cannot be answered blind, so
        the agent reports ``needs_page`` and the client offers to bring the real
        page on screen for exactly that step.
        """
        self.login_start('credentials', callback=callback,
                         email=email, password=password)


_instance: Optional[MessengerWebBackend] = None


def get_messenger_backend(start: bool = True) -> MessengerWebBackend:
    """The process-wide Messenger engine. Created (and started) on first use."""
    global _instance
    if _instance is None:
        _instance = MessengerWebBackend()
    if start and not _instance.running:
        _instance.start()
    return _instance
