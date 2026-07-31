#!/usr/bin/env python3
"""
Remote UI / server sound admin - publish server-defined GUIs and sounds.

Runs from ANY machine that can reach the server. It logs in over WebSocket
the way a normal client does, then drives the HTTP API - it never opens the
database directly, because a second ``Database()`` alongside the live server
corrupts SQLCipher (see sqlcipher_safety.md rule 1, and the PID lock that
enforces it). Same approach as ``admin_change_password.py``.

    python remote_ui_admin.py screens
    python remote_ui_admin.py save remote_ui_handlers/example_service.json \\
           --slug noticeboard --handler example_service
    python remote_ui_admin.py show noticeboard
    python remote_ui_admin.py delete noticeboard
    python remote_ui_admin.py submissions noticeboard
    python remote_ui_admin.py push noticeboard --user ala

    python remote_ui_admin.py sounds
    python remote_ui_admin.py add-sound notify /path/to/notify.ogg -d "Generic ping"
    python remote_ui_admin.py play notify --user ala
    python remote_ui_admin.py play notify --all --say "Time is up"
    python remote_ui_admin.py del-sound notify

Credentials come from ``--user``/``--password``, the ``TITAN_ADMIN_USER`` /
``TITAN_ADMIN_PASSWORD`` environment variables, or an interactive prompt.
The account must be staff (moderator, developer or admin).

``--handler`` is checked against the handlers this machine can import from
``remote_ui_handlers/``; run it on the server, or pass ``--no-handler-check``
when publishing from a workstation that does not have the handler files.
"""

import argparse
import asyncio
import base64
import getpass
import json
import os
import ssl
import sys

import aiohttp
import websockets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import remote_ui  # noqa: E402

DEFAULT_WS = os.environ.get('TITAN_ADMIN_WS', 'wss://titosofttitan.com:8001')
DEFAULT_API = os.environ.get('TITAN_ADMIN_API', 'https://titosofttitan.com/api')


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------

def _load_handlers():
    """Import remote_ui_handlers/*.py so --handler can be checked locally."""
    import importlib.util
    directory = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'remote_ui_handlers')
    if not os.path.isdir(directory):
        return
    for name in sorted(os.listdir(directory)):
        if not name.endswith('.py') or name.startswith('_'):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"remote_ui_handlers.{name[:-3]}", os.path.join(directory, name))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"warning: handler module {name} did not load: {e}")


async def _login(args) -> str:
    """WS-login and return the HTTP Bearer token, exactly like a client does."""
    username = (args.user or os.environ.get('TITAN_ADMIN_USER')
                or input('Titan-Net username: ').strip())
    password = (args.password or os.environ.get('TITAN_ADMIN_PASSWORD')
                or getpass.getpass(f'Password for {username}: '))

    ssl_ctx = ssl.create_default_context() if args.ws.startswith('wss') else None
    async with websockets.connect(args.ws, ssl=ssl_ctx, max_size=2 ** 24) as ws:
        await ws.send(json.dumps({'type': 'login', 'username': username,
                                  'password': password, 'language': 'en'}))
        login = None
        # Broadcasts can arrive before our response; read until we see it.
        for _ in range(50):
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if message.get('type') == 'login_response':
                login = message
                break
        if login is None:
            sys.exit("No login_response from the server")

    if not login.get('success'):
        sys.exit(f"Login failed: {login.get('error')}")
    # Prefer the signed, role-bound token the server issued; fall back to the
    # legacy format only for servers still running in grace mode.
    token = login.get('http_token') or login.get('token')
    if token:
        return token
    user = login.get('user') or {}
    if not user.get('id'):
        sys.exit("Login response carried no user id")
    return base64.b64encode(f"{user['id']}:{username}".encode()).decode()


class Api:
    """Thin HTTP wrapper that reports failures in one place."""

    def __init__(self, base: str, token: str):
        self.base = base.rstrip('/')
        self.headers = {'Authorization': f'Bearer {token}'}

    async def request(self, method: str, path: str, **kwargs):
        async with aiohttp.ClientSession() as session:
            async with session.request(method, f"{self.base}{path}",
                                       headers=self.headers, **kwargs) as resp:
                try:
                    return await resp.json()
                except aiohttp.ContentTypeError:
                    return {'success': False,
                            'error': f'HTTP {resp.status}',
                            'body': (await resp.text())[:500]}

    async def get(self, path, **kw):
        return await self.request('GET', path, **kw)

    async def post(self, path, **kw):
        return await self.request('POST', path, **kw)

    async def delete(self, path, **kw):
        return await self.request('DELETE', path, **kw)


