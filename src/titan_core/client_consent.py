# -*- coding: utf-8 -*-
"""Whether a program that is not Titan may DRIVE Titan.

An external client on the Action Bus is another program taking hold of
this desktop - the Elten TCE bridge is one, and it is deliberately only
the first. Titan already says out loud when one arrives, because nothing
else on this desktop would tell the user; what it never did is ask
whether it may act.

**Reading and driving are different permissions, and the line is where
this repository has already drawn it once.** The TCE bridge's own
`press_key` is off by default and asked for separately from reading
Elten's screen, for the reason that applies just as well in this
direction: reading tells somebody what is there, and Enter in a messenger
sends the message. So:

- **Reading is always allowed.** What applications are installed, what a
  screen holds, what a setting is, what the AI remembers. A client that
  can only read can still show Titan whole, which is what the bridge is
  for, and asking about that would be a question with no risk behind it.
- **Driving needs the user's yes** - running an action, pressing a
  control, changing a setting, speaking, letting the AI act. Once, per
  client, in plain words, remembered afterwards as an ordinary setting
  the user can change or take back.

**The question is asked when the client ARRIVES, not when it first acts.**
Titan already announces the arrival, so the question rides along with
something the user is being told about anyway - and by the time the
client does anything, it has been answered. Asked at the first action
instead, the first action of every session would fail while a dialog the
user had not noticed waited for them.
"""

import threading
import time

#: Where the answers live - one key per client, in Titan's own settings,
#: so the user can see and change them like anything else.
SECTION = 'external_clients'

#: How long a client that arrived while the user was away may keep a
#: question standing. A dialog nobody answers is not consent.
ASK_SECONDS = 180.0

_LOCK = threading.RLock()
_ASKING = {}                      # client id -> when the question went up


def _key(client_id):
    """A client's id as a settings key.

    Titan's settings file is `key=value` a line at a time, so a `=`, a
    `[` or a newline in a client's own id would write a line the parser
    reads back as something else - and the id comes from whatever
    connected, which is not Titan's to trust.
    """
    kept = ''.join(character if character.isalnum() or character in '._-'
                   else '_' for character in str(client_id or '').strip())
    return (kept or 'client')[:64].lower()


def known(client_id):
    """The remembered answer: True, False, or None for never asked."""
    from src.settings.settings import get_setting
    value = str(get_setting(_key(client_id), '', SECTION) or '').strip().lower()
    if value in ('yes', 'true', '1'):
        return True
    if value in ('no', 'false', '0'):
        return False
    return None


def remember(client_id, allowed):
    from src.settings.settings import set_setting
    set_setting(_key(client_id), 'yes' if allowed else 'no', SECTION)
    return bool(allowed)


def forget(client_id):
    """Take an answer back, so the next arrival asks again."""
    from src.settings.settings import load_settings, save_settings
    settings = load_settings()
    if settings.get(SECTION, {}).pop(_key(client_id), None) is None:
        return False
    save_settings(settings)
    return True


def clients():
    """Every client that has ever been answered about, and the answer."""
    from src.settings.settings import load_settings
    return [{'client': name, 'allowed': str(value).strip().lower()
             in ('yes', 'true', '1')}
            for name, value in sorted(
                (load_settings().get(SECTION) or {}).items())]


def may_drive(client_id, label=''):
    """May this client change anything? Never asks; never blocks.

    Called on the path of a real request, so an unanswered question is a
    no - and it is a no that says why, not one that pretends the call
    failed. `ask` is what puts the question up, and it happens when the
    client arrives.
    """
    answer = known(client_id)
    if answer is not None:
        return answer
    ask(client_id, label)
    return False


def refusal(client_id, label=''):
    """What to tell a client that has not been allowed to act.

    In Titan's own language, because it is shown to the person sitting at
    Titan as often as it is read by the program - and it names the one
    thing that will change the answer.
    """
    from src.titan_core.translation import get_translation_function
    translate = get_translation_function()
    name = str(label or client_id or 'a program')
    if known(client_id) is False:
        return translate(
            "%s is not allowed to control Titan. Turn it on in Settings, "
            "General, under External clients.") % name
    return translate(
        "%s has asked to control Titan and Titan is asking you whether it "
        "may. Answer the question and try again.") % name


def ask(client_id, label=''):
    """Put the question up, once, without holding the caller.

    Never on the calling thread: this is reached from the bus, while a
    connection is being set up or a request is being answered, and a
    modal dialog there would hold the client - and, through it, whatever
    the user was doing in the program the client belongs to.
    """
    client_id = str(client_id or '').strip()
    if not client_id:
        return
    with _LOCK:
        if known(client_id) is not None:
            return
        when = _ASKING.get(client_id)
        if when is not None and time.time() - when < ASK_SECONDS:
            return
        _ASKING[client_id] = time.time()
    threading.Thread(target=_ask_now, args=(client_id, str(label or '')),
                     name='TitanClientConsent', daemon=True).start()


def _ask_now(client_id, label):
    try:
        answer = _dialog(client_id, label)
    except Exception:
        answer = None
    with _LOCK:
        _ASKING.pop(client_id, None)
    if answer is None:
        return                              # not answered is not an answer
    try:
        remember(client_id, answer)
    except Exception:
        pass


