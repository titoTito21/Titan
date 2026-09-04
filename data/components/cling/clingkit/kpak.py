# -*- coding: utf-8 -*-
"""`.kpak` - the container a Klango application's own code arrives in.

A Klango installation is two halves.  The half on the disk is the application's
DATA - its texts, its sounds, its levels - and Cling reads that directly, which
is why a game like Mole No More can be played with nothing decrypted at all.
The other half is the application's Lua, and it is inside a `.kpak`: an
authenticated, encrypted container whose key lives in the Klango client that
shipped it.

This module is honest about that boundary rather than pretending it is not
there.  It reads the header of any `.kpak` - so Cling can say what a file is,
which application it belongs to and whether it is one it can open - and it
extracts one when, and only when, it has been given the key that opens it.  A
key is never guessed, never derived from the file, and never taken off the
internet: it is either in `data/components/cling/keys/` (a file the user puts
there, one key per line, hexadecimal or base64) or it is not, and a package
whose key is not there comes back as a package Cling cannot open, saying so.

    KPAK
    'K' 'P' 'A' 'K'   magic
    version           one byte
    nonce             12 bytes
    index_length      unsigned 32-bit, little endian
    index             AEAD ciphertext + tag: the file list
    payload           AEAD ciphertext + tag: the files
"""

import base64
import binascii
import json
import lzma
import os
import struct

MAGIC = b'KPAK'
HEADER_SIZE = 21          # magic 4 + version 1 + nonce 12 + length 4
NONCE_SIZE = 12
TAG_SIZE = 16


class KpakError(Exception):
    """A file that is not a package, or one Cling has no key for."""


class Header(object):
    """What a `.kpak` says about itself before anything is decrypted."""

    __slots__ = ('path', 'version', 'nonce', 'index_length', 'payload_length')

    def __init__(self, path, version, nonce, index_length, payload_length):
        self.path = path
        self.version = version
        self.nonce = nonce
        self.index_length = index_length
        self.payload_length = payload_length

    @property
    def name(self):
        return os.path.splitext(os.path.basename(self.path))[0]

    def describe(self):
        return ('%s: Klango package, format %d, %d bytes of index and %d of '
                'payload' % (os.path.basename(self.path), self.version,
                             self.index_length, self.payload_length))

    def __repr__(self):                                  # pragma: no cover
        return '<kpak %s v%d>' % (self.name, self.version)


def is_package(path):
    """Cheap enough to ask of every file in a folder."""
    try:
        with open(path, 'rb') as handle:
            return handle.read(4) == MAGIC
    except OSError:
        return False


def read_header(path):
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as handle:
            raw = handle.read(HEADER_SIZE)
    except OSError as error:
        raise KpakError('%s could not be read: %s' % (path, error))
    if len(raw) < HEADER_SIZE or raw[:4] != MAGIC:
        raise KpakError('%s is not a Klango package' % os.path.basename(path))
    version = raw[4]
    nonce = raw[5:5 + NONCE_SIZE]
    index_length = struct.unpack('<I', raw[17:21])[0]
    payload_length = max(0, size - HEADER_SIZE - index_length)
    if index_length > size:
        raise KpakError('%s is damaged (its index does not fit in the file)'
                        % os.path.basename(path))
    return Header(path, version, nonce, index_length, payload_length)


