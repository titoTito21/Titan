# -*- coding: utf-8 -*-
"""The server Klango's own library talked to, answered inside Cling.

Klango is not a platform an application runs on top of - it is a platform an
application runs *through*.  Before `main()` reaches a single line of its own,
`llib_appsession.lua` has asked klango.net three questions: who is signed in
(`_login`), may this application start (`_StartAppSession`), and - every sixty
seconds afterwards - is this session still the only one (`pingAppSession`).
klango.net has been gone for years, so all three used to answer "no server",
and the games did the correct thing with that answer: `OneInstanceStart`
returned false and `main()` returned before the menu was ever built.  That is
why every emulated application was silent - not because the sound was wrong,
but because the game had already decided it was not allowed to run.

So Cling answers them, because Cling is what they were asking about:

- **the account is the Titan-Net account.**  `_login` answers with the name
  `k_GetUser()` gives, which is what the library then compares against, so a
  signed-in player is `tito` and a player who is not is `local` - and both are
  a real account as far as the application is concerned.  Klango's own
  `default` is the one name that means "nobody", and Cling never uses it.
- **the session is Cling's**, and it is a real one: this process runs one
  instance of an application at a time, which is exactly what
  `_StartAppSession` was protecting.  Asking twice for the same application
  answers `multisession`, the same code the server sent, so the library's own
  handling of it is what runs.
- **the user's records are Titan-Net's** (`_UserSRWrite` / `_UserSRRead`),
  through the extension data the scoreboard already uses.

Everything Klango-only - the shop, the licence, the chat rooms of a network
that no longer exists - answers "finished, nothing", which is a shape the
caller can carry on from.  What it must never answer is nil: `_KRPC` reads
`r.result` on the next line.
"""

import time


#: Klango's own name for "nobody is signed in". `login()` refuses it, so the
#: emulator never reports it - a Titan without a Titan-Net account is still
#: somebody, playing locally.
NOBODY = 'default'


class AppSessionServer(object):
    """One application's view of the server. Held by the Klango session."""

    def __init__(self, host):
        self.host = host
        #: pid -> when it was started. Klango's `pid` is the application's own
        #: name for the session ('mole'), not an operating system process.
        self.sessions = {}
        self.log = []

    # ------------------------------------------------------------- account
    def user(self):
        name = ''
        try:
            name = self.host.whoami().name or ''
        except Exception:
            name = ''
        return name or 'local'

    # ------------------------------------------------------------- answers
    def answer(self, method, arguments):
        """(handled, payload) - payload is what the caller reads as `r.result`.

        `handled` is False for a method this server has no opinion about, so
        the KRPC layer can fall through to the scoreboard and then to
        "finished, nothing" rather than this table having to know about
        everything.
        """
        name = str(method or '')
        low = name.lower()
        self.log.append(name)
        handler = _HANDLERS.get(low)
        if handler is None:
            return False, None
        return True, handler(self, list(arguments))


# --------------------------------------------------------------- handlers
def _login(server, _arguments):
    """The klangoid of whoever is playing.

    `login()` compares this with `k_GetUser()` and is happy when they match,
    so answering with the same name is what signs the player in.
    """
    return server.user()


def _start(server, arguments):
    """`_StartAppSession(user, driveid, pid)`.

    A second start for the same pid is a real multisession - the same code the
    server used - so the library's own handling of it is what runs.
    """
    pid = str(arguments[2]) if len(arguments) > 2 else ''
    if pid and pid in server.sessions:
        return {'ok': False, 'code': 'multisession'}
    server.sessions[pid] = time.time()
    return {'ok': True, 'code': 'ok'}


def _stop(server, arguments):
    pid = str(arguments[1]) if len(arguments) > 1 else ''
    server.sessions.pop(pid, None)
    return {'ok': True, 'code': 'ok'}


def _ping(server, arguments):
    """`pingAppSession(user, driveid, pid)`.

    Always ok. The two answers that are not - `suspicious_session` and
    `nosession` - mean somebody else is playing on this account elsewhere,
    which cannot be true of a session this process owns; and `nosession` ends
    in `k_KillKlango()`, so answering it wrongly would close the game.
    """
    pid = str(arguments[2]) if len(arguments) > 2 else ''
    if pid and pid not in server.sessions:
        server.sessions[pid] = time.time()
    return {'ok': True, 'code': 'ok'}


def _write_record(server, arguments):
    """`_UserSRWrite(user, appid, index, data)`."""
    from .. import account as account_module
    app_id = str(arguments[1]) if len(arguments) > 1 else ''
    index = arguments[2] if len(arguments) > 2 else ''
    data = arguments[3] if len(arguments) > 3 else ''
    account_module.write_user_record(app_id or server.host.app.id, index, data,
                                     getattr(server.host, 'store', None))
    return {'ok': True}


def _read_record(server, arguments):
    """`_UserSRRead(user, appid, index)`.

    The library reads the answer as Klango's own row list - `{index=, data=}`
    per row, shifted from zero - so that is the shape, whether one record was
    asked for or all of them.
    """
    from .. import account as account_module
    app_id = str(arguments[1]) if len(arguments) > 1 else ''
    index = arguments[2] if len(arguments) > 2 else None
    records = account_module.user_records(app_id or server.host.app.id,
                                          getattr(server.host, 'store', None))
    if index is not None and index != '':
        value = records.get(str(index))
        if value is None:
            return []
        return [{'index': index, 'data': value}]
    return [{'index': key, 'data': value}
            for key, value in sorted(records.items())]


def _dummy(_server, _arguments):
    """`KRPC:exec("dummy")` is how the library proves it has a connection."""
    return {'ok': True}


def _nothing_installed(_server, _arguments):
    return []


_HANDLERS = {
    '_login': _login,
    'login': _login,
    '_startappsession': _start,
    'startappsession': _start,
    'stopappsession': _stop,
    '_stopappsession': _stop,
    'pingappsession': _ping,
    '_pingappsession': _ping,
    '_usersrwrite': _write_record,
    'usersrwrite': _write_record,
    '_usersrread': _read_record,
    'usersrread': _read_record,
    'dummy': _dummy,
    'getinstalledapps': _nothing_installed,
}
