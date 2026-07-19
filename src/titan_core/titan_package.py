# -*- coding: utf-8 -*-
"""
Titan Package format (.TCA / .TCD)
===================================
Optional single-file container for add-ons that would otherwise ship as a
`data/<subdir>/{id}/` directory: applications and games use `.TCA`, every
other add-on kind (components, launchers, Titan IM modules, gamepad modes,
TTS engines, widgets/applets, statusbar applets) uses `.TCD`. Both share one
binary layout; the extension is a developer-facing convention enforced by
the packer, not read by the loader.

This is deliberate obfuscation, not encryption: a custom magic header plus
LZMA compression means 7-Zip / Windows Explorer do not recognize the file as
an archive, but the format itself is not secret (this module documents it).

Layout::

    magic        4 bytes   b'TCPK'
    version      1 byte    0x01
    kind         1 byte    see KIND_TO_SUBDIR
    id_len       1 byte
    id           N bytes   UTF-8, the package's folder-name-equivalent id
    payload_len  8 bytes   uint64 LE
    payload      LZMA-compressed stream of file records:
                 [path_len:u16 LE][path: UTF-8, POSIX-style '/']
                 [mode:u16 LE][size:u64 LE][raw bytes]
                 terminated by a record with path_len == 0

The payload, once extracted, is byte-identical to the directory it was
packed from -- including that add-on kind's own existing config file
(`__app.TCE`, `__component__.TCE`, etc). Nothing about the manifest format
itself changes; this module only adds a transport container around it.
"""

import os
import sys
import struct
import lzma
import shutil
import uuid


MAGIC = b'TCPK'
VERSION = 1

KIND_APP = 1
KIND_GAME = 2
KIND_COMPONENT = 3
KIND_LAUNCHER = 4
KIND_IM_MODULE = 5
KIND_GAMEPAD_MODE = 6
KIND_TTS_ENGINE = 7
KIND_WIDGET = 8
KIND_STATUSBAR_APPLET = 9

KIND_TO_SUBDIR = {
    KIND_APP: 'applications',
    KIND_GAME: 'games',
    KIND_COMPONENT: 'components',
    KIND_LAUNCHER: 'launchers',
    KIND_IM_MODULE: 'titanIM_modules',
    KIND_GAMEPAD_MODE: 'gamepad/modes',
    KIND_TTS_ENGINE: 'titantts engines',
    KIND_WIDGET: 'applets',
    KIND_STATUSBAR_APPLET: 'statusbar_applets',
}
SUBDIR_TO_KIND = {v: k for k, v in KIND_TO_SUBDIR.items()}
# engine_registry.py scans a second, legacy-named subdir for the same kind.
SUBDIR_TO_KIND['titan tts engines'] = KIND_TTS_ENGINE

KIND_NAMES = {
    KIND_APP: 'app', KIND_GAME: 'game', KIND_COMPONENT: 'component',
    KIND_LAUNCHER: 'launcher', KIND_IM_MODULE: 'im_module',
    KIND_GAMEPAD_MODE: 'gamepad_mode', KIND_TTS_ENGINE: 'tts_engine',
    KIND_WIDGET: 'widget', KIND_STATUSBAR_APPLET: 'statusbar_applet',
}
NAME_TO_KIND = {v: k for k, v in KIND_NAMES.items()}

# Apps/games ship as .TCA; every other kind ships as .TCD. The reader accepts
# both extensions everywhere (location decides the subsystem, same trust
# model directories already have) -- this mapping is only used by the packer
# to choose the conventional output extension.
_TCA_KINDS = (KIND_APP, KIND_GAME)

_HEADER_FIXED = struct.Struct('<4sBBB')   # magic, version, kind, id_len
_PAYLOAD_LEN = struct.Struct('<Q')        # payload_len
_REC_HEAD = struct.Struct('<HHQ')         # path_len, mode, size

_PACKAGE_EXTENSIONS = ('.tca', '.tcd')


class PackageError(Exception):
    """Raised for malformed or unreadable .TCA/.TCD files."""


class PackageHeader:
    __slots__ = ('kind', 'id', 'payload_offset', 'payload_len')

    def __init__(self, kind, pkg_id, payload_offset, payload_len):
        self.kind = kind
        self.id = pkg_id
        self.payload_offset = payload_offset
        self.payload_len = payload_len

    @property
    def subdir(self):
        return KIND_TO_SUBDIR.get(self.kind)

    @property
    def kind_name(self):
        return KIND_NAMES.get(self.kind, f'unknown_{self.kind}')

    def __repr__(self):
        return f"PackageHeader(kind={self.kind_name!r}, id={self.id!r})"


