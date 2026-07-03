"""
Titan-Net Server - Outbound mailer

A thin wrapper around smtplib that hands messages to an SMTP relay. By default
the relay is the local Postfix instance on the VPS (127.0.0.1:25), so this code
is identical whether you self-host Postfix or point SMTP_* at an external
provider - only the .env changes.

Used for account email verification and password recovery, and by the mailbox
subsystem to deliver user-composed mail. All failures are logged and swallowed
so a mail problem never crashes the request that triggered it; callers decide
what to tell the user.
"""

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from config import Config

logger = logging.getLogger('titan-net.mailer')


def is_enabled() -> bool:
    return bool(Config.MAIL_ENABLED)


def _public_url() -> str:
    return (Config.MAIL_PUBLIC_URL or '').rstrip('/')


def send_mail(to_addr: str, subject: str, body: str,
              from_addr: str = None, from_name: str = None) -> bool:
    """Send a plain-text email. Returns True on success, False otherwise.

    Never raises - a mailer failure must not take down the caller."""
    if not is_enabled():
        logger.info("Mail disabled (MAIL_ENABLED=0); would have sent to %s: %s", to_addr, subject)
        return False
    if not to_addr:
        return False
    from_addr = from_addr or Config.MAIL_FROM
    from_name = from_name or Config.MAIL_FROM_NAME
    try:
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = formataddr((from_name, from_addr))
        msg['To'] = to_addr
        msg['Message-ID'] = make_msgid(domain=Config.MAIL_DOMAIN)
        msg.set_content(body)
        _deliver(msg, from_addr, [to_addr])
        logger.info("Sent mail to %s: %s", to_addr, subject)
        return True
    except Exception as e:
        logger.error("Failed to send mail to %s: %s", to_addr, e, exc_info=True)
        return False


def send_message(msg: EmailMessage, envelope_from: str, recipients) -> bool:
    """Deliver a pre-built EmailMessage (used by the mailbox 'send' path)."""
    if not is_enabled():
        logger.info("Mail disabled; would have sent message to %s", recipients)
        return False
    try:
        _deliver(msg, envelope_from, list(recipients))
        return True
    except Exception as e:
        logger.error("Failed to send message to %s: %s", recipients, e, exc_info=True)
        return False


def _deliver(msg: EmailMessage, envelope_from: str, recipients):
    host = Config.SMTP_HOST
    port = Config.SMTP_PORT
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        if Config.SMTP_TLS:
            smtp.starttls()
        if Config.SMTP_USER:
            smtp.login(Config.SMTP_USER, Config.SMTP_PASS)
        smtp.send_message(msg, from_addr=envelope_from, to_addrs=recipients)


# ----- Transactional templates -----

def send_verification(to_addr: str, username: str, token: str) -> bool:
    """Email an account-verification link."""
    link = f"{_public_url()}/verify.html?token={token}"
    subject = "Verify your Titan-Net email address"
    body = (
        f"Hello {username},\n\n"
        "Please confirm this email address for your Titan-Net account by "
        "opening the link below:\n\n"
        f"{link}\n\n"
        "This link expires in 24 hours. If you did not request this, you can "
        "safely ignore this message.\n\n"
        "Titan-Net"
    )
    return send_mail(to_addr, subject, body)


def send_password_reset(to_addr: str, username: str, token: str) -> bool:
    """Email a password-reset link."""
    link = f"{_public_url()}/reset.html?token={token}"
    subject = "Reset your Titan-Net password"
    body = (
        f"Hello {username},\n\n"
        "We received a request to reset your Titan-Net password. Open the link "
        "below to choose a new one:\n\n"
        f"{link}\n\n"
        "This link expires in 1 hour and can be used once. If you did not "
        "request a reset, you can ignore this message - your password will not "
        "change.\n\n"
        "Titan-Net"
    )
    return send_mail(to_addr, subject, body)
