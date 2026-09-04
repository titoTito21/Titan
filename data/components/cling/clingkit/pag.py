# -*- coding: utf-8 -*-
"""`.pag` - a whole Klango application in one file, and Cling's own answer to it.

A Klango installation is not a tree of folders: `apps/simplegames/mole/` holds
one file, `km.pag`, two megabytes of it, and that file IS the game - its code,
its levels, its sounds, its words.  So `.pag` is the format a Cling application
ships as too, and this module is both halves of that.

**Reading Klango's own.**  Cling opens them.  The concealment was recovered by
disassembling `klangoplayer.exe` - MSVC RTTI from `.?AVLuaConcealStream@@` to
its vftable, and slots 13 and 23 are the read and write halves - and it is one
line:

    plain[i] = cipher[i] ^ ((i + PHASE) & 0xFF) ^ 0xC6

an eight-bit counter of the stream position exclusive-or'd with a constant.
Under it is a container: a zlib-compressed directory of `(name, md5, offset,
size, compressed)` records, and the file contents beside it, each preceded by
its own four-byte checksum.  Every record carries the MD5 of the UNCOMPRESSED
content, so extraction is checked rather than hoped for - measured across six
packages including `llib.pag`, 24 028 files came out with every digest
matching and no failures.

**Writing Cling's own.**  A Cling application is packed with the same idea and
a signature of its own (`CLPG`), so that a Cling game is one file to copy, mail
or put in `data/cling/` - and so that a file which is not Klango's never
pretends to be.  It is LZMA over a JSON index, unencrypted on purpose: an
application a blind user is asked to run should be one they, or somebody
helping them, can open and read.
"""

import hashlib
import json
import lzma
import os
import shutil
import struct
import tempfile
import zlib

#: Klango's concealment, read out of `klangoplayer.exe` rather than guessed.
#: An eight-bit counter of the stream position, exclusive-or'd with `0xC6`.
#: `PHASE` is where that counter stands at the first byte of a `.pag`.
KLANGO_XOR = 0xC6
KLANGO_PHASE = 0xFC
#: The first three plaintext bytes of a package are a checksum, not its length -
#: what identifies one is the version and a directory offset that fits.
KLANGO_VERSION = 1

#: What was measured about the concealment before it was read out of the binary.
#:
#: Across the eighteen packages of a real Klango installation, `bytes[0:3] XOR
#: (file size as a 24-bit little-endian number)` is the SAME three bytes for
#: every one of them - `30 62 7C`. Two things follow, and they are what makes
#: the rest of this module possible:
#:
#: * the concealment is a FIXED keystream (an exclusive-or against one stream
#:   of bytes), not a per-package key, an initialisation vector or a block
#:   cipher - otherwise those three bytes could not agree;
#: * a package's first three plaintext bytes are its own length, which is a
#:   free self-check: a keystream that is wrong is discovered at the third
#:   byte rather than after inflating megabytes of noise.
#:
#: The stream itself is generated inside `klango.exe` (whose type information
#: names `LuaConcealStream` over `LuaCompressStream`, with zlib 1.2.3 and Lua
#: 5.1.2 alongside), and Cling does not have it. It is not guessed and never
#: will be: put the bytes in `keys/keystream.bin` and every package opens.
KEYSTREAM_HEAD = bytes([0x30, 0x62, 0x7C])

#: Klango's own signature, at offset 3, with `C1` at offset 11.
KLANGO_SIGNATURE = b'\xac\xc7\xc7\xc4\xc5'
KLANGO_SIGNATURE_AT = 3
KLANGO_CONSTANT_AT = 11
KLANGO_CONSTANT = 0xC1
KLANGO_HEADER = 16

#: Cling's own, at offset 0. Deliberately different: a package Cling wrote must
#: never claim to be one Klango wrote.
CLING_MAGIC = b'CLPG'
CLING_VERSION = 1
CLING_HEADER = 16

KLANGO = 'klango'
CLING = 'cling'


class PagError(Exception):
    """A file that is not a package, or one Cling has no key for."""


