# -*- coding: utf-8 -*-
"""
The External clients tab of the Component Manager.

An external client is another program on Titan's Action Bus - the Elten TCE
bridge, the NVDA add-on, a script of somebody's own. Titan asks, when one
arrives, whether it may CONTROL Titan (`client_consent.py`), and says out
loud that it arrived and left (`actions/bus.py`). Until now neither answer
could be found again: the refusal told the user to look "in Settings,
General, under External clients", and there was no such place.

This is that place, as rows of the Component Manager:

* two rows that are Titan's own settings about clients - what happens when a
  NEW client connects (ask, allow, refuse) and whether arriving and leaving
  is announced;
* one row per client Titan has met - connected now, or answered about
  before - saying whether it may control Titan. Space switches it; the
  actions menu also offers "ask again next time".

Reading Titan is never part of this: a client may always read, and these
settings are only about acting.
"""

from src.titan_core import client_consent
from src.titan_core.translation import set_language
from src.settings.settings import get_setting

_ = set_language(get_setting('language', 'pl'))

KIND = 'client'
POLICY_ROW = '__new_client_policy__'
ANNOUNCE_ROW = '__announce_clients__'
POLICIES = ('ask', 'allow', 'deny')


def _policy_words():
    return {'ask': _("ask me"),
            'allow': _("allow it to control Titan"),
            'deny': _("do not allow it to control Titan")}


def _connected():
    """{client id: label} of the clients on the bus right now."""
    found = {}
    try:
        from src.titan_core.actions import bus
        for peer in bus.list_peers():
            if bus._is_external_client(peer) and getattr(peer, 'alive', True):
                found[client_consent._key(peer.addon_id)] = (
                    getattr(peer, 'label', '') or peer.addon_id)
    except Exception as error:                       # noqa: BLE001
        print(f"[external_clients] could not read the bus: {error}")
    return found


def _module(ident, name, enabled, state, description=''):
    from src.titan_core.modules import Module
    module = Module(KIND, ident, name, description, '', enabled)
    # The Component Manager says this instead of "Enabled"/"Disabled": a
    # client is allowed or not, a setting has an answer.
    module.state_text = state
    return module


def _client_state(answer, connected):
    if answer is True:
        state = _("allowed to control Titan")
    elif answer is False:
        state = _("not allowed to control Titan")
    else:
        state = _("Titan will ask")
    if connected:
        state += ", " + _("connected")
    return state


def rows():
    """Every row of the tab: the two settings, then the clients."""
    policy = client_consent.new_client_policy()
    announce = client_consent.announce_clients()
    result = [
        _module(POLICY_ROW, _("When a new external client connects"),
                policy != 'deny', _policy_words()[policy],
                _("What Titan does when a program it has not met before "
                  "connects and wants to control it. A client can always "
                  "read what Titan is showing; this is about acting.")),
        _module(ANNOUNCE_ROW,
                _("Announce when an external client connects or closes"),
                announce, _("on") if announce else _("off"),
                _("A sound and a sentence when another program takes hold "
                  "of Titan and when it lets go.")),
    ]
    connected = _connected()
    answers = {entry['client']: entry['allowed']
               for entry in client_consent.clients()}
    for ident in sorted(set(answers) | set(connected)):
        answer = client_consent.known(ident)
        label = connected.get(ident) or ident
        description = (_("Connected to Titan now.") if ident in connected
                       else _("Not connected now."))
        result.append(_module(ident, label, answer is True,
                              _client_state(answer, ident in connected),
                              description))
    return result


def _refresh(module):
    for fresh in rows():
        if fresh.id == module.id:
            module.enabled = fresh.enabled
            module.state_text = fresh.state_text
            module.description = fresh.description
            return module
    return module


def set_policy(policy):
    client_consent.set_new_client_policy(policy)
    return _("When a new external client connects: {}").format(
        _policy_words()[client_consent.new_client_policy()])


def set_announce(on):
    client_consent.set_announce_clients(on)
    return (_("Connections of external clients will be announced") if on
            else _("Connections of external clients will not be announced"))


def set_client(module, allowed):
    client_consent.remember(module.id, bool(allowed))
    _refresh(module)
    return (_("{} may control Titan").format(module.name) if allowed
            else _("{} may not control Titan").format(module.name))


def ask_again(module):
    client_consent.forget(module.id)
    _refresh(module)
    return _("Titan will ask about {} when it next connects").format(module.name)


def toggle(module):
    """Space on a row. Answers the sentence to say."""
    if module.id == POLICY_ROW:
        current = client_consent.new_client_policy()
        following = POLICIES[(POLICIES.index(current) + 1) % len(POLICIES)]
        message = set_policy(following)
    elif module.id == ANNOUNCE_ROW:
        message = set_announce(not client_consent.announce_clients())
    else:
        message = set_client(module, client_consent.known(module.id) is not True)
    _refresh(module)
    return message


def set_enabled(module, enabled):
    """The Component Manager's (and the modules actions') on/off."""
    from src.titan_core.modules import Change
    if module.id == POLICY_ROW:
        set_policy('ask' if enabled else 'deny')
    elif module.id == ANNOUNCE_ROW:
        set_announce(enabled)
    else:
        set_client(module, enabled)
    _refresh(module)
    return Change(True, 'live')


def menu(module):
    """[(label, callable -> sentence)] for the row's actions menu."""
    if module.id == POLICY_ROW:
        words = _policy_words()
        return [(_("When a new client connects: {}").format(words[policy]),
                 lambda p=policy: set_policy(p)) for policy in POLICIES]
    if module.id == ANNOUNCE_ROW:
        return [(_("Announce connections"), lambda: set_announce(True)),
                (_("Do not announce connections"), lambda: set_announce(False))]
    return [(_("Allow it to control Titan"), lambda: set_client(module, True)),
            (_("Do not allow it to control Titan"),
             lambda: set_client(module, False)),
            (_("Ask again when it next connects"), lambda: ask_again(module))]
