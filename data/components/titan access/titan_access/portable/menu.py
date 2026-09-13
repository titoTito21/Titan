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

from . import compat
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
    """NVDA's interface, or Titan's own window where there is no NVDA.

    ``compat`` is what differs between the two trees, so this module is
    the same file in both: inside NVDA it is NVDA's ``gui``, inside Titan
    Access it is a shim whose ``mainFrame`` is Titan's own window.

    It answers None unless there really is a frame to put a window on.
    Every caller here already checks - and the alternative is a
    ``NoneType`` raised inside wx's own event loop, where nothing catches
    it and the user is told nothing at all.
    """
    found = compat.gui
    if found is None:
        return None
    try:
        if getattr(found, 'mainFrame', None) is None:
            return None
    except Exception:                                # noqa: BLE001
        return None
    return found


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
        #: Every id this menu bound on NVDA's main frame, so it can be let
        #: go again. A handler left bound outlives the menu item it was
        #: for, and wx recycles ``ID_ANY`` - so the next menu built here
        #: inherits whatever the last one left behind, growing by one
        #: binding per open for the rest of the session.
        self.bound = []

    def item(self, menu, label, what, enabled=True):
        entry = menu.Append(self.wx.ID_ANY, label)
        if not enabled:
            entry.Enable(False)
            return entry
        self.doing[entry.GetId()] = what
        self._bind(entry)
        return entry

    def _bind(self, entry):
        self.frame.Bind(self.wx.EVT_MENU, self._fired, entry)
        self.bound.append(entry.GetId())

    def release(self):
        """Let go of every handler this menu put on NVDA's own frame."""
        for identifier in self.bound:
            try:
                self.frame.Unbind(self.wx.EVT_MENU, id=identifier)
            except Exception:                        # noqa: BLE001
                pass
        self.bound = []
        self.doing.clear()

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
        builder.item(menu, _('(not asked yet)'), None,
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
        builder.item(menu, _('More actions...'),
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
    """One entry of the menu, done.

    **A part this reader has not got is said, not raised.** The menu is
    one definition in two readers, and some of what is on it is NVDA's
    own - its speech filter, its audio session, its review cursor. Inside
    Titan Access those commands reach a module that is not there, and an
    ImportError from inside a menu event is a menu entry that does
    nothing and says nothing about why.
    """
    try:
        from . import commands
        what = getattr(commands, name, None)
    except ImportError as error:                     # noqa: BLE001
        return dialogs.report(_('This reader has not got that: {what}')
                              .format(what=error))
    if what is None:
        return dialogs.report(_('This reader has not got that: {what}')
                              .format(what=name))
    try:
        what(*args)
    except ImportError as error:                     # noqa: BLE001
        dialogs.report(_('This reader has not got that: {what}')
                       .format(what=error))


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
    builder.item(ai, _('Ask a question...'),
                 lambda: _run_command('assistant', False))
    builder.item(ai, _('Give an instruction...'),
                 lambda: _run_command('assistant', True))
    ai.AppendSeparator()
    builder.item(ai, _('The conversation'),
                 lambda: _run_command('assistant_history'))
    builder.item(ai, _('Forget it'),
                 lambda: _run_command('assistant_forget'))
    menu.AppendSubMenu(ai, _('Assistant'))

    ocr = wx.Menu()
    builder.item(ocr, _('Read this window'), lambda: _run_command('ocr_read'))
    builder.item(ocr, _('Ask about this window...'),
                 lambda: _run_command('ocr_ask'))
    builder.item(ocr, _('The last reading again'),
                 lambda: _run_command('ocr_again'))
    ocr.AppendSeparator()
    # Reading a window nothing can read is half of it; PRESSING something in
    # it is the other half, and on a window that exposes nothing it is the
    # only way to press anything at all.
    builder.item(ocr, _('Press what it read...'),
                 lambda: _run_command('ocr_press'))
    builder.item(ocr, _('Send a key...'),
                 lambda: _run_command('ocr_key'))
    builder.item(ocr, _("Put Titan's controls over this window"),
                 lambda: _run_command('ocr_overlay'))
    menu.AppendSubMenu(ocr, _('AI OCR'))

    # **A menu entry is the NAME of a thing, not a sentence about it.**
    # These read "Open an application and walk it with the arrows..." and
    # the submenu holding them was called "Titan itself", which is a
    # description of a feature rather than a place to go. A menu is walked
    # one row at a time with the arrows, so a row that is a sentence is a
    # sentence heard on the way to the row below it.
    apps_menu = wx.Menu()
    # Translators: an entry in the Titan menu.
    builder.item(apps_menu, _('Applications...'),
                 lambda: _run_command('titan_applications'))
    # Translators: an entry in the Titan menu.
    builder.item(apps_menu, _('As real controls'),
                 lambda: _run_command('application_as_a_window'))
    # Translators: an entry in the Titan menu.
    builder.item(apps_menu, _('Close'),
                 lambda: _run_command('close_application'))
    # Translators: an entry in the Titan menu.
    builder.item(apps_menu, _('The log'),
                 lambda: _run_command('application_log'))
    # Translators: a submenu of the Titan menu - TCE is what Titan's own
    # applications have always been called.
    menu.AppendSubMenu(apps_menu, _('TCE applications'))

    # Translators: an entry in the Titan menu.
    builder.item(menu, _('Titan...'), lambda: _run_command('titan_window'))
    # Translators: an entry in the Titan menu - the same thing as a real
    # dialog, for somebody who would rather have a form than a list.
    builder.item(menu, _('Titan as a form...'),
                 lambda: _run_command('titan_window_as_a_form'))

    builder.item(menu, _('Macros...'), lambda: _run_command('macros'))
    menu.AppendSubMenu(_actions_menu(builder, wx),
                       _('Everything Titan can do'))

    # What Titan can be ASKED, as against what it can be told to do. Every
    # one of these is a list of what has happened rather than something to
    # run, which is why none of them belongs in the actions menu above.
    what = wx.Menu()
    builder.item(what, _('Notifications'),
                 lambda: _run_command('notifications'))
    builder.item(what, _('Buffers'),
                 lambda: _run_command('buffers'))
    builder.item(what, _('Views'),
                 lambda: _run_command('showing'))
    builder.item(what, _('Components'), lambda: _run_command('components'))
    menu.AppendSubMenu(what, _('News'))
    menu.AppendSeparator()

    # **The reader's own half.** Everything above needs Titan; none of this
    # does, which is why it is a group of its own and why it is here even
    # when Titan is not running.
    # **The managers are a menu of their own.** They were in the reading
    # submenu, mixed in among "where am I" and "read this window", and by
    # the time there were twenty of them that list was something a user
    # arrowed through looking for the one they came for. A manager is not a
    # thing you do to the control you are on: it is a thing you keep, and
    # keeping them apart is what makes both lists short enough to read.
    managers = wx.Menu()
    # Translators: an entry in the Titan menu - the manager window.
    builder.item(managers, _('Manager window...'),
                 lambda: _run_command('manager'))

    markers = wx.Menu()
    # Translators: an entry in the Titan menu.
    builder.item(markers, _('Mark this control'),
                 lambda: _run_command('mark_this'))
    # Translators: an entry in the Titan menu.
    builder.item(markers, _('Go to a marker...'),
                 lambda: _run_command('go_to_marker'))
    # Translators: an entry in the Titan menu.
    builder.item(markers, _('Forget a marker...'),
                 lambda: _run_command('forget_marker'))
    # Translators: a submenu of the Titan menu.
    managers.AppendSubMenu(markers, _('Place markers'))

    watched = wx.Menu()
    # Translators: an entry in the Titan menu.
    builder.item(watched, _('Watch this object'),
                 lambda: _run_command('watch_this'))
    # Translators: an entry in the Titan menu.
    builder.item(watched, _('Watch this object\'s area'),
                 lambda: _run_command('watch_this_area'))
    # Translators: an entry in the Titan menu.
    builder.item(watched, _('Watch this window'),
                 lambda: _run_command('watch_this_window'))
    # Translators: an entry in the Titan menu.
    builder.item(watched, _('What is being watched...'),
                 lambda: _run_command('watched_areas'))
    # Translators: a submenu of the Titan menu.
    managers.AppendSubMenu(watched, _('Watched areas'))

    doing = wx.Menu()
    # Translators: an entry in the Titan menu.
    builder.item(doing, _('Record, or keep'),
                 lambda: _run_command('record_procedure'))
    # Translators: an entry in the Titan menu.
    builder.item(doing, _('Do one again...'),
                 lambda: _run_command('run_procedure'))
    # Translators: an entry in the Titan menu.
    builder.item(doing, _('Read the steps of one...'),
                 lambda: _run_command('read_procedure'))
    # Translators: an entry in the Titan menu.
    builder.item(doing, _('Discard the recording'),
                 lambda: _run_command('cancel_procedure'))
    # Translators: a submenu of the Titan menu.
    managers.AppendSubMenu(doing, _('Procedures'))

    spoken = wx.Menu()
    # Translators: an entry in the Titan menu.
    builder.item(spoken, _('What was said...'),
                 lambda: _run_command('read_journal'))
    # Translators: an entry in the Titan menu.
    builder.item(spoken, _('Find something that was said...'),
                 lambda: _run_command('search_journal'))
    # Translators: an entry in the Titan menu.
    builder.item(spoken, _('As a page'),
                 lambda: _run_command('journal_page'))
    # Translators: a submenu of the Titan menu.
    managers.AppendSubMenu(spoken, _('Speech history'))

    finding = wx.Menu()
    # Translators: an entry in the Titan menu.
    builder.item(finding, _('By name...'),
                 lambda: _run_command('find_control'))
    # Translators: an entry in the Titan menu.
    builder.item(finding, _('By what it does (AI)...'),
                 lambda: _run_command('find_control_with_ai'))
    # Translators: a submenu of the Titan menu.
    managers.AppendSubMenu(finding, _('Find a control'))

    modules = wx.Menu()
    # Translators: an entry in the Titan menu.
    builder.item(modules, _('What is installed...'),
                 lambda: _run_command('reader_modules'))
    # Translators: an entry in the Titan menu.
    builder.item(modules, _('Write one...'),
                 lambda: _run_command('draft_module'))
    # Translators: a submenu of the Titan menu.
    managers.AppendSubMenu(modules, _('Reader modules'))

    # Translators: an entry in the Titan menu.
    builder.item(managers, _('Does it all work?'),
                 lambda: _run_command('self_test'))
    # Translators: an entry in the Titan menu.
    builder.item(managers, _('Windows and actions...'),
                 lambda: _run_command('windows_and_actions'))
    # Translators: an entry in the Titan menu.
    builder.item(managers, _('Sound scheme...'),
                 lambda: _run_command('sound_scheme'))
    # Translators: an entry in the Titan menu.
    builder.item(managers, _('Voices and reading order...'),
                 lambda: _run_command('voice_classes'))
    # Translators: a submenu of the Titan menu.
    menu.AppendSubMenu(managers, _('Managers'))

    # **What is left here is what is done TO the window in front**, which
    # is a different question from what the user keeps.
    reader = wx.Menu()
    builder.item(reader, _('Where am I'), lambda: _run_command('where_am_i'))
    builder.item(reader, _('Name this control...'),
                 lambda: _run_command('label_control'))
    # Translators: an entry in the Titan menu.
    builder.item(reader, _('Customise this control...'),
                 lambda: _run_command('customise_control'))
    # Translators: an entry in the Titan menu - share what has been named
    # with Titan's own screen reader.
    builder.item(reader, _('Share names with Titan Access'),
                 lambda: _run_command('share_names'))
    builder.item(reader, _('What does this show?'),
                 lambda: _run_command('describe_control'))
    # Translators: an entry in the Titan menu.
    builder.item(reader, _('What is this written in?'),
                 lambda: _run_command('what_is_this_written_in'))
    # Translators: an entry in the Titan menu.
    builder.item(reader, _('Does this module work?'),
                 lambda: _run_command('check_module'))
    builder.item(reader, _('Read this window'),
                 lambda: _run_command('read_locally'))
    # Translators: an entry in the Titan menu.
    builder.item(reader, _('Screen review'),
                 lambda: _run_command('ocr_review'))
    builder.item(reader, _('As a picture'),
                 lambda: _run_command('watch_surface'))
    builder.item(reader, _('Game or application'),
                 lambda: _run_command('surface_mode'))
    # Translators: an entry in the Titan menu.
    builder.item(reader, _('Virtual window'),
                 lambda: _run_command('virtual_window'))
    # Translators: an entry in the Titan menu.
    builder.item(reader, _('Quick navigation keys...'),
                 lambda: _run_command('virtual_window_help'))
    builder.item(reader, _('Touchpad'),
                 lambda: _run_command('toggle_trackpad'))
    menu.AppendSubMenu(reader, _('This program'))

    # **The switches that spend something, answered for THIS program.**
    # Not in the settings page: the question is about the window the user
    # is in at the moment they are wondering about it, and a settings page
    # is somewhere else by the time they get there.
    here = _this_program(builder, wx)
    if here is not None:
        menu.AppendSubMenu(here[0], here[1])
    menu.AppendSeparator()

    builder.item(menu, _("Titan's settings"),
                 lambda: _open_titan_settings())
    builder.item(menu, _('Status'), lambda: _run_command('status'))
    builder.item(menu, _('What can Titan do?'),
                 lambda: _run_command('refresh_actions', plugin))
    menu.AppendSeparator()

    # **Both of these are NVDA's own** - what stands in for its focus
    # report, and its audio session - so a reader without them gets a menu
    # without the submenu rather than no menu at all.
    try:
        from . import channel
        from . import panner
    except ImportError:                              # noqa: BLE001
        return menu, builder
    switches = wx.Menu()
    _switch(builder, switches, _("Titan's own announcements"),
            channel.CHANNEL.enabled, lambda: _run_command('toggle_announcements'))
    _switch(builder, switches, _('Positioned speech'),
            panner.PANNER.enabled, lambda: _run_command('toggle_position'))
    menu.AppendSubMenu(switches, _('Switches'))
    return menu, builder


def _this_program(builder, wx):
    """A submenu of the per-program switches, or None with no window.

    Each one says what it is and where its answer came from: a switch the
    user has never touched here shows what it inherited, because otherwise
    they cannot tell why something they did not ask for is on.
    """
    from . import perProgram
    program = perProgram.application_of()
    if not program:
        return None
    words = {
        # Translators: a per-program switch in the Titan menu.
        'autoLabel': _('Work out names for unnamed controls (AI)'),
        # Translators: a per-program switch in the Titan menu.
        'surfaceReading': _('Read this window as a picture (AI)'),
        # Translators: a per-program switch in the Titan menu.
        'graphicKinds': _('Say what pictures are'),
    }
    here = wx.Menu()
    for row in perProgram.described():
        label = words.get(row['id'], row['id'])
        if not row['own']:
            # Translators: marks a per-program switch that has no answer of
            # its own and is following the general setting.
            label = _('{what} (following the general setting)').format(
                what=label)
        _switch(builder, here, label, row['on'],
                lambda name=row['id']: _run_command('toggle_here', name))
    here.AppendSeparator()
    builder.item(here, _('Use the general settings'),
                 lambda: _run_command('forget_here'))
    # Translators: a submenu in the Titan menu. {program} is the program
    # the user is in.
    return here, _('In {program}').format(program=perProgram.label_of())


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
    builder._bind(entry)
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
            builder.release()
    wx.CallAfter(popup)