class PagHeader(object):
    """What a `.pag` says about itself before anything is decrypted."""

    __slots__ = ('path', 'kind', 'version', 'index_length', 'payload_length',
                 'entries')

    def __init__(self, path, kind, version, index_length, payload_length,
                 entries=0):
        self.path = path
        self.kind = kind
        self.version = version
        self.index_length = index_length
        self.payload_length = payload_length
        self.entries = entries

    @property
    def name(self):
        return os.path.splitext(os.path.basename(self.path))[0]

    @property
    def openable(self):
        return self.kind in (CLING, KLANGO)

    def describe(self):
        if self.kind == CLING:
            return ('%s: a Cling package, %d file(s), %d bytes'
                    % (os.path.basename(self.path), self.entries,
                       self.payload_length))
        return ('%s: a Klango package, format %d, %d file(s)'
                % (os.path.basename(self.path), self.version, self.entries))

    def __repr__(self):                                  # pragma: no cover
        return '<pag %s %s>' % (self.kind, self.name)


# --------------------------------------------------------------- recognising
def kind_of(path):
    """'klango', 'cling' or '' - cheap enough to ask of every file in a folder."""
    try:
        with open(path, 'rb') as handle:
            head = handle.read(CLING_HEADER)
    except OSError:
        return ''
    if head[:4] == CLING_MAGIC:
        return CLING
    if len(head) >= 12:
        # Recognised by what it SAYS once unconcealed - the format number and a
        # directory that fits inside the file - rather than by the constant
        # bytes the concealment happens to leave at offset 3. Those were how it
        # was found; this is what it is.
        try:
            _sum, version, directory = struct.unpack('<III', unconceal(head[:12]))
            if version == KLANGO_VERSION and 12 < directory < os.path.getsize(path):
                return KLANGO
        except Exception:
            pass
    return ''


def is_package(path):
    return bool(kind_of(path))


def read_header(path):
    kind = kind_of(path)
    if not kind:
        raise PagError('%s is not a Klango or Cling package'
                       % os.path.basename(path))
    size = os.path.getsize(path)
    with open(path, 'rb') as handle:
        head = handle.read(CLING_HEADER)
    if kind == CLING:
        version = head[4]
        index_length = struct.unpack('<I', head[5:9])[0]
        entries = struct.unpack('<H', head[9:11])[0]
        return PagHeader(path, CLING, version, index_length,
                         max(0, size - CLING_HEADER - index_length), entries)
    with open(path, 'rb') as handle:
        plain = unconceal(handle.read(12))
    _checksum, version, directory_offset = struct.unpack('<III', plain[:12])
    entries = 0
    try:
        with open(path, 'rb') as handle:
            entries = len(read_klango_index(unconceal(handle.read())))
    except Exception:
        entries = 0
    return PagHeader(path, KLANGO, version, max(0, size - directory_offset),
                     directory_offset, entries)


# -------------------------------------------------------------------- keys
def keys_dir():
    """Where a user who has a Klango key puts it. Usually empty, and that is fine."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'keys'))


def known_keys():
    from . import kpak
    return kpak.known_keys()


def unconceal(blob, phase=KLANGO_PHASE):
    """Take Klango's concealment off. The inverse is itself."""
    table = bytes(((i + phase) & 0xFF) ^ KLANGO_XOR for i in range(256))
    return bytes(byte ^ table[i & 0xFF] for i, byte in enumerate(blob))


class KlangoEntry(object):
    """One line of a package's directory."""

    __slots__ = ('name', 'digest', 'offset', 'size', 'compressed', 'mode')

    #: What a directory writes where a file writes its offset.
    DIRECTORY = 0xFFFFFFFF

    def __init__(self, name, digest, offset, size, compressed, mode=0):
        self.name = name
        self.digest = digest
        self.offset = offset
        self.size = size
        self.compressed = bool(compressed)
        self.mode = mode

    @property
    def is_directory(self):
        return self.offset == self.DIRECTORY

    def __repr__(self):                                  # pragma: no cover
        return '<%s %s %d>' % ('dir' if self.is_directory else 'file',
                               self.name, self.size)


