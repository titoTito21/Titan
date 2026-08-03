# -*- coding: utf-8 -*-
"""WhatsApp Web as a Titan IM backend."""

from __future__ import annotations

from typing import Optional

from src.network.im_web.base import (
    IMBackend,
    CAP_ARCHIVE, CAP_ATTACHMENTS, CAP_PARTICIPANTS, CAP_PRESENCE, CAP_SEARCH,
    CAP_VIDEO_CALL, CAP_VOICE_CALL, CAP_VOICE_NOTES,
)
from src.network.im_web.js_whatsapp import build_whatsapp_agent


class WhatsAppWebBackend(IMBackend):
    SERVICE = 'whatsapp'
    SERVICE_LABEL = 'WhatsApp'
    URL = 'https://web.whatsapp.com/'
    BUFFER_CATEGORY = 'whatsapp'

    # What the DOM path alone can do. Anything richer (reactions, editing,
    # channels, deletion) is reported by the agent once it finds the store.
    DEFAULT_CAPABILITIES = {
        CAP_ATTACHMENTS, CAP_SEARCH, CAP_ARCHIVE, CAP_VOICE_CALL,
        CAP_VIDEO_CALL, CAP_PRESENCE, CAP_VOICE_NOTES, CAP_PARTICIPANTS,
    }

    def build_agent_js(self) -> str:
        return build_whatsapp_agent()

    # ------------------------------------------------------------------ login
    def request_pairing_code(self, phone: str, callback=None) -> None:
        """Ask WhatsApp for the 8-character link-device code for ``phone``.

        This is the accessible way in: a QR image is useless to a blind user,
        while the pairing code is plain text we can put in a dialog.
        """
        self.login_start('pairing', callback=callback, phone=phone)


_instance: Optional[WhatsAppWebBackend] = None


def get_whatsapp_backend(start: bool = True) -> WhatsAppWebBackend:
    """The process-wide WhatsApp engine. Created (and started) on first use."""
    global _instance
    if _instance is None:
        _instance = WhatsAppWebBackend()
    if start and not _instance.running:
        _instance.start()
    return _instance
