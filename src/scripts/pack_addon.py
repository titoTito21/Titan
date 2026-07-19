#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Pack (or convert) a TCE add-on directory into a .TCA/.TCD package, or unpack
one back into a directory for inspection.

Usage:
    python src/scripts/pack_addon.py <source_dir> [-o output] [--kind KIND] [--level 0-9]
    python src/scripts/pack_addon.py --unpack <package> -o <dest_dir>

--kind is inferred from which data/<subdir>/ the source directory lives
under if omitted (e.g. data/applications/tcalc -> app). Required if the
source directory isn't under a recognizable data/<subdir>/ path.
"""

import argparse
import os
import sys

TCE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

from src.titan_core import titan_package  # noqa: E402


def _infer_kind(source_dir):
    """Best-effort: look for a data/<subdir>/ path component."""
    parts = os.path.normpath(os.path.abspath(source_dir)).split(os.sep)
    for i, part in enumerate(parts):
        if part == 'data' and i + 1 < len(parts):
            subdir_candidate = parts[i + 1]
            kind = titan_package.SUBDIR_TO_KIND.get(subdir_candidate)
            if kind:
                return kind
    return None


def cmd_pack(args):
    source_dir = os.path.abspath(args.source)
    if not os.path.isdir(source_dir):
        print(f"Not a directory: {source_dir}")
        return 1

    kind = titan_package.NAME_TO_KIND.get(args.kind) if args.kind else _infer_kind(source_dir)
    if kind is None:
        print("Could not determine --kind (source isn't under a recognizable "
              "data/<subdir>/ path). Pass --kind explicitly, one of: "
              + ", ".join(sorted(titan_package.NAME_TO_KIND)))
        return 1

    if args.output:
        output_path = args.output
    else:
        ext = titan_package.default_extension(kind)
        base = os.path.basename(source_dir.rstrip(os.sep))
        output_path = os.path.join(os.path.dirname(source_dir), base + ext)

    titan_package.build_package(source_dir, output_path, kind, level=args.level)
    kind_name = titan_package.KIND_NAMES[kind]
    print(f"Packed '{source_dir}' -> '{output_path}' (kind={kind_name})")
    return 0


def cmd_unpack(args):
    package_path = os.path.abspath(args.unpack)
    if not titan_package.is_package_file(package_path):
        print(f"Not a recognized .tca/.tcd package: {package_path}")
        return 1

    header = titan_package.read_header(package_path)
    dest_dir = args.output or os.path.join(
        os.path.dirname(package_path), header.id
    )
    titan_package.unpack(package_path, dest_dir)
    print(f"Unpacked '{package_path}' (kind={header.kind_name}, id={header.id}) "
          f"-> '{dest_dir}'")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('source', nargs='?', help='Directory to pack (omit when using --unpack)')
    parser.add_argument('-o', '--output', help='Output file (pack) or destination directory (--unpack)')
    parser.add_argument('--kind', choices=sorted(titan_package.NAME_TO_KIND),
                         help='Add-on kind; inferred from the source path if omitted')
    parser.add_argument('--level', type=int, default=6, choices=range(0, 10),
                         metavar='0-9', help='LZMA compression preset (default 6, higher = smaller/slower)')
    parser.add_argument('--unpack', metavar='PACKAGE', help='Unpack a .tca/.tcd for inspection instead of packing')
    args = parser.parse_args()

    if args.unpack:
        return cmd_unpack(args)

    if not args.source:
        parser.error('source directory is required unless --unpack is used')
    return cmd_pack(args)


if __name__ == '__main__':
    sys.exit(main())