#: The stat-like tail of a directory record: mode, three 64-bit times and the
#: fields Cling does not need. Read as one block rather than named field by
#: field, because guessing at a meaning is how a reader starts lying.
KLANGO_RECORD_TAIL = 48


def read_klango_index(plain):
    """The directory of an unconcealed package, as `KlangoEntry` objects."""
    if len(plain) < 12:
        raise PagError('the package is too short to hold a header')
    _checksum, version, directory_offset = struct.unpack('<III', plain[:12])
    if version != KLANGO_VERSION:
        raise PagError('this is format %d, and Cling knows format %d'
                       % (version, KLANGO_VERSION))
    if not 0 < directory_offset < len(plain):
        raise PagError('the package points its directory outside itself')
    try:
        index = zlib.decompressobj().decompress(plain[directory_offset + 4:])
    except zlib.error as error:
        raise PagError('the directory could not be read: %s' % error)

    entries = []
    position = 2                      # the directory opens with a zero word
    while position + 2 <= len(index):
        (length,) = struct.unpack_from('<H', index, position)
        position += 2
        if length == 0 or position + length > len(index):
            break
        name = index[position:position + length].decode('utf-8', 'replace')
        position += length
        digest = index[position:position + 16]
        position += 16
        if position + 9 > len(index):
            break
        offset, size = struct.unpack_from('<II', index, position)
        position += 8
        compressed = index[position]
        position += 1
        tail = index[position:position + KLANGO_RECORD_TAIL]
        position += KLANGO_RECORD_TAIL
        mode = struct.unpack_from('<Q', tail, 6)[0] if len(tail) >= 14 else 0
        entries.append(KlangoEntry(name, digest, offset, size, compressed, mode))
    if not entries:
        raise PagError('the package has an empty directory')
    return entries


def read_klango_file(plain, entry):
    """One file out of an unconcealed package, checked against its own MD5."""
    if entry.is_directory:
        return b''
    start = entry.offset + 4          # each block carries its own checksum
    if entry.compressed:
        try:
            content = zlib.decompressobj().decompress(plain[start:])
        except zlib.error as error:
            raise PagError("'%s' would not decompress: %s" % (entry.name, error))
    else:
        content = plain[start:start + entry.size]
    if entry.digest and hashlib.md5(content).digest() != entry.digest:
        raise PagError("'%s' did not come out as the package says it should"
                       % entry.name)
    return content


# ------------------------------------------------------------------ writing
def build(source_dir, target, names=None):
    """Pack a folder into a Cling `.pag`. Returns the path written."""
    source_dir = os.path.abspath(source_dir)
    if not os.path.isdir(source_dir):
        raise PagError('%s is not a folder' % source_dir)

    entries = []
    payload = bytearray()
    for relative in sorted(names or _walk(source_dir)):
        full = os.path.join(source_dir, relative)
        if not os.path.isfile(full):
            continue
        with open(full, 'rb') as handle:
            blob = handle.read()
        entries.append({'name': relative.replace(os.sep, '/'),
                        'offset': len(payload), 'size': len(blob)})
        payload += blob
    if not entries:
        raise PagError('%s holds no files' % source_dir)

    index = lzma.compress(json.dumps(entries, ensure_ascii=False).encode('utf-8'))
    body = lzma.compress(bytes(payload))
    header = (CLING_MAGIC + bytes([CLING_VERSION])
              + struct.pack('<I', len(index))
              + struct.pack('<H', len(entries))
              + b'\x00' * (CLING_HEADER - 11))
    with open(target, 'wb') as handle:
        handle.write(header)
        handle.write(index)
        handle.write(body)
    return target


def _walk(root):
    for directory, _subdirs, files in os.walk(root):
        for leaf in files:
            full = os.path.join(directory, leaf)
            yield os.path.relpath(full, root)


