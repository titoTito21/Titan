"""Tolerant hook for webrtcvad / webrtcvad-wheels.

The PyInstaller-contrib hook calls ``copy_metadata('webrtcvad')`` unconditionally
and aborts the whole build with PackageNotFoundError when only the alternate
distribution ``webrtcvad-wheels`` is installed (typical on Python 3.13+ where
upstream ``webrtcvad`` no longer ships wheels). This local override is loaded
first via ``--additional-hooks-dir`` and tries each known distribution name in
turn, skipping silently if none has installed metadata.
"""

from PyInstaller.utils.hooks import copy_metadata, collect_dynamic_libs

datas = []
for _dist in ("webrtcvad", "webrtcvad-wheels", "webrtcvad_wheels"):
    try:
        datas += copy_metadata(_dist)
        break
    except Exception:
        continue

binaries = collect_dynamic_libs("webrtcvad")
