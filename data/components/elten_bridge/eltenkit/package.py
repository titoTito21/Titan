# -*- coding: utf-8 -*-
"""`.eltenapp` - one Elten 3 application, as one file.

Every Elten application is a single `.eltenapp`, and the format was worked out
here by reading the bytes rather than the builder: `tools/build-eltenapp.rb` is
in Elten's own repository but the container it writes is not documented
anywhere, and Cling's `.pag` had already shown that a format read from the
files themselves is the one that actually opens what people have.

    "EltenPKSignature"  u8 major  u8 minor  u32 cert_len  u32 signature_len
    <DER X.509 certificate>            issuer: Elten / Program Signing
    <RSA signature over what follows>
    "Elten3AppPackage"  u32 manifest_len  <zstd: the manifest, as JSON>
    records, one after another, each:
        u8 kind
        kind 1  source     u16 name_len, name, u32 len, zstd
        kind 2  asset      u16 name_len, name, u32 len, the bytes as they are
        kind 3  catalogue  2 bytes of language code, u32 len, zstd

Three things about it are worth writing down, because each one is a way to get
it wrong:

* **An asset is NOT compressed** (kind 2). Every asset in every application
  installed here is an `.ogg` or an `.mp3` - already compressed - so the
  builder stores them whole. A reader that runs zstd over every record parses
  the first few source files, throws on the first sound, and reports an
  application with no audio at all; that is exactly what happened here, and
  four of the eleven applications came out with zero files in them.
* **A catalogue's name is two bytes and there is no length in front of it**
  (kind 3). It is the language code - `PL` - and what is inside is a GNU
  gettext `.mo`, which is a format Titan already speaks.
* **The signature is a signature, not encryption.** Nothing here is
  concealed: the payload is plain zstd and the certificate is in front of it
  so a reader can *check* who built the package. Elten's own key is not
  public, so this can verify and never mint - which is the right way round,
  because Titan is opening somebody else's applications and has no business
  being able to sign one.
"""

import hashlib
import json
import os
import struct

#: What the file begins with when it was signed - which is every application
#: from Elten's own repository. An unsigned build (`build-eltenapp.rb
#: --unsigned`) has no such header and begins at the payload.
SIGNATURE_MAGIC = b'EltenPKSignature'

#: Where the payload begins, signed or not.
PAYLOAD_MAGIC = b'Elten3AppPackage'

#: What a record can be.
SOURCE, ASSET, CATALOGUE = 1, 2, 3

#: The extension, which is also what the user calls these.
EXTENSION = '.eltenapp'

#: How much of a file to read while deciding whether it is one of ours. The
#: header is under two kilobytes even with a 3072-bit certificate in it.
PROBE_BYTES = 8192


class PackageError(Exception):
    """A package that cannot be opened, with a sentence saying why."""


class Signature(object):
    """Who signed a package, as far as the file itself says.

    Deliberately shallow: the certificate is kept whole so anything that
    wants to verify it can, and what is offered here is the little a user
    would want read out - whether it was signed at all, and by whom.
    """

    __slots__ = ('certificate', 'signature', 'version')

    def __init__(self, certificate=b'', signature=b'', version=(0, 0)):
        self.certificate = certificate
        self.signature = signature
        self.version = version

    def __bool__(self):
        return bool(self.certificate)

    @property
    def signed(self):
        return bool(self.certificate)

    @property
    def fingerprint(self):
        """The certificate's SHA-256, which is what identifies the signer."""
        if not self.certificate:
            return ''
        return hashlib.sha256(self.certificate).hexdigest()

    def subject(self):
        """The certificate's subject, in the words it carries.

        Read out of the DER by looking for the printable strings rather than
        by parsing X.509: what this is for is telling a user who built the
        application they are about to run, and a full ASN.1 reader for one
        line of text would be a library Titan does not need. An unreadable
        certificate answers nothing rather than raising - a package is still
        openable when Cling cannot say who signed it.
        """
        if not self.certificate:
            return ''
        found = []
        data = self.certificate
        index = 0
        while index < len(data) - 2:
            tag, length = data[index], data[index + 1]
            # 0x0c UTF8String, 0x13 PrintableString - the ones a name is in.
            if tag in (0x0c, 0x13) and 0 < length < 0x80 \
                    and index + 2 + length <= len(data):
                try:
                    text = data[index + 2:index + 2 + length].decode('utf-8')
                except UnicodeDecodeError:
                    text = ''
                if text and text not in found and _printable(text):
                    found.append(text)
                index += 2 + length
                continue
            index += 1
        return ', '.join(found)


