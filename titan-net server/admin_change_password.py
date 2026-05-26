"""One-off CLI: change any titan-net user's password via the admin API.

Usage (interactive, recommended):
    python admin_change_password.py

Usage (scripted, for one-shot runs):
    python admin_change_password.py \\
        --admin-username Tito --admin-password '...' \\
        --target Tito --new-password '...'

Flow:
  1. WS-login as a developer account (your normal admin login).
  2. Build the HTTP Bearer token the same way the server constructs it
     (base64('<user_id>:<username>')).
  3. POST /api/moderation/change_password.

Run from any machine that can reach wss://titosofttitan.com:8001 and
https://titosofttitan.com/api/. No direct DB access — safe even while the
server is live (no parallel Database() instance gets opened).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import json
import ssl
import sys

import aiohttp
import websockets


DEFAULT_WS = 'wss://titosofttitan.com:8001'
DEFAULT_API = 'https://titosofttitan.com/api'


async def ws_login(ws_url: str, username: str, password: str) -> dict:
    # The server uses Let's Encrypt; default SSL context is fine.
    ssl_ctx = ssl.create_default_context()
    async with websockets.connect(ws_url, ssl=ssl_ctx, max_size=2 ** 24) as ws:
        await ws.send(json.dumps({
            'type': 'login',
            'username': username,
            'password': password,
            'language': 'en',
        }))
        # The server can interleave broadcasts before the login_response; loop
        # until we see the one we want, with a hard ceiling.
        for _ in range(50):
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            try:
                msg = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if msg.get('type') == 'login_response':
                return msg
        raise RuntimeError('No login_response from server')


def build_token(user_id: int, username: str) -> str:
    raw = f'{user_id}:{username}'.encode('utf-8')
    return base64.b64encode(raw).decode('ascii')


async def call_change_password(api_base: str, token: str,
                               target_username: str, new_password: str) -> dict:
    headers = {'Authorization': f'Bearer {token}'}
    payload = {'username': target_username, 'new_password': new_password}
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f'{api_base}/moderation/change_password',
            json=payload, headers=headers,
        ) as resp:
            try:
                return await resp.json()
            except aiohttp.ContentTypeError:
                return {'success': False, 'error': f'HTTP {resp.status}',
                        'body': await resp.text()}


async def amain(args: argparse.Namespace) -> int:
    admin_username = args.admin_username or input('Admin username: ').strip()
    admin_password = args.admin_password or getpass.getpass('Admin password: ')
    target = args.target or input('Target username: ').strip()
    new_password = args.new_password or getpass.getpass('New password for target: ')

    print(f'[1/2] Logging in as {admin_username!r}...')
    login = await ws_login(args.ws, admin_username, admin_password)
    if not login.get('success'):
        print(f'  login failed: {login.get("error")}')
        return 2
    user = login.get('user') or {}
    user_id = user.get('id')
    if not user_id:
        print('  login response missing user.id — aborting')
        return 2
    token = build_token(user_id, admin_username)
    print(f'  ok — user_id={user_id}')

    print(f'[2/2] Resetting password for {target!r}...')
    result = await call_change_password(args.api, token, target, new_password)
    print('  ' + json.dumps(result, indent=2))
    return 0 if result.get('success') else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ws', default=DEFAULT_WS, help=f'WebSocket URL (default: {DEFAULT_WS})')
    p.add_argument('--api', default=DEFAULT_API, help=f'HTTPS API base (default: {DEFAULT_API})')
    p.add_argument('--admin-username')
    p.add_argument('--admin-password')
    p.add_argument('--target')
    p.add_argument('--new-password')
    args = p.parse_args()
    return asyncio.run(amain(args))


if __name__ == '__main__':
    sys.exit(main())
