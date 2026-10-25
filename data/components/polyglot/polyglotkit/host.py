# -*- coding: utf-8 -*-
"""The process an application or game in another language runs inside.

Titan starts this with its own Python (``_internal/pythonw.exe`` in a compiled
Titan), exactly as it starts a Python application, so the program gets a
wxPython of its own for dialogs and its game window, and joins Titan's Action
Bus under its own name - which is how it speaks in the user's voice and plays
through the user's mixer without loading either itself.

    host.py --file <source> --runtime <id> --dir <app folder>
            --kind app|game|macro --title <name> --id <shortname>
"""

import argparse
import os
import sys
import time


def _log_path(ident):
    from .runtimes import user_dir
    folder = os.path.join(user_dir(), 'logs')
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, '%s.log' % (ident or 'program'))


def make_logger(ident):
    path = _log_path(ident)
    try:
        if os.path.getsize(path) > 1024 * 1024:
            os.replace(path, path + '.old')
    except OSError:
        pass

    def log(text):
        try:
            with open(path, 'a', encoding='utf-8') as handle:
                handle.write('%s %s\n' % (time.strftime('%H:%M:%S'), text))
        except OSError:
            pass
    return log


def bus_caller(ident, label, kind, log):
    """``titan_call`` over the Action Bus, joined on first use."""
    state = {}

    def titan_call(addon, action, **args):
        bus = state.get('bus')
        if bus is None:
            from src.titan_core import titan_actions as bus
            bus.connect(id='polyglot_' + ident, label=label, kind=kind)
            state['bus'] = bus
        if not bus.wait_until_connected(5.0):
            raise RuntimeError('Titan is not running')
        return bus.call(addon, action, **args)
    return titan_call


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', required=True)
    parser.add_argument('--runtime', default='')
    parser.add_argument('--dir', default='')
    parser.add_argument('--kind', default='app')
    parser.add_argument('--title', default='')
    parser.add_argument('--id', default='')
    options = parser.parse_args(argv)

    from . import runtimes
    from .api import TitanAPI, gui_caller
    from .guests import make_guest, failure_text
    from .i18n import _

    path = os.path.abspath(options.file)
    folder = options.dir or os.path.dirname(path)
    ident = options.id or os.path.basename(folder.rstrip('\\/'))
    title = options.title or ident
    log = make_logger(ident)
    log('--- %s (%s)' % (path, options.runtime))

    import wx
    app = wx.App(False)
    app.SetExitOnFrameDelete(False)
    # wx's main loop returns at once when there is no top-level window at
    # all - and a program that only ever speaks has none - which ended the
    # process while the program was still running. A frame that is never
    # shown keeps the loop alive; finish() ends it.
    anchor = wx.Frame(None)

    runtime = runtimes.by_id(options.runtime) or runtimes.for_file(path)
    api = TitanAPI(folder, title, kind=options.kind,
                   runtime_id=getattr(runtime, 'id', ''),
                   titan_call=bus_caller(ident, title, options.kind, log),
                   on_gui=gui_caller(), log=log, ident=ident)
    outcome = {'code': 0}

    def finish(code, error):
        outcome['code'] = code
        if code and error:
            wx.MessageBox(failure_text(title, code, error), title,
                          wx.OK | wx.ICON_ERROR)
        if api.window is not None:
            api.window.destroy()
        anchor.Destroy()
        app.ExitMainLoop()

    def on_exit(code, error):
        wx.CallAfter(finish, code, error)

    try:
        if runtime is None:
            raise RuntimeError(_("No language is registered for {}.").format(
                os.path.basename(path)))
        guest = make_guest(runtime, api, path, log, on_exit)
        guest.start()
    except Exception as error:
        log('cannot start: %s' % error)
        wx.MessageBox(str(error), title, wx.OK | wx.ICON_ERROR)
        anchor.Destroy()
        return 2

    app.MainLoop()
    return outcome['code']


if __name__ == '__main__':
    sys.exit(main())
