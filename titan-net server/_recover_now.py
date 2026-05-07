#!/usr/bin/env python3
"""SQLCipher recovery — `sqlcipher_export` from live with backup fallback.

Used when titan-net.service refuses to start because
``PRAGMA integrity_check`` fails (HMAC drift / page corruption). Walks
candidate source DBs newest-first, each time tries
``sqlcipher_export`` into a fresh file, runs ``integrity_check`` on the
copy, and on success atomically swaps it in as the new live DB.

Run on the SERVER. Stop ``titan-net`` first — running this against the
live file while the service is up violates the SQLCipher single-process
rule from memory (sqlcipher_safety.md).
"""
from __future__ import annotations

import datetime
import os
import shutil
import sys

LIVE_DB = '/opt/titan-net/database/titannet.db'
BACKUP_DIR = '/opt/titan-net/database/backups'
ENV_FILE = '/opt/titan-net/.env'


def load_env(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def import_sqlcipher():
    try:
        from sqlcipher3 import dbapi2 as sqlite3  # type: ignore
        return sqlite3
    except Exception:
        from pysqlcipher3 import dbapi2 as sqlite3  # type: ignore
        return sqlite3


def candidate_sources() -> list[str]:
    """Return source DB paths newest-first: live, then backups newest-first."""
    sources: list[str] = []
    if os.path.exists(LIVE_DB):
        sources.append(LIVE_DB)
    if os.path.isdir(BACKUP_DIR):
        backups = []
        for name in os.listdir(BACKUP_DIR):
            if 'corrupt' in name.lower():
                continue
            if not name.startswith('titannet_'):
                continue
            if not name.endswith('.db'):
                continue
            full = os.path.join(BACKUP_DIR, name)
            if not os.path.isfile(full):
                continue
            try:
                backups.append((os.path.getmtime(full), full))
            except Exception:
                pass
        backups.sort(key=lambda t: t[0], reverse=True)
        sources.extend(p for _, p in backups)
    return sources


def attempt_export(src: str, dst: str, key: str, sqlite3) -> tuple[bool, str]:
    """Try sqlcipher_export(src→dst). Returns (ok, message)."""
    if os.path.exists(dst):
        try:
            os.remove(dst)
        except Exception:
            pass
    try:
        conn = sqlite3.connect(src, timeout=30.0)
        try:
            conn.execute(f"PRAGMA key = '{key}'")
            conn.execute("SELECT count(*) FROM sqlite_master")
            conn.execute(
                f"ATTACH DATABASE '{dst}' AS rebuilt KEY '{key}'"
            )
            conn.execute("SELECT sqlcipher_export('rebuilt')")
            conn.execute("DETACH DATABASE rebuilt")
        finally:
            conn.close()
    except Exception as e:
        return False, f"sqlcipher_export from {src!r} crashed: {type(e).__name__}: {e}"
    if not os.path.exists(dst):
        return False, f"sqlcipher_export from {src!r} produced no file"
    try:
        verify = sqlite3.connect(dst, timeout=30.0)
        try:
            verify.execute(f"PRAGMA key = '{key}'")
            row = verify.execute("PRAGMA integrity_check").fetchone()
            n_users = verify.execute(
                "SELECT count(*) FROM users"
            ).fetchone()[0]
        finally:
            verify.close()
    except Exception as e:
        return False, (
            f"integrity_check on rebuilt {dst!r} crashed: "
            f"{type(e).__name__}: {e}"
        )
    if not row or (row[0] or '').lower() != 'ok':
        return False, f"integrity_check returned {row!r} on {dst!r}"
    return True, f"OK ({n_users} users) — exported from {src!r}"


def main() -> int:
    load_env(ENV_FILE)
    key = os.environ.get('DATABASE_KEY') or '***REMOVED***'
    if not key:
        print('FATAL: DATABASE_KEY not set', flush=True)
        return 2

    sqlite3 = import_sqlcipher()

    ts = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    rebuilt = LIVE_DB + f'.rebuilt_{ts}'
    forensic = LIVE_DB + f'.hmac_drift_{ts}'

    if os.path.exists(LIVE_DB):
        try:
            shutil.copy2(LIVE_DB, forensic)
            print(f'forensic copy -> {forensic}', flush=True)
        except Exception as e:
            print(f'WARN: forensic copy failed: {e}', flush=True)

    sources = candidate_sources()
    print(f'candidate sources ({len(sources)}):', flush=True)
    for s in sources:
        try:
            sz = os.path.getsize(s)
            mt = datetime.datetime.fromtimestamp(os.path.getmtime(s)).isoformat()
        except Exception:
            sz = '?'
            mt = '?'
        print(f'  - {s} ({sz} B, mtime {mt})', flush=True)

    chosen_src = None
    for src in sources:
        print(f'\n=== trying source: {src} ===', flush=True)
        ok, msg = attempt_export(src, rebuilt, key, sqlite3)
        print(msg, flush=True)
        if ok:
            chosen_src = src
            break

    if chosen_src is None:
        print('\nFATAL: every candidate failed sqlcipher_export+integrity_check.',
              flush=True)
        if os.path.exists(rebuilt):
            try:
                os.remove(rebuilt)
            except Exception:
                pass
        return 3

    # Atomic swap. Keep the corrupt live as ".corrupt_<ts>" (in addition to the
    # forensic copy taken at the top) so we still have it post-swap.
    if os.path.exists(LIVE_DB):
        corrupt_kept = LIVE_DB + f'.corrupt_{ts}'
        try:
            os.rename(LIVE_DB, corrupt_kept)
            print(f'\nmoved corrupt live -> {corrupt_kept}', flush=True)
        except Exception as e:
            print(f'WARN: rename live to corrupt_kept failed: {e}', flush=True)
    # Wipe stale WAL/SHM that belonged to the corrupt connection — they are
    # tied to the now-replaced file and confuse the next start.
    for sidecar in (LIVE_DB + '-wal', LIVE_DB + '-shm', LIVE_DB + '.pid'):
        if os.path.exists(sidecar):
            try:
                os.remove(sidecar)
                print(f'removed stale {sidecar}', flush=True)
            except Exception as e:
                print(f'WARN: remove {sidecar} failed: {e}', flush=True)

    os.rename(rebuilt, LIVE_DB)
    print(f'\nrecovered live DB in place; source was {chosen_src}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