def _printable(text):
    return all(character.isprintable() for character in text)


class Package(object):
    """An opened `.eltenapp`: its manifest, its files and its translations."""

    __slots__ = ('path', 'manifest', 'files', 'catalogues', 'signature')

    def __init__(self, path='', manifest=None, files=None, catalogues=None,
                 signature=None):
        self.path = path
        self.manifest = manifest or {}
        #: name -> bytes, in the order the builder wrote them.
        self.files = files or []
        #: two-letter language code (lower case) -> the `.mo` as bytes.
        self.catalogues = catalogues or {}
        self.signature = signature or Signature()

    # ------------------------------------------------------------- reading
    @property
    def id(self):
        return str(self.manifest.get('id') or '')

    @property
    def name(self):
        return str(self.manifest.get('name') or '')

    @property
    def version(self):
        return str(self.manifest.get('version') or '')

    @property
    def author(self):
        return str(self.manifest.get('author') or '')

    @property
    def api_version(self):
        return str(self.manifest.get('EltenAPIVersion') or '')

    @property
    def main(self):
        """The entry file, as the manifest names it."""
        return str(self.manifest.get('main') or '__app.rb')

    @property
    def main_class(self):
        """The class to launch. It must be a `Program`; Elten says so and so
        does the shim, because a manifest that names something else is an
        application that would load and then do nothing."""
        return str(self.manifest.get('main_class') or '')

    def description(self, language=''):
        """What the application says it is, in the best language it has.

        Elten's own order, from `docs/eltenapps.md`: the interface language,
        then English, then the application's own main language, then whatever
        it has, then the raw manifest string.
        """
        return _localised(self.manifest, 'description', language)

    def display_name(self, language=''):
        return _localised(self.manifest, 'name', language) or self.id

    def languages(self):
        """Every language the package really carries a catalogue for."""
        return sorted(self.catalogues)

    def file(self, name):
        """One file's bytes, or None. Names are as the package wrote them,
        with forward slashes."""
        wanted = name.replace('\\', '/').lstrip('/')
        for held, data in self.files:
            if held == wanted:
                return data
        return None


def _localised(manifest, field, language=''):
    """A manifest string in the best language available.

    `localized_names` / `localized_descriptions` are objects keyed by language
    code; the bare `name` / `description` is the raw one, in `main_language`.
    """
    raw = str(manifest.get(field) or '')
    table = manifest.get('localized_%ss' % field) or {}
    if not isinstance(table, dict) or not table:
        return raw
    wanted = (language or '').lower().split('-')[0]
    for code in (wanted, 'en', str(manifest.get('main_language') or '').lower()):
        if code and table.get(code):
            return str(table[code])
    for code in sorted(table):
        if table[code]:
            return str(table[code])
    return raw


# --------------------------------------------------------------------- read
def looks_like_package(path):
    """Cheap enough to ask about every file in a folder.

    The payload magic is what decides, not the extension: an unsigned build
    has no signature header at all, and a file called `.eltenapp` that is not
    one should be reported as unopenable rather than listed as an
    application.
    """
    if not path.lower().endswith(EXTENSION) or not os.path.isfile(path):
        return False
    try:
        with open(path, 'rb') as handle:
            return PAYLOAD_MAGIC in handle.read(PROBE_BYTES)
    except OSError:
        return False


def read_manifest(path):
    """Just the manifest - what a listing needs, without the sounds.

    An application's package is up to two megabytes of audio and the list only
    wants its name; reading the whole thing once per row is how a window takes
    a second to open.
    """
    with open(path, 'rb') as handle:
        head = handle.read(PROBE_BYTES)
        start = head.find(PAYLOAD_MAGIC)
        if start < 0:
            raise PackageError('%s is not an Elten application package'
                               % os.path.basename(path))
        handle.seek(start + len(PAYLOAD_MAGIC))
        length = struct.unpack('<I', handle.read(4))[0]
        blob = handle.read(length)
    return _json(_decompress(blob, path)), _signature(head)


