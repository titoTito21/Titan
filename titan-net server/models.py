"""
Titan-Net Server - Database Models
SQLite database models for user accounts, messages, rooms, and repository
Uses SQLCipher for encrypted database storage
"""

try:
    import sqlcipher3 as sqlite3
    _USE_SQLCIPHER = True
except ImportError:
    import sqlite3
    _USE_SQLCIPHER = False

import atexit
import hashlib
import os
import secrets
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
import json
import logging

# Argon2id password hashing (RFC-9106). Replaces the legacy unsalted
# SHA-256 scheme. Existing SHA-256 hashes in the DB stay verifiable via the
# legacy fallback in Database.verify_password and are upgraded in place on
# the user's next successful login (lazy migration). Hard-fail at import
# time if argon2-cffi is missing so the server cannot accidentally boot
# back to the old algorithm.
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash, VerificationError

# RFC-9106 baseline parameters: 64 MiB memory, 3 iterations, 4 lanes.
# ~80-150 ms per verify on a typical Linux server, comfortably inside the
# 8 s wait_for(authenticate_user) ceiling in server.py.
_PASSWORD_HASHER = PasswordHasher()

logger = logging.getLogger('TitanNetDB')


# Module-level registry of live Database instances, keyed by absolute db_path.
# Prevents the bug we hit on 2026-05-03 where ``main.py`` instantiated
# ``Database()`` once for the websocket server AND once for the HTTP server.
# Two instances meant two ``_writer_lock`` RLocks and two ``_writer_executor``
# pools — Python-side serialization broke down and SQLite saw concurrent
# writers from both, returning ``database is locked`` instantly (no
# busy_timeout because the locked-out connection wasn't in any wait state
# the busy handler can engage). Sharing the single instance fixes coordination
# at the Python level. See sqlcipher_writer_singleton.md.
_LIVE_INSTANCES: Dict[str, "Database"] = {}
_LIVE_INSTANCES_LOCK = threading.Lock()


