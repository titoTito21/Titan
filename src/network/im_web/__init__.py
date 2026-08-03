# -*- coding: utf-8 -*-
"""Web-as-backend layer for Titan IM (WhatsApp Web, Facebook Messenger).

The web page is no longer the user interface - it is the *engine*. A single
offscreen WebView2 host (``bridge.WebBridge``) loads the service, an injected
JavaScript agent talks to the page's own internals and pushes structured
events, and a Titan-native accessible client renders them.

Nothing in this package draws user-facing UI: it only produces the data model
described in ``base`` (chats, messages, presence, calls) and accepts the
commands listed there.
"""

from src.network.im_web.base import (  # noqa: F401
    Chat, Message, Contact, CallState, IMBackend,
    EV_READY, EV_AUTH_STATE, EV_CHATS, EV_CHAT_UPDATED, EV_MESSAGES,
    EV_MESSAGE_NEW, EV_MESSAGE_UPDATED, EV_TYPING, EV_PRESENCE, EV_CALL,
    EV_MEDIA_READY, EV_ERROR, EV_LOG,
    CAP_CHANNELS, CAP_STATUS_UPDATES, CAP_REACTIONS, CAP_EDIT, CAP_VOICE_NOTES,
    CAP_MESSAGE_REQUESTS, CAP_COMMUNITIES, CAP_VIDEO_CALL, CAP_VOICE_CALL,
    CAP_ATTACHMENTS, CAP_SEARCH, CAP_PARTICIPANTS, CAP_ARCHIVE,
)
