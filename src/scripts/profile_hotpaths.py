"""
Profile hot-path analyzer for Titan (Phase 0 of the code-optimization plan).

Turns a cProfile .pstats dump into a ranked report of where CPU time actually
goes, so cythonization targets are chosen from measurements - not guesses.

The key output is the PROJECT-ONLY view: functions living in Titan's own code
(src/ and main.py), excluding library internals. Those are the only frames
Cython can realistically speed up; time spent inside wxPython, pygame, ctypes
(eSpeak), opuslib, COM, etc. is already native and won't benefit.

Usage
-----
Gather a profile first, either:

  # Runtime (main()+GUI; use the app, then close it):
  python main.py --profile

  # Full startup incl. imports (captures the heavy import phase too):
  python -m cProfile -o profile_out/startup.pstats main.py

Then analyze:

  python src/scripts/profile_hotpaths.py                 # newest dump in profile_out/
  python src/scripts/profile_hotpaths.py path/to.pstats  # a specific dump
  python src/scripts/profile_hotpaths.py --top 30        # show more rows

Live sampling alternative (no dump, no code change), if py-spy is installed:

  py-spy top --pid <titan_pid>
  py-spy record -o profile_out/titan.svg --pid <titan_pid>
"""

import argparse
import glob
import os
import pstats
import sys

# Project root = two levels up from this file (src/scripts/ -> project root).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROFILE_DIR = os.path.join(_PROJECT_ROOT, 'profile_out')


def _is_project_frame(filename):
    """True if a stats frame belongs to Titan's own code (not a library)."""
    if not filename:
        return False
    norm = filename.replace('\\', '/').lower()
    if 'site-packages' in norm or 'lib/python' in norm or '<' in norm:
        return False
    return ('/src/' in norm) or norm.endswith('/main.py') or norm.endswith('main.py')


def _short(filename):
    """Render a filename relative to the project root when possible."""
    try:
        rel = os.path.relpath(filename, _PROJECT_ROOT)
        if not rel.startswith('..'):
            return rel.replace('\\', '/')
    except Exception:
        pass
    return filename


def _find_latest_dump():
    """Return the newest .pstats file in profile_out/, or None."""
    if not os.path.isdir(_PROFILE_DIR):
        return None
    dumps = glob.glob(os.path.join(_PROFILE_DIR, '*.pstats'))
    if not dumps:
        return None
    return max(dumps, key=os.path.getmtime)


def _rows(stats):
    """Yield (tottime, cumtime, ncalls, filename, lineno, func) for each frame."""
    for (filename, lineno, func), (cc, nc, tt, ct, callers) in stats.stats.items():
        yield (tt, ct, nc, filename, lineno, func)


def _print_table(title, rows, top):
    print()
    print(title)
    print("-" * len(title))
    print(f"{'tottime':>9} {'cumtime':>9} {'ncalls':>10}  location")
    for tt, ct, nc, filename, lineno, func in rows[:top]:
        loc = f"{_short(filename)}:{lineno}({func})"
        print(f"{tt:9.4f} {ct:9.4f} {nc:>10}  {loc}")


def analyze(path, top):
    if not os.path.isfile(path):
        print(f"Profile file not found: {path}")
        return 1

    stats = pstats.Stats(path)
    total = stats.total_tt
    rows = list(_rows(stats))

    print("=" * 78)
    print(f"Profile: {_short(path)}")
    print(f"Total run time captured: {total:.3f}s   |   frames: {len(rows)}")
    print("=" * 78)
    print("tottime = time in the function itself (Cython helps here)")
    print("cumtime = time including everything it called")

    # Whole-process views.
    by_tot = sorted(rows, key=lambda r: r[0], reverse=True)
    _print_table(f"TOP {top} BY tottime (whole process)", by_tot, top)

    # Project-only view - the actual cythonization candidates.
    proj = [r for r in rows if _is_project_frame(r[3])]
    proj_by_tot = sorted(proj, key=lambda r: r[0], reverse=True)
    proj_tot_sum = sum(r[0] for r in proj)
    _print_table(
        f"TOP {top} BY tottime (Titan code only - cythonization candidates)",
        proj_by_tot, top)

    # Per-module roll-up of project tottime, to spot whole modules worth compiling.
    per_module = {}
    for tt, ct, nc, filename, lineno, func in proj:
        per_module[_short(filename)] = per_module.get(_short(filename), 0.0) + tt
    module_rows = sorted(per_module.items(), key=lambda kv: kv[1], reverse=True)

    print()
    print("PROJECT tottime BY MODULE")
    print("-------------------------")
    print(f"{'tottime':>9}  module")
    for mod, tt in module_rows[:top]:
        print(f"{tt:9.4f}  {mod}")

    print()
    print(f"Titan-code tottime: {proj_tot_sum:.3f}s of {total:.3f}s "
          f"({(proj_tot_sum / total * 100.0) if total else 0.0:.1f}% of captured time).")
    print("Rule of thumb: only compile modules with a clearly nonzero share here; "
          "the rest is native/library time Cython cannot touch.")
    return 0


def run_and_analyze(extra_args, top):
    """Run main.py under cProfile (captures imports too), then analyze."""
    import subprocess
    import time

    os.makedirs(_PROFILE_DIR, exist_ok=True)
    out_path = os.path.join(_PROFILE_DIR, f"startup_{time.strftime('%Y%m%d_%H%M%S')}.pstats")
    main_py = os.path.join(_PROJECT_ROOT, 'main.py')
    cmd = [sys.executable, '-m', 'cProfile', '-o', out_path, main_py] + list(extra_args)
    print(f"Running: {' '.join(cmd)}")
    print("(Use the app for your scenario, then close it to end profiling.)")
    subprocess.run(cmd, cwd=_PROJECT_ROOT)
    return analyze(out_path, top)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze a Titan cProfile .pstats dump for cythonization targets.")
    parser.add_argument('pstats', nargs='?', default=None,
                        help='Path to a .pstats file (default: newest in profile_out/).')
    parser.add_argument('--top', type=int, default=20,
                        help='Number of rows per table (default: 20).')
    parser.add_argument('--run', action='store_true',
                        help='Run main.py under cProfile (captures imports) then analyze.')
    args, extra = parser.parse_known_args()

    if args.run:
        return run_and_analyze(extra, args.top)

    path = args.pstats or _find_latest_dump()
    if not path:
        print("No .pstats file given and none found in profile_out/.")
        print("Generate one with:  python main.py --profile")
        print("or:                 python -m cProfile -o profile_out/startup.pstats main.py")
        return 1
    return analyze(path, args.top)


if __name__ == "__main__":
    sys.exit(main())