# ------------------------------------------------------------------ reading
def entries_of(path):
    """The file list inside a Cling package."""
    header = read_header(path)
    if header.kind != CLING:
        raise PagError(header.describe())
    with open(path, 'rb') as handle:
        handle.seek(CLING_HEADER)
        index = handle.read(header.index_length)
    try:
        loaded = json.loads(lzma.decompress(index).decode('utf-8'))
    except (lzma.LZMAError, ValueError, UnicodeDecodeError) as error:
        raise PagError('%s has an index Cling could not read: %s'
                       % (os.path.basename(path), error))
    if not isinstance(loaded, list):
        raise PagError('%s has an index that is not a file list'
                       % os.path.basename(path))
    return [entry for entry in loaded if isinstance(entry, dict)]


def extract(path, destination, stream=None):
    """Unpack a package into `destination`. Returns the files written.

    A Klango package is handed to the keystream reader; without one it raises
    with a sentence that says so, which is not a fault - it is the ordinary
    case, and the application's data folder plays without it.
    """
    header = read_header(path)
    if header.kind == KLANGO:
        return _extract_klango(path, destination, stream)

    entries = entries_of(path)
    with open(path, 'rb') as handle:
        handle.seek(CLING_HEADER + header.index_length)
        body = handle.read()
    try:
        payload = lzma.decompress(body)
    except lzma.LZMAError as error:
        raise PagError('%s is damaged: %s' % (os.path.basename(path), error))

    root = os.path.abspath(destination)
    written = []
    for entry in entries:
        name = str(entry.get('name') or '').replace('\\', '/').lstrip('/')
        if not name:
            continue
        target = os.path.abspath(os.path.join(root, name))
        # A package came from wherever the user found it; an entry named
        # `../../autostart` is how one would write outside the folder it was
        # asked to unpack into.
        if not _inside(root, target):
            raise PagError("%s contains an entry that points outside the "
                           "folder ('%s')" % (os.path.basename(path), name))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        offset = int(entry.get('offset', 0))
        size = int(entry.get('size', 0))
        with open(target, 'wb') as out:
            out.write(payload[offset:offset + size])
        written.append(target)
    return written


def _extract_klango(path, destination, stream=None):
    """Unpack a Klango package. Returns the files written."""
    with open(path, 'rb') as handle:
        plain = unconceal(handle.read())
    entries = read_klango_index(plain)
    root = os.path.abspath(destination)
    written = []
    for entry in entries:
        name = entry.name.replace('\\', '/').lstrip('/')
        if not name:
            continue
        target = os.path.abspath(os.path.join(root, name))
        # A package came from wherever the user found it; an entry named
        # `../../autostart` is how one would write outside the folder it was
        # asked to unpack into.
        if not _inside(root, target):
            raise PagError("%s contains an entry that points outside the "
                           "folder ('%s')" % (os.path.basename(path), entry.name))
        if entry.is_directory:
            os.makedirs(target, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'wb') as out:
            out.write(read_klango_file(plain, entry))
        written.append(target)
    return written


def _inside(root, candidate):
    try:
        return os.path.commonpath([root, candidate]) == root
    except ValueError:
        return False


# ------------------------------------------------------------------ mounting
_MOUNTS = {}


def cache_dir():
    """Where a package is unpacked to be used. Transient, never user data."""
    try:
        from src.platform_utils import get_user_resource_path
        base = get_user_resource_path(os.path.join('pkg_cache', 'cling'))
    except Exception:
        base = os.path.join(tempfile.gettempdir(), 'cling_pkg_cache')
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        pass
    return base


#: The name of the stamp a mounted package leaves behind, so a package
#: already unpacked by an earlier RUN of Titan is used rather than unpacked
#: again. Without it `llib.pag` - 24 784 files - is extracted on every single
#: boot of an emulated application.
STAMP = '.cling_mount'


