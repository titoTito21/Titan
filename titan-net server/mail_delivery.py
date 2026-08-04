#!/usr/bin/env python3
"""
Titan-Net inbound mail delivery pipe.

Postfix pipes each message destined for @MAIL_DOMAIN to this script on stdin
(the recipient is passed as the first CLI argument, ${recipient}). Rather than
open the SQLCipher database directly - which the running server already holds a
single-writer PID lock on - this script parses the message and POSTs it to the
server's internal /api/mail/incoming endpoint, authenticated with a shared
secret. The server performs the DB write.

Uses only the Python standard library and does NOT import the app config, so it
runs from Postfix's restricted, unprivileged pipe environment (a dedicated
`titanmail` user, a locked-down CWD) without touching the root-only .env or
triggering config side effects.

Configuration (all optional, sensible defaults):
  MAIL_INGEST_URL         default http://127.0.0.1:8000/api/mail/incoming
  MAIL_INGEST_TOKEN       the shared secret; if unset, read from a token file
  MAIL_INGEST_TOKEN_FILE  default /opt/titan-net/.mail_ingest_token

Example Postfix master.cf transport:
    titanmail unix - n n - - pipe
      flags=Rq user=titanmail argv=/opt/titan-net/venv/bin/python3
      /opt/titan-net/mail_delivery.py ${recipient}
"""

import email
import email.policy
import email.utils
import html
import json
import os
import re
import ssl
import sys
import urllib.request

# The internal HTTP API listens with TLS (self-signed) on :8000, so we POST over
# https to localhost and skip certificate verification for the loopback call.
INGEST_URL = os.getenv('MAIL_INGEST_URL', 'https://127.0.0.1:8000/api/mail/incoming')


def _load_token() -> str:
    token = os.getenv('MAIL_INGEST_TOKEN', '').strip()
    if token:
        return token
    for path in (os.getenv('MAIL_INGEST_TOKEN_FILE', ''),
                 '/opt/titan-net/.mail_ingest_token'):
        if path and os.path.isfile(path):
            try:
                with open(path, 'r') as f:
                    return f.read().strip()
            except Exception:
                pass
    return ''


def _part_text(part) -> str:
    try:
        return part.get_content()
    except Exception:
        payload = part.get_payload(decode=True) or b''
        charset = part.get_content_charset() or 'utf-8'
        try:
            return payload.decode(charset, 'replace')
        except (LookupError, TypeError):
            return payload.decode('utf-8', 'replace')


def _html_to_text(source: str) -> str:
    """Reduce an HTML body to readable plain text.

    Phone/webmail clients (Gmail, Outlook mobile) often reply with an
    HTML-only body; without this the raw markup ends up in the mailbox and the
    Mail client shows tag soup instead of the reply.
    """
    text = re.sub(r'(?is)<(script|style|head)[^>]*>.*?</\1\s*>', '', source)
    text = re.sub(r'(?i)<br\s*/?>', '\n', text)
    text = re.sub(r'(?i)</\s*(p|div|tr|li|h[1-6]|blockquote|table)\s*>', '\n', text)
    text = re.sub(r'(?s)<[^>]+>', '', text)
    text = html.unescape(text)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[ \t ]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _html_body(msg) -> str:
    """The message's HTML part, kept verbatim, or '' when there is none.

    The plain-text flattening below is what the mailbox stores as the body, but
    throwing the markup away loses the headings, lists and links the sender
    wrote - the Mail client parses this into a readable structure instead."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/html' and not part.get_filename():
                return _part_text(part)
        return ''
    if msg.get_content_type() == 'text/html':
        return _part_text(msg)
    return ''


def _plain_body(msg) -> str:
    """Extract a readable text body, preferring text/plain over text/html."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain' and not part.get_filename():
                return _part_text(part)
        for part in msg.walk():
            if part.get_content_type() == 'text/html' and not part.get_filename():
                return _html_to_text(_part_text(part))
        return ''
    body = _part_text(msg)
    if msg.get_content_type() == 'text/html':
        return _html_to_text(body)
    return body


def _header(msg, name: str) -> str:
    """A header's decoded value as a single unfolded line.

    Folded headers (a long ``Subject``, a ``References`` chain) otherwise carry
    embedded newlines into the database and the Mail client's list view.
    """
    try:
        value = msg.get(name)
    except Exception:
        return ''
    if value is None:
        return ''
    try:
        value = str(value)
    except Exception:
        return ''
    return re.sub(r'\s+', ' ', value).strip()


def _address(raw: str) -> str:
    """The bare ``user@host`` from a header that may carry a display name.

    ``From: Some One <someone@gmail.com>`` must be stored as the address alone:
    the Mail client shows this value in the message list and reuses it verbatim
    as the recipient when replying, and a display name there makes the reply
    unroutable.
    """
    if not raw:
        return ''
    _name, addr = email.utils.parseaddr(raw)
    addr = (addr or '').strip()
    if not addr:
        # Not a parseable address (e.g. a bare local part); keep it as-is
        # minus any angle brackets so the value stays human-readable.
        addr = raw.strip().strip('<>').strip()
    return addr


def main() -> int:
    recipient = sys.argv[1].strip() if len(sys.argv) > 1 else ''
    raw = sys.stdin.buffer.read()
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception:
        # Malformed message: accept-and-drop so Postfix does not loop.
        return 0

    if not recipient:
        recipient = _header(msg, 'Delivered-To') or _header(msg, 'To')
    recipient = _address(recipient)
    sender = _address(_header(msg, 'From'))
    subject = _header(msg, 'Subject')
    body = _plain_body(msg)
    body_html = _html_body(msg)

    payload = json.dumps({
        'recipient': recipient,
        'sender': sender,
        'subject': subject,
        'body': body,
        'body_html': body_html,
        'content_type': 'text/html' if body_html else 'text/plain',
        # Threading + de-duplication. Postfix retries this pipe whenever we
        # exit EX_TEMPFAIL, which includes the case where the server stored the
        # message but the HTTP response never made it back; the ingest endpoint
        # uses Message-ID to avoid filing the same reply twice.
        'message_id': _header(msg, 'Message-ID'),
        'in_reply_to': _header(msg, 'In-Reply-To'),
    }).encode('utf-8')

    req = urllib.request.Request(
        INGEST_URL, data=payload, method='POST',
        headers={'Content-Type': 'application/json',
                 'X-Titan-Mail-Token': _load_token()},
    )
    ctx = None
    if INGEST_URL.lower().startswith('https'):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            resp.read()
    except Exception as e:
        # Temporary failure: exit non-zero so Postfix retries later.
        sys.stderr.write(f"titan mail delivery failed: {e}\n")
        return 75  # EX_TEMPFAIL
    return 0


if __name__ == '__main__':
    sys.exit(main())
