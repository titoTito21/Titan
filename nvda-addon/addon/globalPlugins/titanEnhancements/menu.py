# -*- coding: utf-8 -*-
"""The Titan menu, on one key.

NVDA has NVDA+n for everything NVDA can do. Titan is a whole desktop and
this add-on reaches most of it, and until now that was eight gestures plus
whatever the user had bound in Input Gestures - which is the right answer
for the thing you do forty times a day and the wrong one for everything
else. Nobody remembers a key for "run the macro that files my downloads".

So: **NVDA+shift+t**, and one menu with all of it - the assistant, AI OCR,
the macros, and every action of every add-on Titan has, grouped by add-on.

**It is a real ``wx.Menu``**, which is the whole reason it is worth having.
A menu is a thing Windows itself knows about: NVDA announces it as a menu,
counts the items, follows the arrows into a submenu, says "submenu" without
the word being written into any label, and closes on Escape - and not one
line of that is written here. A list of our own in a dialog would be a
control NVDA has to be taught about, and it would be worse at every one of
those things. It is the same rule the Titan shell and the Elten bridge both
arrived at independently: it is accessible because it is native.

The menu is built when it is opened, from the catalogue
(:mod:`gestures`) - so an add-on the user installed a minute ago is on it,
and a Titan that is not running still opens it and says so on whichever
entry is pressed.
"""

from . import dialogs
from . import gestures
from . import i18n
from .link import LINK

_ = i18n.install(globals())

#: An add-on with more actions than this gets them in a submenu of its own
#: whatever happens; below it, a single-action add-on is put straight on the
#: menu rather than making the user open a submenu to find one item.
GROUP_FROM = 2

#: Titan can have a lot installed. A menu longer than this stops being
#: something to arrow through, so the rest stays where it already is - the
#: browse-by-add-on command and the Input Gestures dialog.
MAX_GROUPS = 40


def _gui():
    try:
        import gui
        return gui
    except Exception:                                # noqa: BLE001
        return None


def _wx():
    try:
        import wx
        return wx
    except Exception:                                # noqa: BLE001
        return None


class _Builder:
    """A menu whose items remember what to do, keyed by their own wx id."""

    def __init__(self, wx, frame):
        self.wx = wx
        self.frame = frame
        self.doing = {}

    def item(self, menu, label, what, enabled=True):
        entry = menu.Append(self.wx.ID_ANY, label)
        if not enabled:
            entry.Enable(False)
            return entry
        self.doing[entry.GetId()] = what
        self.frame.Bind(self.wx.EVT_MENU, self._fired, entry)
        return entry

    def _fired(self, event):
        what = self.doing.get(event.GetId())
        if what is None:
            return
        # After the menu has gone: a dialog raised from inside a menu event
        # comes up behind the menu that is still closing, which for somebody
        # who cannot see it is a window that did not open.
        self.wx.CallAfter(what)


def _actions_menu(builder, wx):
    """Every Titan action there is, one submenu per add-on."""
    rows = gestures.load_catalogue()
    menu = wx.Menu()
    if not rows:
        builder.item(menu, _('(Titan has not been asked yet)'), None,
                     enabled=False)
        return menu
    groups = {}
    for row in rows:
        groups.setdefault(row['addon'], []).append(row)
    ordered = sorted(groups.items(),
                     key=lambda pair: (pair[1][0].get('label')
                                       or pair[0]).lower())
    for addon_id, actions in ordered[:MAX_GROUPS]:
        label = actions[0].get('label') or addon_id
        actions = sorted(actions, key=lambda row: row['action'])
        if len(actions) < GROUP_FROM:
            row = actions[0]
            builder.item(menu, '{}: {}'.format(label, _label_of(row)),
                         lambda row=row: gestures.run(row))
            continue
        submenu = wx.Menu()
        for row in actions:
            builder.item(submenu, _label_of(row),
                         lambda row=row: gestures.run(row))
        menu.AppendSubMenu(submenu, label)
    if len(ordered) > MAX_GROUPS:
        builder.item(menu, _('More, in the Titan actions command...'),
                     lambda: _run_command('actions'))
    return menu


