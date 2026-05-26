# Titan-Net Web Portal

Accessible browser front-end for Titan-Net. Mirrors the desktop UI in standard
web layout (WCAG 2.2 AA) with Polish / English i18n.

**Public URL:** https://titosofttitan.com/titannet/

## Architecture

- **Static files** served by Apache from `/opt/titan-net/web/` (aiohttp also
  serves `/titannet/` as a fallback).
- **REST API** at `/api/*` — Apache reverse-proxies to aiohttp on `127.0.0.1:8000`.
- **WebSocket** at `wss://titosofttitan.com:8001` — direct to `server.py` (the
  server terminates TLS using the same Let's Encrypt cert as Apache).
- **Cerberus** protects both layers. The WS layer was already gated; HTTP now
  goes through `_cerberus_middleware` (banned IPs → 403, lockdown → 503).

## Files

| File | Purpose |
| ---- | ------- |
| `index.html`        | Landing page |
| `login.html`        | Log in |
| `register.html`     | Sign up |
| `chat.html`         | Rooms + online users + voice + MOTD modal |
| `repository.html`   | Browse app repository |
| `forum.html`        | Forum topic list + thread view + new-topic dialog |
| `account.html`      | Signed-in user info + logout |
| `css/titan.css`     | WCAG AA stylesheet (light + dark, prefers-reduced-motion) |
| `js/i18n.js`        | `Titan.t()` + PL / EN string table |
| `js/app.js`         | Header / theme / language switchers + live region |
| `js/api.js`         | Fetch wrapper for `/api/*` |
| `js/ws.js`          | WebSocket client mirroring the desktop protocol |
| `js/voice.js`       | Web Audio mic capture → 16 kHz PCM → binary WS frame |
| `js/auth.js`        | Login / register pages |
| `js/chat.js`        | Chat page logic |
| `js/repository.js`  | Repository page logic |
| `js/forum.js`       | Forum page logic |

## Accessibility highlights (WCAG 2.2 AA)

- Skip link, `<header>/<nav>/<main>/<aside>/<footer>` landmarks.
- Focus indicator: 3 px outline with `--focus` colour (≥ 3 : 1 vs both themes).
- All text contrast ≥ 4.5 : 1 in both light and dark themes.
- 44 × 44 px minimum target size on every interactive control.
- `aria-live="polite"` region on every page + chat log marked `role="log"`.
- Native `<dialog>` for MOTD and new-topic modals (handles focus trap +
  Escape).
- `prefers-reduced-motion` honoured; `forced-colors` (Windows high contrast)
  honoured.
- Form fields: `aria-required`, `aria-invalid`, `aria-describedby` for errors.
- Polish / English switch persists in `localStorage` and updates `lang` attr.

## How login flows from browser to server

1. `login.html` opens `wss://titosofttitan.com:8001`, sends `{type:'login', ...}`.
2. On success, the user blob and the REST API token (`base64(id:username)`)
   are stored in `localStorage`. The password is stashed in `sessionStorage`
   (per-tab) so `chat.html` can re-login on its own WS connection, then it
   is immediately discarded.
3. `chat.html` opens a fresh WS, re-logs in, fetches rooms / users and
   shows the MOTD modal once per new MOTD hash.

## Message of the Day

The server returns `motd = {text, hash}` in `login_response`. The browser
shows it in a native `<dialog>` only when the hash differs from the
previously seen one (kept in `localStorage` under `titan.motd_hash`).

## Voice chat

`voice.js` requests microphone permission, captures audio at 16 kHz mono,
packs each frame as the same 13-byte binary header (`type, room_id, user_id,
seq`) the desktop client uses, and sends raw Int16 LE PCM payload over the
existing WS. Incoming frames are decoded back into Float32 and queued through
a Web Audio chain. Echo / noise / AGC are enabled in `getUserMedia` so the
browser handles AEC by default.

## Cerberus

Same `Cerberus` instance protects WS and HTTP. The HTTP middleware:

- 403 if the source IP is in `_banned_ips` or `_permanent_banned_ips`.
- 503 if a global lockdown is active and the IP is not whitelisted.
- OAuth callbacks (`/oauth/...`) bypass the gate so providers can always
  reach us.

`X-Forwarded-For` is set by Apache so the middleware sees the real client IP.