def _is_pid_alive(pid: int) -> bool:
    """Cross-platform check whether a PID is currently alive."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by another user — treat as alive.
        return True
    except OSError:
        return False
    return True


def _serialized_write(fn):
    """Decorator: serialize writes behind ``self._writer_lock`` (RLock).

    Iteration history on 2026-05-02 (kept here so future-me doesn't
    repeat the same dead-ends):

      1. **THIS shape** — RLock around per-thread keyed connections.
         Stops `database is locked` storms (Python lock prevents
         concurrent SQLite EXCLUSIVE attempts). Each thread keeps using
         its own SQLCipher connection. Memory worried about cache drift
         here, but in practice the only HMAC error seen (page 45 at
         19:43:41) was almost certainly pre-existing on disk from the
         22 h of pure-concurrent writes that ran BEFORE this fix landed.

      2. Single-thread executor (`_writer_executor.submit + .result()`,
         one db-writer thread, one connection). Killed any cache
         coherency concern but became a HARD queue bottleneck: under
         6-7 users `authenticate_user` blew past its 8s timeout and
         clients got "Server is busy, please try again". Service had to
         be SIGKILLed because graceful SIGTERM couldn't drain the queue.
         **Do not reintroduce.**

      3. Shared writer connection swapped into per-thread `_tls.conn`
         under RLock. Looked clean for ~16 minutes, then per-thread
         **read** connections started returning `MemoryError` from
         `sqlite3Codec: deferred error condition`. SQLCipher's
         per-connection cipher contexts apparently can't peacefully
         coexist with a shared third connection writing pages they then
         try to read. **Do not reintroduce.**

    Reentrant by RLock — write methods may call other write methods
    without self-deadlock.

    Transient ``OperationalError: database is locked`` is retried with
    exponential backoff. With the singleton ``Database`` instance every
    writer path now shares this RLock, so SQLite-level lock contention
    should be unreachable in normal operation. The retry is defense in
    depth for: (a) the brief window during a WAL checkpoint where a write
    can be blocked by readers, (b) any future code path that opens a side
    connection. We never want a real user's login to fail because a
    checkpoint happened to land at the wrong millisecond.
    """
    def _wrapper(self, *args, **kwargs):
        with self._writer_lock:
            attempts = 0
            backoff = 0.05  # 50 ms
            while True:
                try:
                    return fn(self, *args, **kwargs)
                except sqlite3.OperationalError as e:
                    msg = str(e).lower()
                    if 'database is locked' not in msg and 'database is busy' not in msg:
                        raise
                    attempts += 1
                    if attempts >= 6:  # ~50+100+200+400+800+1600 ≈ 3.15 s total
                        logger.error(
                            f"_serialized_write: giving up on {fn.__name__} "
                            f"after {attempts} retries — {e}"
                        )
                        raise
                    logger.warning(
                        f"_serialized_write: transient lock on {fn.__name__} "
                        f"(attempt {attempts}), retrying in {backoff*1000:.0f} ms"
                    )
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 1.6)
    _wrapper.__name__ = fn.__name__
    _wrapper.__qualname__ = fn.__qualname__
    _wrapper.__doc__ = fn.__doc__
    _wrapper.__wrapped__ = fn
    return _wrapper


class _PooledConn:
    """Wrapper around a thread-local SQLCipher connection.

    SQLCipher runs a very expensive PBKDF2 key derivation every time a new
    connection is opened. The original code opened a fresh connection for
    every single query (68+ call sites, each dispatched via
    ``run_in_executor``), which made the encrypted server dramatically
    slower than the plain SQLite version.

    This wrapper keeps one real connection alive per worker thread and turns
    ``close()`` into a no-op so existing call sites keep working unchanged.
    The real connection stays cached in ``threading.local`` and is reused
    across calls, so the KDF only runs once per thread.
    """
    __slots__ = ('_real',)

    def __init__(self, real):
        object.__setattr__(self, '_real', real)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        setattr(self._real, name, value)

    def __enter__(self):
        return self._real.__enter__()

    def __exit__(self, exc_type, exc, tb):
        return self._real.__exit__(exc_type, exc, tb)

    def close(self):
        # Intentional no-op: keep the connection alive in the thread-local pool.
        pass


class Database:
    """SQLCipher-backed database. Singleton per ``db_path`` within a process.

    Constructing ``Database()`` twice in the same process for the same file
    used to silently produce two coordinator-less writer pools (one for the
    websocket server, one for the HTTP API server). With separate
    ``_writer_lock`` RLocks, both could hand cursors to SQLite concurrently
    and the second one got ``database is locked`` instantly — no
    busy_timeout could help because the contention was at the *connection
    level*, not at a wait-for-busy-handler level. We now route every
    construction through ``__new__`` so the second call returns the first
    instance instead.
    """

    def __new__(cls, db_path: str = "database/titannet.db"):
        canonical = os.path.abspath(db_path)
        with _LIVE_INSTANCES_LOCK:
            existing = _LIVE_INSTANCES.get(canonical)
            if existing is not None:
                # Same process re-entering: hand back the live instance so the
                # caller transparently shares the writer lock + executor +
                # connection pool. Without this we hit the 2026-05-03
                # ``database is locked`` storm where http_server.py and
                # server.py each had their own Database object.
                return existing
            inst = super().__new__(cls)
            inst._initialized = False
            _LIVE_INSTANCES[canonical] = inst
            return inst

    def __init__(self, db_path: str = "database/titannet.db"):
        # ``__new__`` returns the cached instance for repeat constructions,
        # but Python still runs ``__init__`` on it. Skip re-initialization so
        # we don't reopen connections or re-run integrity checks every time
        # somebody types ``Database()``.
        if getattr(self, '_initialized', False):
            return
        self._initialized = True
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else '.', exist_ok=True)

        # Load encryption key from config
        try:
            from config import Config
            self.db_key = Config.DATABASE_KEY
        except Exception:
            self.db_key = None

        # Thread-local connection pool. SQLCipher's PBKDF2 key derivation is
        # the dominant cost of opening a connection; caching one real
        # connection per worker thread means the KDF runs once per thread
        # instead of once per query.
        self._tls = threading.local()
        self._pid_lock_path = None

        # Single shared connection used for ALL writes. SQLCipher's
        # per-connection page cache drifts under multi-threaded writes
        # (production HMAC mismatches 2026-04-30, 2026-05-01, 2026-05-02),
        # so even though SQLite serializes writers at the file level, we
        # MUST funnel every write through one connection. ``_writer_lock``
        # (RLock) serializes Python-side access; the connection itself is
        # opened with ``check_same_thread=False`` so any thread holding the
        # lock can use it. This gives:
        #
        #   - No per-thread cache drift (one cache, one set of pages).
        #   - No "database is locked" storms (Python lock prevents SQLite
        #     from ever seeing concurrent EXCLUSIVE attempts).
        #   - No single-thread queue bottleneck (the dedicated
        #     ``_writer_executor`` was tested 2026-05-02 and produced
        #     "Server is busy" timeouts under 6-7 user load — writes piled
        #     up behind hot ones; doing the work on the caller's thread
        #     scales linearly with concurrency limited only by the lock).
        #
        # Lazily opened on first write so startup migrate/init paths run
        # against fresh per-thread connections like before.
        self._writer_real_conn = None

        # Single-worker executor that ALL writes should funnel through.
        # SQLCipher under multi-threaded writes (many threads each holding
        # their own keyed connection) has caused subtle page-cache drift /
        # HMAC mismatches twice (2026-04-30 and 2026-05-01). Concurrent
        # reads through the per-thread pool are still safe; only writes
        # need to be serialized. Writes routed through this executor are
        # guaranteed to run on the same thread, against the same
        # connection, with no concurrency. See `run_write` below.
        #
        # Hot-path callers that get hammered (game_session_log, online
        # status updates, etc.) MUST migrate to `run_write`. Lower-traffic
        # writes can stay on the legacy thread-local pool until they are
        # touched, but any NEW write code is required to use `run_write`.
        self._writer_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix='db-writer'
        )
        # Lock for ad-hoc serialization when callers can't easily refactor
        # to the executor pattern (e.g. multi-statement transactions that
        # must stay in the calling thread).
        self._writer_lock = threading.RLock()

        if _USE_SQLCIPHER:
            logger.info("Database encryption: SQLCipher enabled (thread-local pooled connections)")
        else:
            logger.warning("Database encryption: SQLCipher NOT available, using plain sqlite3")

        # Acquire a process-level lock BEFORE opening the file. This is the
        # belt-and-braces enforcement of sqlcipher_safety.md rule 1: no second
        # Database() instance can attach to a live file. Stale locks (dead
        # PID) are cleaned up automatically.
        self._acquire_pid_lock()

        self._migrate_to_encrypted()
        # Run integrity_check (with auto-recovery from backups) BEFORE
        # init_database. Previously init_database ran first and would crash
        # with "database disk image is malformed" on a corrupted file —
        # reaching the integrity gate / auto-recovery was therefore
        # impossible because the process aborted earlier in init. Now we
        # run the gate first, recover from a clean backup if needed, and
        # only then attempt init_database against a known-good file.
        # Belt-and-braces: if init_database STILL fails (some other
        # corruption surfaces during table creation), force one more
        # recovery cycle and retry once before giving up.
        self._verify_integrity_at_startup()
        try:
            self.init_database()
        except Exception as init_e:
            err_text = str(init_e).lower()
            if 'malformed' in err_text or 'disk image' in err_text:
                logger.error(
                    f"init_database hit malformed-DB AFTER integrity check: "
                    f"{init_e}. Forcing one more recovery pass."
                )
                if self._attempt_db_recovery():
                    logger.warning("init_database retrying after recovery")
                    self.init_database()
                else:
                    raise
            else:
                raise
        # Force a clean WAL on every startup. After a long uptime the WAL can
        # grow well past ``wal_autocheckpoint`` if any reader was holding an
        # old snapshot when the autocheckpoint fired (snapshot pins the wal
        # frames). A bloated WAL increases checkpoint contention windows
        # which surfaces as transient ``database is locked``. Truncating
        # before we accept any traffic gives every deploy a clean slate.
        try:
            self.checkpoint_wal('TRUNCATE')
        except Exception as e:
            logger.warning(f"Startup WAL checkpoint failed (non-fatal): {e}")

    def _acquire_pid_lock(self):
        """Refuse to open the DB if another live process holds it.

        The lock file lives next to the DB at ``<db_path>.pid`` and contains
        the PID of the owning process. On startup we check whether that PID
        is still alive; if yes we fail loudly, if no we treat the lock as
        stale and reclaim it.
        """
        if not self.db_path or self.db_path == ':memory:':
            return
        lock_path = self.db_path + '.pid'
        try:
            with open(lock_path, 'r') as f:
                old_pid_raw = f.read().strip()
            if old_pid_raw:
                old_pid = int(old_pid_raw)
                if old_pid == os.getpid():
                    # Same process re-entering (unusual, but harmless).
                    return
                if _is_pid_alive(old_pid):
                    raise RuntimeError(
                        f"Another process (pid={old_pid}) already holds the "
                        f"database lock at {lock_path}. Refusing to open the "
                        f"DB — opening it concurrently corrupts SQLCipher "
                        f"(see sqlcipher_safety.md rule 1). If you really "
                        f"need offline access, stop titan-net first."
                    )
                logger.warning(
                    f"Removing stale DB lock from dead pid={old_pid} at {lock_path}"
                )
        except FileNotFoundError:
            pass
        except (ValueError, OSError) as e:
            logger.warning(f"Ignoring unreadable DB lock at {lock_path}: {e}")

        try:
            with open(lock_path, 'w') as f:
                f.write(str(os.getpid()))
            self._pid_lock_path = lock_path
            atexit.register(self._release_pid_lock)
        except OSError as e:
            logger.warning(f"Could not write DB lock at {lock_path}: {e}")

    def _release_pid_lock(self):
        path = self._pid_lock_path
        if not path:
            return
        try:
            with open(path, 'r') as f:
                if f.read().strip() == str(os.getpid()):
                    os.remove(path)
        except OSError:
            pass

    def _verify_integrity_at_startup(self):
        """Fail-fast on a corrupted DB; auto-recover from backups if possible.

        Old behaviour was to raise RuntimeError on integrity failure and let
        systemd crash-loop the service. That left the operator on the hook
        for manual `_recover_now.py` runs every time SQLCipher developed
        page-level HMAC drift (which has happened multiple times — see
        sqlcipher_shared_writer.md, sqlcipher_hardening.md). We now attempt
        ``sqlcipher_export`` against the live file first (some pages may
        still decrypt) and then fall back through ``database/backups/``
        newest-first. On the first candidate that produces a file that
        passes ``integrity_check``, we atomically swap it into place,
        re-run schema init so any deploy-time migrations land on the
        fresh file, and re-verify. Only if every candidate fails do we
        raise — same hard-stop behaviour the operator already expects,
        but only as a true last resort.
        """
        ok, status = self._run_integrity_check_with_throwaway_conn()
        if ok:
            logger.info("Database integrity check passed (ok)")
            return
        logger.error(
            f"Database integrity check FAILED ({status!r}) — attempting "
            f"auto-recovery from backups"
        )
        if self._attempt_db_recovery():
            # Schema-side init is normally already done in __init__, but the
            # recovered file came from a backup that may pre-date today's
            # deploy. Re-running init_database (idempotent CREATE IF NOT
            # EXISTS) ensures any new tables / indexes added today end up on
            # the recovered file.
            try:
                self.init_database()
            except Exception as e:
                logger.warning(f"init_database after auto-recovery failed: {e}")
            ok2, status2 = self._run_integrity_check_with_throwaway_conn()
            if ok2:
                logger.warning(
                    "Database integrity restored via auto-recovery — "
                    "service will continue startup"
                )
                return
            logger.error(
                f"Database still failing integrity_check after recovery: {status2!r}"
            )
        raise RuntimeError(
            f"Database integrity check failed ({status!r}) and auto-recovery "
            f"could not produce a valid copy from any backup. Refusing to "
            f"start. See sqlcipher_safety.md rule 4 / _recover_now.py."
        )

    def _run_integrity_check_with_throwaway_conn(self):
        """Open a fresh keyed connection (NOT thread-local cached), run
        ``PRAGMA integrity_check``, close. Returns ``(ok, status_string)``.

        Throwaway because after a recovery swap we MUST NOT keep an open
        handle pointing at the now-deleted inode.
        """
        try:
            conn = self._open_keyed_connection()
        except Exception as e:
            return False, f"open_failed: {type(e).__name__}: {e}"
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        except Exception as e:
            try:
                conn.close()
            except Exception:
                pass
            return False, f"pragma_failed: {type(e).__name__}: {e}"
        try:
            conn.close()
        except Exception:
            pass
        if not row:
            return False, 'no_row'
        status = (row[0] or '') if not isinstance(row[0], bytes) else row[0].decode('utf-8', errors='replace')
        return (str(status).lower() == 'ok'), str(status)

    def _attempt_db_recovery(self) -> bool:
        """Try ``sqlcipher_export`` against live + every backup, newest-first.

        On success, atomically swaps the rebuilt file into ``self.db_path``,
        keeps the corrupt original as ``<db_path>.corrupt_<ts>``, takes a
        forensic copy as ``<db_path>.hmac_drift_<ts>``, and clears stale
        WAL/SHM sidecars (they belonged to the corrupt file). Returns True
        on success.

        Recovery uses throwaway connections only — no thread-local cache
        is touched until we reset it after the swap.
        """
        import shutil
        if not self.db_key:
            logger.error("Auto-recovery aborted: DATABASE_KEY is not configured")
            return False

        ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        rebuilt_path = self.db_path + f'.rebuilt_{ts}'
        forensic_path = self.db_path + f'.hmac_drift_{ts}'

        if os.path.exists(self.db_path):
            try:
                shutil.copy2(self.db_path, forensic_path)
                logger.info(f"Auto-recovery: forensic copy at {forensic_path}")
            except Exception as e:
                logger.warning(f"Auto-recovery: forensic copy failed: {e}")

        candidates = []
        if os.path.exists(self.db_path):
            candidates.append(self.db_path)
        db_dir = os.path.dirname(self.db_path) or '.'
        backup_dir = os.path.join(db_dir, 'backups')
        if os.path.isdir(backup_dir):
            backups = []
            for name in os.listdir(backup_dir):
                lower = name.lower()
                if 'corrupt' in lower:
                    continue
                if not name.startswith('titannet_') or not name.endswith('.db'):
                    continue
                full = os.path.join(backup_dir, name)
                if os.path.isfile(full):
                    try:
                        backups.append((os.path.getmtime(full), full))
                    except Exception:
                        pass
            backups.sort(reverse=True)
            candidates.extend(p for _, p in backups)

        if not candidates:
            logger.error("Auto-recovery: no candidate sources (live missing, no backups)")
            return False

        chosen = None
        for src in candidates:
            if os.path.exists(rebuilt_path):
                try:
                    os.remove(rebuilt_path)
                except Exception:
                    pass
            try:
                src_conn = sqlite3.connect(src, timeout=30.0)
                try:
                    if _USE_SQLCIPHER:
                        try:
                            src_conn.execute("PRAGMA cipher_memory_security = OFF")
                        except Exception:
                            pass
                        src_conn.execute(f"PRAGMA key = '{self.db_key}'")
                        src_conn.execute("SELECT count(*) FROM sqlite_master")
                    src_conn.execute(
                        f"ATTACH DATABASE '{rebuilt_path}' AS rebuilt KEY '{self.db_key}'"
                    )
                    src_conn.execute("SELECT sqlcipher_export('rebuilt')")
                    src_conn.execute("DETACH DATABASE rebuilt")
                finally:
                    src_conn.close()
            except Exception as e:
                logger.warning(
                    f"Auto-recovery: sqlcipher_export from {src!r} failed: "
                    f"{type(e).__name__}: {e}"
                )
                continue
            # Verify the rebuilt file independently.
            try:
                verify = sqlite3.connect(rebuilt_path, timeout=30.0)
                try:
                    if _USE_SQLCIPHER:
                        verify.execute(f"PRAGMA key = '{self.db_key}'")
                    row = verify.execute("PRAGMA integrity_check").fetchone()
                finally:
                    verify.close()
            except Exception as e:
                logger.warning(
                    f"Auto-recovery: integrity_check on rebuilt failed: "
                    f"{type(e).__name__}: {e}"
                )
                row = None
            if row and (row[0] or '').lower() == 'ok':
                chosen = src
                logger.warning(
                    f"Auto-recovery: rebuilt file verifies OK from source {src!r}"
                )
                break
            try:
                os.remove(rebuilt_path)
            except Exception:
                pass

        if chosen is None:
            logger.error("Auto-recovery: every candidate failed export+verify")
            return False

        # Atomic swap with sidecar cleanup. PID lock file is left alone — it
        # holds OUR pid and points to the same path, which we still own.
        try:
            if os.path.exists(self.db_path):
                corrupt_kept = self.db_path + f'.corrupt_{ts}'
                try:
                    os.rename(self.db_path, corrupt_kept)
                    logger.warning(
                        f"Auto-recovery: moved corrupt live DB to {corrupt_kept}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Auto-recovery: rename live to corrupt_kept failed: {e}"
                    )
            for suffix in ('-wal', '-shm'):
                sidecar = self.db_path + suffix
                if os.path.exists(sidecar):
                    try:
                        os.remove(sidecar)
                        logger.info(f"Auto-recovery: removed stale {sidecar}")
                    except Exception as e:
                        logger.warning(f"Auto-recovery: remove {sidecar} failed: {e}")
            os.rename(rebuilt_path, self.db_path)
        except Exception as e:
            logger.error(f"Auto-recovery: atomic swap failed: {e}", exc_info=True)
            return False

        # Reset thread-local + writer connection caches — every cached fd
        # belongs to the (now-renamed) corrupt file.
        try:
            self._tls = threading.local()
        except Exception:
            pass
        try:
            if self._writer_real_conn is not None:
                try:
                    self._writer_real_conn.close()
                except Exception:
                    pass
                self._writer_real_conn = None
        except Exception:
            pass

        logger.warning(
            f"Auto-recovery: live DB recovered from {chosen!r}; "
            f"corrupt original kept for forensics"
        )
        return True

    def run_write(self, fn, *args, **kwargs):
        """Submit a write callable to the serialized writer executor.

        REQUIRED entry point for any NEW write path. Returns a
        ``concurrent.futures.Future`` which callers can ``await`` via
        ``loop.run_in_executor``-style patterns or block on with
        ``.result()``.

        The callable runs on a single dedicated thread, against a single
        thread-local SQLCipher connection. Concurrent writers from other
        threads do NOT exist by construction, eliminating the SQLCipher
        page-cache race that has corrupted the production DB twice.

        Example::

            future = db.run_write(db.log_session_event,
                                  session_id, turn_n, actor, action_type, payload)
            log_id = future.result()

        Or in async code::

            loop = asyncio.get_event_loop()
            log_id = await loop.run_in_executor(
                None, lambda: db.run_write(db.log_session_event, ...).result()
            )
        """
        return self._writer_executor.submit(fn, *args, **kwargs)

    async def run_write_async(self, fn, *args, **kwargs):
        """Async helper that awaits a write submitted through `run_write`."""
        import asyncio
        future = self.run_write(fn, *args, **kwargs)
        # Wrap concurrent.futures.Future as an asyncio future bound to the
        # current loop so callers can ``await`` it naturally.
        return await asyncio.wrap_future(future)

    @_serialized_write
    def heartbeat_check(self) -> bool:
        """Round-trip the writer connection to prove the DB is responsive.

        Inserts (or replaces) one row in a tiny ``_heartbeat`` table, reads
        it back, then exercises a real production table to catch page-cache
        corruption that the 1-row heartbeat table can miss. Exercises the
        same code path as every real write (writer lock, keyed connection,
        commit), so a stuck writer or poisoned connection surfaces here
        long before users notice. Called every 60 s by
        ``TitanNetServer._db_heartbeat_loop`` — three consecutive failures
        (~3 minutes) trigger ``os._exit(1)``, and any single fatal cipher
        error short-circuits to immediate exit. systemd then restarts the
        process and auto-recovery rebuilds the file from a clean backup.

        The ``users`` page-cache canary was added 2026-05-06 after a six-
        hour incident where ``_heartbeat`` (which sits on its own page)
        stayed readable while every ``SELECT * FROM users`` returned
        ``MemoryError`` from SQLCipher's "deferred error condition". The
        old heartbeat probe missed it because the corruption hit pgno=84
        and the heartbeat row's page wasn't among the corrupt set.

        Cheap: a single UPSERT + two SELECTs on small tables. Sub-
        millisecond once the connection is warm.
        """
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS _heartbeat (id INTEGER PRIMARY KEY, ts TEXT NOT NULL)"
        )
        ts = datetime.now().isoformat()
        cur.execute(
            "INSERT INTO _heartbeat (id, ts) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET ts = excluded.ts",
            (ts,),
        )
        conn.commit()
        cur.execute("SELECT ts FROM _heartbeat WHERE id = 1")
        row = cur.fetchone()
        if not (row and row[0] == ts):
            return False
        # Page-cache canary on a real production table. Surfaces HMAC drift
        # and the SQLCipher deferred-error condition that the _heartbeat row
        # alone cannot detect (see overnight 2026-05-06 incident notes
        # above). Raises through the wrapper if reads are poisoned, and the
        # heartbeat watchdog suicides the process so auto-recovery runs.
        cur.execute("SELECT count(*) FROM users")
        cur.fetchone()
        return True

    PERIODIC_BACKUP_PREFIX = 'titannet_periodic_'

    @_serialized_write
    def create_periodic_backup(self, keep_last: int = 10) -> Optional[str]:
        """Export the live DB to a fresh encrypted backup via
        ``sqlcipher_export`` and trim old periodic backups to ``keep_last``
        newest. ``keep_last`` defaults to 10 to bound disk usage on the
        small VM (≈330 KB × 10 ≈ 3.3 MB).

        Why: ``update.py`` backups land at deploy time only. Users that
        registered or sent messages between deploys would be lost if HMAC
        drift forced a recovery from the latest deploy backup. A periodic
        in-process backup (every 5 min from
        ``TitanNetServer._periodic_backup_loop``) means the auto-recovery
        path always has a recent committed snapshot to fall back on —
        worst-case data loss is bounded by the backup interval, not by
        the deploy cadence.

        Periodic backups use the ``titannet_periodic_*.db`` prefix so this
        cleanup never touches the deploy-time ``titannet_*.db`` backups
        (those are rotated by ``update.py`` separately, also to 10 newest).
        Both prefixes still match the recovery candidate filter in
        ``_attempt_db_recovery`` / ``_recover_now.py``.

        How: opens a side connection (so it doesn't share the live
        connection's open transaction), keys it, ATTACHes a fresh tmp
        file, runs ``sqlcipher_export`` to copy every page through the
        cipher, DETACHes, then atomically renames the tmp into place.
        Decorated ``@_serialized_write`` so it never fights another
        writer; keyed side connection means it doesn't disturb the
        thread-local pool.
        """
        if not self.db_key:
            logger.warning("Periodic backup skipped: DATABASE_KEY missing")
            return None
        backup_dir = os.path.join(os.path.dirname(self.db_path) or '.', 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f'{self.PERIODIC_BACKUP_PREFIX}{ts}.db'
        backup_path = os.path.join(backup_dir, backup_name)
        tmp_path = backup_path + '.tmp'
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

        side_conn = None
        try:
            side_conn = sqlite3.connect(self.db_path, timeout=30.0)
            if _USE_SQLCIPHER:
                try:
                    side_conn.execute("PRAGMA cipher_memory_security = OFF")
                except Exception:
                    pass
                side_conn.execute(f"PRAGMA key = '{self.db_key}'")
                side_conn.execute("SELECT count(*) FROM sqlite_master")
            side_conn.execute(
                f"ATTACH DATABASE '{tmp_path}' AS bkp KEY '{self.db_key}'"
            )
            side_conn.execute("SELECT sqlcipher_export('bkp')")
            side_conn.execute("DETACH DATABASE bkp")
        except Exception as e:
            logger.error(f"Periodic backup export crashed: {e}")
            if side_conn is not None:
                try:
                    side_conn.close()
                except Exception:
                    pass
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            return None
        finally:
            if side_conn is not None:
                try:
                    side_conn.close()
                except Exception:
                    pass

        try:
            os.replace(tmp_path, backup_path)
        except Exception as e:
            logger.error(f"Periodic backup atomic rename failed: {e}")
            return None

        # Trim old PERIODIC backups by mtime newest-first. We only touch the
        # ``titannet_periodic_*.db`` set so the deploy-time ``titannet_*.db``
        # backups are left alone (update.py rotates those independently).
        try:
            entries = []
            for name in os.listdir(backup_dir):
                if 'corrupt' in name.lower():
                    continue
                if not name.startswith(self.PERIODIC_BACKUP_PREFIX) or not name.endswith('.db'):
                    continue
                full = os.path.join(backup_dir, name)
                if os.path.isfile(full):
                    try:
                        entries.append((os.path.getmtime(full), full))
                    except Exception:
                        pass
            entries.sort(reverse=True)
            for _, path in entries[keep_last:]:
                try:
                    os.remove(path)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Periodic backup cleanup failed: {e}")

        return backup_path

    def checkpoint_wal(self, mode: str = 'TRUNCATE'):
        """Merge -wal back into the main file. Call on graceful shutdown.

        Modes:
            PASSIVE  — non-blocking (default for periodic flushes)
            FULL     — block until done
            RESTART  — full + restart WAL
            TRUNCATE — full + restart + truncate WAL to zero (clean shutdown)
        """
        if mode not in ('PASSIVE', 'FULL', 'RESTART', 'TRUNCATE'):
            raise ValueError(f"Invalid wal_checkpoint mode: {mode}")
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            row = cur.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
            logger.info(f"WAL checkpoint ({mode}): busy={row[0]}, log={row[1]}, ckpt={row[2]}")
            return row
        except Exception as e:
            logger.error(f"WAL checkpoint failed: {e}")
            return None

    def _migrate_to_encrypted(self):
        """Migrate plain SQLite database to encrypted SQLCipher format (one-time)"""
        import os
        if not _USE_SQLCIPHER or not self.db_key:
            return
        if not os.path.exists(self.db_path):
            return

        # Check if database is already encrypted by trying to open without key
        try:
            import sqlite3 as plain_sqlite
            conn = plain_sqlite.connect(self.db_path)
            conn.execute("SELECT count(*) FROM sqlite_master")
            conn.close()
        except Exception:
            # Can't open without key = already encrypted
            return

        # Database is plain - encrypt it
        logger.info("Migrating plain database to encrypted format...")
        encrypted_path = self.db_path + ".encrypted"
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(f"ATTACH DATABASE '{encrypted_path}' AS encrypted KEY '{self.db_key}'")
            conn.execute("SELECT sqlcipher_export('encrypted')")
            conn.execute("DETACH DATABASE encrypted")
            conn.close()

            # Replace plain DB with encrypted one
            backup_path = self.db_path + ".plain_backup"
            os.rename(self.db_path, backup_path)
            os.rename(encrypted_path, self.db_path)
            logger.info("Database encrypted successfully (plain backup saved as .plain_backup)")
        except Exception as e:
            logger.error(f"Encryption migration failed: {e}")
            if os.path.exists(encrypted_path):
                os.remove(encrypted_path)

    def _open_keyed_connection(self):
        """Open a fresh SQLCipher connection, key it, and apply tuning PRAGMAs.

        PRAGMA values tuned for the production target: 50-100 concurrent
        users, mostly read-heavy with bursty writes (logins, status updates,
        feedback, game session logs).
        """
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=60.0)

        if _USE_SQLCIPHER and self.db_key:
            # cipher_memory_security = OFF disables SQLCipher 4's paranoid
            # memory zeroing of every page on release. Set BEFORE the key so
            # KDF benefits.
            try:
                conn.execute("PRAGMA cipher_memory_security = OFF")
            except Exception:
                pass
            conn.execute(f"PRAGMA key = '{self.db_key}'")
            # Force KDF now so key errors surface immediately.
            conn.execute("SELECT count(*) FROM sqlite_master")

        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        # 60s busy timeout is defense-in-depth; the singleton ``_writer_lock``
        # should make SQLite-level contention unreachable, but if a future
        # admin tool legitimately holds the file we want a long wait, not an
        # error.
        conn.execute("PRAGMA busy_timeout = 60000")
        # 4 MB per-connection page cache. Bumped from 2 MB so reader
        # connections under 50-100-user load keep hot pages without
        # constantly reaching for the OS page cache. Total worker-pool
        # memory: ~50 MB across reader connections + the writer.
        conn.execute("PRAGMA cache_size = -4000")
        conn.execute("PRAGMA temp_store = MEMORY")
        # 2000 pages (~8 MB) before SQLite tries to autocheckpoint at commit
        # time. Lower values made every commit attempt a checkpoint and
        # interleaved with concurrent readers — 8 MB lets writes accumulate
        # briefly while the periodic 5-minute TRUNCATE checkpoint
        # (TitanNetServer._wal_checkpoint_loop) keeps the file bounded.
        conn.execute("PRAGMA wal_autocheckpoint = 2000")
        # IMPORTANT: do NOT enable PRAGMA mmap_size on a SQLCipher database.
        # mmap reads bypass the cipher layer and hand encrypted bytes to
        # SQLite as if they were plaintext pages. Symptoms are immediate
        # and brutal: ``MemoryError`` and ``disk I/O error`` raised from
        # ``cursor.execute`` on every SELECT. Confirmed in production
        # 2026-05-03 — the deploy that turned mmap on bricked logins within
        # seconds even though ``PRAGMA integrity_check`` still reported
        # ``ok`` on the file (the file was fine; the live connection's
        # decrypted-page cache was nonsense).
        return conn

    def _get_writer_connection(self):
        """Return the SHARED writer connection (lazy-init under _writer_lock).

        Every ``@_serialized_write`` method runs against this single
        connection, regardless of which Python thread called the method.
        That keeps the SQLCipher decrypted-page cache coherent (one cache,
        one set of pages) so the HMAC drift that bit production three
        times in 2026-04 / 2026-05 cannot recur. The caller MUST be
        holding ``self._writer_lock`` — the connection is not thread-safe
        and we use Python-side serialization to enforce that.
        """
        if self._writer_real_conn is None:
            self._writer_real_conn = self._open_keyed_connection()
            logger.info("Writer connection opened (shared, RLock-serialized)")
        return self._writer_real_conn

    def get_connection(self):
        """Return a pooled thread-local database connection.

        The real connection is opened once per worker thread, the SQLCipher
        key is derived once, and performance PRAGMAs are applied once.
        Subsequent calls return a lightweight wrapper whose ``close()`` is a
        no-op, so existing ``conn = db.get_connection(); ...; conn.close()``
        call sites keep working without changes.

        Inside a ``@_serialized_write`` body the decorator overrides
        ``self._tls.conn`` to point at the shared writer connection, so
        ``get_connection()`` transparently returns it. Reads outside the
        decorator continue to get their own per-thread connection.
        """
        real = getattr(self._tls, 'conn', None)
        if real is not None:
            return _PooledConn(real)

        # First call on this thread: open + key + tune.
        conn = self._open_keyed_connection()

        self._tls.conn = conn
        return _PooledConn(conn)

    def close_all(self):
        """Close the pooled connection for the current thread (test/shutdown helper)."""
        real = getattr(self._tls, 'conn', None)
        if real is not None:
            try:
                real.close()
            except Exception:
                pass
            self._tls.conn = None

    def init_database(self):
        """Initialize database schema with error handling"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            # Test database accessibility
            cursor.execute("SELECT sqlite_version()")

            # Users table with roles
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    titan_number INTEGER UNIQUE NOT NULL,
                    full_name TEXT,
                    created_at TEXT NOT NULL,
                    last_login TEXT,
                    is_admin INTEGER DEFAULT 0,
                    role TEXT DEFAULT 'user',
                    blog_url TEXT,
                    status TEXT DEFAULT 'offline'
                )
            """)

            # Private messages table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS private_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                recipient_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                read INTEGER DEFAULT 0,
                FOREIGN KEY (sender_id) REFERENCES users(id),
                FOREIGN KEY (recipient_id) REFERENCES users(id)
            )
            """)

            # Chat rooms table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                creator_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                room_type TEXT DEFAULT 'text',
                password_hash TEXT,
                is_private INTEGER DEFAULT 0,
                FOREIGN KEY (creator_id) REFERENCES users(id)
            )
            """)

            # Room messages table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS room_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                FOREIGN KEY (room_id) REFERENCES chat_rooms(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """)

            # Room members table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS room_members (
                room_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TEXT NOT NULL,
                PRIMARY KEY (room_id, user_id),
                FOREIGN KEY (room_id) REFERENCES chat_rooms(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """)

            # Application repository table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_repository (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                category TEXT NOT NULL,
                version TEXT,
                author_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER,
                uploaded_at TEXT NOT NULL,
                approved INTEGER DEFAULT 0,
                approved_by INTEGER,
                approved_at TEXT,
                downloads INTEGER DEFAULT 0,
                metadata TEXT,
                FOREIGN KEY (author_id) REFERENCES users(id),
                FOREIGN KEY (approved_by) REFERENCES users(id)
            )
            """)

            # Sessions table for WebSocket connections
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                connected_at TEXT NOT NULL,
                last_activity TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """)

            # Forum topics table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS forum_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                author_id INTEGER NOT NULL,
                category TEXT DEFAULT 'general',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                is_pinned INTEGER DEFAULT 0,
                is_locked INTEGER DEFAULT 0,
                views INTEGER DEFAULT 0,
                FOREIGN KEY (author_id) REFERENCES users(id)
            )
            """)

            # Forum replies table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS forum_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                edited_at TEXT,
                FOREIGN KEY (topic_id) REFERENCES forum_topics(id),
                FOREIGN KEY (author_id) REFERENCES users(id)
            )
            """)

            # Room bans table (extended with ban types)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS room_bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                banned_by INTEGER NOT NULL,
                banned_at TEXT NOT NULL,
                expires_at TEXT,
                ban_type TEXT DEFAULT 'permanent',
                reason TEXT,
                ip_address TEXT,
                UNIQUE(room_id, user_id),
                FOREIGN KEY (room_id) REFERENCES chat_rooms(id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (banned_by) REFERENCES users(id)
            )
            """)

            # Moderators table (for custom titles)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS moderators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                title TEXT,
                appointed_by INTEGER NOT NULL,
                appointed_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (appointed_by) REFERENCES users(id)
            )
            """)

            # Global bans table (server-wide bans)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS global_bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                banned_by INTEGER NOT NULL,
                banned_at TEXT NOT NULL,
                expires_at TEXT,
                ban_type TEXT DEFAULT 'permanent',
                reason TEXT,
                ip_address TEXT,
                hardware_id TEXT,
                UNIQUE(user_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (banned_by) REFERENCES users(id)
            )
            """)

            # IP/Hardware bans table (for hard bans)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS ip_hardware_bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT,
                hardware_id TEXT,
                banned_by INTEGER NOT NULL,
                banned_at TEXT NOT NULL,
                reason TEXT,
                FOREIGN KEY (banned_by) REFERENCES users(id)
            )
            """)

            # Forum bans table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS forum_bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                banned_by INTEGER NOT NULL,
                banned_at TEXT NOT NULL,
                expires_at TEXT,
                ban_type TEXT DEFAULT 'permanent',
                reason TEXT,
                UNIQUE(user_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (banned_by) REFERENCES users(id)
            )
            """)

            # Migration: Add role column if it doesn't exist
            try:
                cursor.execute("SELECT role FROM users LIMIT 1")
            except sqlite3.OperationalError:
                # Column doesn't exist, add it
                cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
                print("Migration: Added 'role' column to users table")

            # Migration: Add ban type columns to room_bans if they don't exist
            try:
                cursor.execute("SELECT expires_at FROM room_bans LIMIT 1")
            except sqlite3.OperationalError:
                cursor.execute("ALTER TABLE room_bans ADD COLUMN expires_at TEXT")
                print("Migration: Added 'expires_at' column to room_bans table")

            try:
                cursor.execute("SELECT ban_type FROM room_bans LIMIT 1")
            except sqlite3.OperationalError:
                cursor.execute("ALTER TABLE room_bans ADD COLUMN ban_type TEXT DEFAULT 'permanent'")
                print("Migration: Added 'ban_type' column to room_bans table")

            try:
                cursor.execute("SELECT ip_address FROM room_bans LIMIT 1")
            except sqlite3.OperationalError:
                cursor.execute("ALTER TABLE room_bans ADD COLUMN ip_address TEXT")
                print("Migration: Added 'ip_address' column to room_bans table")

            # Migration: Add hardware_id column to global_bans if it doesn't exist
            try:
                cursor.execute("SELECT hardware_id FROM global_bans LIMIT 1")
            except sqlite3.OperationalError:
                cursor.execute("ALTER TABLE global_bans ADD COLUMN hardware_id TEXT")
                print("Migration: Added 'hardware_id' column to global_bans table")

            # Forum read status table - tracks which topics user has read
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS forum_read_status (
                user_id INTEGER NOT NULL,
                topic_id INTEGER NOT NULL,
                last_read_at TEXT NOT NULL,
                last_known_reply_count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, topic_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (topic_id) REFERENCES forum_topics(id)
            )
            """)

            # OAuth: encrypted external-provider tokens (Spotify, Allegro, ...)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                user_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                access_token_enc TEXT NOT NULL,
                refresh_token_enc TEXT,
                expires_at TEXT,
                scope TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, provider),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """)

            # OAuth: short-lived CSRF state values for the authorize -> callback hop
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """)

            # Create indexes for performance optimization
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_titan_number ON users(titan_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_private_messages_sender ON private_messages(sender_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_private_messages_recipient ON private_messages(recipient_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_room_members_room ON room_members(room_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_room_members_user ON room_members(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_room_messages_room ON room_messages(room_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_forum_topics_category ON forum_topics(category)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_forum_replies_topic ON forum_replies(topic_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_room_bans_room_user ON room_bans(room_id, user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_global_bans_user ON global_bans(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_forum_bans_user ON forum_bans(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_forum_read_status_user_topic ON forum_read_status(user_id, topic_id)")

            # Additional performance indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_private_messages_recipient_read ON private_messages(recipient_id, read)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_private_messages_sent_at ON private_messages(sent_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_room_messages_room_sent ON room_messages(room_id, sent_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_forum_topics_updated ON forum_topics(updated_at DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_forum_topics_pinned_updated ON forum_topics(is_pinned DESC, updated_at DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_app_repository_approved ON app_repository(approved, approved_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_oauth_states_created ON oauth_states(created_at)")

            # Feedback Hub: ideas and feedback items submitted by users
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                author_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                attachment_path TEXT,
                attachment_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (author_id) REFERENCES users(id)
            )
            """)

            # Feedback Hub: upvotes (one per user per item, author cannot upvote own item)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback_upvotes (
                feedback_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (feedback_id, user_id),
                FOREIGN KEY (feedback_id) REFERENCES feedback_items(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_items_type ON feedback_items(item_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_items_status ON feedback_items(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_items_author ON feedback_items(author_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_items_updated ON feedback_items(updated_at DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_upvotes_feedback ON feedback_upvotes(feedback_id)")

            # =========================================================
            # Interactive Games (Entertainment tab)
            # =========================================================
            # Game catalog: each row is a published game with creator,
            # provider (gemini/openai/anthropic), Fernet-encrypted API
            # key, and per-session resource caps (token + minute budget).
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS interactive_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                provider TEXT NOT NULL DEFAULT 'gemini',
                api_key_enc TEXT NOT NULL,
                max_tokens INTEGER NOT NULL DEFAULT 200000,
                max_minutes INTEGER NOT NULL DEFAULT 60,
                max_players INTEGER NOT NULL DEFAULT 6,
                rules_text TEXT,
                npc_voices_json TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (creator_id) REFERENCES users(id)
            )
            """)

            # Game attachments: rules zip, prompt txt, sound effects.
            # Stored encrypted on disk under interactive_games/<creator>/<game_id>/.
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS game_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL,
                attachment_type TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                mime_type TEXT,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (game_id) REFERENCES interactive_games(id) ON DELETE CASCADE
            )
            """)

            # Game sessions: a running multiplayer game instance.
            # state_json holds AI-managed schemaless game state.
            # turn_order_json is a list of user_ids in turn rotation.
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS game_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL,
                host_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'lobby',
                state_json TEXT NOT NULL DEFAULT '{}',
                turn_order_json TEXT NOT NULL DEFAULT '[]',
                current_turn_idx INTEGER NOT NULL DEFAULT 0,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                FOREIGN KEY (game_id) REFERENCES interactive_games(id) ON DELETE CASCADE,
                FOREIGN KEY (host_id) REFERENCES users(id)
            )
            """)

            # Players in a session, with their character_state_json blob.
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS game_session_players (
                session_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                character_state_json TEXT NOT NULL DEFAULT '{}',
                joined_at TEXT NOT NULL,
                left_at TEXT,
                PRIMARY KEY (session_id, user_id),
                FOREIGN KEY (session_id) REFERENCES game_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """)

            # Audit log of every AI tool call / player action / sound event.
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS game_session_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                turn_n INTEGER NOT NULL DEFAULT 0,
                actor TEXT NOT NULL,
                action_type TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES game_sessions(id) ON DELETE CASCADE
            )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactive_games_creator ON interactive_games(creator_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactive_games_status ON interactive_games(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactive_games_updated ON interactive_games(updated_at DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_game_attachments_game ON game_attachments(game_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_game_sessions_game ON game_sessions(game_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_game_sessions_status ON game_sessions(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_game_session_players_user ON game_session_players(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_game_session_log_session ON game_session_log(session_id, id)")

            conn.commit()
            conn.close()

            # Log successful initialization
            import logging
            logger = logging.getLogger('TitanNetDB')
            logger.info("Database initialized successfully with performance indexes")

        except sqlite3.Error as e:
            import logging
            logger = logging.getLogger('TitanNetDB')
            logger.error(f"Database initialization failed: {e}")
            raise RuntimeError(f"Failed to initialize database: {e}")

    def generate_unique_titan_number(self) -> int:
        """Generate unique 5-digit Titan number - optimized: fetch all used numbers once"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT titan_number FROM users")
        used_numbers = {row['titan_number'] for row in cursor.fetchall()}
        conn.close()

        # Generate random number not in used set
        available = set(range(10000, 100000)) - used_numbers
        if not available:
            raise ValueError("Could not generate unique Titan number")
        return random.choice(list(available))

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a plaintext password with Argon2id.

        Returns a self-describing PHC string of the form
        ``$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>``. The string carries
        the algorithm identifier and parameters, so a future parameter bump
        does not require a schema change.
        """
        return _PASSWORD_HASHER.hash(password)

    @staticmethod
    def _legacy_sha256(password: str) -> str:
        """Reproduce the historical unsalted SHA-256 hash for verification."""
        return hashlib.sha256(password.encode()).hexdigest()

    @staticmethod
    def verify_password(password: str, stored_hash: str) -> Tuple[bool, bool]:
        """Verify ``password`` against ``stored_hash``.

        Returns a tuple ``(ok, needs_rehash)``:

        * ``ok``           - the password matches the stored hash.
        * ``needs_rehash`` - the caller should re-hash and persist a new
                             value (legacy SHA-256 hashes always set this;
                             argon2id sets it only when stored parameters
                             are weaker than the current PasswordHasher).

        Two stored formats are recognized transparently:

        * ``$argon2...`` PHC strings (current format).
        * 64-character hex digest (legacy unsalted SHA-256).

        Anything else returns ``(False, False)`` instead of raising, so a
        corrupt row can never crash an auth path.
        """
        if not stored_hash:
            return False, False

        if stored_hash.startswith("$argon2"):
            try:
                _PASSWORD_HASHER.verify(stored_hash, password)
            except VerifyMismatchError:
                return False, False
            except (VerificationError, InvalidHash):
                return False, False
            try:
                needs_rehash = _PASSWORD_HASHER.check_needs_rehash(stored_hash)
            except Exception:
                needs_rehash = False
            return True, bool(needs_rehash)

        # Legacy path: 64-char unsalted SHA-256 hex. Constant-time compare
        # with secrets.compare_digest so a slow re-hash never reveals the
        # length of the stored value via timing.
        if len(stored_hash) == 64:
            try:
                ok = secrets.compare_digest(
                    Database._legacy_sha256(password),
                    stored_hash,
                )
            except Exception:
                ok = False
            # Every successful legacy verify must be re-hashed to argon2id
            # by the caller - that is the lazy migration path.
            return ok, ok

        return False, False

    @_serialized_write
    def create_user(self, username: str, password: str, full_name: Optional[str] = None,
                    ip_address: Optional[str] = None, hardware_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Create new user account
        Checks for hard bans (IP/hardware) before allowing registration
        """
        # Check if IP or hardware ID is hard banned
        if ip_address or hardware_id:
            if self.is_ip_hardware_banned(ip_address, hardware_id):
                return {
                    "success": False,
                    "error": "Account creation blocked - banned IP or device"
                }

        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            titan_number = self.generate_unique_titan_number()
            password_hash = self.hash_password(password)
            created_at = datetime.now().isoformat()

            cursor.execute("""
                INSERT INTO users (username, password_hash, titan_number, full_name, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (username, password_hash, titan_number, full_name, created_at))

            user_id = cursor.lastrowid
            conn.commit()

            return {
                "success": True,
                "user_id": user_id,
                "username": username,
                "titan_number": titan_number,
                "created_at": created_at
            }
        except sqlite3.IntegrityError as e:
            conn.rollback()
            return {
                "success": False,
                "error": "Username already exists"
            }
        finally:
            conn.close()

    @_serialized_write
    def change_user_password(self, username: str, new_password: str) -> Dict[str, Any]:
        """Replace the password hash for ``username`` with a fresh argon2id hash.

        Admin-only path — callers must enforce role checks. There is no
        ``old_password`` check on purpose: this is the recovery / forced-reset
        primitive used by the moderation API. For self-service password
        changes a caller should verify the current password first.
        """
        if not username or not new_password:
            return {"success": False, "error": "Username and new_password required"}
        if len(new_password) < 8:
            return {"success": False, "error": "Password must be at least 8 characters"}

        new_hash = self.hash_password(new_password)
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "User not found"}
            user_id = row['id']
            cursor.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (new_hash, user_id),
            )
            conn.commit()
            return {"success": True, "user_id": user_id, "username": username}
        except Exception as e:
            conn.rollback()
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    @_serialized_write
    def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate user and return user data.

        On a successful login whose stored hash needs upgrading (legacy
        SHA-256, or argon2id with outdated parameters) the row is rehashed
        to a fresh argon2id PHC string in the same transaction - this is
        the lazy migration path for the SHA-256 -> Argon2id transition.
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, username, password_hash, titan_number, full_name, is_admin, blog_url, role
            FROM users WHERE username = ?
        """, (username,))

        user = cursor.fetchone()

        if not user:
            conn.close()
            return None

        # Hard-ban gate: block login before burning argon2 hash time.
        cursor.execute(
            "SELECT id FROM global_bans WHERE user_id = ? AND ban_type = 'hard'",
            (user['id'],)
        )
        if cursor.fetchone():
            logger.warning(
                "[Titan-Net] Hard-banned user %s (%s) attempted login — blocked",
                user['id'], username,
            )
            conn.close()
            return None

        ok, needs_rehash = self.verify_password(password, user['password_hash'])
        if not ok:
            conn.close()
            return None

        # Update last login (and rehash atomically with the same commit).
        cursor.execute("""
            UPDATE users SET last_login = ?, status = 'online'
            WHERE id = ?
        """, (datetime.now().isoformat(), user['id']))

        if needs_rehash:
            try:
                new_hash = self.hash_password(password)
                cursor.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (new_hash, user['id']),
                )
                logger.info(
                    "[Titan-Net] migrated user %s password hash to argon2id",
                    user['id'],
                )
            except Exception as exc:
                # Migration is best-effort: the user is already authenticated.
                # Log and let them in - we will retry on the next login.
                logger.warning(
                    "[Titan-Net] password rehash failed for user %s: %s",
                    user['id'], exc,
                )

        conn.commit()
        conn.close()
        return {
            "id": user['id'],
            "username": user['username'],
            "titan_number": user['titan_number'],
            "full_name": user['full_name'],
            "is_admin": bool(user['is_admin']),
            "blog_url": user['blog_url'],
            "role": user['role'] or 'user'
        }

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, username, titan_number, full_name, is_admin, blog_url, status
            FROM users WHERE id = ?
        """, (user_id,))

        user = cursor.fetchone()
        conn.close()

        if user:
            return dict(user)
        return None

    def get_user_by_titan_number(self, titan_number: int) -> Optional[Dict[str, Any]]:
        """Get user by Titan number"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, username, titan_number, full_name, is_admin, blog_url, status
            FROM users WHERE titan_number = ?
        """, (titan_number,))

        user = cursor.fetchone()
        conn.close()

        if user:
            return dict(user)
        return None

    @_serialized_write
    def update_user_status(self, user_id: int, status: str):
        """Update user online status"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
        conn.commit()
        conn.close()

    @_serialized_write
    def reset_all_online_users(self) -> int:
        """Force every user offline and clear room memberships.

        Called at server startup so a previously crashed / SIGKILLed
        process can't leave stale 'online' statuses or stuck room
        memberships behind. Returns the number of rows updated to offline.
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET status = 'offline' WHERE status = 'online'")
        affected = cursor.rowcount
        cursor.execute("DELETE FROM room_members")
        conn.commit()
        conn.close()
        return affected

    @_serialized_write
    def delete_user_room_memberships(self, user_id: int) -> List[int]:
        """Remove a user from every chat room and return the list of affected room IDs.

        Replaces the inline ``DELETE FROM room_members`` that used to live in
        ``server.py:unregister_client`` outside the writer lock. That call ran
        from the asyncio event loop thread and raced against the rest of the
        write pool, surfacing as ``Error removing user X from rooms on
        disconnect: database is locked`` in production logs. Funneling it
        through ``@_serialized_write`` eliminates the race.
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT room_id FROM room_members WHERE user_id = ?", (user_id,))
        room_ids = [row['room_id'] for row in cursor.fetchall()]
        cursor.execute("DELETE FROM room_members WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return room_ids

    def get_online_users(self) -> List[Dict[str, Any]]:
        """Get list of online users"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, username, titan_number, full_name, status
            FROM users WHERE status = 'online'
        """)

        users = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return users

    @_serialized_write
    def send_private_message(self, sender_id: int, recipient_id: int, message: str) -> Dict[str, Any]:
        """Send private message"""
        conn = self.get_connection()
        cursor = conn.cursor()

        sent_at = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO private_messages (sender_id, recipient_id, message, sent_at)
            VALUES (?, ?, ?, ?)
        """, (sender_id, recipient_id, message, sent_at))

        message_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return {
            "id": message_id,
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "message": message,
            "sent_at": sent_at
        }

    def get_private_messages(self, user1_id: int, user2_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Get private messages between two users"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT pm.*,
                   u1.username as sender_username,
                   u2.username as recipient_username
            FROM private_messages pm
            JOIN users u1 ON pm.sender_id = u1.id
            JOIN users u2 ON pm.recipient_id = u2.id
            WHERE (pm.sender_id = ? AND pm.recipient_id = ?)
               OR (pm.sender_id = ? AND pm.recipient_id = ?)
            ORDER BY pm.sent_at DESC
            LIMIT ?
        """, (user1_id, user2_id, user2_id, user1_id, limit))

        messages = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return messages

    def get_unread_private_messages_summary(self, user_id: int) -> List[Dict[str, Any]]:
        """Get summary of unread private messages grouped by sender"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT u.username as sender_username,
                   COUNT(*) as unread_count
            FROM private_messages pm
            JOIN users u ON pm.sender_id = u.id
            WHERE pm.recipient_id = ? AND pm.read = 0
            GROUP BY pm.sender_id, u.username
            ORDER BY MAX(pm.sent_at) DESC
        """, (user_id,))

        summary = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return summary

    @_serialized_write
    def mark_private_messages_as_read(self, recipient_id: int, sender_id: int) -> bool:
        """Mark all unread private messages from sender to recipient as read"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE private_messages
                SET read = 1
                WHERE recipient_id = ? AND sender_id = ? AND read = 0
            """, (recipient_id, sender_id))

            conn.commit()
            affected_rows = cursor.rowcount
            conn.close()
            return affected_rows > 0
        except Exception as e:
            conn.close()
            return False

    @_serialized_write
    def create_chat_room(self, name: str, creator_id: int, description: str = "",
                        room_type: str = "text", password: Optional[str] = None) -> Dict[str, Any]:
        """Create new chat room"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            created_at = datetime.now().isoformat()
            password_hash = self.hash_password(password) if password else None
            is_private = 1 if password else 0

            cursor.execute("""
                INSERT INTO chat_rooms (name, description, creator_id, created_at, room_type, password_hash, is_private)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, description, creator_id, created_at, room_type, password_hash, is_private))

            room_id = cursor.lastrowid

            # Add creator as member
            cursor.execute("""
                INSERT INTO room_members (room_id, user_id, joined_at)
                VALUES (?, ?, ?)
            """, (room_id, creator_id, created_at))

            conn.commit()
            conn.close()

            return {
                "success": True,
                "room_id": room_id,
                "name": name,
                "room_type": room_type
            }
        except sqlite3.IntegrityError:
            conn.rollback()
            conn.close()
            return {
                "success": False,
                "error": "Room name already exists"
            }

    @_serialized_write
    def join_chat_room(self, room_id: int, user_id: int, password: Optional[str] = None) -> Dict[str, Any]:
        """Join chat room"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Check if user is banned
        cursor.execute("SELECT id FROM room_bans WHERE room_id = ? AND user_id = ?", (room_id, user_id))
        if cursor.fetchone():
            conn.close()
            return {"success": False, "error": "You are banned from this room"}

        # Check if room exists and get password hash
        cursor.execute("SELECT password_hash FROM chat_rooms WHERE id = ?", (room_id,))
        room = cursor.fetchone()

        if not room:
            conn.close()
            return {"success": False, "error": "Room not found"}

        # Verify password if room is private. Lazy migration: a legacy
        # SHA-256 room hash that verifies correctly is rewritten as
        # argon2id in place, same approach as authenticate_user above.
        if room['password_hash']:
            if not password:
                conn.close()
                return {"success": False, "error": "Invalid password"}
            ok, needs_rehash = self.verify_password(password, room['password_hash'])
            if not ok:
                conn.close()
                return {"success": False, "error": "Invalid password"}
            if needs_rehash:
                try:
                    new_hash = self.hash_password(password)
                    cursor.execute(
                        "UPDATE chat_rooms SET password_hash = ? WHERE id = ?",
                        (new_hash, room_id),
                    )
                    logger.info(
                        "[Titan-Net] migrated chat_room %s password hash to argon2id",
                        room_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "[Titan-Net] room password rehash failed for room %s: %s",
                        room_id, exc,
                    )

        try:
            joined_at = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO room_members (room_id, user_id, joined_at)
                VALUES (?, ?, ?)
            """, (room_id, user_id, joined_at))
            conn.commit()
            conn.close()
            return {"success": True}
        except sqlite3.IntegrityError:
            conn.close()
            return {"success": False, "error": "Already a member"}

    @_serialized_write
    def leave_chat_room(self, room_id: int, user_id: int):
        """Leave chat room"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM room_members WHERE room_id = ? AND user_id = ?", (room_id, user_id))
        conn.commit()
        conn.close()

    @_serialized_write
    def delete_chat_room(self, room_id: int, user_id: int) -> bool:
        """Delete chat room (only by creator)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Check if user is creator
        cursor.execute("SELECT creator_id FROM chat_rooms WHERE id = ?", (room_id,))
        room = cursor.fetchone()

        if not room or room['creator_id'] != user_id:
            conn.close()
            return False

        # Delete room and all related data
        cursor.execute("DELETE FROM room_messages WHERE room_id = ?", (room_id,))
        cursor.execute("DELETE FROM room_members WHERE room_id = ?", (room_id,))
        cursor.execute("DELETE FROM chat_rooms WHERE id = ?", (room_id,))

        conn.commit()
        conn.close()
        return True

    @_serialized_write
    def send_room_message(self, room_id: int, user_id: int, message: str) -> Dict[str, Any]:
        """Send message to chat room"""
        conn = self.get_connection()
        cursor = conn.cursor()

        sent_at = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO room_messages (room_id, user_id, message, sent_at)
            VALUES (?, ?, ?, ?)
        """, (room_id, user_id, message, sent_at))

        message_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return {
            "id": message_id,
            "room_id": room_id,
            "user_id": user_id,
            "message": message,
            "sent_at": sent_at
        }

    def get_room_messages(self, room_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Get messages from chat room"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT rm.*, u.username, u.titan_number
            FROM room_messages rm
            JOIN users u ON rm.user_id = u.id
            WHERE rm.room_id = ?
            ORDER BY rm.sent_at DESC
            LIMIT ?
        """, (room_id, limit))

        messages = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return messages

    def get_available_rooms(self) -> List[Dict[str, Any]]:
        """Get list of all chat rooms - optimized with GROUP BY instead of correlated subquery"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT cr.*, u.username as creator_username,
                   COALESCE(COUNT(rm.user_id), 0) as member_count
            FROM chat_rooms cr
            JOIN users u ON cr.creator_id = u.id
            LEFT JOIN room_members rm ON rm.room_id = cr.id
            GROUP BY cr.id
        """)

        rooms = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rooms

    def get_room_by_id(self, room_id: int) -> Optional[Dict[str, Any]]:
        """Get room information by ID"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT cr.*, u.username as creator_username
            FROM chat_rooms cr
            JOIN users u ON cr.creator_id = u.id
            WHERE cr.id = ?
        """, (room_id,))

        room = cursor.fetchone()
        conn.close()
        return dict(room) if room else None

    def is_user_in_room(self, room_id: int, user_id: int) -> bool:
        """Check if user is a member of the room"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 1 FROM room_members
            WHERE room_id = ? AND user_id = ?
        """, (room_id, user_id))

        result = cursor.fetchone() is not None
        conn.close()
        return result

    @_serialized_write
    def add_app_to_repository(self, name: str, description: str, category: str,
                             version: str, author_id: int, file_path: str,
                             file_size: int, metadata: Dict[str, Any]) -> int:
        """Add application to repository (pending approval)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        uploaded_at = datetime.now().isoformat()
        metadata_json = json.dumps(metadata)

        cursor.execute("""
            INSERT INTO app_repository
            (name, description, category, version, author_id, file_path, file_size, uploaded_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, description, category, version, author_id, file_path, file_size, uploaded_at, metadata_json))

        app_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return app_id

    @_serialized_write
    def approve_app(self, app_id: int, admin_id: int) -> bool:
        """Approve application in repository (moderator/developer only)"""
        # Check if user is moderator or developer
        if not self.is_moderator(admin_id):
            return False

        conn = self.get_connection()
        cursor = conn.cursor()

        approved_at = datetime.now().isoformat()
        cursor.execute("""
            UPDATE app_repository
            SET approved = 1, approved_by = ?, approved_at = ?
            WHERE id = ?
        """, (admin_id, approved_at, app_id))

        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success

    @_serialized_write
    def set_user_role(self, user_id: int, role: str) -> bool:
        """Set a user's ``role`` column. Routes through the writer lock so
        it does not race the rest of the write pool.

        SECURITY: this is a privileged primitive. It MUST only be called
        from authorization-checked code paths (e.g. promote/demote handlers
        guarded by ``is_developer``). It must NEVER be exposed to a route
        that lets a caller pick their own role — doing so re-creates the
        privilege-escalation hole that the removed
        ``/api/users/set_developer`` endpoint had."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success

    @_serialized_write
    def delete_app_from_repository(self, app_id: int) -> bool:
        """Remove an app row from ``app_repository`` (the file move is the
        caller's responsibility). Replaces the bare ``cursor.execute('DELETE
        FROM app_repository ...')`` previously running outside the writer
        lock in ``http_server.handle_delete``."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM app_repository WHERE id = ?", (app_id,))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success

    def get_pending_apps(self) -> List[Dict[str, Any]]:
        """Get apps pending approval"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT ar.*, u.username as author_username
            FROM app_repository ar
            JOIN users u ON ar.author_id = u.id
            WHERE ar.approved = 0
            ORDER BY ar.uploaded_at DESC
        """)

        apps = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return apps

    def get_approved_apps(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get approved apps from repository"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if category:
            cursor.execute("""
                SELECT ar.*, u.username as author_username
                FROM app_repository ar
                JOIN users u ON ar.author_id = u.id
                WHERE ar.approved = 1 AND ar.category = ?
                ORDER BY ar.uploaded_at DESC
            """, (category,))
        else:
            cursor.execute("""
                SELECT ar.*, u.username as author_username
                FROM app_repository ar
                JOIN users u ON ar.author_id = u.id
                WHERE ar.approved = 1
                ORDER BY ar.uploaded_at DESC
            """)

        apps = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return apps

    @_serialized_write
    def increment_app_downloads(self, app_id: int):
        """Increment download counter"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE app_repository SET downloads = downloads + 1 WHERE id = ?", (app_id,))
        conn.commit()
        conn.close()

    @_serialized_write
    def update_user_blog(self, user_id: int, blog_url: str):
        """Update user blog URL"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET blog_url = ? WHERE id = ?", (blog_url, user_id))
        conn.commit()
        conn.close()

    # Forum Methods

    @_serialized_write
    def create_forum_topic(self, title: str, content: str, author_id: int, category: str = 'general') -> Dict[str, Any]:
        """Create new forum topic"""
        conn = self.get_connection()
        cursor = conn.cursor()

        created_at = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO forum_topics (title, content, author_id, category, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (title, content, author_id, category, created_at, created_at))

        topic_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return {
            "success": True,
            "topic_id": topic_id,
            "title": title,
            "created_at": created_at
        }

    def get_forum_topics(self, category: Optional[str] = None, limit: int = 50, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get forum topics - optimized with LEFT JOIN and new replies detection"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if category and category != 'all':
            cursor.execute("""
                SELECT ft.*, u.username as author_username, u.titan_number as author_titan_number,
                       COALESCE(COUNT(fr.id), 0) as reply_count,
                       COALESCE(frs.last_known_reply_count, 0) as last_known_reply_count
                FROM forum_topics ft
                JOIN users u ON ft.author_id = u.id
                LEFT JOIN forum_replies fr ON fr.topic_id = ft.id
                LEFT JOIN forum_read_status frs ON frs.topic_id = ft.id AND frs.user_id = ?
                WHERE ft.category = ?
                GROUP BY ft.id
                ORDER BY ft.is_pinned DESC, ft.updated_at DESC
                LIMIT ?
            """, (user_id, category, limit))
        else:
            cursor.execute("""
                SELECT ft.*, u.username as author_username, u.titan_number as author_titan_number,
                       COALESCE(COUNT(fr.id), 0) as reply_count,
                       COALESCE(frs.last_known_reply_count, 0) as last_known_reply_count
                FROM forum_topics ft
                JOIN users u ON ft.author_id = u.id
                LEFT JOIN forum_replies fr ON fr.topic_id = ft.id
                LEFT JOIN forum_read_status frs ON frs.topic_id = ft.id AND frs.user_id = ?
                GROUP BY ft.id
                ORDER BY ft.is_pinned DESC, ft.updated_at DESC
                LIMIT ?
            """, (user_id, limit))

        topics = []
        for row in cursor.fetchall():
            topic = dict(row)
            # Check if there are new replies since last read
            if user_id:
                topic['has_new_replies'] = topic['reply_count'] > topic['last_known_reply_count']
            else:
                topic['has_new_replies'] = False
            topics.append(topic)

        conn.close()
        return topics

    @_serialized_write
    def get_forum_topic(self, topic_id: int) -> Optional[Dict[str, Any]]:
        """Get single forum topic with details - optimized"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT ft.*, u.username as author_username, u.titan_number as author_titan_number,
                   COALESCE(COUNT(fr.id), 0) as reply_count
            FROM forum_topics ft
            JOIN users u ON ft.author_id = u.id
            LEFT JOIN forum_replies fr ON fr.topic_id = ft.id
            WHERE ft.id = ?
            GROUP BY ft.id
        """, (topic_id,))

        topic = cursor.fetchone()

        # Increment view count
        if topic:
            cursor.execute("UPDATE forum_topics SET views = views + 1 WHERE id = ?", (topic_id,))
            conn.commit()

        conn.close()

        if topic:
            return dict(topic)
        return None

    def get_user_topics(self, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Get topics created by specific user - optimized"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT ft.*, u.username as author_username, u.titan_number as author_titan_number,
                   COALESCE(COUNT(fr.id), 0) as reply_count
            FROM forum_topics ft
            JOIN users u ON ft.author_id = u.id
            LEFT JOIN forum_replies fr ON fr.topic_id = ft.id
            WHERE ft.author_id = ?
            GROUP BY ft.id
            ORDER BY ft.created_at DESC
            LIMIT ?
        """, (user_id, limit))

        topics = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return topics

    @_serialized_write
    def add_forum_reply(self, topic_id: int, author_id: int, content: str) -> Dict[str, Any]:
        """Add reply to forum topic"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Check if topic exists and is not locked
        cursor.execute("SELECT is_locked FROM forum_topics WHERE id = ?", (topic_id,))
        topic = cursor.fetchone()

        if not topic:
            conn.close()
            return {"success": False, "error": "Topic not found"}

        if topic['is_locked']:
            conn.close()
            return {"success": False, "error": "Topic is locked"}

        created_at = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO forum_replies (topic_id, author_id, content, created_at)
            VALUES (?, ?, ?, ?)
        """, (topic_id, author_id, content, created_at))

        reply_id = cursor.lastrowid

        # Update topic's updated_at timestamp
        cursor.execute("UPDATE forum_topics SET updated_at = ? WHERE id = ?", (created_at, topic_id))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "reply_id": reply_id,
            "created_at": created_at
        }

    def get_forum_replies(self, topic_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Get replies for a topic"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT fr.*, u.username as author_username, u.titan_number as author_titan_number
            FROM forum_replies fr
            JOIN users u ON fr.author_id = u.id
            WHERE fr.topic_id = ?
            ORDER BY fr.created_at ASC
            LIMIT ?
        """, (topic_id, limit))

        replies = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return replies

    @_serialized_write
    def mark_topic_as_read(self, user_id: int, topic_id: int, reply_count: int) -> bool:
        """Mark forum topic as read by user with current reply count"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            read_at = datetime.now().isoformat()
            cursor.execute("""
                INSERT OR REPLACE INTO forum_read_status
                (user_id, topic_id, last_read_at, last_known_reply_count)
                VALUES (?, ?, ?, ?)
            """, (user_id, topic_id, read_at, reply_count))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error marking topic as read: {e}")
            conn.close()
            return False

    def get_whats_new(self, user_id: int) -> Dict[str, Any]:
        """Get what's new with detailed items for each category."""
        conn = self.get_connection()
        cursor = conn.cursor()

        result = {}

        # Unread private messages - grouped by sender
        cursor.execute("""
            SELECT pm.sender_id, u.username, COUNT(*) as count, MAX(pm.sent_at) as last_at
            FROM private_messages pm
            JOIN users u ON u.id = pm.sender_id
            WHERE pm.recipient_id = ? AND pm.read = 0
            GROUP BY pm.sender_id
            ORDER BY last_at DESC
        """, (user_id,))
        messages = [{'sender_id': r['sender_id'], 'sender': r['username'], 'count': r['count']} for r in cursor.fetchall()]
        result['unread_messages'] = sum(m['count'] for m in messages)
        result['unread_messages_items'] = messages

        # Forum topics with new replies - with topic titles
        cursor.execute("""
            SELECT ft.id, ft.title, COUNT(fr.id) - frs.last_known_reply_count as new_replies
            FROM forum_read_status frs
            JOIN forum_topics ft ON ft.id = frs.topic_id
            LEFT JOIN forum_replies fr ON fr.topic_id = ft.id
            WHERE frs.user_id = ?
            GROUP BY ft.id, frs.last_known_reply_count
            HAVING COUNT(fr.id) > frs.last_known_reply_count
            ORDER BY MAX(fr.created_at) DESC
        """, (user_id,))
        topics = [{'id': r['id'], 'title': r['title'], 'new_replies': r['new_replies']} for r in cursor.fetchall()]
        result['unread_forum_topics'] = len(topics)
        result['unread_forum_topics_items'] = topics

        # New apps (first version) - with details
        cursor.execute("""
            SELECT ar.id, ar.name, ar.version, u.username as author
            FROM app_repository ar
            JOIN users u ON u.id = ar.author_id
            WHERE ar.approved = 1 AND ar.approved_at IS NOT NULL
            AND datetime(ar.approved_at) > datetime('now', '-7 days')
            AND (ar.version = '1.0' OR ar.version = '0.1')
            ORDER BY ar.approved_at DESC
        """)
        new_apps = [{'id': r['id'], 'name': r['name'], 'version': r['version'], 'author': r['author']} for r in cursor.fetchall()]
        result['new_apps'] = len(new_apps)
        result['new_apps_items'] = new_apps

        # App updates (version > 1.0/0.1) - with details
        cursor.execute("""
            SELECT ar.id, ar.name, ar.version, u.username as author
            FROM app_repository ar
            JOIN users u ON u.id = ar.author_id
            WHERE ar.approved = 1 AND ar.approved_at IS NOT NULL
            AND datetime(ar.approved_at) > datetime('now', '-7 days')
            AND ar.version != '1.0' AND ar.version != '0.1'
            ORDER BY ar.approved_at DESC
        """)
        app_updates = [{'id': r['id'], 'name': r['name'], 'version': r['version'], 'author': r['author']} for r in cursor.fetchall()]
        result['app_updates'] = len(app_updates)
        result['app_updates_items'] = app_updates

        conn.close()
        return result

    @_serialized_write
    def delete_forum_topic(self, topic_id: int, user_id: int) -> bool:
        """Delete forum topic (author or admin only)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Check if user is author or admin
        cursor.execute("""
            SELECT author_id FROM forum_topics WHERE id = ?
        """, (topic_id,))
        topic = cursor.fetchone()

        if not topic:
            conn.close()
            return False

        # Get user info
        user = self.get_user_by_id(user_id)
        if not user:
            conn.close()
            return False

        # Only author or admin can delete
        if topic['author_id'] != user_id and not user.get('is_admin', False):
            conn.close()
            return False

        # Delete replies first
        cursor.execute("DELETE FROM forum_replies WHERE topic_id = ?", (topic_id,))
        # Delete topic
        cursor.execute("DELETE FROM forum_topics WHERE id = ?", (topic_id,))

        conn.commit()
        conn.close()
        return True

    def search_forum(self, query: str, category: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Search forum topics - optimized"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if category and category != 'all':
            cursor.execute("""
                SELECT ft.*, u.username as author_username, u.titan_number as author_titan_number,
                       COALESCE(COUNT(fr.id), 0) as reply_count
                FROM forum_topics ft
                JOIN users u ON ft.author_id = u.id
                LEFT JOIN forum_replies fr ON fr.topic_id = ft.id
                WHERE ft.category = ? AND (ft.title LIKE ? OR ft.content LIKE ?)
                GROUP BY ft.id
                ORDER BY ft.updated_at DESC
                LIMIT ?
            """, (category, f'%{query}%', f'%{query}%', limit))
        else:
            cursor.execute("""
                SELECT ft.*, u.username as author_username, u.titan_number as author_titan_number,
                       COALESCE(COUNT(fr.id), 0) as reply_count
                FROM forum_topics ft
                JOIN users u ON ft.author_id = u.id
                LEFT JOIN forum_replies fr ON fr.topic_id = ft.id
                WHERE ft.title LIKE ? OR ft.content LIKE ?
                GROUP BY ft.id
                ORDER BY ft.updated_at DESC
                LIMIT ?
            """, (f'%{query}%', f'%{query}%', limit))

        topics = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return topics

    # Role Management Methods

    def get_user_role(self, user_id: int) -> str:
        """Get user's role (developer, moderator, or user)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result['role'] if result else 'user'

    def is_developer(self, user_id: int) -> bool:
        """Check if user is a developer"""
        return self.get_user_role(user_id) == 'developer'

    def is_moderator(self, user_id: int) -> bool:
        """Check if user is a moderator or developer"""
        role = self.get_user_role(user_id)
        return role in ('moderator', 'developer')

    @_serialized_write
    def promote_to_moderator(self, user_id: int, appointed_by: int, title: str = "Moderator") -> Dict[str, Any]:
        """Promote user to moderator (developer only)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Check if appointer is developer
        if not self.is_developer(appointed_by):
            conn.close()
            return {"success": False, "error": "Only developers can appoint moderators"}

        try:
            # Update user role
            cursor.execute("UPDATE users SET role = 'moderator' WHERE id = ?", (user_id,))

            # Add to moderators table with custom title
            appointed_at = datetime.now().isoformat()
            cursor.execute("""
                INSERT OR REPLACE INTO moderators (user_id, title, appointed_by, appointed_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, title, appointed_by, appointed_at))

            conn.commit()
            conn.close()
            return {"success": True, "message": "User promoted to moderator"}
        except Exception as e:
            conn.rollback()
            conn.close()
            return {"success": False, "error": str(e)}

    @_serialized_write
    def demote_from_moderator(self, user_id: int, demoted_by: int) -> Dict[str, Any]:
        """Demote moderator to regular user (developer only)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Check if demoter is developer
        if not self.is_developer(demoted_by):
            conn.close()
            return {"success": False, "error": "Only developers can demote moderators"}

        try:
            # Update user role
            cursor.execute("UPDATE users SET role = 'user' WHERE id = ?", (user_id,))

            # Remove from moderators table
            cursor.execute("DELETE FROM moderators WHERE user_id = ?", (user_id,))

            conn.commit()
            conn.close()
            return {"success": True, "message": "User demoted to regular user"}
        except Exception as e:
            conn.rollback()
            conn.close()
            return {"success": False, "error": str(e)}

    def get_all_moderators(self) -> List[Dict[str, Any]]:
        """Get list of all moderators with their titles"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT u.id, u.username, u.titan_number, m.title, m.appointed_at,
                   dev.username as appointed_by_username
            FROM users u
            JOIN moderators m ON u.id = m.user_id
            JOIN users dev ON m.appointed_by = dev.id
            WHERE u.role = 'moderator'
            ORDER BY m.appointed_at DESC
        """)

        moderators = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return moderators

    # App Repository Management Methods (additional)

    @_serialized_write
    def reject_app(self, app_id: int, admin_id: int) -> bool:
        """Reject application in repository"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Verify admin/moderator permission
        if not self.is_moderator(admin_id):
            conn.close()
            return False

        cursor.execute("DELETE FROM app_repository WHERE id = ? AND approved = 0", (app_id,))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success

    def get_user_apps(self, user_id: int) -> List[Dict[str, Any]]:
        """Get apps uploaded by specific user"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT ar.*, u.username as author_username
            FROM app_repository ar
            JOIN users u ON ar.author_id = u.id
            WHERE ar.author_id = ?
            ORDER BY ar.uploaded_at DESC
        """, (user_id,))

        apps = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return apps

    def search_apps(self, query: str, approved_only: bool = True) -> List[Dict[str, Any]]:
        """Search applications by name or description"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if approved_only:
            cursor.execute("""
                SELECT ar.*, u.username as author_username
                FROM app_repository ar
                JOIN users u ON ar.author_id = u.id
                WHERE ar.approved = 1 AND (ar.name LIKE ? OR ar.description LIKE ?)
                ORDER BY ar.downloads DESC, ar.uploaded_at DESC
            """, (f'%{query}%', f'%{query}%'))
        else:
            cursor.execute("""
                SELECT ar.*, u.username as author_username
                FROM app_repository ar
                JOIN users u ON ar.author_id = u.id
                WHERE ar.name LIKE ? OR ar.description LIKE ?
                ORDER BY ar.approved DESC, ar.uploaded_at DESC
            """, (f'%{query}%', f'%{query}%'))

        apps = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return apps

    # Forum Moderation Methods

    @_serialized_write
    def lock_forum_topic(self, topic_id: int, moderator_id: int) -> Dict[str, Any]:
        """Lock forum topic (moderator/developer only)"""
        if not self.is_moderator(moderator_id):
            return {"success": False, "error": "Permission denied"}

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE forum_topics SET is_locked = 1 WHERE id = ?", (topic_id,))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return {"success": success, "message": "Topic locked" if success else "Topic not found"}

    @_serialized_write
    def unlock_forum_topic(self, topic_id: int, moderator_id: int) -> Dict[str, Any]:
        """Unlock forum topic (moderator/developer only)"""
        if not self.is_moderator(moderator_id):
            return {"success": False, "error": "Permission denied"}

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE forum_topics SET is_locked = 0 WHERE id = ?", (topic_id,))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return {"success": success, "message": "Topic unlocked" if success else "Topic not found"}

    @_serialized_write
    def pin_forum_topic(self, topic_id: int, moderator_id: int) -> Dict[str, Any]:
        """Pin forum topic (moderator/developer only)"""
        if not self.is_moderator(moderator_id):
            return {"success": False, "error": "Permission denied"}

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE forum_topics SET is_pinned = 1 WHERE id = ?", (topic_id,))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return {"success": success, "message": "Topic pinned" if success else "Topic not found"}

    @_serialized_write
    def unpin_forum_topic(self, topic_id: int, moderator_id: int) -> Dict[str, Any]:
        """Unpin forum topic (moderator/developer only)"""
        if not self.is_moderator(moderator_id):
            return {"success": False, "error": "Permission denied"}

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE forum_topics SET is_pinned = 0 WHERE id = ?", (topic_id,))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return {"success": success, "message": "Topic unpinned" if success else "Topic not found"}

    @_serialized_write
    def delete_forum_reply(self, reply_id: int, moderator_id: int) -> Dict[str, Any]:
        """Delete forum reply (moderator/developer only)"""
        if not self.is_moderator(moderator_id):
            return {"success": False, "error": "Permission denied"}

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM forum_replies WHERE id = ?", (reply_id,))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return {"success": success, "message": "Reply deleted" if success else "Reply not found"}

    @_serialized_write
    def edit_forum_reply(self, reply_id: int, new_content: str, moderator_id: int) -> Dict[str, Any]:
        """Edit forum reply (moderator/developer only)"""
        if not self.is_moderator(moderator_id):
            return {"success": False, "error": "Permission denied"}

        if not new_content or not new_content.strip():
            return {"success": False, "error": "Content cannot be empty"}

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE forum_replies SET content = ? WHERE id = ?", (new_content.strip(), reply_id))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return {"success": success, "message": "Reply edited" if success else "Reply not found"}

    @_serialized_write
    def move_forum_topic(self, topic_id: int, new_category: str, moderator_id: int) -> Dict[str, Any]:
        """Move forum topic to different category (moderator/developer only)"""
        if not self.is_moderator(moderator_id):
            return {"success": False, "error": "Permission denied"}

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE forum_topics SET category = ? WHERE id = ?", (new_category, topic_id))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return {"success": success, "message": f"Topic moved to {new_category}" if success else "Topic not found"}

    # Room Moderation Methods

    @_serialized_write
    def kick_user_from_room(self, room_id: int, user_id: int, moderator_id: int) -> Dict[str, Any]:
        """Kick user from room (moderator/developer/room creator only)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Check if moderator or room creator
        cursor.execute("SELECT creator_id FROM chat_rooms WHERE id = ?", (room_id,))
        room = cursor.fetchone()

        if not room:
            conn.close()
            return {"success": False, "error": "Room not found"}

        if not self.is_moderator(moderator_id) and room['creator_id'] != moderator_id:
            conn.close()
            return {"success": False, "error": "Permission denied"}

        # Remove user from room
        cursor.execute("DELETE FROM room_members WHERE room_id = ? AND user_id = ?", (room_id, user_id))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return {"success": success, "message": "User kicked from room" if success else "User not in room"}

    @_serialized_write
    def ban_user_from_room(self, room_id: int, user_id: int, moderator_id: int, reason: str = "") -> Dict[str, Any]:
        """Ban user from room (moderator/developer/room creator only)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Check if moderator or room creator
        cursor.execute("SELECT creator_id FROM chat_rooms WHERE id = ?", (room_id,))
        room = cursor.fetchone()

        if not room:
            conn.close()
            return {"success": False, "error": "Room not found"}

        if not self.is_moderator(moderator_id) and room['creator_id'] != moderator_id:
            conn.close()
            return {"success": False, "error": "Permission denied"}

        try:
            # Remove from room
            cursor.execute("DELETE FROM room_members WHERE room_id = ? AND user_id = ?", (room_id, user_id))

            # Add ban
            banned_at = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO room_bans (room_id, user_id, banned_by, banned_at, reason)
                VALUES (?, ?, ?, ?, ?)
            """, (room_id, user_id, moderator_id, banned_at, reason))

            conn.commit()
            conn.close()
            return {"success": True, "message": "User banned from room"}
        except sqlite3.IntegrityError:
            conn.rollback()
            conn.close()
            return {"success": False, "error": "User already banned"}

    @_serialized_write
    def unban_user_from_room(self, room_id: int, user_id: int, moderator_id: int) -> Dict[str, Any]:
        """Unban user from room (moderator/developer/room creator only)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Check if moderator or room creator
        cursor.execute("SELECT creator_id FROM chat_rooms WHERE id = ?", (room_id,))
        room = cursor.fetchone()

        if not room:
            conn.close()
            return {"success": False, "error": "Room not found"}

        if not self.is_moderator(moderator_id) and room['creator_id'] != moderator_id:
            conn.close()
            return {"success": False, "error": "Permission denied"}

        cursor.execute("DELETE FROM room_bans WHERE room_id = ? AND user_id = ?", (room_id, user_id))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return {"success": success, "message": "User unbanned from room" if success else "User not banned"}

    def is_user_banned(self, room_id: int, user_id: int) -> bool:
        """Check if user is banned from room"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM room_bans WHERE room_id = ? AND user_id = ?", (room_id, user_id))
        result = cursor.fetchone()
        conn.close()
        return result is not None

    @_serialized_write
    def delete_room_message(self, message_id: int, moderator_id: int) -> Dict[str, Any]:
        """Delete room message (moderator/developer only)"""
        if not self.is_moderator(moderator_id):
            return {"success": False, "error": "Permission denied"}

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM room_messages WHERE id = ?", (message_id,))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return {"success": success, "message": "Message deleted" if success else "Message not found"}

    @_serialized_write
    def delete_chat_room_by_moderator(self, room_id: int, moderator_id: int) -> Dict[str, Any]:
        """Delete chat room (moderator/developer only - enhanced version)"""
        if not self.is_moderator(moderator_id):
            return {"success": False, "error": "Permission denied"}

        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # Delete room and all related data
            cursor.execute("DELETE FROM room_messages WHERE room_id = ?", (room_id,))
            cursor.execute("DELETE FROM room_members WHERE room_id = ?", (room_id,))
            cursor.execute("DELETE FROM room_bans WHERE room_id = ?", (room_id,))
            cursor.execute("DELETE FROM chat_rooms WHERE id = ?", (room_id,))

            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return {"success": success, "message": "Room deleted" if success else "Room not found"}
        except Exception as e:
            conn.rollback()
            conn.close()
            return {"success": False, "error": str(e)}

    # Extended Ban System Methods

    @_serialized_write
    def ban_user_from_room_extended(self, room_id: int, user_id: int, moderator_id: int,
                                    ban_type: str = 'permanent', duration_hours: int = None,
                                    reason: str = "", ip_address: str = None) -> Dict[str, Any]:
        """Ban user from room with extended options (temporary, permanent, IP)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT creator_id FROM chat_rooms WHERE id = ?", (room_id,))
        room = cursor.fetchone()

        if not room:
            conn.close()
            return {"success": False, "error": "Room not found"}

        if not self.is_moderator(moderator_id) and room['creator_id'] != moderator_id:
            conn.close()
            return {"success": False, "error": "Permission denied"}

        try:
            from datetime import datetime, timedelta

            cursor.execute("DELETE FROM room_members WHERE room_id = ? AND user_id = ?", (room_id, user_id))

            expires_at = None
            if ban_type == 'temporary' and duration_hours:
                expires_at = (datetime.now() + timedelta(hours=duration_hours)).isoformat()

            banned_at = datetime.now().isoformat()

            cursor.execute("""
                INSERT OR REPLACE INTO room_bans
                (room_id, user_id, banned_by, banned_at, expires_at, ban_type, reason, ip_address)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (room_id, user_id, moderator_id, banned_at, expires_at, ban_type, reason, ip_address))

            conn.commit()
            conn.close()
            return {"success": True, "message": "User banned from room"}
        except Exception as e:
            conn.rollback()
            conn.close()
            return {"success": False, "error": str(e)}

    @_serialized_write
    def ban_user_globally(self, user_id: int, moderator_id: int,
                         ban_type: str = 'permanent', duration_hours: int = None,
                         reason: str = "", ip_address: str = None) -> Dict[str, Any]:
        """Ban user from entire Titan-Net (TCE Community)"""
        if not self.is_moderator(moderator_id):
            return {"success": False, "error": "Permission denied"}

        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            from datetime import datetime, timedelta

            expires_at = None
            if ban_type == 'temporary' and duration_hours:
                expires_at = (datetime.now() + timedelta(hours=duration_hours)).isoformat()

            banned_at = datetime.now().isoformat()

            cursor.execute("""
                INSERT OR REPLACE INTO global_bans
                (user_id, banned_by, banned_at, expires_at, ban_type, reason, ip_address, hardware_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, moderator_id, banned_at, expires_at, ban_type, reason, ip_address, None))

            cursor.execute("UPDATE users SET status = 'banned' WHERE id = ?", (user_id,))

            conn.commit()
            conn.close()
            return {"success": True, "message": "User banned from TCE Community"}
        except Exception as e:
            conn.rollback()
            conn.close()
            return {"success": False, "error": str(e)}

    @_serialized_write
    def ban_user_hard(self, user_id: int, moderator_id: int, reason: str = "",
                     ip_address: str = None, hardware_id: str = None) -> Dict[str, Any]:
        """
        Hard ban - most restrictive ban type
        Bans user, their IP, and hardware ID permanently
        Prevents any new accounts from this IP/hardware
        """
        if not self.is_moderator(moderator_id):
            return {"success": False, "error": "Permission denied"}

        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            from datetime import datetime

            banned_at = datetime.now().isoformat()

            # Ban the user globally with hard ban type
            cursor.execute("""
                INSERT OR REPLACE INTO global_bans
                (user_id, banned_by, banned_at, expires_at, ban_type, reason, ip_address, hardware_id)
                VALUES (?, ?, ?, NULL, 'hard', ?, ?, ?)
            """, (user_id, moderator_id, banned_at, reason, ip_address, hardware_id))

            cursor.execute("UPDATE users SET status = 'banned' WHERE id = ?", (user_id,))

            # Add IP/Hardware to permanent ban list (blocks new account creation)
            if ip_address or hardware_id:
                cursor.execute("""
                    INSERT INTO ip_hardware_bans (ip_address, hardware_id, banned_by, banned_at, reason)
                    VALUES (?, ?, ?, ?, ?)
                """, (ip_address, hardware_id, moderator_id, banned_at, reason))

            # Ban all other accounts from the same IP/hardware
            if ip_address or hardware_id:
                # Find all users with matching IP (would need IP tracking in users table)
                # For now, just mark in ban table
                pass

            conn.commit()
            conn.close()
            return {"success": True, "message": "User hard banned - IP and hardware blocked"}
        except Exception as e:
            conn.rollback()
            conn.close()
            return {"success": False, "error": str(e)}

    def is_ip_hardware_banned(self, ip_address: str = None, hardware_id: str = None) -> bool:
        """Check if IP or hardware ID is banned.

        Checks both ip_hardware_bans (explicit IP/HW entries) and global_bans
        where ban_type='hard' (IP/HW stored directly on the ban record).
        This covers the case where a hard ban was applied before the ip_hardware_bans
        row was written, or where a single lookup is sufficient to block registration.
        """
        if not ip_address and not hardware_id:
            return False

        conn = self.get_connection()
        cursor = conn.cursor()

        # Check dedicated ip_hardware_bans table first
        if ip_address and hardware_id:
            cursor.execute("""
                SELECT id FROM ip_hardware_bans
                WHERE ip_address = ? OR hardware_id = ?
            """, (ip_address, hardware_id))
        elif ip_address:
            cursor.execute("SELECT id FROM ip_hardware_bans WHERE ip_address = ?", (ip_address,))
        else:
            cursor.execute("SELECT id FROM ip_hardware_bans WHERE hardware_id = ?", (hardware_id,))

        if cursor.fetchone():
            conn.close()
            return True

        # Also check global_bans: hard bans store IP/HW on the ban record itself.
        # This catches bans applied before ip_hardware_bans was populated.
        if ip_address and hardware_id:
            cursor.execute("""
                SELECT id FROM global_bans
                WHERE ban_type = 'hard' AND (ip_address = ? OR hardware_id = ?)
            """, (ip_address, hardware_id))
        elif ip_address:
            cursor.execute("""
                SELECT id FROM global_bans WHERE ban_type = 'hard' AND ip_address = ?
            """, (ip_address,))
        else:
            cursor.execute("""
                SELECT id FROM global_bans WHERE ban_type = 'hard' AND hardware_id = ?
            """, (hardware_id,))

        result = cursor.fetchone()
        conn.close()
        return result is not None

    @_serialized_write
    def ban_user_from_forum(self, user_id: int, moderator_id: int,
                           ban_type: str = 'permanent', duration_hours: int = None,
                           reason: str = "") -> Dict[str, Any]:
        """Ban user from forum"""
        if not self.is_moderator(moderator_id):
            return {"success": False, "error": "Permission denied"}

        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            from datetime import datetime, timedelta

            expires_at = None
            if ban_type == 'temporary' and duration_hours:
                expires_at = (datetime.now() + timedelta(hours=duration_hours)).isoformat()

            banned_at = datetime.now().isoformat()

            cursor.execute("""
                INSERT OR REPLACE INTO forum_bans
                (user_id, banned_by, banned_at, expires_at, ban_type, reason)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, moderator_id, banned_at, expires_at, ban_type, reason))

            conn.commit()
            conn.close()
            return {"success": True, "message": "User banned from forum"}
        except Exception as e:
            conn.rollback()
            conn.close()
            return {"success": False, "error": str(e)}

    def is_user_banned_globally(self, user_id: int) -> Dict[str, Any]:
        """Check if user is globally banned"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT ban_type, reason, expires_at, banned_at FROM global_bans WHERE user_id = ?", (user_id,))
        ban = cursor.fetchone()
        conn.close()

        if not ban:
            return {"banned": False}

        if ban['expires_at']:
            from datetime import datetime
            expires_at = datetime.fromisoformat(ban['expires_at'])
            if datetime.now() > expires_at:
                self.unban_user_globally(user_id)
                return {"banned": False}

        return {"banned": True, "ban_type": ban['ban_type'], "reason": ban['reason'], "banned_at": ban['banned_at'], "expires_at": ban['expires_at']}

    def is_user_banned_from_forum(self, user_id: int) -> Dict[str, Any]:
        """Check if user is banned from forum"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT ban_type, reason, expires_at, banned_at FROM forum_bans WHERE user_id = ?", (user_id,))
        ban = cursor.fetchone()
        conn.close()

        if not ban:
            return {"banned": False}

        if ban['expires_at']:
            from datetime import datetime
            expires_at = datetime.fromisoformat(ban['expires_at'])
            if datetime.now() > expires_at:
                self.unban_user_from_forum(user_id)
                return {"banned": False}

        return {"banned": True, "ban_type": ban['ban_type'], "reason": ban['reason'], "banned_at": ban['banned_at'], "expires_at": ban['expires_at']}

    @_serialized_write
    def unban_user_globally(self, user_id: int) -> Dict[str, Any]:
        """Unban user globally"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM global_bans WHERE user_id = ?", (user_id,))
        cursor.execute("UPDATE users SET status = 'offline' WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
        return {"success": True}

    @_serialized_write
    def unban_user_from_forum(self, user_id: int) -> Dict[str, Any]:
        """Unban user from forum"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM forum_bans WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return {"success": True}

    # User Management Methods

    @_serialized_write
    def delete_user(self, user_id: int, moderator_id: int) -> Dict[str, Any]:
        """
        Delete user account permanently (admin/developer only)
        Removes user and all their data (messages, forum posts, etc.)
        """
        if not self.is_moderator(moderator_id):
            return {"success": False, "error": "Permission denied - moderator access required"}

        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # Check if user exists
            cursor.execute("SELECT username FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
            if not user:
                conn.close()
                return {"success": False, "error": "User not found"}

            # Delete all user data
            cursor.execute("DELETE FROM private_messages WHERE sender_id = ? OR recipient_id = ?", (user_id, user_id))
            cursor.execute("DELETE FROM room_messages WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM room_members WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM forum_replies WHERE author_id = ?", (user_id,))
            cursor.execute("DELETE FROM forum_topics WHERE author_id = ?", (user_id,))
            cursor.execute("DELETE FROM room_bans WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM global_bans WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM forum_bans WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM moderators WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

            # Delete user account
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))

            conn.commit()
            conn.close()
            return {"success": True, "message": f"User {user['username']} deleted successfully"}
        except Exception as e:
            conn.rollback()
            conn.close()
            return {"success": False, "error": str(e)}

    def get_all_users(self, moderator_id: int = None) -> List[Dict[str, Any]]:
        """
        Get list of all users (admin/developer only)
        Returns user info including status and role
        """
        if moderator_id and not self.is_moderator(moderator_id):
            return []

        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT u.id, u.username, u.titan_number, u.full_name, u.status, u.role,
                   u.created_at, u.last_login, u.is_admin
            FROM users u
            ORDER BY u.created_at DESC
        """)

        users = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return users

    # ------------------------------------------------------------------
    # OAuth: external-provider tokens (Spotify, Allegro, ...)
    # ------------------------------------------------------------------
    def _oauth_fernet(self):
        """Lazy-load Fernet instance keyed from TITAN_OAUTH_KEY config."""
        if hasattr(self, '_fernet_cached'):
            return self._fernet_cached
        try:
            from cryptography.fernet import Fernet
            from config import Config
            key = getattr(Config, 'OAUTH_KEY', None)
            if not key:
                raise RuntimeError(
                    "OAUTH_KEY missing - set env var TITAN_OAUTH_KEY to a "
                    "Fernet key (Fernet.generate_key().decode())"
                )
            if isinstance(key, str):
                key = key.encode()
            self._fernet_cached = Fernet(key)
            return self._fernet_cached
        except ImportError:
            raise RuntimeError(
                "cryptography package not installed - pip install cryptography"
            )

    @_serialized_write
    def oauth_save_token(self, user_id: int, provider: str,
                         access_token: str, refresh_token: Optional[str],
                         expires_at: Optional[str], scope: Optional[str]) -> None:
        """Encrypt and upsert an OAuth token row."""
        f = self._oauth_fernet()
        access_enc = f.encrypt(access_token.encode()).decode()
        refresh_enc = f.encrypt(refresh_token.encode()).decode() if refresh_token else None
        now = datetime.now().isoformat()

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO oauth_tokens
                (user_id, provider, access_token_enc, refresh_token_enc,
                 expires_at, scope, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, provider) DO UPDATE SET
                access_token_enc = excluded.access_token_enc,
                refresh_token_enc = COALESCE(excluded.refresh_token_enc, oauth_tokens.refresh_token_enc),
                expires_at = excluded.expires_at,
                scope = excluded.scope,
                updated_at = excluded.updated_at
        """, (user_id, provider, access_enc, refresh_enc, expires_at, scope, now, now))
        conn.commit()
        conn.close()

    def oauth_get_token(self, user_id: int, provider: str) -> Optional[Dict[str, Any]]:
        """Return decrypted token row or None."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT access_token_enc, refresh_token_enc, expires_at, scope, updated_at
            FROM oauth_tokens
            WHERE user_id = ? AND provider = ?
        """, (user_id, provider))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        f = self._oauth_fernet()
        return {
            'access_token': f.decrypt(row['access_token_enc'].encode()).decode(),
            'refresh_token': f.decrypt(row['refresh_token_enc'].encode()).decode() if row['refresh_token_enc'] else None,
            'expires_at': row['expires_at'],
            'scope': row['scope'],
            'updated_at': row['updated_at'],
        }

    @_serialized_write
    def oauth_delete_token(self, user_id: int, provider: str) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM oauth_tokens WHERE user_id = ? AND provider = ?",
            (user_id, provider)
        )
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    @_serialized_write
    def oauth_save_state(self, state: str, user_id: int, provider: str) -> None:
        """Store CSRF state. Caller should purge after consumption."""
        conn = self.get_connection()
        cursor = conn.cursor()
        # Best-effort cleanup of stale states (>10 min) on every write
        cursor.execute("""
            DELETE FROM oauth_states
            WHERE created_at < datetime('now', '-10 minutes')
        """)
        cursor.execute("""
            INSERT INTO oauth_states (state, user_id, provider, created_at)
            VALUES (?, ?, ?, ?)
        """, (state, user_id, provider, datetime.now().isoformat()))
        conn.commit()
        conn.close()

    @_serialized_write
    def oauth_consume_state(self, state: str) -> Optional[Dict[str, Any]]:
        """Return {user_id, provider} if state is fresh, then delete it."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_id, provider, created_at FROM oauth_states WHERE state = ?
        """, (state,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
        cursor.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        conn.commit()
        conn.close()

        # Reject states older than 10 minutes
        try:
            created = datetime.fromisoformat(row['created_at'])
            if (datetime.now() - created).total_seconds() > 600:
                return None
        except (ValueError, TypeError):
            return None

        return {'user_id': row['user_id'], 'provider': row['provider']}

    # =====================================================================
    # FEEDBACK HUB
    # =====================================================================
    # Statuses for feedback (item_type='feedback'):
    #   'pending'        - not yet reviewed
    #   'next_version'   - planned for next version
    #   'considering'    - under consideration
    #   'reproducing'    - reproducing the problem
    #   'resolved'       - resolved
    #   'wont_fix'       - cannot be resolved
    # Statuses for ideas (item_type='idea'):
    #   'pending'        - waiting for consideration
    #   'accepted'       - accepted
    #   'rejected'       - rejected
    FEEDBACK_STATUSES = ('next_version', 'considering', 'reproducing', 'resolved', 'wont_fix')
    IDEA_STATUSES = ('accepted', 'rejected')

    @_serialized_write
    def create_feedback_item(self, item_type: str, title: str, content: str,
                             author_id: int, attachment_path: Optional[str] = None,
                             attachment_name: Optional[str] = None) -> Dict[str, Any]:
        """Create a new feedback or idea entry. item_type must be 'feedback' or 'idea'."""
        if item_type not in ('feedback', 'idea'):
            return {"success": False, "error": "Invalid item type"}
        if not title.strip() or not content.strip():
            return {"success": False, "error": "Title and content are required"}

        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO feedback_items
                (item_type, title, content, author_id, status, attachment_path, attachment_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
        """, (item_type, title.strip(), content.strip(), author_id,
              attachment_path, attachment_name, now, now))
        feedback_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return {
            "success": True,
            "feedback_id": feedback_id,
            "item_type": item_type,
            "title": title.strip(),
            "created_at": now,
        }

    def get_feedback_items(self, item_type: Optional[str] = None,
                           viewer_id: Optional[int] = None,
                           limit: int = 200) -> List[Dict[str, Any]]:
        """List feedback or ideas with upvote counts and author info."""
        conn = self.get_connection()
        cursor = conn.cursor()

        params: List[Any] = []
        where = ""
        if item_type in ('feedback', 'idea'):
            where = "WHERE fi.item_type = ?"
            params.append(item_type)

        cursor.execute(f"""
            SELECT fi.*, u.username AS author_username, u.titan_number AS author_titan_number,
                   COALESCE((SELECT COUNT(*) FROM feedback_upvotes fu WHERE fu.feedback_id = fi.id), 0) AS upvote_count,
                   COALESCE((SELECT 1 FROM feedback_upvotes fu WHERE fu.feedback_id = fi.id AND fu.user_id = ?), 0) AS viewer_upvoted
            FROM feedback_items fi
            JOIN users u ON fi.author_id = u.id
            {where}
            ORDER BY fi.updated_at DESC
            LIMIT ?
        """, [viewer_id or 0] + params + [limit])

        items = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return items

    def get_feedback_item(self, feedback_id: int, viewer_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Fetch a single feedback/idea entry with author and upvote info."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT fi.*, u.username AS author_username, u.titan_number AS author_titan_number,
                   COALESCE((SELECT COUNT(*) FROM feedback_upvotes fu WHERE fu.feedback_id = fi.id), 0) AS upvote_count,
                   COALESCE((SELECT 1 FROM feedback_upvotes fu WHERE fu.feedback_id = fi.id AND fu.user_id = ?), 0) AS viewer_upvoted
            FROM feedback_items fi
            JOIN users u ON fi.author_id = u.id
            WHERE fi.id = ?
        """, (viewer_id or 0, feedback_id))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    @_serialized_write
    def upvote_feedback(self, feedback_id: int, user_id: int) -> Dict[str, Any]:
        """Toggle an upvote. Authors cannot upvote their own items."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT author_id, item_type, title FROM feedback_items WHERE id = ?", (feedback_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {"success": False, "error": "Feedback not found"}
        if row['author_id'] == user_id:
            conn.close()
            return {"success": False, "error": "You cannot upvote your own item"}

        cursor.execute("SELECT 1 FROM feedback_upvotes WHERE feedback_id = ? AND user_id = ?",
                       (feedback_id, user_id))
        already = cursor.fetchone() is not None

        if already:
            cursor.execute("DELETE FROM feedback_upvotes WHERE feedback_id = ? AND user_id = ?",
                           (feedback_id, user_id))
            action = 'removed'
        else:
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO feedback_upvotes (feedback_id, user_id, created_at) VALUES (?, ?, ?)
            """, (feedback_id, user_id, now))
            action = 'added'

        cursor.execute("SELECT COUNT(*) AS c FROM feedback_upvotes WHERE feedback_id = ?", (feedback_id,))
        upvote_count = cursor.fetchone()['c']
        conn.commit()
        conn.close()

        return {
            "success": True,
            "action": action,
            "feedback_id": feedback_id,
            "item_type": row['item_type'],
            "title": row['title'],
            "upvote_count": upvote_count,
        }

    @_serialized_write
    def set_feedback_status(self, feedback_id: int, new_status: str,
                            moderator_id: int) -> Dict[str, Any]:
        """Change a feedback/idea status (moderator/developer only)."""
        if not self.is_moderator(moderator_id):
            return {"success": False, "error": "Permission denied - moderator access required"}

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, item_type, title, author_id FROM feedback_items WHERE id = ?", (feedback_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {"success": False, "error": "Feedback not found"}

        item_type = row['item_type']
        if item_type == 'feedback' and new_status not in self.FEEDBACK_STATUSES:
            conn.close()
            return {"success": False, "error": "Invalid status for feedback"}
        if item_type == 'idea' and new_status not in self.IDEA_STATUSES:
            conn.close()
            return {"success": False, "error": "Invalid status for idea"}

        now = datetime.now().isoformat()
        cursor.execute("""
            UPDATE feedback_items SET status = ?, updated_at = ? WHERE id = ?
        """, (new_status, now, feedback_id))
        conn.commit()
        conn.close()

        return {
            "success": True,
            "feedback_id": feedback_id,
            "item_type": item_type,
            "title": row['title'],
            "author_id": row['author_id'],
            "status": new_status,
        }

    @_serialized_write
    def delete_feedback_item(self, feedback_id: int, requester_id: int) -> Dict[str, Any]:
        """Delete a feedback/idea. Allowed for the author or any moderator."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT author_id, item_type, title, attachment_path FROM feedback_items WHERE id = ?",
                       (feedback_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {"success": False, "error": "Feedback not found"}

        is_author = (row['author_id'] == requester_id)
        if not is_author and not self.is_moderator(requester_id):
            conn.close()
            return {"success": False, "error": "Permission denied"}

        cursor.execute("DELETE FROM feedback_upvotes WHERE feedback_id = ?", (feedback_id,))
        cursor.execute("DELETE FROM feedback_items WHERE id = ?", (feedback_id,))
        conn.commit()
        conn.close()

        return {
            "success": True,
            "feedback_id": feedback_id,
            "item_type": row['item_type'],
            "title": row['title'],
            "attachment_path": row['attachment_path'],
        }

    # =====================================================================
    # INTERACTIVE GAMES (Entertainment tab)
    # =====================================================================
    # Providers and per-session caps
    GAME_PROVIDERS = ('gemini', 'openai', 'anthropic')
    GAME_DEFAULT_MAX_TOKENS = 200000
    GAME_DEFAULT_MAX_MINUTES = 60
    GAME_DEFAULT_MAX_PLAYERS = 6
    GAME_HARD_TOKEN_CEILING = 2_000_000
    GAME_HARD_MINUTE_CEILING = 240
    GAME_HARD_PLAYER_CEILING = 12

    def _game_fernet(self):
        """Reuse OAuth Fernet for game API key encryption at rest."""
        return self._oauth_fernet()

    @_serialized_write
    def create_game(self, creator_id: int, name: str, description: str,
                    provider: str, api_key: str,
                    max_tokens: Optional[int] = None,
                    max_minutes: Optional[int] = None,
                    max_players: Optional[int] = None,
                    rules_text: Optional[str] = None,
                    npc_voices: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Create a new interactive game with encrypted API key."""
        if provider not in self.GAME_PROVIDERS:
            return {"success": False, "error": "Invalid provider"}
        if not name.strip():
            return {"success": False, "error": "Name is required"}
        if not api_key or not api_key.strip():
            return {"success": False, "error": "API key is required"}

        # Cap caller-supplied limits to hard ceilings so a typo can't
        # produce a session that runs forever.
        max_tokens = min(int(max_tokens or self.GAME_DEFAULT_MAX_TOKENS),
                         self.GAME_HARD_TOKEN_CEILING)
        max_minutes = min(int(max_minutes or self.GAME_DEFAULT_MAX_MINUTES),
                          self.GAME_HARD_MINUTE_CEILING)
        max_players = min(int(max_players or self.GAME_DEFAULT_MAX_PLAYERS),
                          self.GAME_HARD_PLAYER_CEILING)

        try:
            f = self._game_fernet()
            api_key_enc = f.encrypt(api_key.strip().encode()).decode()
        except Exception as e:
            logger.error(f"[GAMES] API key encryption failed: {e}")
            return {"success": False, "error": "Server is not configured for encryption"}

        npc_voices_json = json.dumps(npc_voices or {}, ensure_ascii=False)

        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO interactive_games
                (creator_id, name, description, provider, api_key_enc,
                 max_tokens, max_minutes, max_players, rules_text, npc_voices_json,
                 status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """, (creator_id, name.strip(), (description or '').strip(), provider,
              api_key_enc, max_tokens, max_minutes, max_players,
              rules_text, npc_voices_json, now, now))
        game_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return {
            "success": True,
            "game_id": game_id,
            "name": name.strip(),
            "provider": provider,
            "created_at": now,
        }

    def list_games(self, viewer_id: Optional[int] = None,
                   only_active: bool = True, limit: int = 200) -> List[Dict[str, Any]]:
        """List interactive games. Never returns the API key."""
        conn = self.get_connection()
        cursor = conn.cursor()
        where = "WHERE g.status = 'active'" if only_active else ""
        cursor.execute(f"""
            SELECT g.id, g.creator_id, g.name, g.description, g.provider,
                   g.max_tokens, g.max_minutes, g.max_players, g.status,
                   g.created_at, g.updated_at,
                   u.username AS creator_username,
                   u.titan_number AS creator_titan_number,
                   COALESCE((SELECT COUNT(*) FROM game_sessions s
                             WHERE s.game_id = g.id AND s.status IN ('lobby','running')), 0)
                       AS active_sessions
            FROM interactive_games g
            JOIN users u ON g.creator_id = u.id
            {where}
            ORDER BY g.updated_at DESC
            LIMIT ?
        """, (limit,))
        items = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return items

    def get_game(self, game_id: int, viewer_id: Optional[int] = None,
                 include_api_key: bool = False) -> Optional[Dict[str, Any]]:
        """Fetch a single game definition.

        ``include_api_key`` decrypts the key — only ever set this from
        server-internal call paths (never from a request response).
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT g.*, u.username AS creator_username,
                   u.titan_number AS creator_titan_number
            FROM interactive_games g
            JOIN users u ON g.creator_id = u.id
            WHERE g.id = ?
        """, (game_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        item = dict(row)
        # Pull attachments inline so callers get a single round-trip
        attachments = self.list_game_attachments(game_id)
        item['attachments'] = attachments
        if include_api_key:
            try:
                f = self._game_fernet()
                item['api_key'] = f.decrypt(item['api_key_enc'].encode()).decode()
            except Exception as e:
                logger.error(f"[GAMES] API key decrypt failed for game {game_id}: {e}")
                item['api_key'] = None
        # Always strip the encrypted blob from the dict we hand back
        item.pop('api_key_enc', None)
        # Decode npc_voices JSON
        try:
            item['npc_voices'] = json.loads(item.get('npc_voices_json') or '{}')
        except Exception:
            item['npc_voices'] = {}
        item.pop('npc_voices_json', None)
        return item

    @_serialized_write
    def delete_game(self, game_id: int, requester_id: int) -> Dict[str, Any]:
        """Owner or moderator deletes a game (atomic).

        All cascade DELETEs run inside a single BEGIN/COMMIT so a crash
        mid-cascade can never leave orphaned game_session_log /
        game_session_players / game_attachments rows. ROLLBACK on any
        exception. Returns attachment paths the caller should unlink.
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT creator_id, name FROM interactive_games WHERE id = ?", (game_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {"success": False, "error": "Game not found"}
        is_owner = (row['creator_id'] == requester_id)
        if not is_owner and not self.is_moderator(requester_id):
            conn.close()
            return {"success": False, "error": "Permission denied"}

        # Collect attachment paths before cascade so the caller can unlink files.
        cursor.execute("SELECT file_path FROM game_attachments WHERE game_id = ?", (game_id,))
        paths = [r['file_path'] for r in cursor.fetchall()]

        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("DELETE FROM game_session_log WHERE session_id IN "
                           "(SELECT id FROM game_sessions WHERE game_id = ?)", (game_id,))
            cursor.execute("DELETE FROM game_session_players WHERE session_id IN "
                           "(SELECT id FROM game_sessions WHERE game_id = ?)", (game_id,))
            cursor.execute("DELETE FROM game_sessions WHERE game_id = ?", (game_id,))
            cursor.execute("DELETE FROM game_attachments WHERE game_id = ?", (game_id,))
            cursor.execute("DELETE FROM interactive_games WHERE id = ?", (game_id,))
            conn.commit()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            logger.error(f"[GAMES] delete_game cascade failed: {e}", exc_info=True)
            return {"success": False, "error": "Database error during cascade delete"}
        conn.close()
        return {
            "success": True,
            "game_id": game_id,
            "name": row['name'],
            "attachment_paths": paths,
        }

    @_serialized_write
    def add_game_attachment(self, game_id: int, attachment_type: str,
                            file_path: str, file_name: str,
                            mime_type: Optional[str], size_bytes: int) -> Dict[str, Any]:
        """Insert an attachment row for a game."""
        if attachment_type not in ('rules_zip', 'prompt_txt', 'sound', 'other'):
            return {"success": False, "error": "Invalid attachment type"}
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO game_attachments
                (game_id, attachment_type, file_path, file_name, mime_type, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (game_id, attachment_type, file_path, file_name, mime_type, size_bytes, now))
        att_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return {"success": True, "attachment_id": att_id}

    def list_game_attachments(self, game_id: int) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, attachment_type, file_name, mime_type, size_bytes, created_at
            FROM game_attachments WHERE game_id = ?
            ORDER BY id ASC
        """, (game_id,))
        items = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return items

    def get_game_attachment(self, attachment_id: int) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.*, g.creator_id AS game_creator_id
            FROM game_attachments a
            JOIN interactive_games g ON a.game_id = g.id
            WHERE a.id = ?
        """, (attachment_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    @_serialized_write
    def delete_game_attachment(self, attachment_id: int, requester_id: int) -> Dict[str, Any]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.file_path, a.game_id, g.creator_id
            FROM game_attachments a
            JOIN interactive_games g ON a.game_id = g.id
            WHERE a.id = ?
        """, (attachment_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {"success": False, "error": "Attachment not found"}
        if row['creator_id'] != requester_id and not self.is_moderator(requester_id):
            conn.close()
            return {"success": False, "error": "Permission denied"}
        cursor.execute("DELETE FROM game_attachments WHERE id = ?", (attachment_id,))
        conn.commit()
        conn.close()
        return {
            "success": True,
            "attachment_id": attachment_id,
            "file_path": row['file_path'],
        }

    # ----- Sessions (Phase 3) -----

    @_serialized_write
    def create_game_session(self, game_id: int, host_id: int) -> Dict[str, Any]:
        """Create a new lobby session for a game (atomic).

        Session row + host's player row insert as one transaction so we
        can never end up with a session whose host isn't a player.
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, max_players FROM interactive_games WHERE id = ? AND status = 'active'",
                       (game_id,))
        game = cursor.fetchone()
        if not game:
            conn.close()
            return {"success": False, "error": "Game not found or inactive"}
        now = datetime.now().isoformat()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("""
                INSERT INTO game_sessions
                    (game_id, host_id, status, state_json, turn_order_json,
                     current_turn_idx, tokens_used, started_at)
                VALUES (?, ?, 'lobby', '{}', '[]', 0, 0, ?)
            """, (game_id, host_id, now))
            session_id = cursor.lastrowid
            cursor.execute("""
                INSERT INTO game_session_players
                    (session_id, user_id, character_state_json, joined_at)
                VALUES (?, ?, '{}', ?)
            """, (session_id, host_id, now))
            conn.commit()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            logger.error(f"[GAMES] create_game_session crashed: {e}", exc_info=True)
            return {"success": False, "error": "Database error"}
        conn.close()
        return {
            "success": True,
            "session_id": session_id,
            "game_id": game_id,
            "game_name": game['name'],
            "max_players": game['max_players'],
            "started_at": now,
        }

    def get_game_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.*, g.name AS game_name, g.provider, g.max_tokens,
                   g.max_minutes, g.max_players, g.creator_id AS game_creator_id
            FROM game_sessions s
            JOIN interactive_games g ON s.game_id = g.id
            WHERE s.id = ?
        """, (session_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
        item = dict(row)
        # Decode JSON columns
        try:
            item['state'] = json.loads(item.get('state_json') or '{}')
        except Exception:
            item['state'] = {}
        try:
            item['turn_order'] = json.loads(item.get('turn_order_json') or '[]')
        except Exception:
            item['turn_order'] = []
        # Players
        cursor.execute("""
            SELECT p.user_id, p.joined_at, p.left_at, p.character_state_json,
                   u.username, u.titan_number
            FROM game_session_players p
            JOIN users u ON p.user_id = u.id
            WHERE p.session_id = ?
            ORDER BY p.joined_at ASC
        """, (session_id,))
        players = []
        for prow in cursor.fetchall():
            pdict = dict(prow)
            try:
                pdict['character_state'] = json.loads(pdict.get('character_state_json') or '{}')
            except Exception:
                pdict['character_state'] = {}
            pdict.pop('character_state_json', None)
            players.append(pdict)
        item['players'] = players
        conn.close()
        # Strip raw JSON columns (decoded versions are exposed instead)
        item.pop('state_json', None)
        item.pop('turn_order_json', None)
        return item

    def list_active_sessions(self, game_id: Optional[int] = None) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        params: List[Any] = []
        where = "WHERE s.status IN ('lobby','running')"
        if game_id:
            where += " AND s.game_id = ?"
            params.append(game_id)
        cursor.execute(f"""
            SELECT s.id, s.game_id, s.host_id, s.status, s.started_at,
                   g.name AS game_name, u.username AS host_username,
                   COALESCE((SELECT COUNT(*) FROM game_session_players p
                             WHERE p.session_id = s.id AND p.left_at IS NULL), 0) AS player_count
            FROM game_sessions s
            JOIN interactive_games g ON s.game_id = g.id
            JOIN users u ON s.host_id = u.id
            {where}
            ORDER BY s.started_at DESC
        """, params)
        items = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return items

    @_serialized_write
    def add_session_player(self, session_id: int, user_id: int) -> Dict[str, Any]:
        """Join an existing session. Idempotent for re-joins."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.status, g.max_players,
                   (SELECT COUNT(*) FROM game_session_players p
                    WHERE p.session_id = s.id AND p.left_at IS NULL) AS active_players
            FROM game_sessions s
            JOIN interactive_games g ON s.game_id = g.id
            WHERE s.id = ?
        """, (session_id,))
        srow = cursor.fetchone()
        if not srow:
            conn.close()
            return {"success": False, "error": "Session not found"}
        if srow['status'] not in ('lobby', 'running'):
            conn.close()
            return {"success": False, "error": "Session has ended"}

        cursor.execute("""
            SELECT left_at FROM game_session_players
            WHERE session_id = ? AND user_id = ?
        """, (session_id, user_id))
        existing = cursor.fetchone()
        now = datetime.now().isoformat()

        if existing is None:
            if srow['active_players'] >= srow['max_players']:
                conn.close()
                return {"success": False, "error": "Session is full"}
            cursor.execute("""
                INSERT INTO game_session_players (session_id, user_id, character_state_json, joined_at)
                VALUES (?, ?, '{}', ?)
            """, (session_id, user_id, now))
        else:
            # Re-join: clear left_at so the player counts as active again
            cursor.execute("""
                UPDATE game_session_players SET left_at = NULL, joined_at = ?
                WHERE session_id = ? AND user_id = ?
            """, (now, session_id, user_id))
        conn.commit()
        conn.close()
        return {"success": True, "session_id": session_id, "user_id": user_id}

    @_serialized_write
    def remove_session_player(self, session_id: int, user_id: int) -> Dict[str, Any]:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            UPDATE game_session_players SET left_at = ?
            WHERE session_id = ? AND user_id = ? AND left_at IS NULL
        """, (now, session_id, user_id))
        changed = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return {"success": changed, "session_id": session_id, "user_id": user_id}

    @_serialized_write
    def update_session_state(self, session_id: int, state: Dict[str, Any]) -> Dict[str, Any]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE game_sessions SET state_json = ? WHERE id = ?",
                       (json.dumps(state, ensure_ascii=False), session_id))
        conn.commit()
        conn.close()
        return {"success": True, "session_id": session_id}

    @_serialized_write
    def update_session_turn(self, session_id: int, turn_order: List[int],
                            current_turn_idx: int) -> Dict[str, Any]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE game_sessions
            SET turn_order_json = ?, current_turn_idx = ?
            WHERE id = ?
        """, (json.dumps(turn_order), int(current_turn_idx), session_id))
        conn.commit()
        conn.close()
        return {"success": True, "session_id": session_id}

    @_serialized_write
    def update_character_state(self, session_id: int, user_id: int,
                               character_state: Dict[str, Any]) -> Dict[str, Any]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE game_session_players SET character_state_json = ?
            WHERE session_id = ? AND user_id = ?
        """, (json.dumps(character_state, ensure_ascii=False), session_id, user_id))
        conn.commit()
        conn.close()
        return {"success": True}

    @_serialized_write
    def add_session_tokens(self, session_id: int, tokens: int) -> Dict[str, Any]:
        """Increment the per-session token counter, return current total + cap."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE game_sessions SET tokens_used = tokens_used + ?
            WHERE id = ?
        """, (max(0, int(tokens)), session_id))
        cursor.execute("""
            SELECT s.tokens_used, g.max_tokens
            FROM game_sessions s JOIN interactive_games g ON s.game_id = g.id
            WHERE s.id = ?
        """, (session_id,))
        row = cursor.fetchone()
        conn.commit()
        conn.close()
        if not row:
            return {"success": False, "error": "Session not found"}
        return {
            "success": True,
            "tokens_used": row['tokens_used'],
            "max_tokens": row['max_tokens'],
            "exceeded": row['tokens_used'] >= row['max_tokens'],
        }

    @_serialized_write
    def end_game_session(self, session_id: int) -> Dict[str, Any]:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            UPDATE game_sessions SET status = 'ended', ended_at = ?
            WHERE id = ? AND status != 'ended'
        """, (now, session_id))
        changed = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return {"success": changed, "session_id": session_id, "ended_at": now}

    @_serialized_write
    def delete_game_session(self, session_id: int) -> Dict[str, Any]:
        """Hard-delete a session row plus its players + log (atomic)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("DELETE FROM game_session_log WHERE session_id = ?", (session_id,))
            cursor.execute("DELETE FROM game_session_players WHERE session_id = ?", (session_id,))
            cursor.execute("DELETE FROM game_sessions WHERE id = ?", (session_id,))
            changed = cursor.rowcount > 0
            conn.commit()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            logger.error(f"[GAMES] delete_game_session crashed: {e}", exc_info=True)
            return {"success": False, "session_id": session_id, "error": "Database error"}
        conn.close()
        return {"success": changed, "session_id": session_id}

    @_serialized_write
    def delete_all_game_sessions(self) -> Dict[str, Any]:
        """Wipe every session row + all session-scoped children (atomic).

        Admin-tool path. ALWAYS call from the running server process via
        a handler — never from a parallel `Database()` standalone script,
        or you risk SQLCipher page corruption (see sqlcipher_safety.md).
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("DELETE FROM game_session_log")
            log_deleted = cursor.rowcount
            cursor.execute("DELETE FROM game_session_players")
            players_deleted = cursor.rowcount
            cursor.execute("DELETE FROM game_sessions")
            sessions_deleted = cursor.rowcount
            conn.commit()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            logger.error(f"[GAMES] delete_all_game_sessions crashed: {e}", exc_info=True)
            return {"success": False, "error": "Database error"}
        conn.close()
        return {
            "success": True,
            "sessions_deleted": sessions_deleted,
            "players_deleted": players_deleted,
            "log_deleted": log_deleted,
        }

    @_serialized_write
    def set_session_status(self, session_id: int, status: str) -> Dict[str, Any]:
        if status not in ('lobby', 'running', 'ended'):
            return {"success": False, "error": "Invalid status"}
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE game_sessions SET status = ? WHERE id = ?",
                       (status, session_id))
        conn.commit()
        conn.close()
        return {"success": True, "status": status}

    @_serialized_write
    def log_session_event(self, session_id: int, turn_n: int, actor: str,
                          action_type: str, payload: Optional[Dict] = None) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO game_session_log
                (session_id, turn_n, actor, action_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, int(turn_n), actor, action_type,
              json.dumps(payload or {}, ensure_ascii=False), now))
        log_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return log_id or 0

    def get_session_log(self, session_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, turn_n, actor, action_type, payload_json, created_at
            FROM game_session_log
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (session_id, limit))
        rows = cursor.fetchall()
        conn.close()
        items = []
        for r in rows:
            d = dict(r)
            try:
                d['payload'] = json.loads(d.get('payload_json') or '{}')
            except Exception:
                d['payload'] = {}
            d.pop('payload_json', None)
            items.append(d)
        return items
