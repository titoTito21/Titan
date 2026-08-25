#!/usr/bin/env python3
"""
Give the bans that were already in the database a TERM.

Until 2026-08-24 the ``permanent`` column was written on every ban and never
read back, so a LOCKDOWN ban the code called temporary was restored at every
boot and enforced for ever. Production had accumulated 295 addresses that way,
and among them - measured from the auth log - 194 had made exactly ONE failed
login and 94 had made two: addresses banned for converging on a username
('root', 'crypto', 'docker'), which is what every scanner on the internet
tries against every host it walks past.

The code now sets ``expires_at`` on each new LOCKDOWN ban, escalating with the
offence count, and permanent only at CERBERUS level or after four offences.
This applies the same policy backwards to the rows that already exist.

  * A permanent ban (CERBERUS level) is left exactly as it is.
  * A LOCKDOWN ban gets ``banned_at + term(offences)``. Most are older than
    their term, so they lapse at the next hourly sweep - which is the point:
    they have served longer than the policy would ever have given them.
  * ``--grace N`` holds every lapse back by N minutes so the release is
    spread out rather than landing as one burst of iptables deletions.

Nothing here touches cerberus_whitelist.txt or titannet.db, and it opens no
connection to the live server's database - run it with the service stopped,
the way cerberus_reset.py is run.

Usage:
    python cerberus_backfill_terms.py --dry-run
    python cerberus_backfill_terms.py --yes [--grace 15]
"""

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime

DB = os.path.join("database", "cerberus_bans.db")

# Must match DangerousCerberus.BAN_TERMS.
BAN_TERMS = (24 * 3600, 3 * 24 * 3600, 7 * 24 * 3600, 30 * 24 * 3600)


def term_for(offences: int) -> float:
    """The term a legacy row gets. Never 0 - see below.

    The live policy stops letting an address out after four offences, and this
    script deliberately does NOT apply that half backwards. ``total_attempts``
    is the offence count, and on these rows it is inflated by the very bug
    being fixed: the distributed-attack handler re-banned every participating
    address each time it fired, and it fired sixteen times in one morning with
    a growing list, so an address that was seen once could carry a dozen
    'offences' it never committed. Promoting those to permanent would make the
    false positives permanent on the strength of the miscount that created
    them. A legacy row therefore gets a term - at most the longest one - and
    earns a permanent ban only by re-offending under the corrected rules.
    """
    return float(BAN_TERMS[min(offences, len(BAN_TERMS) - 1)])


# Reasons that identify a ban the answer channel manufactured rather than one
# the attacker earned. 'tar_pit_connection' is the username the tar pit reports
# for a connection with no login at all, so it only ever appears for traffic
# that reached the tar pit - and once the channel is open, that is our own
# redirect of the address's ordinary SSH retries.
MANUFACTURED = ("tar_pit_connection",)


def is_manufactured(reason: str) -> bool:
    r = (reason or "").lower()
    return any(m in r for m in MANUFACTURED)


def parse_when(value: str) -> float:
    try:
        return datetime.fromisoformat(value).timestamp()
    except Exception:
        return time.time()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--grace", type=int, default=15,
                    help="minutes before the earliest lapse (default 15)")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"[ERROR] no ban database at {args.db}")
        return 1
    if not (args.dry_run or args.yes):
        print("Refusing to write without --yes (or use --dry-run).")
        return 1

    now = time.time()
    floor = now + args.grace * 60

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(banned_ips)")}
        if "expires_at" not in cols:
            conn.execute("ALTER TABLE banned_ips ADD COLUMN expires_at REAL DEFAULT 0")
            conn.commit()

        rows = conn.execute(
            "SELECT ip, banned_at, permanent, threat_level, total_attempts, "
            "       COALESCE(expires_at, 0) AS expires_at, reason "
            "FROM banned_ips").fetchall()

        kept_permanent = 0
        already = 0
        demoted = 0
        updates = []
        for r in rows:
            if r["permanent"]:
                # A permanent ban that the ANSWER CHANNEL manufactured is not
                # a verdict about the attacker, it is a verdict about our own
                # redirect. Cerberus put a `REDIRECT --to-ports 2223` in front
                # of a banned address's port 22 so Blackwall could speak to
                # it; the bot's next two SSH retries landed in the tar pit and
                # were read as "2nd login attempt - confirmed attacker",
                # which is a permanent all-ports ban plus countermeasures.
                # 217 of the 224 permanent bans on this server say exactly
                # that. They are demoted to a term like any other LOCKDOWN
                # ban - the address stays blocked, it just stops being blocked
                # for ever on evidence we produced ourselves.
                if is_manufactured(r["reason"]):
                    offences = max(0, int(r["total_attempts"] or 1) - 1)
                    expiry = max(parse_when(r["banned_at"]) + term_for(offences),
                                 floor)
                    updates.append((expiry, 0, r["ip"]))
                    demoted += 1
                    continue
                kept_permanent += 1
                continue
            if r["expires_at"]:
                already += 1
                continue
            # total_attempts counts how many times this row has been re-banned,
            # which is the same thing _seed_offense_history reads for the
            # escalation - so the backfilled term matches what the address
            # would be given today.
            offences = max(0, int(r["total_attempts"] or 1) - 1)
            expiry = max(parse_when(r["banned_at"]) + term_for(offences), floor)
            updates.append((expiry, 0, r["ip"]))

        lapsing_soon = sum(1 for e, p, _ in updates if e <= floor + 1)
        print(f"rows                : {len(rows)}")
        print(f"left permanent      : {kept_permanent}")
        print(f"demoted from wrongly-permanent: {demoted}"
              f"  (manufactured by the answer channel)")
        print(f"already had a term  : {already}")
        print(f"given a term now    : {len(updates)}")
        print(f"  of which lapse at the {args.grace}-minute floor: {lapsing_soon}")
        print(f"  none is promoted to permanent - see term_for()")

        if args.dry_run:
            print("\n--dry-run: nothing written.")
            for expiry, perm, ip in updates[:10]:
                when = "never" if perm else datetime.fromtimestamp(expiry).isoformat(" ", "seconds")
                print(f"  {ip:<18} -> {when}")
            if len(updates) > 10:
                print(f"  ... and {len(updates) - 10} more")
            return 0

        conn.executemany(
            "UPDATE banned_ips SET expires_at = ?, permanent = ? WHERE ip = ?",
            updates)
        conn.commit()
        print(f"\n[OK] {len(updates)} ban(s) now have a term. The server's hourly "
              f"sweep lifts them as they lapse.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
