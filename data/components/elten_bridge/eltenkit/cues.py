# -*- coding: utf-8 -*-
"""Elten's interface sounds, made out of Titan's sound theme.

Copyright (C) 2026 titosoft. Part of the Elten API bridge, licensed under the
GNU General Public License version 3 or later; see `LICENSE` beside this
component.

Moving onto a row, choosing it, reaching the end of a list, a dialog opening,
a wrong key: an Elten application makes a sound for each of these, and it
should make TITAN's. The user chose a sound theme and this is their desktop -
an application that brought its own set would be the one thing on it that
sounds like somewhere else.

The rule is exactly Cling's, for exactly the same reason, and so is its
limit: this maps the PLATFORM's cues only. A sound that belongs to the
application - a card being dealt, a clay pigeon, a bird - is the application,
not the interface, and Titan has nothing to say about it. Those come out of
the package's own `Audio/` folder as they always did.

A name that is not here falls through to the application's own sound of that
name, so mapping one can never lose a sound - it can only replace one that
Titan has an opinion about.
"""

#: Elten's own cue name -> the sound in Titan's theme.
#:
#: The names on the left are read out of Elten's own source (`play_sound("…")`
#: across `src/`), not invented, and the ones on the right are the cues Titan
#: already uses for the same thing everywhere else.
CUES = {
    # ---------------------------------------------------- moving onto things
    'listbox_focus': 'core/FOCUS.ogg',
    'listbox_marker': 'core/FOCUS.ogg',
    'form_marker': 'core/FOCUS.ogg',
    'editbox_marker': 'core/FOCUS.ogg',
    'button_marker': 'core/FOCUS.ogg',
    'table_marker': 'core/FOCUS.ogg',
    'tree_marker': 'core/FOCUS.ogg',

    # ------------------------------------------- what KIND of file that is
    # Elten's file manager plays one of these as the cursor moves, and it
    # is not decoration: it is how somebody who cannot see the folder
    # knows a folder from a song from a document without waiting for the
    # name to be read out. Five different sounds Titan already has, so
    # the five stay five.
    'file_dir': 'ui/focus_expanded.ogg',
    'file_audio': 'ui/notify.ogg',
    'file_text': 'ui/statusbar.ogg',
    'file_archive': 'ui/drag.ogg',
    'file_document': 'ui/popup.ogg',

    # ------------------------------------------------------- choosing one
    'listbox_select': 'core/SELECT.ogg',
    'button_press': 'core/SELECT.ogg',
    'activate': 'core/SELECT.ogg',
    'signal': 'core/SELECT.ogg',

    # ------------------------------------------- a branch opening and closing
    'listbox_treeexpand': 'ui/focus_expanded.ogg',
    'listbox_treecollapse': 'ui/focus_collabsed.ogg',

    # ------------------------------------------------------- a tick box
    'listbox_statechecked': 'ui/cb_listitem_checked.ogg',
    'listbox_stateunchecked': 'ui/cb_listitem_checked.ogg',

    # --------------------------------------------- the end of it, and errors
    'border': 'ui/endoflist.ogg',
    'endoflist': 'ui/endoflist.ogg',
    'error': 'core/error.ogg',
    'cancel': 'ui/popupclose.ogg',

    # ------------------------------------------ windows opening and closing
    'menu_open': 'ui/contextmenu.ogg',
    'menu_close': 'ui/contextmenuclose.ogg',
    'dialog_open': 'ui/dialog.ogg',
    'dialog_close': 'ui/dialogclose.ogg',
    'window_open': 'ui/uiopen.ogg',
    'window_close': 'ui/uiclose.ogg',

    # -------------------------------------------------------- typing in a box
    'editbox_space': 'ui/statusbar.ogg',
    'editbox_endofline': 'ui/endoflist.ogg',
    'editbox_delete': 'core/click.ogg',
    'editbox_bigletter': 'ui/tip.ogg',
    'editbox_textselected': 'ui/drag.ogg',
    'editbox_textunselected': 'ui/drop.ogg',

    # ------------------------------------------------- the network and mail
    'messages_update': 'ui/msg.ogg',
    'notification': 'ui/notify.ogg',
    'login': 'ui/uiopen.ogg',
    'logout': 'ui/uiclose.ogg',

    # ------------------------------------------------------------ recording
    'recording_start': 'ui/srbegin.ogg',
    'recording_stop': 'ui/srend.ogg',
}


def titan_cue(name):
    """The Titan theme sound for one of Elten's cues, or ''.

    An empty answer means "not one of Titan's" - the caller then looks for
    the application's own sound of that name, which is what keeps a mapping
    from ever losing a sound.
    """
    return CUES.get(str(name or '').strip().lower(), '')