# ------------------------------------------------------------------- keys
def keys_dir():
    """`data/components/cling/keys/` - where the user puts a key, if they have one."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'keys'))


def known_keys():
    """Every key Cling has been given, as bytes. Usually none, and that is fine."""
    out = []
    folder = keys_dir()
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for leaf in names:
        if leaf.startswith('.') or leaf.lower().endswith(('.md', '.txt.md')):
            continue
        path = os.path.join(folder, leaf)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as handle:
                content = handle.read()
        except OSError:
            continue
        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key = _decode_key(line)
            if key is not None and key not in out:
                out.append(key)
    return out


def _decode_key(text):
    for decoder in (_from_hex, _from_base64):
        key = decoder(text)
        if key is not None and len(key) in (16, 24, 32):
            return key
    return None


def _from_hex(text):
    cleaned = text.replace(' ', '').replace(':', '')
    try:
        return binascii.unhexlify(cleaned)
    except (binascii.Error, ValueError):
        return None


def _from_base64(text):
    try:
        return base64.b64decode(text + '=' * (-len(text) % 4), validate=True)
    except (binascii.Error, ValueError):
        return None


# ------------------------------------------------------------ decryption
def _ciphers():
    """The AEADs a package may have been sealed with, best first.

    `cryptography` is what Titan already carries for its own encrypted files;
    a build without it falls back to `pycryptodome`, and a build with neither
    can still read a header and say what the file is.
    """
    out = []
    try:
        from cryptography.hazmat.primitives.ciphers.aead import (
            AESGCM, ChaCha20Poly1305)
        out.append(('aes-256-gcm', lambda key, nonce, data, aad:
                    AESGCM(key).decrypt(nonce, data, aad)))
        out.append(('chacha20-poly1305', lambda key, nonce, data, aad:
                    ChaCha20Poly1305(key).decrypt(nonce, data, aad)))
    except Exception:
        pass
    if not out:
        try:
            from Crypto.Cipher import AES, ChaCha20_Poly1305

            def aes_gcm(key, nonce, data, aad):
                cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
                if aad:
                    cipher.update(aad)
                return cipher.decrypt_and_verify(data[:-TAG_SIZE], data[-TAG_SIZE:])

            def chacha(key, nonce, data, aad):
                cipher = ChaCha20_Poly1305.new(key=key, nonce=nonce)
                if aad:
                    cipher.update(aad)
                return cipher.decrypt_and_verify(data[:-TAG_SIZE], data[-TAG_SIZE:])

            out.append(('aes-256-gcm', aes_gcm))
            out.append(('chacha20-poly1305', chacha))
        except Exception:
            pass
    return out


def crypto_available():
    return bool(_ciphers())


def _open_block(block, nonce, keys):
    for key in keys:
        for _name, decrypt in _ciphers():
            try:
                return decrypt(key, nonce, block, None)
            except Exception:
                continue
    return None


def _decompress(raw):
    """The payload is LZMA where it is compressed, and plain where it is not."""
    for opener in (lzma.decompress,):
        try:
            return opener(raw)
        except Exception:
            pass
    return raw


def extract(path, destination, keys=None):
    """Unpack a package into `destination`. Returns the files written.

    Raises `KpakError` with a sentence a user can act on when the package
    cannot be opened - which, for a package from a Klango installation whose
    key Cling has not been given, is the ordinary case and not a fault.
    """
    header = read_header(path)
    keys = list(keys if keys is not None else known_keys())
    if not keys:
        raise KpakError(
            "%s is encrypted and Cling has no key for it. A key file in "
            "'%s' is what opens one; the application's own data folder is "
            "read without any key." % (os.path.basename(path), keys_dir()))
    if not crypto_available():
        raise KpakError('this build has no cryptography library, so an '
                        'encrypted package cannot be opened')

    with open(path, 'rb') as handle:
        handle.seek(HEADER_SIZE)
        index_block = handle.read(header.index_length)
        payload_block = handle.read()

    index_raw = _open_block(index_block, header.nonce, keys)
    if index_raw is None:
        raise KpakError('%s did not open with any key Cling has (wrong key, or '
                        'the file has been altered)' % os.path.basename(path))
    entries = _read_index(_decompress(index_raw))
    payload = _open_block(payload_block, header.nonce, keys)
    if payload is None:
        raise KpakError('%s has an index Cling could read and a payload it '
                        'could not' % os.path.basename(path))
    payload = _decompress(payload)

    written = []
    root = os.path.abspath(destination)
    for entry in entries:
        name = str(entry.get('name') or '').replace('\\', '/').lstrip('/')
        offset = int(entry.get('offset', 0))
        size = int(entry.get('size', 0))
        if not name:
            continue
        target = os.path.abspath(os.path.join(root, name))
        # A package is a file from somewhere else; an entry named
        # `../../autostart` is how one would write outside the folder it was
        # asked to unpack into.
        if not _inside(root, target):
            raise KpakError("%s contains an entry that points outside the "
                            "folder ('%s')" % (os.path.basename(path), name))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'wb') as out:
            out.write(payload[offset:offset + size])
        written.append(target)
    return written


def _inside(root, candidate):
    """A package entry that landed outside the folder - or on another drive,
    which is what `commonpath` refuses to answer about - is refused."""
    try:
        return os.path.commonpath([root, candidate]) == root
    except ValueError:
        return False


def _read_index(raw):
    """The file list. JSON where the package writes JSON, lines where it does not."""
    text = raw.decode('utf-8', 'replace')
    try:
        loaded = json.loads(text)
    except ValueError:
        loaded = None
    if isinstance(loaded, list):
        return [entry for entry in loaded if isinstance(entry, dict)]
    if isinstance(loaded, dict) and isinstance(loaded.get('files'), list):
        return [entry for entry in loaded['files'] if isinstance(entry, dict)]
    entries = []
    for line in text.split('\n'):
        parts = line.strip().split('\t')
        if len(parts) >= 3:
            try:
                entries.append({'name': parts[0], 'offset': int(parts[1]),
                                'size': int(parts[2])})
            except ValueError:
                continue
    if not entries:
        raise KpakError('the package index is in a form Cling does not know')
    return entries


def inspect(path):
    """What Cling can say about a package without opening it."""
    header = read_header(path)
    lines = [header.describe()]
    if known_keys():
        lines.append('Cling has %d key(s) it can try.' % len(known_keys()))
    else:
        lines.append("Cling has no key for Klango's packages, so the code "
                     "inside this one cannot be read. The application's data "
                     "folder needs no key.")
    return '\n'.join(lines)
