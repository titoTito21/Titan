"""
Cython build for selected Titan modules (Phase 1 of the optimization plan).

Compiles an explicit allow-list of pure-Python modules to C extensions (.pyd)
*in place* - the .pyd lands next to the .py so CPython imports the compiled
version automatically while the .py stays for development (python main.py keeps
working). PyInstaller then bundles the .pyd like any other file.

Design rules (deliberate, see plan):
  - NEVER "compile all of src/". Only modules with a measured, nonzero CPU
    share belong here. Profile first with src/scripts/profile_hotpaths.py.
  - Pure-Python mode (compile existing .py, no .pyx, no cdef). This keeps full
    Python exception semantics - no segfaults - at the cost of some peak speed.

Usage:
  python build_cython.py            # build every module in CYTHON_MODULES
  python build_cython.py --clean    # remove generated .c and built .pyd
"""

import glob
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Allow-list of modules to compile (paths relative to the project root).
#
# EMPTY ON PURPOSE. Profiling (2026-06) found no Titan module that benefits:
#   - The startup/import phase is ~98% native/library time (COM InvokeTypes,
#     subprocess TTS bridges, eSpeak voice enumeration, .pyc/dynamic loading) -
#     only ~2% is Titan's own Python, which Cython cannot meaningfully speed up.
#   - The best real-time candidate, src/network/voice_codec.py, was compiled
#     and benchmarked: the .pyd ran ~0.88x (SLOWER) than the .py, because its
#     work is already in C (struct.pack/unpack, bytes, opuslib). Compiling only
#     added wrapper overhead.
#
# So nothing is compiled today. This pipeline stays ready: if a RUNTIME profile
# (python main.py --profile while exercising a feature) ever shows a real
# pure-Python CPU hot path, add that module here and re-measure. Never add a
# module without a measured, positive speedup.
# ---------------------------------------------------------------------------
CYTHON_MODULES = [
]


def _abspaths():
    out = []
    for rel in CYTHON_MODULES:
        p = os.path.join(PROJECT_ROOT, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            print(f"[cython] WARNING: not found, skipping: {rel}")
            continue
        out.append(p)
    return out


def clean():
    """Remove generated .c and built .pyd for the listed modules."""
    removed = 0
    for rel in CYTHON_MODULES:
        base = os.path.join(PROJECT_ROOT, rel.replace("/", os.sep))
        stem = os.path.splitext(base)[0]
        # Cython emits <module>.c; build emits <module>*.pyd (cpXYZ-win_amd64).
        candidates = [stem + ".c"] + glob.glob(stem + "*.pyd") + glob.glob(stem + "*.so")
        for c in candidates:
            try:
                os.remove(c)
                print(f"[cython] removed {os.path.relpath(c, PROJECT_ROOT)}")
                removed += 1
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"[cython] could not remove {c}: {e}")
    print(f"[cython] clean done ({removed} file(s) removed).")


def build():
    """Compile the allow-list to .pyd in place."""
    sources = _abspaths()
    if not sources:
        print("[cython] nothing to build (CYTHON_MODULES empty or missing).")
        return 0

    try:
        from setuptools import setup
        from Cython.Build import cythonize
    except ImportError as e:
        print(f"[cython] build tools missing: {e}")
        print("[cython] install with: pip install Cython setuptools")
        return 1

    print("[cython] building:")
    for s in sources:
        print(f"    - {os.path.relpath(s, PROJECT_ROOT)}")

    ext_modules = cythonize(
        sources,
        compiler_directives={"language_level": "3"},
        # Quiet, deterministic builds.
        force=True,
        quiet=False,
    )

    # Drive an in-place build_ext. Run from PROJECT_ROOT so the package layout
    # (src.network.voice_codec) is resolved correctly.
    old_cwd = os.getcwd()
    os.chdir(PROJECT_ROOT)
    try:
        setup(
            name="titan_cython_ext",
            ext_modules=ext_modules,
            script_args=["build_ext", "--inplace"],
        )
    finally:
        os.chdir(old_cwd)
    print("[cython] build complete (.pyd placed next to .py).")
    return 0


if __name__ == "__main__":
    if "--clean" in sys.argv:
        clean()
        sys.exit(0)
    sys.exit(build())
