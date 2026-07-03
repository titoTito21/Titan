# Titan-Net mail server setup (VPS)

This document explains how to stand up the mail subsystem on the production
Titan-Net VPS (titosofttitan.com). It covers **outbound** transactional mail
(email verification + password recovery) and **inbound** delivery to user
mailboxes (`username@titosofttitan.com`) that the in-app / web Mail client reads.

> The application code (server, endpoints, mailer, delivery pipe) is already in
> the repo. This document is the **host-level** part that only the VPS operator
> can do: install Postfix + OpenDKIM and publish DNS records. Nothing here can
> be done from a developer machine.

Everything runs self-hosted: outbound mail leaves via the local Postfix; the
app hands messages to `127.0.0.1:25`, so the Python code is identical whether
you keep Postfix local or later switch `SMTP_*` to an external relay.

---

## 0. Prerequisites / decisions

- A domain you control DNS for: `titosofttitan.com`.
- A mail hostname, e.g. `mail.titosofttitan.com`, pointing (A/AAAA) at the VPS IP.
- The VPS provider must let you set **reverse DNS (PTR)** for the IP to
  `mail.titosofttitan.com`. Without PTR, big providers (Gmail) reject or spam
  your mail.
- Ports 25 (inbound + outbound SMTP) and 587 (submission, optional) open.

## 1. Titan-Net `.env` keys

Set these in `/opt/titan-net/.env` (see `.env.example`) and restart the service:

```
MAIL_ENABLED=1
MAIL_DOMAIN=titosofttitan.com
MAIL_FROM=no-reply@titosofttitan.com
MAIL_FROM_NAME=Titan-Net
MAIL_PUBLIC_URL=https://titosofttitan.com
SMTP_HOST=127.0.0.1
SMTP_PORT=25
SMTP_USER=
SMTP_PASS=
SMTP_TLS=0
# Random shared secret for the inbound delivery pipe:
MAIL_INGEST_TOKEN=<python -c "import secrets;print(secrets.token_urlsafe(32))">
```

`MAIL_ENABLED=0` (the default) keeps the whole feature dark: the app logs
"would have sent…" instead of sending, so nothing breaks before DNS is ready.

## 2. DNS records (publish at your DNS host)

Replace `<VPS_IP>` with the server's public IPv4.

| Type  | Name                         | Value                                                        |
|-------|------------------------------|-------------------------------------------------------------|
| A     | `mail.titosofttitan.com`     | `<VPS_IP>`                                                   |
| MX    | `titosofttitan.com`          | `10 mail.titosofttitan.com.`                                 |
| TXT   | `titosofttitan.com` (SPF)    | `v=spf1 a mx ip4:<VPS_IP> -all`                              |
| TXT   | `default._domainkey...`      | DKIM public key from step 4 (`v=DKIM1; k=rsa; p=...`)        |
| TXT   | `_dmarc.titosofttitan.com`   | `v=DMARC1; p=quarantine; rua=mailto:postmaster@titosofttitan.com` |

Plus **PTR** (reverse DNS) `<VPS_IP> -> mail.titosofttitan.com` — set this in
the VPS provider's control panel, not your DNS zone.

## 3. Install Postfix

```bash
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y postfix
```

Choose "Internet Site", system mail name `titosofttitan.com`. Then edit
`/etc/postfix/main.cf`:

```
myhostname = mail.titosofttitan.com
mydestination =            # leave empty; virtual handles our domain
virtual_mailbox_domains = titosofttitan.com
virtual_transport = titanmail:
inet_interfaces = all
inet_protocols = ipv4
# TLS for outbound (uses a Let's Encrypt cert if you have one)
smtp_tls_security_level = may
smtpd_tls_security_level = may
```

Add the **pipe transport** in `/etc/postfix/master.cf` (one entry) so every
message for our domain is handed to the Titan delivery script:

```
titanmail unix - n n - - pipe
  flags=Rq user=titan argv=/opt/titan-net/venv/bin/python /opt/titan-net/mail_delivery.py ${recipient}
```

`mail_delivery.py` does **not** open the SQLCipher DB (the running service holds
a single-writer lock). It parses the message and POSTs it to the local
`/api/mail/incoming` endpoint using `MAIL_INGEST_TOKEN`; the server writes it.

Reload: `sudo systemctl reload postfix`.

## 4. DKIM with OpenDKIM

```bash
sudo apt-get install -y opendkim opendkim-tools
sudo mkdir -p /etc/opendkim/keys/titosofttitan.com
cd /etc/opendkim/keys/titosofttitan.com
sudo opendkim-genkey -s default -d titosofttitan.com
sudo chown -R opendkim:opendkim /etc/opendkim
sudo cat default.txt   # -> publish this as the DKIM TXT record (step 2)
```

`/etc/opendkim.conf` essentials:

```
Domain                  titosofttitan.com
Selector                default
KeyFile                 /etc/opendkim/keys/titosofttitan.com/default.private
Socket                  inet:8891@localhost
Mode                    sv
```

Wire the milter into Postfix `main.cf`:

```
milter_default_action = accept
smtpd_milters = inet:localhost:8891
non_smtpd_milters = inet:localhost:8891
```

```bash
sudo systemctl enable --now opendkim
sudo systemctl restart opendkim postfix
```

## 5. Verify

```bash
# Outbound + auth: from the VPS, hit the app once (or trigger a real
# password-reset from the web) and confirm the mail arrives (not spam):
echo 'test' | mail -s 'titan test' you@gmail.com

# Score your setup:
#   send a message to the address shown by https://www.mail-tester.com
# and aim for 10/10 (SPF, DKIM, DMARC, PTR all green).

# Inbound: send an email to <someuser>@titosofttitan.com from an external
# account; it should appear in that user's inbox in the app / web Mail client.
# If not, check:
sudo tail -f /var/log/mail.log
sudo journalctl -u titan-net -f     # ingest endpoint hits
```

Common gotchas:
- Mail lands in spam -> missing/incorrect SPF, DKIM, or PTR.
- Inbound 403 in the app log -> `MAIL_INGEST_TOKEN` mismatch between `.env` and
  what `mail_delivery.py` reads (it reads the same `.env` via `config.py`).
- "Relay access denied" on inbound -> `virtual_mailbox_domains` doesn't list
  `titosofttitan.com`, or the `titanmail` transport isn't in `master.cf`.

## 6. Deploy the app changes

The Python/JS changes deploy with the normal flow:

```bash
python "titan-net server/update.py"     # from the repo, per project convention
```

DB migrations (email columns, verification/reset/mail tables) are idempotent and
run at service startup. Enable mail by flipping `MAIL_ENABLED=1` once DNS +
Postfix are in place.
