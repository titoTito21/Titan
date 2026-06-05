"""One-off CLI: delete an interactive game from titan-net via the running server.

Usage (interactive, recommended):
    python admin_delete_game.py --name test

Usage (scripted):
    python admin_delete_game.py \\
        --admin-username Tito --admin-password '...' \\
        --name test --yes

You can also target by id directly:
    python admin_delete_game.py --game-id 7

Flow:
  1. WS-login as a moderator / game-owner account.
  2. `list_games` to resolve the game by name (case-insensitive) -> game_id.
  3. `delete_game` through the live server (cascades sessions + attachments,
     unlinks attachment files, broadcasts `game_deleted`).

Run from any machine that can reach wss://titosofttitan.com:8001. No direct DB
access -- safe even while the server is live (no parallel Database() instance
gets opened, per the SQLCipher singleton rule).
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import ssl
import sys

import websockets


DEFAULT_WS = 'wss://titosofttitan.com:8001'


async def _recv_type(ws, wanted: str, timeout: int = 15) -> dict:
    """Read frames until we see the response type we want (broadcasts skipped)."""
    for _ in range(80):
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        try:
            msg = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if msg.get('type') == wanted:
            return msg
    raise RuntimeError(f'No {wanted} from server')


async def amain(args: argparse.Namespace) -> int:
    admin_username = args.admin_username or input('Admin username: ').strip()
    admin_password = args.admin_password or getpass.getpass('Admin password: ')

    ssl_ctx = ssl.create_default_context()
    async with websockets.connect(args.ws, ssl=ssl_ctx, max_size=2 ** 24) as ws:
        # 1) Login --------------------------------------------------------
        print(f'[1/3] Logging in as {admin_username!r}...')
        await ws.send(json.dumps({
            'type': 'login',
            'username': admin_username,
            'password': admin_password,
            'language': 'en',
        }))
        login = await _recv_type(ws, 'login_response')
        if not login.get('success'):
            print(f'  login failed: {login.get("error")}')
            return 2
        user = login.get('user') or {}
        print(f"  ok -- user_id={user.get('id')}")

        # 2) Resolve game_id ---------------------------------------------
        game_id = args.game_id
        game_name = None
        if not game_id:
            print(f'[2/3] Looking up game by name {args.name!r}...')
            await ws.send(json.dumps({'type': 'list_games'}))
            listing = await _recv_type(ws, 'list_games_response')
            if not listing.get('success'):
                print(f'  list_games failed: {listing.get("error")}')
                return 1
            games = listing.get('games') or []
            matches = [g for g in games if (g.get('name') or '').strip().lower()
                       == args.name.strip().lower()]
            if not matches:
                print(f'  no active game named {args.name!r}. Active games:')
                for g in games:
                    print(f"    id={g['id']:<4} {g['name']!r} "
                          f"(by {g.get('creator_username')})")
                return 1
            if len(matches) > 1:
                print(f'  multiple games named {args.name!r} -- rerun with --game-id:')
                for g in matches:
                    print(f"    id={g['id']:<4} (by {g.get('creator_username')}, "
                          f"updated {g.get('updated_at')})")
                return 1
            game_id = matches[0]['id']
            game_name = matches[0]['name']
            print(f'  found id={game_id} ({game_name!r}, '
                  f"by {matches[0].get('creator_username')})")
        else:
            print(f'[2/3] Using explicit game_id={game_id}')

        # 3) Confirm + delete --------------------------------------------
        label = f"{game_name!r} (id={game_id})" if game_name else f'id={game_id}'
        if not args.yes:
            ans = input(f'[3/3] Delete game {label} from PRODUCTION? [y/N]: ').strip().lower()
            if ans not in ('y', 'yes'):
                print('  aborted.')
                return 0
        else:
            print(f'[3/3] Deleting game {label}...')

        await ws.send(json.dumps({'type': 'delete_game', 'game_id': game_id}))
        result = await _recv_type(ws, 'delete_game_response')
        if result.get('success'):
            print(f"  deleted game {result.get('name')!r} (id={result.get('game_id')})")
            return 0
        print(f"  delete failed: {result.get('error')}")
        return 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--ws', default=DEFAULT_WS, help=f'WebSocket URL (default: {DEFAULT_WS})')
    p.add_argument('--admin-username')
    p.add_argument('--admin-password')
    p.add_argument('--name', default='test', help="Game name to delete (default: 'test')")
    p.add_argument('--game-id', type=int, help='Delete by id instead of resolving by name')
    p.add_argument('--yes', action='store_true', help='Skip the confirmation prompt')
    args = p.parse_args()
    return asyncio.run(amain(args))


if __name__ == '__main__':
    sys.exit(main())
