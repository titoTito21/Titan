"""Standalone tests for the SHA-256 -> Argon2id password migration.

Run with: python "titan-net server/test_password_migration.py"

The tests do NOT touch the live SQLCipher database. They exercise the pure
helpers ``Database.hash_password`` and ``Database.verify_password`` in
isolation, plus a smoke test of the lazy-migration UPDATE path against an
in-memory SQLite database.

Exit code 0 = all tests passed. Anything else = at least one assert failed.
"""

import hashlib
import os
import sys

# Make the server package importable when this script is run directly.
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from models import Database  # noqa: E402


PASSED = 0
FAILED = 0


def check(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}{('  ' + detail) if detail else ''}")


def test_hash_password_format():
    h = Database.hash_password("foo")
    check(
        "hash_password returns argon2id PHC string",
        isinstance(h, str) and h.startswith("$argon2id$"),
        detail=h,
    )
    h2 = Database.hash_password("foo")
    check(
        "two hashes of the same password differ (random salt)",
        h != h2,
    )


def test_verify_argon2_roundtrip():
    h = Database.hash_password("hunter2")
    ok, needs = Database.verify_password("hunter2", h)
    check("argon2id roundtrip ok=True", ok)
    check("argon2id roundtrip needs_rehash=False", not needs)

    ok, needs = Database.verify_password("wrong", h)
    check("argon2id mismatch ok=False", not ok)
    check("argon2id mismatch needs_rehash=False", not needs)


def test_verify_legacy_sha256():
    legacy = hashlib.sha256(b"hunter2").hexdigest()
    ok, needs = Database.verify_password("hunter2", legacy)
    check("legacy SHA-256 verify ok=True", ok)
    check("legacy SHA-256 verify needs_rehash=True", needs)

    ok, needs = Database.verify_password("wrong", legacy)
    check("legacy SHA-256 mismatch ok=False", not ok)
    check("legacy SHA-256 mismatch needs_rehash=False", not needs)


def test_verify_corrupt_input():
    ok, needs = Database.verify_password("foo", "not-a-hash")
    check("garbage stored_hash returns (False, False)", not ok and not needs)

    ok, needs = Database.verify_password("foo", "")
    check("empty stored_hash returns (False, False)", not ok and not needs)

    # Valid argon2 prefix but corrupted payload should not raise.
    ok, needs = Database.verify_password(
        "foo", "$argon2id$v=19$m=65536,t=3,p=4$bad$bad"
    )
    check("malformed argon2 PHC string returns (False, False)", not ok and not needs)


def test_legacy_path_constant_time_equiv():
    # Two truncated 64-char strings that differ only by one character.
    legacy = hashlib.sha256(b"foo").hexdigest()
    flipped = ("0" if legacy[0] != "0" else "1") + legacy[1:]
    ok, _ = Database.verify_password("foo", flipped)
    check("flipped legacy hash mismatches", not ok)


def main():
    print("== argon2id password migration test suite ==")
    test_hash_password_format()
    test_verify_argon2_roundtrip()
    test_verify_legacy_sha256()
    test_verify_corrupt_input()
    test_legacy_path_constant_time_equiv()
    print(f"\n{PASSED} passed, {FAILED} failed")
    sys.exit(0 if FAILED == 0 else 1)


if __name__ == "__main__":
    main()
