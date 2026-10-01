"""A decoded copy of a sound file that pygame's own decoder cannot read.

Measured on Debian 11 with pygame-ce 2.5.6: twenty of Titan's bundled
Vorbis files - ordinary libVorbis 2020 files, ``window.ogg`` among them -
come back from ``pygame.mixer.Sound`` as a Sound of NO samples, and
playing one is a segmentation fault. Windows' pygame decodes every one of
them. So off Windows a file that decodes to nothing is decoded once by
``oggdec`` (vorbis-tools) or ``opusdec`` (opus-tools) into a WAV kept
under the user's cache, and that is what plays. Without either tool the
answer is None and the cue is simply not played.
"""
import hashlib
import os
import shutil
import subprocess
import sys

IS_WINDOWS = sys.platform == 'win32'


def _cache_dir():
    base = os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))
    path = os.path.join(base, 'titan', 'decoded')
    os.makedirs(path, exist_ok=True)
    return path


def decoded_copy(path):
    """The WAV that stands in for *path*, made if need be, or None."""
    if IS_WINDOWS or not path or not os.path.isfile(path):
        return None
    try:
        stat = os.stat(path)
        key = hashlib.sha1(f"{os.path.abspath(path)}|{stat.st_size}|{int(stat.st_mtime)}"
                           .encode('utf-8')).hexdigest()[:20]
        target = os.path.join(_cache_dir(), key + '.wav')
        if os.path.isfile(target) and os.path.getsize(target) > 44:
            return target
        tools = []
        with open(path, 'rb') as f:
            head = f.read(200)
        if b'OpusHead' in head:
            tools = [['opusdec', '--quiet', path, target]]
        else:
            tools = [['oggdec', '-Q', '-o', target, path]]
        for command in tools:
            if not shutil.which(command[0]):
                continue
            done = subprocess.run(command, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=20)
            if done.returncode == 0 and os.path.isfile(target) and os.path.getsize(target) > 44:
                return target
        return None
    except Exception:
        return None


def why_unavailable():
    if IS_WINDOWS:
        return ''
    if shutil.which('oggdec') or shutil.which('opusdec'):
        return ''
    return 'install vorbis-tools (oggdec) or opus-tools (opusdec)'