def _target_from(args) -> dict:
    """Turn --all / --to / --role / --room into a target the server understands."""
    if getattr(args, 'all', False):
        return {'type': 'all'}
    if getattr(args, 'to', None):
        return {'type': 'user', 'username': args.to}
    if getattr(args, 'role', None):
        return {'type': 'role', 'role': args.role.lower()}
    if getattr(args, 'room', None) is not None:
        return {'type': 'room', 'room_id': int(args.room)}
    return {'type': 'all'}


def _fail(result: dict):
    sys.exit(f"Failed: {result.get('error') or result}")


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------

async def cmd_screens(api: Api, args):
    result = await api.get('/remote-screens', params={'all': '1'})
    if not result.get('success'):
        _fail(result)
    screens = result.get('screens') or []
    if not screens:
        print("No remote screens defined.")
        return
    for screen in screens:
        state = 'active' if screen['active'] else 'disabled'
        menu = 'menu' if screen['in_menu'] else 'hidden'
        print(f"{screen['slug']:<24} v{screen['version']:<3} {state:<9} "
              f"{menu:<7} {screen['audience']:<11} "
              f"handler={screen['handler']:<24} {screen['title']}")


async def cmd_show(api: Api, args):
    result = await api.get(f'/remote-screens/{args.slug}')
    if not result.get('success'):
        _fail(result)
    screen = result['screen']
    try:
        screen['definition'] = json.loads(screen['definition'])
    except Exception:
        pass
    print(json.dumps(screen, indent=2, ensure_ascii=False))


async def cmd_save(api: Api, args):
    with open(args.file, encoding='utf-8') as fh:
        definition = json.load(fh)

    # Validate here as well as server-side so a typo is caught before it is
    # published to everyone.
    ok, why, _normalised = remote_ui.validate_definition(definition)
    if not ok:
        sys.exit(f"Screen definition rejected: {why}")

    handler = args.handler or 'store'
    if not args.no_handler_check and handler not in remote_ui.HANDLERS:
        known = ', '.join(sorted(remote_ui.HANDLERS))
        sys.exit(f"No handler named '{handler}' on this machine. "
                 f"Known here: {known}. Use --no-handler-check if the handler "
                 f"only exists on the server.")

    slug = args.slug or os.path.splitext(os.path.basename(args.file))[0]
    result = await api.post('/remote-screens', json={
        'slug': slug, 'definition': definition, 'handler': handler,
        'audience': args.audience, 'in_menu': not args.no_menu,
        'active': not args.disabled,
    })
    if not result.get('success'):
        _fail(result)
    print(f"Saved '{result['slug']}' as version {result['version']} "
          f"(handler={handler}, audience={args.audience}).")
    print("Clients pick it up on their next 'Refresh Server Screens' or reconnect.")


async def cmd_delete(api: Api, args):
    result = await api.delete(f'/remote-screens/{args.slug}')
    if not result.get('success'):
        _fail(result)
    print(f"Deleted screen '{args.slug}'.")


async def cmd_submissions(api: Api, args):
    result = await api.get(f'/remote-screens/{args.slug}/submissions',
                           params={'limit': args.limit})
    if not result.get('success'):
        _fail(result)
    rows = result.get('submissions') or []
    if not rows:
        print("No submissions.")
        return
    for row in rows:
        print(f"[{row['created_at']}] {row['username']} ({row['action']}): "
              f"{json.dumps(row['payload'], ensure_ascii=False)}")


async def cmd_push(api: Api, args):
    result = await api.post(f'/remote-screens/{args.slug}/push',
                            json={'target': _target_from(args)})
    if not result.get('success'):
        _fail(result)
    print(f"Opened '{args.slug}' on {result.get('pushed_to', 0)} client(s).")


# ---------------------------------------------------------------------------
# Sounds
# ---------------------------------------------------------------------------

async def cmd_sounds(api: Api, args):
    result = await api.get('/sounds')
    if not result.get('success'):
        _fail(result)
    sounds = result.get('sounds') or []
    if not sounds:
        print("No server sounds registered.")
        return
    for sound in sounds:
        size_kb = max(1, int(sound['size'] / 1024))
        print(f"{sound['name']:<24} {size_kb:>6} KB  {sound['sha256'][:12]}  "
              f"{sound.get('description') or ''}")


