"""The welcome window shown as the reader starts.

"Welcome to Titan Access": a read-only edit field holding
``locale/welcome_<language>.txt`` (the most important shortcuts), a tick
box "Show the welcome screen at startup" and OK. The tick box is
``General/ShowWelcome``, on by default; unticked, the window is never
shown again (it can be ticked back in the reader's General settings).

It is a real wx dialog, so a screen reader reads it as one, and the
keyboard starts in the edit field so the help is read first. It is put
up on the GUI thread (`wx.CallAfter`) and never waited for: the reader
is already running behind it. Without a running wx application - Titan
Access started outside Titan - nothing is shown.
"""

import io
import os

from titan_access.log import log

_COMPONENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOCALE = os.path.join(_COMPONENT, 'locale')

#: The dialog currently on the screen, so a second start does not put up
#: a second copy.
_open = None


def _L(key):
    try:
        from titan_access.localization import L
        return L(key)
    except Exception:                                # noqa: BLE001
        return key


def _language():
    try:
        from titan_access.localization import get_language
        return (get_language() or 'en').lower()
    except Exception:                                # noqa: BLE001
        return 'en'


def help_text(language=None):
    """The welcome text in ``language`` (the reader's own by default),
    falling back to English and then Polish."""
    language = (language or _language())[:2]
    for lang in (language, 'en', 'pl'):
        path = os.path.join(_LOCALE, 'welcome_%s.txt' % lang)
        try:
            with io.open(path, encoding='utf-8-sig') as f:
                return f.read().strip()
        except OSError:
            continue
    return ''


def wanted():
    """Whether the user still wants the window at startup."""
    try:
        from titan_access.settings_store import get_settings
        return bool(get_settings().show_welcome)
    except Exception:                                # noqa: BLE001
        return True


def _remember(show):
    try:
        from titan_access.settings_store import get_settings
        settings = get_settings()
        if bool(settings.show_welcome) != bool(show):
            settings.show_welcome = bool(show)
            settings.save()
    except Exception as e:                           # noqa: BLE001
        log('[TitanAccess] welcome screen: could not save: %s', e)


def build(parent=None):
    """The dialog itself (not shown). Separate from :func:`offer` so it
    can be built and checked without putting anything on the screen."""
    import wx

    dialog = wx.Dialog(parent, title=_L('welcome.title'),
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    sizer = wx.BoxSizer(wx.VERTICAL)

    label = wx.StaticText(dialog, label=_L('welcome.text'))
    sizer.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
    text = wx.TextCtrl(dialog, value=help_text(),
                       style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
                       size=(560, 300))
    text.SetName(_L('welcome.text'))
    sizer.Add(text, 1, wx.EXPAND | wx.ALL, 10)

    check = wx.CheckBox(dialog, label=_L('welcome.show'))
    check.SetValue(wanted())
    sizer.Add(check, 0, wx.LEFT | wx.RIGHT, 10)

    ok = wx.Button(dialog, wx.ID_OK, _L('welcome.ok'))
    ok.SetDefault()
    buttons = wx.BoxSizer(wx.HORIZONTAL)
    buttons.AddStretchSpacer()
    buttons.Add(ok, 0)
    sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)

    dialog.SetSizerAndFit(sizer)
    dialog.SetEscapeId(wx.ID_OK)
    dialog.SetAffirmativeId(wx.ID_OK)
    dialog.text, dialog.check, dialog.ok = text, check, ok

    def close(_event=None):
        global _open
        _remember(check.GetValue())
        if _open is dialog:
            _open = None
        try:
            dialog.Destroy()
        except Exception:                            # noqa: BLE001
            pass

    ok.Bind(wx.EVT_BUTTON, close)
    dialog.Bind(wx.EVT_CLOSE, close)
    dialog.Bind(wx.EVT_CHAR_HOOK, lambda e: close() if
                e.GetKeyCode() == wx.WXK_ESCAPE else e.Skip())
    dialog.close = close
    return dialog


def _show():
    global _open
    try:
        import wx
        if _open is not None:
            try:
                _open.Raise()
                return
            except Exception:                        # noqa: BLE001
                _open = None
        dialog = build(None)
        _open = dialog
        dialog.CentreOnScreen()
        dialog.Show()
        dialog.Raise()
        dialog.text.SetFocus()
        dialog.text.SetInsertionPoint(0)
        # Windows answers the activation by focusing the dialog itself;
        # the focus is put on the help again once that has gone through.
        wx.CallLater(150, lambda: dialog and dialog.text.SetFocus())
    except Exception as e:                           # noqa: BLE001
        log('[TitanAccess] welcome screen could not be shown: %s', e)


def offer():
    """Put the window up on the GUI thread if the user still wants it."""
    if not wanted():
        log('[TitanAccess] welcome screen: turned off')
        return False
    try:
        import wx
        app = wx.GetApp()
        if app is None:
            log('[TitanAccess] welcome screen: no wx application to show it in')
            return False
        log('[TitanAccess] welcome screen: offered')
        # A loop not running yet (components start before it) still
        # delivers the call once it does.
        wx.CallAfter(_show)
        return True
    except Exception as e:                           # noqa: BLE001
        log('[TitanAccess] welcome screen: %s', e)
        return False