def default_extension(kind):
    """Return the conventional extension ('.tca' or '.tcd') for a kind."""
    return '.tca' if kind in _TCA_KINDS else '.tcd'


def is_package_file(path):
    """True if `path` looks like a Titan package: right extension AND magic
    bytes match. Never raises -- returns False for anything unreadable."""
    try:
        if os.path.splitext(path)[1].lower() not in _PACKAGE_EXTENSIONS:
            return False
        if not os.path.isfile(path):
            return False
        with open(path, 'rb') as f:
            return f.read(len(MAGIC)) == MAGIC
    except Exception:
        return False


def read_header(path):
    """Read just the header (magic/version/kind/id/payload bounds) without
    decompressing the payload. Raises PackageError on malformed input."""
    try:
        with open(path, 'rb') as f:
            fixed = f.read(_HEADER_FIXED.size)
            if len(fixed) != _HEADER_FIXED.size:
                raise PackageError(f"{path}: truncated header")
            magic, version, kind, id_len = _HEADER_FIXED.unpack(fixed)
            if magic != MAGIC:
                raise PackageError(f"{path}: bad magic")
            if version != VERSION:
                raise PackageError(f"{path}: unsupported version {version}")
            id_bytes = f.read(id_len)
            if len(id_bytes) != id_len:
                raise PackageError(f"{path}: truncated id")
            pkg_id = id_bytes.decode('utf-8', errors='replace')
            len_bytes = f.read(_PAYLOAD_LEN.size)
            if len(len_bytes) != _PAYLOAD_LEN.size:
                raise PackageError(f"{path}: truncated payload length")
            (payload_len,) = _PAYLOAD_LEN.unpack(len_bytes)
            payload_offset = f.tell()
        return PackageHeader(kind, pkg_id, payload_offset, payload_len)
    except PackageError:
        raise
    except Exception as e:
        raise PackageError(f"{path}: {e}")


# --------------------------------------------------------------------------- #
# Payload (de)serialization -- a minimal internal "tar" compressed as one
# LZMA stream (better ratio than compressing each file independently).
# --------------------------------------------------------------------------- #

def _iter_source_files(source_dir):
    """Yield (rel_posix_path, abs_path, mode) for every file under
    source_dir, skipping __pycache__ directories (disposable, CPython
    version-specific, regenerated on demand -- not worth shipping)."""
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for name in files:
            abs_path = os.path.join(root, name)
            rel = os.path.relpath(abs_path, source_dir).replace(os.sep, '/')
            try:
                mode = os.stat(abs_path).st_mode & 0o777
            except OSError:
                mode = 0o644
            yield rel, abs_path, mode


def _build_payload_bytes(source_dir):
    """Serialize source_dir's file tree into the uncompressed record stream."""
    chunks = []
    for rel, abs_path, mode in _iter_source_files(source_dir):
        rel_bytes = rel.encode('utf-8')
        with open(abs_path, 'rb') as f:
            data = f.read()
        chunks.append(_REC_HEAD.pack(len(rel_bytes), mode, len(data)))
        chunks.append(rel_bytes)
        chunks.append(data)
    chunks.append(struct.pack('<H', 0))  # terminator record (path_len == 0)
    return b''.join(chunks)


def _extract_payload_bytes(raw, dest_dir):
    """Write the decompressed record stream out into dest_dir."""
    pos = 0
    total = len(raw)
    while pos < total:
        path_len = struct.unpack_from('<H', raw, pos)[0]
        pos += 2
        if path_len == 0:
            break
        mode, size = struct.unpack_from('<HQ', raw, pos)
        pos += 10
        rel = raw[pos:pos + path_len].decode('utf-8')
        pos += path_len
        data = raw[pos:pos + size]
        pos += size

        dest_path = os.path.join(dest_dir, *rel.split('/'))
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, 'wb') as f:
            f.write(data)
        try:
            os.chmod(dest_path, mode or 0o644)
        except OSError:
            pass  # best-effort; Windows doesn't honour unix mode bits anyway


def read_payload(path, header=None):
    """Decompress and return the raw (uncompressed) record-stream bytes."""
    header = header or read_header(path)
    with open(path, 'rb') as f:
        f.seek(header.payload_offset)
        compressed = f.read(header.payload_len)
    if len(compressed) != header.payload_len:
        raise PackageError(f"{path}: truncated payload")
    return lzma.decompress(compressed, format=lzma.FORMAT_ALONE)


# --------------------------------------------------------------------------- #
# Packing
# --------------------------------------------------------------------------- #

