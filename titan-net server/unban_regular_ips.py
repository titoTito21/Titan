"""
One-shot script: unban regular-user IPs from cerberus_bans.db but KEEP
cloud provider IPs banned (DigitalOcean, AWS, Hetzner, Vultr, Linode,
OVH, Contabo, Akamai, etc.).

Also removes corresponding firewall rules (iptables + ufw) for unbanned IPs.
"""
import sqlite3
import subprocess
import sys

sys.path.insert(0, "/opt/titan-net")
from hackback import identify_cloud_provider

DB = "/opt/titan-net/database/cerberus_bans.db"
BLOCKED_PORTS = [8000, 8001]


def run(cmd):
    try:
        subprocess.run(cmd, capture_output=True, timeout=5)
    except Exception:
        pass


def unblock_firewall(ip):
    for port in BLOCKED_PORTS:
        run(['iptables', '-D', 'INPUT', '-s', ip, '-p', 'tcp',
             '--dport', str(port), '-j', 'DROP'])
        # Delete all copies (rules sometimes duplicated)
        for _ in range(5):
            run(['iptables', '-D', 'INPUT', '-s', ip, '-p', 'tcp',
                 '--dport', str(port), '-j', 'DROP'])
        # ufw
        p = subprocess.Popen(
            ['ufw', 'delete', 'deny', 'from', ip, 'to', 'any',
             'port', str(port)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            p.communicate(b'y\n', timeout=5)
        except Exception:
            p.kill()


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT ip, reason, threat_level FROM banned_ips")
    all_bans = cur.fetchall()

    cloud_ips = []
    regular_ips = []

    for ip, reason, level in all_bans:
        provider = identify_cloud_provider(ip)
        if provider:
            cloud_ips.append((ip, provider, reason or ""))
        else:
            regular_ips.append((ip, reason or "", level))

    print(f"Total bans in DB: {len(all_bans)}")
    print(f"Cloud IPs (KEEP BANNED): {len(cloud_ips)}")
    for ip, prov, reason in cloud_ips:
        print(f"  [KEEP] {ip:<20} [{prov}] - {reason[:60]}")

    print(f"\nRegular IPs (WILL UNBAN): {len(regular_ips)}")
    for ip, reason, level in regular_ips:
        print(f"  [UNBAN] {ip:<20} L{level} - {reason[:60]}")

    print("\nUnbanning regular IPs...")
    for ip, _, _ in regular_ips:
        # Remove from DB
        cur.execute("DELETE FROM banned_ips WHERE ip = ?", (ip,))
        # Remove firewall rules
        unblock_firewall(ip)
        print(f"  Unbanned: {ip}")

    conn.commit()
    conn.close()

    print(f"\nDone. Unbanned {len(regular_ips)} regular IPs, "
          f"kept {len(cloud_ips)} cloud IPs banned.")


if __name__ == "__main__":
    main()
