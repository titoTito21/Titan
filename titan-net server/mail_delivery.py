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
import json
import os
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


def _plain_body(msg) -> str:
    """Extract a readable text body, preferring text/plain."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain' and not part.get_filename():
                try:
                    return part.get_content()
                except Exception:
                    payload = part.get_payload(decode=True) or b''
                    return payload.decode('utf-8', 'replace')
        for part in msg.walk():
            if part.get_content_type() == 'text/html' and not part.get_filename():
                try:
                    return part.get_content()
                except Exception:
                    payload = part.get_payload(decode=True) or b''
                    return payload.decode('utf-8', 'replace')
        return ''
    try:
        return msg.get_content()
    except Exception:
        payload = msg.get_payload(decode=True) or b''
        return payload.decode('utf-8', 'replace')


def main() -> int:
    recipient = sys.argv[1].strip() if len(sys.argv) > 1 else ''
    raw = sys.stdin.buffer.read()
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception:
        # Malformed message: accept-and-drop so Postfix does not loop.
        return 0

    if not recipient:
        recipient = (msg.get('Delivered-To') or msg.get('To') or '').strip()
    sender = (msg.get('From') or '').strip()
    subject = (msg.get('Subject') or '').strip()
    body = _plain_body(msg)

    payload = json.dumps({
        'recipient': recipient,
        'sender': sender,
        'subject': subject,
        'body': body,
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