def build_package(source_dir, output_path, kind, pkg_id=None, level=6):
    """Pack an existing add-on directory into a .TCA/.TCD file.

    Also serves as the "convert an existing directory" tool -- packing IS
    converting, there is no separate code path.

    Args:
        source_dir: directory to pack (e.g. data/applications/tcalc).
        output_path: destination file path.
        kind: one of the KIND_* constants.
        pkg_id: override for the package id (default: source_dir's folder name,
            matching the existing folder-name-is-id convention everywhere).
        level: LZMA preset 0-9 (higher = smaller but slower). Default 6.
    """
    if kind not in KIND_TO_SUBDIR:
        raise PackageError(f"unknown kind: {kind!r}")
    if not os.path.isdir(source_dir):
        raise PackageError(f"not a directory: {source_dir}")

    pkg_id = pkg_id or os.path.basename(os.path.normpath(source_dir))
    id_bytes = pkg_id.encode('utf-8')
    if len(id_bytes) > 255:
        raise PackageError("package id too long (max 255 UTF-8 bytes)")

    raw = _build_payload_bytes(source_dir)
    # FORMAT_ALONE (legacy .lzma) has no embedded container signature, unlike
    # the default FORMAT_XZ (which starts with the recognizable "7zXZ" magic)
    # -- keeps the payload from carrying its own archive-format fingerprint.
    compressed = lzma.compress(raw, format=lzma.FORMAT_ALONE, preset=level)

    header = _HEADER_FIXED.pack(MAGIC, VERSION, kind, len(id_bytes))
    header += id_bytes
    header += _PAYLOAD_LEN.pack(len(compressed))

    tmp_path = output_path + f'.tmp-{os.getpid()}'
    try:
        with open(tmp_path, 'wb') as f:
            f.write(header)
            f.write(compressed)
        os.replace(tmp_path, output_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return output_path


# --------------------------------------------------------------------------- #
# Extraction / cache
# --------------------------------------------------------------------------- #
#
# The .tca/.tcd file itself is the permanent artifact: it stays exactly
# where it's found (data/<subdir>/, bundled or per-user overlay) and is
# never deleted or converted into a directory. Extraction is a transient,
# on-the-fly runtime detail -- needed only because some subsystems (native
# DLL/EXE dependencies, ctypes, subprocess targets) require real files on
# disk. The cache below exists purely to avoid re-decompressing on every
# scan; it is not "installed" content and the user never manages it
# directly.

def _cache_digest(pkg_id, mtime, size):
    import hashlib
    raw = f"{pkg_id}:{int(mtime)}:{size}".encode('utf-8')
    return hashlib.sha256(raw).hexdigest()[:16]


def ensure_extracted(package_path, cache_root=None):
    """Extract package_path (once) into a cache directory and return that
    directory's absolute path. The source .tca/.tcd file is left completely
    untouched. Safe to call repeatedly and from multiple processes
    concurrently -- reuses the cache if the source is unchanged, and
    extraction itself is race-safe (extract to a unique temp dir, then
    atomically move it into place; a losing race just discards its temp dir
    and reuses whatever the winner produced).

    Args:
        package_path: path to a .tca/.tcd file.
        cache_root: override for the cache root directory. Defaults to
            `%APPDATA%/titosoft/Titan/pkg_cache/<subdir>/` (or the macOS/
            Linux equivalent) via platform_utils.ensure_user_data_subdir --
            a purely technical runtime cache, not user-managed data.
    """
    header = read_header(package_path)
    subdir = header.subdir or f'unknown_kind_{header.kind}'

    st = os.stat(package_path)
    digest = _cache_digest(header.id, st.st_mtime, st.st_size)

    if cache_root is None:
        from src.platform_utils import ensure_user_data_subdir
        root = ensure_user_data_subdir('pkg_cache', subdir)
    else:
        root = cache_root
        os.makedirs(root, exist_ok=True)

    target = os.path.join(root, digest)
    if os.path.isdir(target) and os.listdir(target):
        return target

    raw = read_payload(package_path, header)

    tmp = os.path.join(root, f'.tmp-{os.getpid()}-{uuid.uuid4().hex}')
    os.makedirs(tmp, exist_ok=True)
    try:
        _extract_payload_bytes(raw, tmp)
        try:
            os.replace(tmp, target)
        except OSError:
            # Another process/thread won the race and already created
            # `target` first -- discard our temp copy and use theirs.
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)

    return target


def unpack(package_path, dest_dir):
    """Debug/inspection helper: extract package_path into an explicit
    destination directory (not the managed cache), without touching the
    source file. Raises if dest_dir already exists and is non-empty."""
    if os.path.isdir(dest_dir) and os.listdir(dest_dir):
        raise PackageError(f"destination is not empty: {dest_dir}")
    os.makedirs(dest_dir, exist_ok=True)
    raw = read_payload(package_path)
    _extract_payload_bytes(raw, dest_dir)
    return dest_dir
