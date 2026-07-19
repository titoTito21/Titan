# -*- coding: utf-8 -*-
"""
Package installation
=====================
Copies a .TCA/.TCD file dropped on Titan from outside the app (e.g. a
Windows Explorer file-association double-click) into the correct per-user
overlay `data/<subdir>/` directory, where it stays as a normal file (never
extracted into a directory, never deleted) and is picked up by the regular
discovery mechanism from then on. Extraction, if the caller needs to
inspect the manifest immediately, goes through the same transient runtime
cache as any other discovery (titan_package.ensure_extracted).

This is intentionally separate from `titan_package.py` (the format itself)
-- this module is about *installing into Titan's library*, one specific use
of the format, not the format's mechanics.
"""

import os
import shutil

from src.titan_core import titan_package


class InstallResult:
    __slots__ = ('kind', 'id', 'installed_path', 'extracted_dir')

    def __init__(self, kind, pkg_id, installed_path, extracted_dir):
        self.kind = kind
        self.id = pkg_id
        # The permanent, real location of the .tca/.tcd file itself.
        self.installed_path = installed_path
        # A transient runtime-cache directory with its unpacked contents,
        # useful for inspecting the manifest right after install -- not a
        # substitute for installed_path and not guaranteed to persist.
        self.extracted_dir = extracted_dir


def _same_file(a, b):
    """True if two existing files have identical size+mtime -- a cheap
    dedupe check so re-installing the same download twice doesn't create
    myapp_2.tca, myapp_3.tca clutter."""
    try:
        sa, sb = os.stat(a), os.stat(b)
        return sa.st_size == sb.st_size and int(sa.st_mtime) == int(sb.st_mtime)
    except OSError:
        return False


def install_package(source_path):
    """Copy source_path into the per-user overlay data/<subdir>/ directory
    for its kind (as a normal, permanent file) and return an InstallResult.

    Returns None (never raises) if source_path isn't a recognizable package
    or installation otherwise fails -- a bad/corrupt file must not be able
    to crash startup.
    """
    try:
        if not titan_package.is_package_file(source_path):
            print(f"[PackageInstall] Not a recognized package: {source_path}")
            return None

        header = titan_package.read_header(source_path)
        subdir = header.subdir
        if not subdir:
            print(f"[PackageInstall] Unknown kind {header.kind} in {source_path}")
            return None

        from src.platform_utils import ensure_user_data_subdir
        dest_dir = ensure_user_data_subdir('data', subdir)

        ext = os.path.splitext(source_path)[1] or titan_package.default_extension(header.kind)
        base_name = header.id or os.path.splitext(os.path.basename(source_path))[0]
        dest_path = os.path.join(dest_dir, base_name + ext)
        counter = 2
        while os.path.exists(dest_path) and not _same_file(dest_path, source_path):
            dest_path = os.path.join(dest_dir, f"{base_name}_{counter}{ext}")
            counter += 1

        if os.path.abspath(dest_path) != os.path.abspath(source_path):
            if not (os.path.exists(dest_path) and _same_file(dest_path, source_path)):
                shutil.copy2(source_path, dest_path)

        extracted_dir = titan_package.ensure_extracted(dest_path)
        print(f"[PackageInstall] Installed '{source_path}' -> '{dest_path}' "
              f"(kind={header.kind_name}, id={header.id})")
        return InstallResult(header.kind, header.id, dest_path, extracted_dir)
    except Exception as e:
        print(f"[PackageInstall] Failed to install '{source_path}': {e}")
        return None
