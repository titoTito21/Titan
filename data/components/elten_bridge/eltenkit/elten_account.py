# -*- coding: utf-8 -*-
"""The EltenLink account, from wherever the user has already signed in.

Copyright (C) 2026 titosoft. Part of the Elten API bridge, licensed under
the GNU General Public License version 3 or later.

An application asking for its scores, its tables or the forum needs an
EltenLink session, and there are two places on this machine that already
have one:

* **Titan IM**, where the user signed in to EltenLink through Titan. This
  is asked first, because it is the account Titan itself is using.
* **Elten's own installation** - `%APPDATA%/elten/login.dat`, which is
  what Elten signs itself in with when it starts. A user who has Elten
  installed and logged in should not have to sign in a second time to
  play their own games here.

`login.dat` is Elten's own format, read exactly as `Scene_Login#read_logindata`
writes it:

    "EltenLoginCredentialsPRVDataFile"  u8 autologin
    u32 name_len   name
    u32 token_len  token
    i8  token_encrypted

`token_encrypted` is the part worth being careful about. **1 means DPAPI**
(`CryptUnprotectData` with no entropy), so the token can be read back only
by this Windows account on this machine - which is the right property and
the same one Titan's own secret store relies on. **2 means DPAPI with a PIN
the user chose**, and that PIN is not on the disk: a session cannot be had
without asking for it, and asking for a PIN because a game wanted a
scoreboard is not something this does. That account is reported as "not
signed in", which is honest.

Nothing here is ever shown to an application: it asks for its rows and gets
its rows.
"""

import os
import struct

#: What Elten writes in front of its auto-login file.
MAGIC = b'EltenLoginCredentialsPRVDataFile'

#: Elten's own settings folder.
def elten_data_dir():
    appdata = os.environ.get('APPDATA') or ''
    return os.path.join(appdata, 'elten') if appdata else ''


def read_login_dat(path=''):
    """Elten's saved auto-login, as `(name, token)` - or `('', '')`.

    Never raises: a file that is not there, is truncated, was written by a
    newer Elten or is encrypted with a PIN all mean "no account here", and
    the caller has somewhere else to look.
    """
    path = path or os.path.join(elten_data_dir(), 'login.dat')
    try:
        with open(path, 'rb') as handle:
            raw = handle.read()
    except Exception:
        return '', ''
    if not raw.startswith(MAGIC):
        return '', ''
    try:
        at = len(MAGIC)
        autologin = raw[at]
        at += 1
        length = struct.unpack_from('<I', raw, at)[0]
        at += 4
        name = raw[at:at + length].decode('utf-8', 'replace')
        at += length
        length = struct.unpack_from('<I', raw, at)[0]
        at += 4
        token = raw[at:at + length]
        at += length
        encrypted = struct.unpack_from('<b', raw, at)[0]
    except Exception:
        return '', ''
    if not name or autologin <= 0:
        return '', ''
    if encrypted == 2:
        # A PIN only the user has. Asking for it because a game wanted a
        # scoreboard is not something to do unprompted.
        return '', ''
    if encrypted == 1:
        token = _unprotect(token)
        if not token:
            return '', ''
    try:
        return name, token.decode('utf-8', 'replace')
    except Exception:
        return '', ''


def read_ini_login(path=''):
    """The older place: `[Login] Name` / `Token` in `elten.ini`.

    Elten moves these into `login.dat` the first time it starts, so this is
    only ever reached on an installation that has not been run since.
    """
    path = path or os.path.join(elten_data_dir(), 'elten.ini')
    name = token = ''
    try:
        import configparser
        parser = configparser.ConfigParser(strict=False, interpolation=None)
        parser.read(path, encoding='utf-8')
        if parser.has_section('Login'):
            name = parser.get('Login', 'Name', fallback='') or ''
            token = parser.get('Login', 'Token', fallback='') or ''
            if parser.getint('Login', 'TokenEncrypted', fallback=0) > 0:
                import base64
                token = (_unprotect(base64.b64decode(token))
                         or b'').decode('utf-8', 'replace')
    except Exception:
        return '', ''
    return name, token


def _unprotect(blob):
    """DPAPI, this account only. `b''` when it cannot be read.

    Deliberately no entropy: that is what Elten passes for `tokenenc == 1`,
    and a blob written on another machine or by another user simply will
    not come back - which is the whole point of using it.
    """
    if not blob:
        return b''
    try:
        import ctypes
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD),
                        ('pbData', ctypes.POINTER(ctypes.c_char))]

        source = Blob(len(blob), ctypes.cast(ctypes.create_string_buffer(blob),
                                             ctypes.POINTER(ctypes.c_char)))
        answer = Blob()
        crypt32 = ctypes.windll.crypt32
        if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None,
                                          None, None, 0,
                                          ctypes.byref(answer)):
            return b''
        try:
            return ctypes.string_at(answer.pbData, answer.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(answer.pbData)
    except Exception:
        return b''


def elten_account():
    """Elten's own account on this machine, as `(name, auto_login_token)`."""
    name, token = read_login_dat()
    if name and token:
        return name, token
    return read_ini_login()


def app_id():
    """The installation id Elten signs its requests with.

    Elten generates one per installation (`appid.dat`) and the server ties
    an auto-login token to it, so a session asked for without it is a
    session that will be refused.
    """
    try:
        path = os.path.join(elten_data_dir(), 'appid.dat')
        with open(path, 'rb') as handle:
            return handle.read().decode('utf-8', 'replace').strip()
    except Exception:
        return ''