def on_screen():
    """Is there a running Titan a person could answer a question in?

    Not "is wx importable" and not "is there an App object": a headless
    run, a test runner and a compiled tool all have both. What is asked
    is whether the main loop is running, which is the only state in which
    a modal dialog is something somebody can see and press.
    """
    try:
        import wx
    except Exception:
        return False
    try:
        app = wx.GetApp()
    except Exception:
        return False
    if app is None:
        return False
    try:
        return bool(app.IsMainLoopRunning())
    except Exception:
        return False


def _dialog(client_id, label):
    """The question, on Titan's own GUI thread. None if it could not be put.

    **The cue is played and the question is NOT spoken.** A screen reader
    reads a dialog it has just been given, so saying it here as well
    would be the sentence twice - and worse than twice: this is put up in
    the same breath as Titan announcing that the client arrived, and two
    announcements at once means the second erases the first, which is the
    trap this repository has already paid for. What the cue is for is
    telling somebody a dialog is there at all, which is exactly the case
    `play_question_sound` was written for.
    """
    # **Nobody to ask is not a yes.** `run_on_gui` falls back to calling
    # its function on the CALLING thread when wx has no running
    # application, which is right for an add-on's handler and catastrophic
    # here: a `wx.MessageDialog` raised with no Titan behind it answered
    # by itself, and a `yes` was written that no person had given. Caught
    # by a test run doing it, which is exactly the shape of the accident
    # this guards against.
    if not on_screen():
        return None

    from src.titan_core.actions.inproc import run_on_gui
    from src.titan_core.translation import get_translation_function
    translate = get_translation_function()
    name = label or client_id
    question = translate(
        "%s wants to control Titan: to run add-ons, press controls, change "
        "settings and use the AI on your behalf. It can already read what "
        "Titan is showing. Allow it to control Titan?") % name
    title = translate("External client")

    try:
        from src.ai.ai_speech import play_question_sound
        play_question_sound()
    except Exception:
        pass

    def put():
        import wx
        dialog = wx.MessageDialog(None, question, title,
                                  wx.YES_NO | wx.ICON_QUESTION)
        try:
            return dialog.ShowModal() == wx.ID_YES
        finally:
            dialog.Destroy()
    # **Long enough for a person to answer.** `run_on_gui`'s own default
    # is thirty seconds, which is right for an add-on's handler and wrong
    # for a question: it would give up while the dialog was still on the
    # screen, and the yes the user then pressed would reach nobody.
    answer, error = run_on_gui(put, timeout=ASK_SECONDS)
    return None if error else bool(answer)


# --------------------------------------------------------------------------- #
# Seen and taken back
#
# A permission the user cannot find again is not a permission they gave -
# it is one they stopped being asked about. These are on the `titan`
# provider, so the answer is reachable from the settings, from a macro,
# from the AI and from a client's own screen, which is where somebody
# looking at what a client may do will actually be.
# --------------------------------------------------------------------------- #
def _list_clients(**_arguments):
    """Which programs outside Titan may control it."""
    known_now = clients()
    if not known_now:
        return ("No program outside Titan has asked to control it yet.")
    return '\n'.join(
        '%s: %s' % (entry['client'],
                    'may control Titan' if entry['allowed']
                    else 'may only read Titan')
        for entry in known_now)


def _allow(client='', allowed='', **_arguments):
    """Say yes or no about one, without waiting to be asked."""
    name = str(client or '').strip()
    if not name:
        return "Say which client."
    wanted = str(allowed or '').strip().lower()
    if wanted in ('', 'yes', 'true', '1', 'tak'):
        remember(name, True)
        return "%s may now control Titan." % name
    remember(name, False)
    return "%s may now only read Titan." % name


def _forget(client='', **_arguments):
    """Take the answer back, so the next arrival asks again."""
    name = str(client or '').strip()
    if not name:
        return "Say which client."
    if forget(name):
        return "Titan will ask again the next time %s connects." % name
    return "Titan has never been asked about %s." % name


def get_client_consent_actions():
    """(name, summary, params, risk, run) - the `titan` provider's own."""
    return (
        ('external_clients',
         "Which programs outside Titan have asked to control it, and "
         "whether they may. A client may always READ Titan; controlling "
         "it - running add-ons, pressing controls, changing settings, "
         "using the AI - is asked for once and remembered.",
         {}, 'auto', _list_clients),
        ('allow_client',
         "Allow or refuse one external client. Answering 'no' leaves it "
         "able to read Titan and unable to change anything.",
         {'client': {'type': 'string', 'required': True,
                     'description': "The client's id, as "
                                    "'external_clients' lists it."},
          'allowed': {'type': 'string',
                      'description': "'yes' or 'no'. Left out, yes."}},
         'confirm', _allow),
        ('forget_client',
         "Forget what was answered about one external client, so Titan "
         "asks again the next time it connects.",
         {'client': {'type': 'string', 'required': True,
                     'description': "The client's id."}},
         'confirm', _forget),
    )