async def cmd_add_sound(api: Api, args):
    extension = os.path.splitext(args.file)[1].lower()
    if extension not in ('.ogg', '.wav', '.mp3', '.opus', '.flac'):
        sys.exit(f"Unsupported format '{extension}'")
    with open(args.file, 'rb') as fh:
        payload = fh.read()
    result = await api.post('/sounds', json={
        'name': args.name,
        'filename': os.path.basename(args.file),
        'description': args.description,
        'content': base64.b64encode(payload).decode(),
    })
    if not result.get('success'):
        _fail(result)
    print(f"Registered '{result['name']}' ({len(payload)} bytes, "
          f"sha256 {result['sha256'][:12]}).")


async def cmd_del_sound(api: Api, args):
    result = await api.delete(f'/sounds/{args.name}')
    if not result.get('success'):
        _fail(result)
    print(f"Deleted sound '{args.name}'.")


async def cmd_play(api: Api, args):
    body = {'target': _target_from(args), 'volume': args.volume}
    if args.say:
        body['announce'] = args.say
    result = await api.post(f'/sounds/{args.name}/play', json=body)
    if not result.get('success'):
        _fail(result)
    print(f"Played to {result.get('played_to', 0)} listener(s).")


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def _add_target_flags(parser):
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--all', action='store_true', help="Everyone online (default)")
    group.add_argument('--to', metavar='USERNAME', help="One user")
    group.add_argument('--role', help="Everyone with a role, e.g. moderator")
    group.add_argument('--room', type=int, help="Everyone in a chat room")


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--ws', default=DEFAULT_WS, help=f"default: {DEFAULT_WS}")
    parser.add_argument('--api', default=DEFAULT_API, help=f"default: {DEFAULT_API}")
    parser.add_argument('--user', help="Staff account to act as")
    parser.add_argument('--password', help="Prompted for if omitted")
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('screens', help="List every remote screen").set_defaults(func=cmd_screens)

    show = sub.add_parser('show', help="Print one screen's stored definition")
    show.add_argument('slug')
    show.set_defaults(func=cmd_show)

    save = sub.add_parser('save', help="Create or replace a screen from a JSON file")
    save.add_argument('file')
    save.add_argument('--slug', help="Defaults to the file name")
    save.add_argument('--handler', default='store', help="Server-side handler")
    save.add_argument('--audience', default='everyone',
                      choices=['everyone', 'moderators', 'admins'])
    save.add_argument('--no-menu', action='store_true',
                      help="Do not offer it in the client's Server menu")
    save.add_argument('--disabled', action='store_true',
                      help="Store it but keep it closed to clients")
    save.add_argument('--no-handler-check', action='store_true',
                      help="Publish even if the handler is not importable here")
    save.set_defaults(func=cmd_save)

    delete = sub.add_parser('delete', help="Remove a screen")
    delete.add_argument('slug')
    delete.set_defaults(func=cmd_delete)

    submissions = sub.add_parser('submissions', help="Show what users sent back")
    submissions.add_argument('slug')
    submissions.add_argument('--limit', type=int, default=50)
    submissions.set_defaults(func=cmd_submissions)

    push = sub.add_parser('push', help="Open a screen on someone's client now")
    push.add_argument('slug')
    _add_target_flags(push)
    push.set_defaults(func=cmd_push)

    sub.add_parser('sounds', help="List registered server sounds").set_defaults(func=cmd_sounds)

    add_sound = sub.add_parser('add-sound', help="Upload and register an audio file")
    add_sound.add_argument('name')
    add_sound.add_argument('file')
    add_sound.add_argument('-d', '--description')
    add_sound.set_defaults(func=cmd_add_sound)

    del_sound = sub.add_parser('del-sound', help="Remove a registered sound")
    del_sound.add_argument('name')
    del_sound.set_defaults(func=cmd_del_sound)

    play = sub.add_parser('play', help="Play a registered sound at someone")
    play.add_argument('name')
    play.add_argument('--volume', type=float, default=1.0)
    play.add_argument('--say', help="Speak this alongside the sound")
    _add_target_flags(play)
    play.set_defaults(func=cmd_play)

    return parser


async def amain(args) -> int:
    token = await _login(args)
    api = Api(args.api, token)
    await args.func(api, args)
    return 0


def main() -> int:
    _load_handlers()
    args = build_parser().parse_args()
    return asyncio.run(amain(args))


if __name__ == '__main__':
    sys.exit(main())