def mount(path):
    """Unpack a Cling package into the runtime cache and answer with the folder.

    The package file itself is never deleted or turned into a directory: the
    cache is a performance detail, exactly as Titan's own `.TCA`/`.TCD` cache
    is, and a package whose file has since changed is unpacked again.
    """
    path = os.path.abspath(path)
    signature = _signature(path)
    folder = _mount_path(path)
    if _MOUNTS.get(path) == signature and os.path.isdir(folder):
        return folder
    if _stamp_of(folder) == signature and _has_content(folder):
        _MOUNTS[path] = signature
        return folder
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder, exist_ok=True)
    extract(path, folder)
    _write_stamp(folder, signature)
    _prune(folder)
    _MOUNTS[path] = signature
    return folder


def _prune(keep):
    """Throw away the copies of this package the OLD scheme left behind.

    Every run of Titan used to unpack a package into a folder of its own -
    the tag was `hash()` of its path, which Python salts per process - so a
    machine that has run this a hundred times has a hundred copies of it.

    What tells one of those from a real mount is the STAMP, not the name: two
    different packages can be called `wiki.pag` (Cling ships one in `logic/`
    and the user has another in `data/cling/`) and their folders differ only
    by the digest, which is exactly what an old `hash()` tag looked like.
    Pruning by name alone deleted a mount that was in use, and the next thing
    to read it found a folder with nothing in it.
    """
    base = os.path.dirname(keep)
    prefix = os.path.basename(keep).rsplit('_', 1)[0] + '_'
    try:
        names = os.listdir(base)
    except OSError:
        return
    for name in names:
        if not name.startswith(prefix) or name == os.path.basename(keep):
            continue
        folder = os.path.join(base, name)
        if not os.path.isdir(folder):
            continue
        if os.path.isfile(os.path.join(folder, STAMP)):
            continue          # a real mount of some other package
        shutil.rmtree(folder, ignore_errors=True)


def _signature(path):
    """What makes a mount out of date: the file itself having moved."""
    return '%d:%d' % (int(os.path.getmtime(path)), os.path.getsize(path))


def _has_content(folder):
    """Is there anything in the mount besides the note saying it is one?

    A stamp on an empty folder is a mount that was taken away underneath it,
    and believing the stamp then hands the caller a package with nothing in
    it - which reads exactly like a package that is broken.
    """
    try:
        return any(name != STAMP for name in os.listdir(folder))
    except OSError:
        return False


def _stamp_of(folder):
    try:
        with open(os.path.join(folder, STAMP), 'r', encoding='utf-8') as handle:
            return handle.read().strip()
    except OSError:
        return ''


def _write_stamp(folder, signature):
    try:
        with open(os.path.join(folder, STAMP), 'w', encoding='utf-8') as handle:
            handle.write(signature)
    except OSError:
        pass


def _mount_path(path):
    """The one folder this package unpacks to, for every run of Titan.

    The tag was `hash()` of the path, and Python salts string hashing per
    PROCESS - so no two runs agreed on the folder, every boot unpacked the
    whole of `llib.pag` again, and the cache grew a directory per run for ever
    (measured: hundreds of copies of one package). A digest of the path is the
    same number in every process.
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    digest = hashlib.md5(os.path.abspath(path).lower().encode(
        'utf-8', 'replace')).hexdigest()
    return os.path.join(cache_dir(), '%s_%s' % (_safe(stem), digest[:8]))


def _safe(name):
    return ''.join(char if (char.isalnum() or char in '-_.') else '_'
                   for char in str(name))[:60] or 'package'


def inspect(path):
    """What Cling can say about a package without opening it."""
    header = read_header(path)
    lines = [header.describe()]
    if header.kind == CLING:
        try:
            lines.append('Files: %s' % ', '.join(
                entry.get('name', '?') for entry in entries_of(path)[:12]))
        except PagError as error:
            lines.append(str(error))
    else:
        try:
            with open(path, 'rb') as handle:
                entries = read_klango_index(unconceal(handle.read()))
            files = [e.name for e in entries if not e.is_directory]
            lines.append('Files: %s%s' % (', '.join(files[:8]),
                                          ' ...' if len(files) > 8 else ''))
        except PagError as error:
            lines.append(str(error))
    return '\n'.join(lines)