def _label_of(row):
    """What one action is called on the menu.

    The summary, because that is the sentence its author wrote for a person;
    the bare name only when there is none. A trailing full stop is dropped -
    a menu item is a label, not a sentence, and NVDA reads the stop as a
    pause in the middle of the list.
    """
    summary = str(row.get('summary') or '').strip()
    if not summary:
        return row['action']
    first = summary.split('. ')[0].rstrip('.')
    return first if len(first) <= 70 else row['action']


def _run_command(name, *args):
    from . import commands
    getattr(commands, name)(*args)


def build(plugin):
    """The whole menu. Returns (menu, builder) - the builder must outlive it."""
    wx = _wx()
    gui = _gui()
    if wx is None or gui is None:
        return None, None
    frame = gui.mainFrame
    builder = _Builder(wx, frame)
    menu = wx.Menu()
    connected = LINK.connected()

    if not connected:
        builder.item(menu, _('Titan is not running'), None, enabled=False)
        menu.AppendSeparator()

    # The assistant first: it is the one entry that can answer a question
    # the user has not worked out which command to use for.
    ai = wx.Menu()
    builder.item(ai, _('Ask Titan a question...'),
                 lambda: _run_command('assistant', False))
    builder.item(ai, _('Tell Titan to do something...'),
                 lambda: _run_command('assistant', True))
    ai.AppendSeparator()
    builder.item(ai, _('Read the conversation'),
                 lambda: _run_command('assistant_history'))
    builder.item(ai, _('Forget the conversation'),
                 lambda: _run_command('assistant_forget'))
    menu.AppendSubMenu(ai, _('Assistant'))

    ocr = wx.Menu()
    builder.item(ocr, _('Read this window'), lambda: _run_command('ocr_read'))
    builder.item(ocr, _('Ask about this window...'),
                 lambda: _run_command('ocr_ask'))
    builder.item(ocr, _("Put Titan's controls over this window"),
                 lambda: _run_command('ocr_overlay'))
    menu.AppendSubMenu(ocr, _('AI OCR (read a window nothing else can)'))

    builder.item(menu, _('Macros...'), lambda: _run_command('macros'))
    menu.AppendSubMenu(_actions_menu(builder, wx),
                       _('Everything Titan can do'))
    menu.AppendSeparator()

    builder.item(menu, _("Titan's settings"),
                 lambda: _open_titan_settings())
    builder.item(menu, _('Status'), lambda: _run_command('status'))
    builder.item(menu, _('Ask Titan what it can do'),
                 lambda: _run_command('refresh_actions', plugin))
    menu.AppendSeparator()

    from . import channel
    from . import panner
    switches = wx.Menu()
    _switch(builder, switches, _("Titan's own announcements"),
            channel.CHANNEL.enabled, lambda: _run_command('toggle_announcements'))
    _switch(builder, switches, _('Positioned speech'),
            panner.PANNER.enabled, lambda: _run_command('toggle_position'))
    menu.AppendSubMenu(switches, _('Switches'))
    return menu, builder


def _switch(builder, menu, label, on, what):
    """A switch reads as a switch, not as a word in a label.

    A real check item: Windows carries the ticked state and NVDA says
    "checked" in its user's own words. Writing "(on)" into the label would
    be a state spelled out in text, which is the thing this repository
    keeps finding and taking back out.
    """
    wx = builder.wx
    entry = menu.AppendCheckItem(wx.ID_ANY, label)
    entry.Check(bool(on))
    builder.doing[entry.GetId()] = what
    builder.frame.Bind(wx.EVT_MENU, builder._fired, entry)
    return entry


def _open_titan_settings():
    """Titan's own settings window, through whichever interface it uses."""
    def work():
        ok, text = LINK.run_action('titan', 'open_settings')
        if not ok:
            dialogs.report(str(text))
    from . import commands
    commands._work(work)


def show(plugin):
    """Put the menu up. Called from the gesture, on NVDA's main thread."""
    wx = _wx()
    gui = _gui()
    if wx is None or gui is None:
        return

    def popup():
        menu, builder = build(plugin)
        if menu is None:
            return
        gui.mainFrame.prePopup()
        try:
            gui.mainFrame.PopupMenu(menu)
        finally:
            gui.mainFrame.postPopup()
            # The builder holds the callables the items fire; destroying the
            # menu first and dropping it afterwards is the order that leaves
            # nothing bound to a menu that has gone.
            menu.Destroy()
            builder.doing.clear()
    wx.CallAfter(popup)
