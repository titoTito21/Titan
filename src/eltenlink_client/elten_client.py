"""
EltenLink HTTP API Client.
Provides Python interface to the Elten social network for the blind.
Based on Elten Ruby source code (eltenapi.rb, EltenSRV.rb, scene files).
"""

import re
import requests
import random
import socket
import time
import urllib.parse
from datetime import datetime

from src.titan_core.translation import set_language
from src.settings.settings import get_setting

_ = set_language(get_setting('language', 'pl'))


class EltenLinkClient:
    """HTTP client for Elten server API (legacy PHP endpoints).

    Server: srvapi.elten.link/leg1/{module}.php
    Auth: name + token as GET params on every request.
    Response: \\r\\n separated lines, first line is status code.
    Separators: \\004END\\004 for record blocks, \\004LINE\\004 for newlines in content.
    """

    BASE_URL = "https://srvapi.elten.link/leg1/"
    APP_VERSION = "2.5"
    APP_ID = "TCELauncher"

    # Error code mapping from PHP source
    ERROR_MESSAGES = {
        '-1': _("Database error"),
        '-2': _("Invalid username or password"),
        '-3': _("Permission denied"),
        '-4': _("User not found"),
        '-5': _("Two-factor authentication required"),
        '-6': _("Incorrect old password"),
        '-7': _("Email change not allowed"),
    }

    def __init__(self):
        self.username = None
        self.token = None
        self.password = None
        self.is_connected = False
        self.moderator = False
        self.full_name = ""
        self.gender = 0
        self.languages = ""
        self.greeting = ""

        # Callbacks
        self.on_message_received = None
        self.on_user_online = None
        self.on_user_offline = None
        self.on_connection_lost = None

        # HTTP session - User-Agent matches Ruby client format: "Elten {version} agent"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': f'Elten {self.APP_VERSION} agent',
            'Accept-Encoding': 'gzip, deflate',
        })

    # ---- HTTP Request Helpers ----

    def _request(self, endpoint, params=None, timeout=10):
        """Make HTTP GET request to Elten API.

        Args:
            endpoint: PHP file name (e.g., 'login.php')
            params: dict of query parameters
            timeout: request timeout in seconds

        Returns:
            Raw response text
        """
        url = self.BASE_URL + endpoint
        if params is None:
            params = {}

        try:
            response = self.session.get(url, params=params, timeout=timeout)
            response.encoding = 'utf-8'
            return response.text
        except requests.exceptions.Timeout:
            raise TimeoutError(_("Connection timeout"))
        except requests.exceptions.ConnectionError:
            raise ConnectionError(_("Connection failed"))

    def _post_request(self, endpoint, params=None, post_data=None, timeout=10):
        """Make HTTP POST request with multipart form data.

        Used for message sending, forum posting, etc.
        Based on Ruby eltenapi.rb buffer() method.

        Args:
            endpoint: PHP file name
            params: dict of GET query parameters
            post_data: dict of POST form fields
            timeout: request timeout
        """
        url = self.BASE_URL + endpoint
        if params is None:
            params = {}

        # Build multipart boundary like Ruby: "----EltBoundary{random}"
        boundary = f"----EltBoundary{random.randint(100000, 999999)}"

        # Build multipart body
        body_parts = []
        for key, value in (post_data or {}).items():
            body_parts.append(f'--{boundary}\r\n')
            body_parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n')
            body_parts.append(f'{value}\r\n')
        body_parts.append(f'--{boundary}--\r\n')
        body = ''.join(body_parts)

        try:
            response = self.session.post(
                url,
                params=params,
                data=body.encode('utf-8'),
                headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
                timeout=timeout,
            )
            response.encoding = 'utf-8'
            return response.text
        except requests.exceptions.Timeout:
            raise TimeoutError(_("Connection timeout"))
        except requests.exceptions.ConnectionError:
            raise ConnectionError(_("Connection failed"))

    def _auth_request(self, endpoint, params=None, timeout=10):
        """Make authenticated GET request (adds name + token to params).

        Like Ruby srvproc() which auto-adds Session.name and Session.token.
        """
        if not self.is_connected:
            raise ConnectionError(_("Not connected"))

        if not self._ensure_token():
            raise ConnectionError(_("Token refresh failed"))

        if params is None:
            params = {}
        params['name'] = self.username
        params['token'] = self.token

        return self._request(endpoint, params, timeout)

    def _auth_post_request(self, endpoint, params=None, post_data=None, timeout=10):
        """Make authenticated POST request."""
        if not self.is_connected:
            raise ConnectionError(_("Not connected"))

        if not self._ensure_token():
            raise ConnectionError(_("Token refresh failed"))

        if params is None:
            params = {}
        params['name'] = self.username
        params['token'] = self.token

        return self._post_request(endpoint, params, post_data, timeout)

    def _parse_response(self, text):
        """Parse \\r\\n separated response into list of lines."""
        if not text:
            return []
        # Strip BOM (Byte Order Mark) that some server responses include
        text = text.lstrip('\ufeff')
        # Strip HTML tags (PHP sometimes leaks <br /> notices before response)
        # Remove tags entirely (don't convert to newlines) to preserve line indices
        text = re.sub(r'<[^>]+>', '', text)
        return text.split("\r\n")

    def _check_status(self, lines):
        """Check first line status code.

        Returns:
            (success: bool, error_message: str or None)
        """
        if not lines:
            return False, _("Empty response from server")
        status = lines[0].strip()
        if status == '0':
            return True, None
        error_msg = self.ERROR_MESSAGES.get(status, f"Error: {status}")
        return False, error_msg

    def _safe_int(self, value, default=0):
        """Safely parse integer from response field."""
        try:
            return int(value.strip())
        except (ValueError, AttributeError):
            return default

    @staticmethod
    def _strip_html(text):
        """Strip HTML tags and decode entities for plain text display."""
        if not text:
            return text
        # Replace <br>, <br/>, <br /> with newlines
        text = re.sub(r'<br\s*/?\s*>', '\n', text, flags=re.IGNORECASE)
        # Replace <p> and </p> with newlines
        text = re.sub(r'</?p\s*>', '\n', text, flags=re.IGNORECASE)
        # Remove all other HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Decode common HTML entities
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        text = text.replace('&#39;', "'")
        text = text.replace('&nbsp;', ' ')
        # Collapse multiple blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _get_computer_name(self):
        """Get computer name for autologin (like Ruby $computer variable)."""
        try:
            return socket.gethostname()
        except Exception:
            return "TCELauncher"

    # ---- Authentication ----

    def login(self, username, password):
        """Login to EltenLink.

        Based on Ruby Login.rb scene and login.php endpoint.

        Args:
            username: Elten username
            password: Password

        Returns:
            dict with 'success', 'message', 'requires_2fa'
        """
        params = {
            'login': '1',
            'name': username,
            'password': password,
            'version': self.APP_VERSION,
            'appid': self.APP_ID,
            'submitautologin': '1',
            'computer': self._get_computer_name(),
            'output': '1',
        }

        text = self._request('login.php', params)
        lines = self._parse_response(text)

        if not lines:
            return {'success': False, 'message': _("Empty response from server"), 'requires_2fa': False}

        status = lines[0].strip()

        if status == '-5':
            self.username = username
            self.password = password
            return {'success': False, 'message': _("Two-factor authentication required"), 'requires_2fa': True}

        if status == '-2':
            return {'success': False, 'message': _("Invalid username or password"), 'requires_2fa': False}

        if status != '0':
            return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}"), 'requires_2fa': False}

        # Parse successful login (output=1 format from login.php):
        # 0\r\nusername\r\ntoken\r\nmoderator\r\nfullname\r\ngender\r\nlanguages\r\ngreeting
        self.username = lines[1].strip() if len(lines) > 1 else username
        self.token = lines[2].strip() if len(lines) > 2 else None
        self.moderator = lines[3].strip() == '1' if len(lines) > 3 else False
        self.full_name = lines[4].strip() if len(lines) > 4 else ""
        self.gender = self._safe_int(lines[5]) if len(lines) > 5 else 0
        self.languages = lines[6].strip() if len(lines) > 6 else ""
        self.greeting = lines[7].strip() if len(lines) > 7 else ""
        self.password = password
        self.is_connected = True

        return {'success': True, 'message': self.greeting or _("Login successful"), 'requires_2fa': False}

    def verify_2fa(self, code):
        """Verify two-factor authentication code.

        Based on authentication.php: authenticate=1 with code and appid.
        """
        params = {
            'authenticate': '1',
            'name': self.username,
            'code': code,
            'appid': self.APP_ID,
        }

        text = self._request('authentication.php', params)
        lines = self._parse_response(text)
        status = lines[0].strip() if lines else '-1'

        if status == '0':
            result = self.login(self.username, self.password)
            return result
        elif status == '-3':
            return {'success': False, 'message': _("Invalid code")}
        elif status == '-4':
            return {'success': False, 'message': _("Authentication record not found")}
        else:
            return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    def send_2fa_sms(self):
        """Re-trigger login with authmethod=phone to resend SMS."""
        params = {
            'login': '1',
            'name': self.username,
            'password': self.password,
            'version': self.APP_VERSION,
            'appid': self.APP_ID,
            'output': '1',
            'authmethod': 'phone',
        }
        self._request('login.php', params)

    def check_token(self):
        """Check if current token is valid via header.php.

        header.php validates token against tokens table.
        Tokens expire after 1 day but auto-renew if used within 24h.
        """
        if not self.token or not self.username:
            return False

        try:
            text = self._request('header.php', {
                'name': self.username,
                'token': self.token,
            }, timeout=5)
            return not text.strip().startswith('-')
        except Exception:
            return False

    def refresh_token(self):
        """Re-login using stored password to get a fresh token."""
        if not self.password or not self.username:
            return False

        try:
            result = self.login(self.username, self.password)
            return result.get('success', False)
        except Exception:
            return False

    def _ensure_token(self):
        """Check token and refresh if needed. Called before each authenticated request."""
        if not self.token:
            return self.refresh_token()

        if not self.check_token():
            return self.refresh_token()

        return True

    def logout(self):
        """Logout and clear session."""
        self.username = None
        self.token = None
        self.password = None
        self.is_connected = False
        self.moderator = False
        self.full_name = ""

    def register(self, username, password, email):
        """Register new account via register.php."""
        params = {
            'register': '1',
            'name': username,
            'password': password,
            'mail': email,
        }

        text = self._request('register.php', params)
        lines = self._parse_response(text)
        status = lines[0].strip() if lines else '-1'

        if status == '0':
            return {'success': True, 'message': _("Account created successfully")}
        elif status == '-2':
            return {'success': False, 'message': _("Username already exists or is invalid")}
        else:
            return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    # ---- Messages ----

    def get_conversations(self):
        """Get all conversations list.

        Endpoint: messages_conversations.php?details=3
        Response: status[0], count[1], has_more[2],
                  [per conv: user, lastuser, date, subject, read, id, muted, name] (8 fields)
        Based on Ruby Scene_Messages.load_users()
        """
        text = self._auth_request('messages_conversations.php', {
            'details': '3',
            'limit': '100',
        })
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return []

        conversations = []
        count = self._safe_int(lines[1]) if len(lines) > 1 else 0
        idx = 3  # Header: status[0], count[1], has_more[2]
        fields_per_conv = 8  # user, lastuser, date, subject, read, id, muted, name
        for _ in range(count):
            if idx + fields_per_conv - 1 >= len(lines):
                break
            conv = {
                'user': lines[idx].strip(),
                'lastuser': lines[idx + 1].strip(),
                'date': lines[idx + 2].strip(),
                'subject': lines[idx + 3].strip(),
                'read': lines[idx + 4].strip() != '0',
                'id': self._safe_int(lines[idx + 5]),
                'muted': self._safe_int(lines[idx + 6]) == 1,
                'display_name': lines[idx + 7].strip() if idx + 7 < len(lines) else '',
            }
            conversations.append(conv)
            idx += fields_per_conv

        return conversations

    def get_conversation_subjects(self, user):
        """Get conversation subjects with a specific user.

        Endpoint: messages_conversations.php?user={user}&details=1
        Response: status[0], count[1], has_more[2], user_exists[3], name[4],
                  [per subject: subject, lastuser, date, read, id] (5 fields)
        Based on Ruby Scene_Messages.load_conversations()
        """
        text = self._auth_request('messages_conversations.php', {
            'user': user,
            'details': '1',
        })
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return []

        subjects = []
        count = self._safe_int(lines[1]) if len(lines) > 1 else 0
        # Header: status[0], count[1], has_more[2], user_exists[3], name[4]
        idx = 5
        for _ in range(count):
            if idx + 4 >= len(lines):
                break
            subj = {
                'subject': lines[idx].strip(),
                'last_sender': lines[idx + 1].strip(),
                'date': lines[idx + 2].strip(),
                'read': lines[idx + 3].strip() != '0',
                'id': self._safe_int(lines[idx + 4]),
            }
            subjects.append(subj)
            idx += 5

        return subjects

    def get_conversation_messages(self, user, subject="", message_id=None):
        """Get messages in a conversation.

        With subject: messages_conversations.php?user={user}&subj={subject}&details=3
            Returns \004END\004-separated message blocks.
            Per block (details=3): id, sender, subject, date, read, marked, attachments, protected, message
            Based on Ruby Scene_Messages.load_messages()
        Without subject (ignoresubj=1): returns flat 5-field entries (subjects list).
        """
        params = {
            'user': user,
            'details': '3',
        }
        if message_id:
            params['id'] = str(message_id)
        elif subject:
            params['subj'] = subject
        else:
            params['ignoresubj'] = '1'

        text = self._auth_request('messages_conversations.php', params)
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return []

        # Header: status[0], count[1], has_more[2], can_reply[3], conversation_name[4]
        count = self._safe_int(lines[1]) if len(lines) > 1 else 0
        header_end = 5

        # Without specific subject: API returns flat 5-field entries (subjects list)
        # Ruby uses ignoresubj=1 for this case
        if not subject and not message_id:
            messages = []
            idx = header_end
            for _ in range(count):
                if idx + 4 >= len(lines):
                    break
                msg = {
                    'id': self._safe_int(lines[idx]),
                    'sender': lines[idx + 1].strip(),
                    'subject': lines[idx + 2].strip(),
                    'date': lines[idx + 3].strip(),
                    'read': lines[idx + 4].strip() != '0',
                    'message': lines[idx + 2].strip(),  # subject as message preview
                }
                messages.append(msg)
                idx += 5
            return messages

        # With specific subject: messages separated by \004END\004
        # Per block (details=3): id, sender, subject, date, read, marked, attachments, protected, message text
        # Based on Ruby Scene_Messages.load_messages() field order
        content = "\r\n".join(lines[header_end:])
        blocks = content.split("\004END\004")

        messages = []
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            block_lines = block.split("\r\n")
            if len(block_lines) < 5:
                continue

            msg = {
                'id': self._safe_int(block_lines[0]),
                'sender': block_lines[1].strip(),
                'subject': block_lines[2].strip() if len(block_lines) > 2 else subject,
                'date': block_lines[3].strip() if len(block_lines) > 3 else '',
                'read': self._safe_int(block_lines[4]) > 0 if len(block_lines) > 4 else False,
                'marked': self._safe_int(block_lines[5]) if len(block_lines) > 5 else 0,
                'attachments': block_lines[6].strip() if len(block_lines) > 6 else '',
                'protected': self._safe_int(block_lines[7]) if len(block_lines) > 7 else 0,
                'message': "\n".join(block_lines[8:]).replace("\004LINE\004", "\n").strip(),
            }
            messages.append(msg)

        return messages

    def send_message(self, to, subject, text_body):
        """Send a private message.

        Based on Ruby Scene_Messages_New.rb:
        GET params: to, subject (+ auth)
        POST body: multipart with 'text' field
        """
        if not self._ensure_token():
            return {'success': False, 'message': _("Token refresh failed")}

        params = {
            'name': self.username,
            'token': self.token,
            'to': to,
            'subject': subject,
        }

        post_data = {
            'text': text_body,
        }

        resp = self._post_request('message_send.php', params, post_data)
        lines = self._parse_response(resp)
        status = lines[0].strip() if lines else '-1'

        if status == '0':
            return {'success': True, 'message': _("Message sent")}
        elif status == '-3':
            return {'success': False, 'message': _("User has blocked you")}
        elif status == '-4':
            return {'success': False, 'message': _("User not found")}
        else:
            return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    def delete_message(self, message_id):
        """Delete a single message. Endpoint: messages.php?delete=1&id={id}"""
        text = self._auth_request('messages.php', {'delete': '1', 'id': str(message_id)})
        return text.strip().startswith('0')

    def delete_conversation(self, user, subject=""):
        """Delete conversation. messages.php?delete=2 or delete=3"""
        params = {'user': user}
        if subject:
            params['delete'] = '2'
            params['subj'] = subject
        else:
            params['delete'] = '3'
        text = self._auth_request('messages.php', params)
        return text.strip().startswith('0')

    def mark_all_read(self, user=None):
        """Mark messages as read. Endpoint: message_allread.php"""
        params = {}
        if user:
            params['user'] = user
        text = self._auth_request('message_allread.php', params)
        return text.strip().startswith('0')

    def get_new_messages(self):
        """Get new/unread messages. messages_conversations.php?sp=new
        Based on Ruby Scene_Messages.load_conversations(user, "new")
        Field order: subject, user, date, read, id (5 fields per entry)
        """
        text = self._auth_request('messages_conversations.php', {'sp': 'new', 'details': '1'})
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return []

        messages = []
        count = self._safe_int(lines[1]) if len(lines) > 1 else 0
        idx = 5  # Header: status[0], count[1], has_more[2], ?[3], name[4]
        fields_per = 5
        for _ in range(count):
            if idx + fields_per - 1 >= len(lines):
                break
            msg = {
                'subject': lines[idx].strip(),
                'user': lines[idx + 1].strip(),
                'date': lines[idx + 2].strip(),
                'read': lines[idx + 3].strip() != '0',
                'id': self._safe_int(lines[idx + 4]),
                'unread': True,
            }
            messages.append(msg)
            idx += fields_per

        return messages

    # ---- Contacts ----

    def get_contacts(self):
        """Get contacts list. Endpoint: contacts.php
        Response: 0\\r\\nname1\\r\\nname2\\r\\n...
        """
        text = self._auth_request('contacts.php')
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return []

        return [line.strip() for line in lines[1:] if line.strip()]

    def add_contact(self, username):
        """Add contact. contacts_mod.php?insert=1&searchname={user}"""
        text = self._auth_request('contacts_mod.php', {'insert': '1', 'searchname': username})
        lines = self._parse_response(text)
        status = lines[0].strip() if lines else '-1'
        if status == '0':
            return {'success': True, 'message': _("Contact added")}
        elif status == '-3':
            return {'success': False, 'message': _("Already in contacts")}
        else:
            return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    def remove_contact(self, username):
        """Remove contact. contacts_mod.php?delete=1&searchname={user}"""
        text = self._auth_request('contacts_mod.php', {'delete': '1', 'searchname': username})
        lines = self._parse_response(text)
        status = lines[0].strip() if lines else '-1'
        if status == '0':
            return {'success': True, 'message': _("Contact removed")}
        else:
            return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    # ---- Forum ----

    def get_forum_structure(self):
        """Get forum structure (groups, forums, threads).

        Endpoint: forum_struct.php?useflags=1
        Response: structured \\r\\n data with sections: groups, forums, threads
        Each section: type\\r\\ncount\\r\\nfields_per_item\\r\\n[fields...]
        """
        text = self._auth_request('forum_struct.php', {'useflags': '1'})
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return {'groups': [], 'forums': [], 'threads': []}

        result = {'groups': [], 'forums': [], 'threads': []}

        # Skip first line (status "0") and any empty ident line
        idx = 1
        while idx < len(lines) and not lines[idx].strip():
            idx += 1

        # Skip ident line (40-char hash) if present
        if idx < len(lines) and len(lines[idx].strip()) == 40:
            idx += 1

        while idx < len(lines):
            if not lines[idx].strip():
                idx += 1
                continue

            section_type = lines[idx].strip()
            idx += 1

            if section_type not in ('groups', 'forums', 'threads'):
                continue

            if idx >= len(lines):
                break
            count = self._safe_int(lines[idx])
            idx += 1

            if idx >= len(lines):
                break
            fields_per_item = self._safe_int(lines[idx])
            idx += 1

            if fields_per_item == 0 or count == 0:
                continue

            all_values = []
            for _ in range(count * fields_per_item):
                if idx < len(lines):
                    val = lines[idx].replace("\004LINE\004", "\n")
                    all_values.append(val)
                    idx += 1

            for i in range(count):
                start = i * fields_per_item
                end = start + fields_per_item
                if end > len(all_values):
                    break
                vals = all_values[start:end]

                if section_type == 'groups':
                    # Group fields (25): id, name, founder, description, lang, flags, role,
                    #   forums_count, threads_count, posts_count, readposts, acmembers, created, ...
                    group = {
                        'id': self._safe_int(vals[0]),
                        'name': vals[1] if len(vals) > 1 else '',
                        'founder': vals[2] if len(vals) > 2 else '',
                        'description': (vals[3] if len(vals) > 3 else '').replace('$', '\n'),
                        'lang': vals[4] if len(vals) > 4 else '',
                        'flags': self._safe_int(vals[5]) if len(vals) > 5 else 0,
                        'role': self._safe_int(vals[6]) if len(vals) > 6 else 0,
                        'forums_count': self._safe_int(vals[7]) if len(vals) > 7 else 0,
                        'threads_count': self._safe_int(vals[8]) if len(vals) > 8 else 0,
                        'posts_count': self._safe_int(vals[9]) if len(vals) > 9 else 0,
                    }
                    result['groups'].append(group)

                elif section_type == 'forums':
                    # Forum id is a string identifier (like Ruby Struct_Forum_Forum.id)
                    # NOT a numeric int - used as key for thread→forum mapping
                    forum = {
                        'id': vals[0].strip(),
                        'name': vals[1].strip() if len(vals) > 1 else '',
                        'type': vals[2].strip() if len(vals) > 2 else '',
                        'group_id': self._safe_int(vals[3]) if len(vals) > 3 else 0,
                        'description': vals[4].strip() if len(vals) > 4 else '',
                    }
                    result['forums'].append(forum)

                elif section_type == 'threads':
                    # Thread fields (from Ruby Forum.rb threadscache):
                    # 0=thread_id, 1=name, 2=author, 3=forum_id (string ref matching forum['id']),
                    # 4=post_count, 5=read_count, 6=flags, 7=last_update, 8=offered_group
                    thread = {
                        'id': self._safe_int(vals[0]),
                        'name': vals[1].strip() if len(vals) > 1 else '',
                        'author': vals[2].strip() if len(vals) > 2 else '',
                        'forum_id': vals[3].strip() if len(vals) > 3 else '',
                        'post_count': self._safe_int(vals[4]) if len(vals) > 4 else 0,
                        'read_count': self._safe_int(vals[5]) if len(vals) > 5 else 0,
                        'flags': vals[6].strip() if len(vals) > 6 else '',
                        'last_update': vals[7].strip() if len(vals) > 7 else '',
                    }
                    result['threads'].append(thread)

        return result

    def get_forum_groups(self):
        """Get just forum groups."""
        structure = self.get_forum_structure()
        return structure.get('groups', [])

    def get_forums_in_group(self, group_id):
        """Get forums in a specific group."""
        structure = self.get_forum_structure()
        return [f for f in structure.get('forums', []) if f.get('group_id') == group_id]

    def get_threads_in_forum(self, forum_id):
        """Get threads in a specific forum.

        Args:
            forum_id: Forum identifier (string, matches forum['id'] from structure)
        """
        structure = self.get_forum_structure()
        # forum_id is a string matching forum['id'] (Ruby: Struct_Forum_Forum.id)
        forum_id_str = str(forum_id).strip()
        return [t for t in structure.get('threads', []) if t.get('forum_id', '').strip() == forum_id_str]

    def get_thread_posts(self, thread_id):
        """Get posts in a thread.

        Endpoint: forum_thread.php?thread={id}&details=1
        Response: 0, timestamp, total_posts, read_posts, followed,
                  then per post: id, author, [content lines...], \\004END\\004,
                  date, polls, attachments, liked, edited,
                  [signature lines...], \\004END\\004 (resets to next post)
        """
        text = self._auth_request('forum_thread.php', {
            'thread': str(thread_id),
            'details': '1',
        })
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return []

        # Header: status[0], timestamp[1], total_posts[2], read_posts[3], followed[4]
        total_posts = self._safe_int(lines[2]) if len(lines) > 2 else 0
        content = "\r\n".join(lines[5:])

        posts = []
        # Split by \004END\004 to get alternating [content, metadata+signature] blocks
        raw_blocks = content.split("\004END\004")

        # Process in groups of 3: content_block, metadata_block (between 2 ENDs), then next post
        # Actually the pattern is: id\r\nauthor\r\n[text]\004END\004\r\ndate\r\npolls\r\natts\r\nliked\r\nedited\r\n[sig]\004END\004
        i = 0
        while i < len(raw_blocks) - 1:
            content_block = raw_blocks[i]
            # Remove leading/trailing whitespace but preserve internal structure
            content_lines = content_block.strip().split("\r\n")

            if len(content_lines) < 2:
                i += 1
                continue

            post_id = content_lines[0].strip()
            author = content_lines[1].strip()
            post_text = "\n".join(content_lines[2:]).replace("\004LINE\004", "\n")

            # Extract audio URL from \004AUDIO\004<path>\004AUDIO\004 marker
            # Ruby: file = $url + file[1..-1] where $url = "https://srvapi.elten.link/leg1/"
            import re as _re
            audio_url = ''
            audio_match = _re.search(r'\x04AUDIO\x04([^\x04]+)\x04AUDIO\x04', post_text)
            if audio_match:
                audio_path = audio_match.group(1).strip()
                if audio_path.startswith('http'):
                    audio_url = audio_path
                else:
                    audio_url = self.BASE_URL + audio_path.lstrip('/')
                post_text = _re.sub(r'\x04AUDIO\x04[^\x04]+\x04AUDIO\x04', '', post_text).strip()

            # Next block: date, polls, attachments, liked, edited, [signature], ...
            meta_block = raw_blocks[i + 1] if i + 1 < len(raw_blocks) else ""
            meta_lines = meta_block.strip().split("\r\n")

            date_str = meta_lines[0].strip() if meta_lines else ""
            polls = meta_lines[1].strip() if len(meta_lines) > 1 else ""
            attachments = meta_lines[2].strip() if len(meta_lines) > 2 else ""
            liked = meta_lines[3].strip() == '1' if len(meta_lines) > 3 else False
            edited = meta_lines[4].strip() == '1' if len(meta_lines) > 4 else False
            signature = "\n".join(meta_lines[5:]).replace("\004LINE\004", "\n").strip() if len(meta_lines) > 5 else ""

            post = {
                'id': self._safe_int(post_id),
                'author': author,
                'content': post_text,
                'audio_url': audio_url,
                'date': date_str,
                'attachments': attachments,
                'liked': liked,
                'edited': edited,
                'signature': signature,
            }
            posts.append(post)
            # Skip content block + meta/signature block (2 \004END\004 per post)
            i += 2

        return posts

    def search_forum(self, query):
        """Search forum. Endpoint: forum_search.php?query={term}"""
        text = self._auth_request('forum_search.php', {'query': query})
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return []

        results = []
        count = self._safe_int(lines[1]) if len(lines) > 1 else 0
        idx = 2
        for _ in range(count):
            if idx + 1 >= len(lines):
                break
            results.append({
                'thread_id': self._safe_int(lines[idx]),
                'post_count': self._safe_int(lines[idx + 1]),
            })
            idx += 2

        return results

    def join_forum_group(self, group_id):
        """Join a forum group. forum_groups.php?ac=join&groupid={id}"""
        text = self._auth_request('forum_groups.php', {
            'ac': 'join',
            'groupid': str(group_id),
        })
        return text.strip().startswith('0')

    def leave_forum_group(self, group_id):
        """Leave a forum group. forum_groups.php?ac=leave&groupid={id}"""
        text = self._auth_request('forum_groups.php', {
            'ac': 'leave',
            'groupid': str(group_id),
        })
        return text.strip().startswith('0')

    def get_group_members(self, group_id):
        """Get members of a forum group. forum_groups.php?ac=members&groupid={id}"""
        text = self._auth_request('forum_groups.php', {
            'ac': 'members',
            'groupid': str(group_id),
        })
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return []

        return [line.strip() for line in lines[1:] if line.strip()]

    # ---- Blogs ----

    def get_blogs_list(self, order_by=0):
        """Get list of blogs.

        Endpoint: blog_list.php?details=2 (matching Ruby: 9 fields per blog)
        Args:
            order_by: 0=recent, 1=active, 2=discussed, 3=followed, 5=my blogs
        """
        text = self._auth_request('blog_list.php', {
            'orderby': str(order_by),
            'details': '2',
        })
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return []

        blogs = []
        count = self._safe_int(lines[1]) if len(lines) > 1 else 0
        rows = 9  # Ruby: rows = 9 with details=2
        idx = 2
        for _ in range(count):
            if idx + rows - 1 >= len(lines):
                break
            blog = {
                'domain': lines[idx].strip(),
                'name': lines[idx + 1].strip(),
                'posts': self._safe_int(lines[idx + 2]),
                'comments': self._safe_int(lines[idx + 3]),
                'url': lines[idx + 4].strip(),
                'last_post': lines[idx + 5].strip(),
                'description': lines[idx + 6].strip(),
                'followed': self._safe_int(lines[idx + 7]) > 0,
                'lang': lines[idx + 8].strip() if idx + 8 < len(lines) else '',
            }
            blogs.append(blog)
            idx += rows

        return blogs

    def get_blog_posts(self, blog_name, category_id=0, page=1):
        """Get blog posts.

        Endpoint: blog_posts.php?searchname={name}&details=3&categoryid={cat}
        With details=3 (matching Ruby): 10 fields per post:
            id, title, unread, owner, is_audio, date, url, author, comments, followed
        Header: status[0], count[1], has_more[2], then post data from index 3.
        category_id can be numeric (0=all) or string ("FOLLOWED", "MENTIONED").
        Pages are 1-indexed (matching Ruby).
        """
        params = {
            'searchname': blog_name,
            'details': '3',
            'categoryid': str(category_id),
            'paginate': '1',
            'page': str(page),
        }

        text = self._auth_request('blog_posts.php', params)
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return [], False

        posts = []
        count = self._safe_int(lines[1]) if len(lines) > 1 else 0
        has_more = self._safe_int(lines[2]) > 0 if len(lines) > 2 else False
        idx = 3  # status[0], count[1], has_more[2]

        fields_per = 10
        for _ in range(count):
            if idx + fields_per - 1 >= len(lines):
                break
            post = {
                'id': self._safe_int(lines[idx]),
                'title': lines[idx + 1].strip(),
                'is_new': self._safe_int(lines[idx + 2]) > 0,
                'blog': lines[idx + 3].strip(),
                'is_audio': self._safe_int(lines[idx + 4]) > 0,
                'date': lines[idx + 5].strip(),
                'url': lines[idx + 6].strip(),
                'author': lines[idx + 7].strip(),
                'comments': self._safe_int(lines[idx + 8]),
                'followed': lines[idx + 9].strip() == '1',
            }
            posts.append(post)
            idx += fields_per

        return posts, has_more

    def get_blog_categories(self, blog_name):
        """Get blog categories.

        Endpoint: blog_categories.php?searchname={name}&details=1
        Response: 0, blog_name, count, [id, name, parent_id, post_count, url per category]
        """
        text = self._auth_request('blog_categories.php', {
            'searchname': blog_name,
            'details': '1',
        })
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return []

        blog_title = lines[1].strip() if len(lines) > 1 else ''
        count = self._safe_int(lines[2]) if len(lines) > 2 else 0

        categories = []
        idx = 3
        for _ in range(count):
            if idx + 4 >= len(lines):
                break
            cat = {
                'id': self._safe_int(lines[idx]),
                'name': lines[idx + 1].strip(),
                'parent_id': self._safe_int(lines[idx + 2]),
                'post_count': self._safe_int(lines[idx + 3]),
                'url': lines[idx + 4].strip(),
            }
            categories.append(cat)
            idx += 5

        return categories

    def get_blog_post_content(self, post_id, blog_name):
        """Get full blog post content.

        Endpoint: blog_read.php?postid={id}&searchname={name}&details=8
        Parsed line-by-line matching Ruby Blog.rb state machine:
          Header: status[0], entry_count[1], known_posts[2], comments[3], is_elten_blog[4]
          Per entry (state t=1..7+):
            t=1: id, t=2: is_elten_user, t=3: author, t=4: date, t=5: moddate, t=6: audio_url
            t=7: excerpt lines (loop until \\004END\\004)
            t>7: content lines (until \\004END\\004)
        """
        text = self._auth_request('blog_read.php', {
            'postid': str(post_id),
            'searchname': blog_name,
            'details': '8',
            'html': '1',
        })
        lines = self._parse_response(text)
        print(f"[EltenLink] blog_read raw lines count: {len(lines)}, first 10: {lines[:10]}")
        ok, err = self._check_status(lines)
        if not ok:
            print(f"[EltenLink] blog_read status check failed: {err}")
            return {'posts': []}

        # Header
        entry_count = self._safe_int(lines[1]) if len(lines) > 1 else 0
        comments_count = self._safe_int(lines[3]) if len(lines) > 3 else 0
        print(f"[EltenLink] blog_read entry_count={entry_count}, comments={comments_count}")

        entries = []
        l = 5  # Start parsing entries at index 5

        for i in range(entry_count):
            entry = {
                'id': 0,
                'is_elten_user': False,
                'author': '',
                'date': '',
                'moddate': '',
                'audio_url': '',
                'excerpt': '',
                'content': '',
            }
            t = 0
            excerpt_lines = []
            content_lines = []

            while l < len(lines):
                line = lines[l]
                t += 1

                if t == 1:
                    entry['id'] = self._safe_int(line)
                elif t == 2:
                    entry['is_elten_user'] = line.strip() == '1'
                elif t == 3:
                    entry['author'] = line.strip()
                elif t == 4:
                    entry['date'] = line.strip()
                elif t == 5:
                    entry['moddate'] = line.strip()
                elif t == 6:
                    entry['audio_url'] = line.strip()
                elif t == 7:
                    # Excerpt lines until \004END\004
                    if line.strip() == "\004END\004":
                        pass  # End of excerpt, move to content
                    else:
                        excerpt_lines.append(line)
                        t -= 1  # Stay at t=7 to accumulate more excerpt lines
                elif t > 7:
                    # Content lines until \004END\004
                    if line.strip() == "\004END\004":
                        l += 1  # Move past the END marker
                        break  # Done with this entry
                    else:
                        content_lines.append(line)

                l += 1

                if l >= len(lines):
                    break

            entry['excerpt'] = self._strip_html("\n".join(excerpt_lines).replace("\004LINE\004", "\n").strip())
            entry['content'] = self._strip_html("\n".join(content_lines).replace("\004LINE\004", "\n").strip())

            # If content is empty, use excerpt as content
            if not entry['content'] and entry['excerpt']:
                entry['content'] = entry['excerpt']

            print(f"[EltenLink] Parsed entry {i}: author={entry['author']}, content_len={len(entry['content'])}, excerpt_len={len(entry['excerpt'])}, audio={entry['audio_url']}")
            entries.append(entry)

        print(f"[EltenLink] Total entries parsed: {len(entries)}")
        return {'posts': entries, 'comments_count': comments_count}

    def check_blog_exists(self, username):
        """Check if user has a blog. blog_exist.php?searchname={user}"""
        text = self._auth_request('blog_exist.php', {'searchname': username})
        lines = self._parse_response(text)
        if len(lines) > 1:
            return lines[1].strip() == '1'
        return False

    # ---- Profile / Status / Online ----

    def get_online_users(self):
        """Get list of online users.

        Endpoint: online.php
        Response: 0\\r\\nuser1\\r\\nuser2\\r\\n...
        """
        text = self._auth_request('online.php')
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return []

        return [line.strip() for line in lines[1:] if line.strip()]

    def get_profile(self, username):
        """Get user profile information.

        Endpoint: userinfo.php?searchname={user}
        Response (17 fields): 0, last_seen, has_blog, contacts, known_by,
            elten_version, reg_date, polls_voted, forum_posts, in_contacts,
            deprecated, is_banned, honors, is_guest, ...
        """
        text = self._auth_request('userinfo.php', {'searchname': username})
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return {}

        profile = {
            'username': username,
            'last_seen': lines[1].strip() if len(lines) > 1 else '',
            'has_blog': lines[2].strip() == '1' if len(lines) > 2 else False,
            'contacts_count': self._safe_int(lines[3]) if len(lines) > 3 else 0,
            'known_by_count': self._safe_int(lines[4]) if len(lines) > 4 else 0,
            'elten_version': lines[5].strip() if len(lines) > 5 else '',
            'registration_date': lines[6].strip() if len(lines) > 6 else '',
            'forum_posts': self._safe_int(lines[8]) if len(lines) > 8 else 0,
            'in_contacts': lines[9].strip() == '1' if len(lines) > 9 else False,
            'is_banned': lines[11].strip() == '1' if len(lines) > 11 else False,
            'is_guest': lines[13].strip() == '1' if len(lines) > 13 else False,
        }
        return profile

    def user_exists(self, username):
        """Check if user exists. user_exist.php?searchname={user}"""
        text = self._auth_request('user_exist.php', {'searchname': username})
        lines = self._parse_response(text)
        if len(lines) > 1:
            return lines[1].strip() == '1'
        return False

    def search_users(self, query):
        """Search for users. user_search.php?search={query}"""
        text = self._auth_request('user_search.php', {'search': query})
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return []

        count = self._safe_int(lines[1]) if len(lines) > 1 else 0
        return [lines[i].strip() for i in range(2, 2 + count) if i < len(lines) and lines[i].strip()]

    def get_user_status(self, username):
        """Get user status text. status.php?searchname={user}"""
        text = self._auth_request('status.php', {'searchname': username})
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return ""

        return lines[1].strip() if len(lines) > 1 else ""

    def set_status(self, text_status):
        """Set own status. status_mod.php?text={status}"""
        text = self._auth_request('status_mod.php', {'text': text_status})
        return text.strip().startswith('0')

    # ---- Account Management ----

    def get_account_info(self):
        """Get account information by combining profile data and account.php."""
        # Get profile data (works reliably)
        profile = self.get_profile(self.username)
        if not profile:
            return {}

        info = {
            _("Username"): profile.get('username', ''),
            _("Registration date"): profile.get('registration_date', ''),
            _("Elten version"): profile.get('elten_version', ''),
            _("Forum posts"): str(profile.get('forum_posts', 0)),
            _("Contacts"): str(profile.get('contacts_count', 0)),
            _("Known by"): str(profile.get('known_by_count', 0)),
        }

        # Try to get email from account.php
        try:
            text = self._auth_request('account.php')
            lines = self._parse_response(text)
            ok, err = self._check_status(lines)
            if ok and len(lines) > 1 and lines[1].strip():
                info[_("Email")] = lines[1].strip()
        except Exception:
            pass

        return info

    def change_password(self, old_password, new_password):
        """Change account password. account_mod.php"""
        text = self._auth_request('account_mod.php', {
            'changepassword': '1',
            'oldpassword': old_password,
            'password': new_password,
        })
        lines = self._parse_response(text)
        status = lines[0].strip() if lines else '-1'
        if status == '0':
            self.password = new_password
            return {'success': True, 'message': _("Password changed successfully")}
        elif status == '-6':
            return {'success': False, 'message': _("Incorrect old password")}
        else:
            return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    def change_email(self, email, password):
        """Change account email. account_mod.php"""
        text = self._auth_request('account_mod.php', {
            'changemail': '1',
            'oldpassword': password,
            'mail': email,
        })
        lines = self._parse_response(text)
        status = lines[0].strip() if lines else '-1'
        if status == '0':
            return {'success': True, 'message': _("Email changed successfully")}
        elif status == '-6':
            return {'success': False, 'message': _("Incorrect password")}
        elif status == '-7':
            return {'success': False, 'message': _("Email change not allowed")}
        else:
            return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    def get_account_config(self):
        """Get account settings as JSON. account.php?ac=get"""
        text = self._auth_request('account.php', {'ac': 'get'})
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return {}
        try:
            import json
            return json.loads(lines[1].strip()) if len(lines) > 1 else {}
        except Exception:
            return {}

    def save_account_config(self, config):
        """Save account settings as JSON. account.php?ac=set, POST js=json."""
        import json
        json_str = json.dumps(config)
        text = self._auth_post_request('account.php', {'ac': 'set'}, {'js': json_str})
        if text is None:
            return False
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        return ok

    def get_blacklist(self):
        """Get blacklisted users. blacklist.php?get=1"""
        text = self._auth_request('blacklist.php', {'get': '1'})
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return []
        return [line.strip() for line in lines[1:] if line.strip()]

    def add_to_blacklist(self, user):
        """Add user to blacklist. blacklist.php?add=1&user={user}"""
        text = self._auth_request('blacklist.php', {'add': '1', 'user': user})
        lines = self._parse_response(text)
        status = lines[0].strip() if lines else '-1'
        if status == '0':
            return {'success': True, 'message': _("User added to blacklist")}
        elif status == '-3':
            return {'success': False, 'message': _("You cannot add an administrator to the blacklist")}
        elif status == '-4':
            return {'success': False, 'message': _("This user is already on your blacklist")}
        elif status == '-5':
            return {'success': False, 'message': _("User not found")}
        return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    def remove_from_blacklist(self, user):
        """Remove user from blacklist. blacklist.php?del=1&user={user}"""
        text = self._auth_request('blacklist.php', {'del': '1', 'user': user})
        lines = self._parse_response(text)
        status = lines[0].strip() if lines else '-1'
        if status == '0':
            return {'success': True, 'message': _("User removed from blacklist")}
        return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    def get_auto_logins(self, password):
        """Get auto-login tokens list. autologins.php"""
        text = self._auth_request('autologins.php', {'password': password})
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return None
        tokens = []
        i = 1
        while i + 2 < len(lines):
            timestamp = self._safe_int(lines[i])
            ip = lines[i + 1].strip()
            generation = lines[i + 2].strip()
            try:
                date = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')
            except Exception:
                date = str(timestamp)
            tokens.append({'date': date, 'ip': ip, 'generation': generation})
            i += 3
        return tokens

    def global_logout(self, password):
        """Log out all sessions. logout.php?global=1"""
        text = self._auth_request('logout.php', {'global': '1', 'password': password})
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        return ok

    def get_last_logins(self, password):
        """Get last login history. lastlogins.php"""
        text = self._auth_request('lastlogins.php', {'password': password})
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return None
        logins = []
        i = 1
        while i + 1 < len(lines):
            timestamp = self._safe_int(lines[i])
            ip = lines[i + 1].strip()
            try:
                date = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')
            except Exception:
                date = str(timestamp)
            logins.append({'date': date, 'ip': ip})
            i += 2
        return logins

    def check_2fa_state(self):
        """Check if 2FA is enabled. authentication.php?state=1"""
        text = self._auth_request('authentication.php', {'state': '1'})
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return None
        return self._safe_int(lines[1]) if len(lines) > 1 else 0

    def enable_2fa(self, password, phone, lang='en'):
        """Enable two-factor authentication."""
        text = self._auth_request('authentication.php', {
            'password': password, 'phone': phone, 'enable': '1', 'lang': lang,
        })
        lines = self._parse_response(text)
        status = lines[0].strip() if lines else '-1'
        if status == '0':
            return {'success': True, 'message': _("Two-factor authentication enabled")}
        elif status == '-2':
            return {'success': False, 'message': _("Invalid password")}
        return {'success': False, 'message': f"Error: {status}"}

    def disable_2fa(self, password):
        """Disable two-factor authentication."""
        text = self._auth_request('authentication.php', {
            'password': password, 'disable': '1',
        })
        lines = self._parse_response(text)
        status = lines[0].strip() if lines else '-1'
        if status == '0':
            return {'success': True, 'message': _("Two-factor authentication disabled")}
        elif status == '-2':
            return {'success': False, 'message': _("Invalid password")}
        return {'success': False, 'message': f"Error: {status}"}

    def generate_backup_codes(self, password):
        """Generate 2FA backup codes."""
        text = self._auth_request('authentication.php', {
            'password': password, 'generatebackup': '1',
        })
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return None
        return [line.strip() for line in lines[1:] if line.strip()]

    def archive_account(self, password):
        """Archive account. account_mod.php?archive=1"""
        text = self._auth_request('account_mod.php', {
            'oldpassword': password, 'archive': '1',
        })
        lines = self._parse_response(text)
        status = lines[0].strip() if lines else '-1'
        if status == '0':
            return {'success': True, 'message': _("Account archived")}
        elif status == '-6':
            return {'success': False, 'message': _("Incorrect password")}
        return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    def check_mail_events(self, password):
        """Check mail events status. mailevents.php?ac=check"""
        text = self._auth_request('mailevents.php', {'password': password, 'ac': 'check'})
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return None
        verified = self._safe_int(lines[1]) if len(lines) > 1 else 0
        enabled = self._safe_int(lines[2]) if len(lines) > 2 else 0
        return {'verified': verified, 'enabled': enabled}

    def send_mail_events_verification(self, password):
        """Send mail events verification code. mailevents.php?ac=verify"""
        text = self._auth_request('mailevents.php', {'password': password, 'ac': 'verify'})
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        return ok

    def verify_mail_events_code(self, password, code):
        """Verify mail events with code. mailevents.php?ac=verify&code={code}"""
        text = self._auth_request('mailevents.php', {'password': password, 'ac': 'verify', 'code': code})
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        return ok

    def toggle_mail_events(self, password, enable, code=None):
        """Toggle mail events reporting. mailevents.php?ac=events&enable={0|1}"""
        params = {'password': password, 'ac': 'events', 'enable': '1' if enable else '0'}
        if code:
            params['code'] = code
        text = self._auth_request('mailevents.php', params)
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        return ok

    # ---- Forum Actions ----

    def reply_to_thread(self, thread_id, text_body):
        """Reply to a forum thread.

        Based on Ruby Scene_Forum_NewPost.rb:
        GET: threadid={id} (+ auth)
        POST: multipart with 'post' field
        """
        if not self._ensure_token():
            return {'success': False, 'message': _("Token refresh failed")}

        params = {
            'name': self.username,
            'token': self.token,
            'threadid': str(thread_id),
            'format': '0',
        }

        post_data = {'post': text_body}

        resp = self._post_request('forum_edit.php', params, post_data)
        lines = self._parse_response(resp)
        status = lines[0].strip() if lines else '-1'

        if status == '0':
            return {'success': True, 'message': _("Reply posted")}
        else:
            return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    def create_thread(self, forum_id, thread_name, text_body):
        """Create a new forum thread.

        Args:
            forum_id: Forum identifier (e.g., 'general_pl'), NOT display name
            thread_name: Thread title
            text_body: Post content

        GET: forumname={id}&threadname={title}&post={content} (+ auth)
        """
        if not self._ensure_token():
            return {'success': False, 'message': _("Token refresh failed")}

        print(f"[create_thread] Input params:")
        print(f"  forum_id: '{forum_id}' (type: {type(forum_id).__name__})")
        print(f"  thread_name: '{thread_name}'")
        print(f"  text_body: '{text_body[:100]}...'")

        params = {
            'name': self.username,
            'token': self.token,
            'forumname': forum_id,
            'threadname': thread_name,
            'format': '0',
            'follow': '1',
            'post': text_body,  # Send post content in GET params (like Ruby for text posts)
        }

        print(f"[create_thread] Request params dict:")
        for k, v in params.items():
            if k == 'token':
                print(f"  {k}: [REDACTED]")
            else:
                val_str = str(v)[:100]
                print(f"  {k}: '{val_str}'")

        # No POST data for text posts - PHP expects content in GET params
        resp = self._auth_request('forum_edit.php', params)
        print(f"[create_thread] Response: {resp[:500]}")  # Debug
        lines = self._parse_response(resp)
        status = lines[0].strip() if lines else '-1'
        print(f"[create_thread] Status: {status}, Lines: {lines[:5]}")  # Debug

        if status == '0':
            return {'success': True, 'message': _("Thread created")}
        else:
            return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    def mark_forum_as_read(self, group_id=None, forum_name=None):
        """Mark forum as read. forum_markasread.php"""
        params = {}
        if group_id:
            params['groupid'] = str(group_id)
        if forum_name:
            params['forum'] = forum_name
        text = self._auth_request('forum_markasread.php', params)
        return text.strip().startswith('0')

    # ---- Blog Actions ----

    def comment_on_blog(self, post_id, blog_name, text_body):
        """Comment on a blog post.

        Uses buffer_post.php to upload comment text, then blog_posts_comment.php.
        """
        if not self._ensure_token():
            return {'success': False, 'message': _("Token refresh failed")}

        # First upload comment text to buffer
        import random
        buf_id = str(random.randint(100000, 999999))
        buf_params = {
            'name': self.username,
            'token': self.token,
            'id': buf_id,
        }
        buf_data = {'data': text_body}
        self._post_request('buffer_post.php', buf_params, buf_data)

        # Then submit comment
        params = {
            'name': self.username,
            'token': self.token,
            'searchname': blog_name,
            'postid': str(post_id),
            'buffer': buf_id,
        }
        resp = self._request('blog_posts_comment.php', params)
        lines = self._parse_response(resp)
        status = lines[0].strip() if lines else '-1'

        if status == '0':
            return {'success': True, 'message': _("Comment posted")}
        else:
            return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    def create_blog_post(self, blog_name, title, content, category_id=0):
        """Create a new blog post.

        Based on Ruby Blog.rb blog_posts_mod.php:
        GET: add=1&postname={title}&searchname={blog_name}&categoryid={cat} (+ auth)
        POST: multipart with 'buffer' field containing content uploaded via buffer_post.php
        """
        if not self._ensure_token():
            return {'success': False, 'message': _("Token refresh failed")}

        # Upload content to buffer first
        import random
        buf_id = str(random.randint(100000, 999999))
        buf_params = {
            'name': self.username,
            'token': self.token,
            'id': buf_id,
        }
        buf_data = {'data': content}
        self._post_request('buffer_post.php', buf_params, buf_data)

        # Create blog post
        params = {
            'name': self.username,
            'token': self.token,
            'add': '1',
            'postname': title,
            'searchname': blog_name,
            'buffer': buf_id,
        }
        if category_id:
            params['categoryid'] = str(category_id)

        resp = self._request('blog_posts_mod.php', params)
        lines = self._parse_response(resp)
        status = lines[0].strip() if lines else '-1'

        if status == '0':
            return {'success': True, 'message': _("Blog post created")}
        else:
            return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    def create_blog_category(self, blog_name, category_name):
        """Create a new blog category.

        Endpoint: blog_categories_mod.php?add=1&searchname={blog}&categoryname={name}
        """
        params = {
            'add': '1',
            'searchname': blog_name,
            'categoryname': category_name,
        }
        text = self._auth_request('blog_categories_mod.php', params)
        lines = self._parse_response(text)
        status = lines[0].strip() if lines else '-1'

        if status == '0':
            return {'success': True, 'message': _("Category created")}
        else:
            return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    def rename_blog_category(self, blog_name, category_id, new_name):
        """Rename a blog category.

        Endpoint: blog_categories_mod.php?rename=1&searchname={blog}&categoryid={id}&categoryname={name}
        """
        params = {
            'rename': '1',
            'searchname': blog_name,
            'categoryid': str(category_id),
            'categoryname': new_name,
        }
        text = self._auth_request('blog_categories_mod.php', params)
        lines = self._parse_response(text)
        status = lines[0].strip() if lines else '-1'

        if status == '0':
            return {'success': True, 'message': _("Category renamed")}
        else:
            return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    def delete_blog_category(self, blog_name, category_id):
        """Delete a blog category.

        Endpoint: blog_categories_mod.php?del=1&searchname={blog}&categoryid={id}
        """
        params = {
            'del': '1',
            'searchname': blog_name,
            'categoryid': str(category_id),
        }
        text = self._auth_request('blog_categories_mod.php', params)
        lines = self._parse_response(text)
        status = lines[0].strip() if lines else '-1'

        if status == '0':
            return {'success': True, 'message': _("Category deleted")}
        else:
            return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    def follow_blog(self, blog_name):
        """Follow a blog. blog_fb.php?add=1&searchname={name}"""
        text = self._auth_request('blog_fb.php', {'add': '1', 'searchname': blog_name})
        return text.strip().startswith('0')

    def unfollow_blog(self, blog_name):
        """Unfollow a blog. blog_fb.php?remove=1&searchname={name}"""
        text = self._auth_request('blog_fb.php', {'remove': '1', 'searchname': blog_name})
        return text.strip().startswith('0')

    # ---- Additional Social Features ----

    def get_contacts_added_me(self):
        """Get users who added you as contact. contacts_addedme.php?new=1"""
        text = self._auth_request('contacts_addedme.php', {'new': '1'})
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return []
        return [line.strip() for line in lines[1:] if line.strip()]

    def mark_conversation_read(self, user, subject=""):
        """Mark conversation as read. message_allread.php?user={user}"""
        params = {'user': user}
        if subject:
            params['subj'] = subject
        text = self._auth_request('message_allread.php', params)
        return text.strip().startswith('0')

    def follow_thread(self, thread_id):
        """Follow a forum thread. forum_followed.php?follow=1&thread={id}"""
        text = self._auth_request('forum_followed.php', {
            'follow': '1',
            'thread': str(thread_id),
        })
        return text.strip().startswith('0')

    def unfollow_thread(self, thread_id):
        """Unfollow a forum thread. forum_followed.php?unfollow=1&thread={id}"""
        text = self._auth_request('forum_followed.php', {
            'unfollow': '1',
            'thread': str(thread_id),
        })
        return text.strip().startswith('0')

    def follow_blog_post(self, post_id):
        """Follow a blog post. blog_fb.php?add=1&postid={id}"""
        text = self._auth_request('blog_fb.php', {
            'add': '1',
            'postid': str(post_id),
        })
        return text.strip().startswith('0')

    def unfollow_blog_post(self, post_id):
        """Unfollow a blog post. blog_fb.php?remove=1&postid={id}"""
        text = self._auth_request('blog_fb.php', {
            'remove': '1',
            'postid': str(post_id),
        })
        return text.strip().startswith('0')

    def get_whats_new(self):
        """Get 'What's New' notification counts from agent.php.

        Mirrors Ruby: srvproc("agent", { "client" => "1" })
        Response lines: 0, timestamp, version, beta, alpha, fullname, gender, chat,
                        messages, posts, blogposts, blogcomments, forums, forumsposts,
                        friends, birthday, mentions, followedblogposts, blogfollowers,
                        blogmentions, groupinvitations
        """
        result = {
            'messages': 0, 'followed_threads': 0, 'followed_blogs': 0,
            'blog_comments': 0, 'followed_forums': 0, 'followed_forums_posts': 0,
            'friends': 0, 'birthday': 0, 'mentions': 0,
            'followed_blog_posts': 0, 'blog_followers': 0, 'blog_mentions': 0,
            'group_invitations': 0,
        }

        # Try agent.php (primary, like Ruby)
        try:
            text = self._auth_request('agent.php', {'client': '1'}, timeout=15)
            if text:
                # Strip BOM and HTML tags (PHP sometimes leaks <br /> notices)
                # Ruby handles this via to_i which ignores non-numeric prefixes
                # We strip tags entirely (not converting to newlines) to preserve line indices
                text = text.lstrip('\ufeff')
                text = re.sub(r'<[^>]+>', '', text)
                # Ruby: resp.delete("\r").split("\n")
                lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

                # Strip whitespace but keep empty lines (indices must match Ruby)
                lines = [l.strip() for l in lines]

                print(f"[ELTEN] agent.php response: {len(lines)} lines, status={lines[0] if lines else 'empty'}")

                if lines and lines[0] == '0' and len(lines) > 8:
                    def si(idx):
                        try:
                            return int(lines[idx]) if idx < len(lines) and lines[idx] else 0
                        except (ValueError, TypeError):
                            return 0

                    result['messages'] = si(8)
                    result['followed_threads'] = si(9)
                    result['followed_blogs'] = si(10)
                    result['blog_comments'] = si(11)
                    result['followed_forums'] = si(12)
                    result['followed_forums_posts'] = si(13)
                    result['friends'] = si(14)
                    result['birthday'] = si(15)
                    result['mentions'] = si(16)
                    result['followed_blog_posts'] = si(17)
                    result['blog_followers'] = si(18)
                    result['blog_mentions'] = si(19)
                    result['group_invitations'] = si(20)
                    return result
                else:
                    print(f"[ELTEN] agent.php unexpected status or too few lines")
        except Exception as e:
            print(f"[ELTEN] agent.php error: {e}")

        # Fallback: individual API calls
        try:
            msgs = self.get_new_messages()
            result['messages'] = len(msgs) if msgs else 0
        except Exception:
            pass

        try:
            friends = self.get_contacts_added_me()
            result['friends'] = len(friends) if friends else 0
        except Exception:
            pass

        return result

    # ---- Feed / Board (Tablica) ----

    def get_feed(self, username=None):
        """Get feed posts (tablica).

        Endpoint: feeds.php?ac=showfollowed or ac=show&user={user}&details=2
        Response format per post:
            id\\r\\nuser\\r\\ntimestamp\\r\\n[message lines...]\\004END\\004\\r\\n
            response_id\\r\\nresponses_count\\r\\nlikes_count\\r\\nliked_flag
        """
        if username:
            params = {'ac': 'show', 'user': username, 'details': '2'}
        else:
            params = {'ac': 'showfollowed', 'details': '2'}

        text = self._auth_request('feeds.php', params)
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return []

        count = self._safe_int(lines[1]) if len(lines) > 1 else 0
        if count == 0:
            return []

        # Join remaining lines and split by \004END\004
        # Format: id\r\nuser\r\ntimestamp\r\n[msg...]\004END\004\r\nresponse_id\r\nresponses\r\nlikes\r\nliked
        # Then next post starts
        content = "\r\n".join(lines[2:])
        blocks = content.split("\004END\004")

        posts = []
        i = 0
        while i < len(blocks):
            # Block before END = id + user + timestamp + message lines
            msg_block = blocks[i].strip()
            if not msg_block:
                i += 1
                continue

            msg_lines = msg_block.split("\r\n")
            if len(msg_lines) < 3:
                i += 1
                continue

            post_id = self._safe_int(msg_lines[0])
            user = msg_lines[1].strip()
            timestamp = msg_lines[2].strip()
            message = "\n".join(msg_lines[3:]).replace("\004LINE\004", "\n").strip()

            # After END marker: response_id, responses_count, likes_count, liked_flag
            # These are at the START of the next block (before next post's id)
            response_to = 0
            responses = 0
            likes = 0
            liked = False

            if i + 1 < len(blocks):
                meta_block = blocks[i + 1].strip()
                meta_lines = meta_block.split("\r\n")
                # First 4 lines are metadata, rest is next post
                if len(meta_lines) >= 4:
                    response_to = self._safe_int(meta_lines[0])
                    responses = self._safe_int(meta_lines[1])
                    likes = self._safe_int(meta_lines[2])
                    liked = meta_lines[3].strip() == '1'

                    # Remaining lines in this block are the next post's id+user+timestamp+msg
                    if len(meta_lines) > 4:
                        # Reconstruct: put remaining lines back as next block
                        remaining = "\r\n".join(meta_lines[4:])
                        blocks[i + 1] = remaining
                    else:
                        # No more data in this block, skip it
                        i += 1

            post = {
                'id': post_id,
                'user': user,
                'time': timestamp,
                'message': message,
                'response': response_to,
                'responses': responses,
                'likes': likes,
                'liked': liked,
            }
            posts.append(post)
            i += 1

        return posts

    def post_feed(self, message, response_to=0):
        """Publish a feed post. Max 300 characters.

        Args:
            message: Post text (max 300 chars)
            response_to: ID of parent post (0 for new post)
        """
        params = {'ac': 'publish', 'response': str(response_to)}
        post_data = {'text': message[:300]}
        resp = self._auth_post_request('feeds.php', params, post_data)
        lines = self._parse_response(resp)
        status = lines[0].strip() if lines else '-1'
        if status == '0':
            return {'success': True, 'message': _("Post published")}
        return {'success': False, 'message': self.ERROR_MESSAGES.get(status, f"Error: {status}")}

    def delete_feed(self, feed_id):
        """Delete a feed post."""
        text = self._auth_request('feeds.php', {'ac': 'delete', 'id': str(feed_id)})
        return text.strip().startswith('0')

    def like_feed(self, feed_id, like=True):
        """Like or unlike a feed post."""
        text = self._auth_request('feeds.php', {
            'ac': 'liking',
            'message': str(feed_id),
            'like': '1' if like else '0',
        })
        return text.strip().startswith('0')

    def get_feed_responses(self, feed_id):
        """Get responses to a feed post."""
        params = {'ac': 'showresponses', 'id': str(feed_id), 'details': '2'}
        text = self._auth_request('feeds.php', params)
        lines = self._parse_response(text)
        ok, err = self._check_status(lines)
        if not ok:
            return []

        count = self._safe_int(lines[1]) if len(lines) > 1 else 0
        content = "\r\n".join(lines[2:])
        blocks = content.split("\004END\004")

        posts = []
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            block_lines = block.split("\r\n")
            if len(block_lines) < 3:
                continue
            post = {
                'id': self._safe_int(block_lines[0]),
                'user': block_lines[1].strip() if len(block_lines) > 1 else '',
                'time': block_lines[2].strip() if len(block_lines) > 2 else '',
                'message': "\n".join(block_lines[3:]).replace("\004LINE\004", "\n").strip(),
            }
            posts.append(post)

        return posts

    def follow_feed(self, username):
        """Follow a user's feed."""
        text = self._auth_request('feeds.php', {'ac': 'follow', 'user': username})
        return text.strip().startswith('0')

    def unfollow_feed(self, username):
        """Unfollow a user's feed."""
        text = self._auth_request('feeds.php', {'ac': 'unfollow', 'user': username})
        return text.strip().startswith('0')

    def get_forum_group_info(self, group_id):
        """Get group description/info. Returns group dict from structure."""
        structure = self.get_forum_structure()
        for g in structure.get('groups', []):
            if g.get('id') == group_id:
                return g
        return {}

    def check_server(self):
        """Check if Elten server is reachable."""
        try:
            text = self._request('online.php', {'name': 'ping', 'token': 'ping'}, timeout=3)
            return len(text.strip()) > 0
        except Exception:
            return False