def read(path):
    """The whole package: manifest, files, catalogues and who signed it."""
    try:
        with open(path, 'rb') as handle:
            data = handle.read()
    except OSError as error:
        raise PackageError('%s could not be read: %s'
                           % (os.path.basename(path), error))
    start = data.find(PAYLOAD_MAGIC)
    if start < 0:
        raise PackageError('%s is not an Elten application package'
                           % os.path.basename(path))
    at = start + len(PAYLOAD_MAGIC)
    length = struct.unpack('<I', data[at:at + 4])[0]
    at += 4
    manifest = _json(_decompress(data[at:at + length], path))
    at += length

    files, catalogues = [], {}
    while at + 7 <= len(data):
        kind = data[at]
        if kind in (SOURCE, ASSET):
            name_length = struct.unpack('<H', data[at + 1:at + 3])[0]
            if name_length == 0:
                break
            try:
                name = data[at + 3:at + 3 + name_length].decode('utf-8')
            except UnicodeDecodeError:
                break
            here = at + 3 + name_length
        elif kind == CATALOGUE:
            name = data[at + 1:at + 3].decode('ascii', 'replace')
            here = at + 3
        else:
            # Not a record we know. Everything after it is unreadable too -
            # the records are one after another with no index - so this is
            # where the package ends as far as Titan is concerned.
            break
        size = struct.unpack('<I', data[here:here + 4])[0]
        blob = data[here + 4:here + 4 + size]
        if len(blob) != size:
            break
        at = here + 4 + size
        if kind == ASSET:
            files.append((name, blob))
        elif kind == SOURCE:
            files.append((name, _decompress(blob, path)))
        else:
            catalogues[name.strip().lower()] = _decompress(blob, path)

    return Package(path, manifest, files, catalogues, _signature(data))


def extract(path, folder):
    """Write a package out as a directory, and answer where its entry is.

    An Elten application is Ruby that does `require_relative`, so it has to be
    real files on a real disk before the interpreter can be pointed at it.
    The directory is a CACHE - the `.eltenapp` is the application and is never
    deleted, converted or written to - and it is keyed on the package's own
    content, so a package that has not changed is unpacked once and a package
    that HAS is unpacked again rather than half-overwritten.
    """
    package = read(path)
    os.makedirs(folder, exist_ok=True)
    for name, data in package.files:
        target = os.path.join(folder, *name.split('/'))
        if not _inside(folder, target):
            # A name with `..` in it would write outside the cache. A package
            # comes from wherever the user got it; this is the one place that
            # matters.
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'wb') as handle:
            handle.write(data)
    for code, blob in package.catalogues.items():
        target = os.path.join(folder, 'locale', '%s.mo' % code)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'wb') as handle:
            handle.write(blob)
    return package


def _inside(root, path):
    root = os.path.abspath(root)
    full = os.path.abspath(path)
    return full == root or full.startswith(root + os.sep)


def _signature(head):
    if not head.startswith(SIGNATURE_MAGIC):
        return Signature()
    try:
        major, minor = head[16], head[17]
        cert_length, sig_length = struct.unpack('<II', head[18:26])
        certificate = head[26:26 + cert_length]
        signature = head[26 + cert_length:26 + cert_length + sig_length]
    except (IndexError, struct.error):
        return Signature()
    return Signature(certificate, signature, (major, minor))


def _decompress(blob, path=''):
    try:
        from compression import zstd
    except ImportError:                                    # Python before 3.14
        try:
            import zstandard
        except ImportError:
            raise PackageError(
                'this build has no zstd, so Elten application packages '
                'cannot be opened')
        try:
            return zstandard.ZstdDecompressor().decompress(blob)
        except Exception as error:
            raise PackageError('%s is damaged: %s'
                               % (os.path.basename(path), error))
    try:
        return zstd.decompress(blob)
    except Exception as error:
        raise PackageError('%s is damaged: %s'
                           % (os.path.basename(path), error))


def _json(raw):
    try:
        return json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        raise PackageError('the manifest could not be read: %s' % error)
