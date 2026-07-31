"""
Example Titan-Net SERVICE - a whole multi-screen tool, written only here.

This is the shape to copy when you want more than a form: a service window
with a menu bar, a tab bar, a list you arrow through, and screens that open
other screens. None of it exists in the Titan client. The client owns one
generic renderer; everything below - the tabs, the rows, what Enter does,
what the menu items mean - is decided by this file, on the server.

Which means: you (or Claude) can write a new Titan-Net service today and it
opens on Titan installs that were built long before it existed.

Publish it::

    python remote_ui_admin.py save remote_ui_handlers/example_service.json \\
           --slug noticeboard --handler example_service

It then appears in every client's "Server" menu.

The handler contract, in full:

* ``ctx.action`` is ``'open'`` the first time, then the id of whatever the
  user fired - a row's ``action``, a button's ``id``, a menu item's ``id``,
  or one of the built-ins ``'refresh'`` (F5 / auto-refresh) and ``'tab'``
  (tab bar cycled; the new tab is in ``ctx.values['tab']``).
* ``ctx.item`` is the id of the row the user pressed Enter on, and
  ``ctx.row`` is that whole row including any ``data`` you attached.
* ``ctx.values`` holds the control values, already typed and range-checked.
* Return ``view(...)`` to go deeper, ``refresh(...)`` to update the list the
  user is standing in without moving them, ``back()`` to go up, ``goto()``
  for a form, ``close()`` to finish, ``error()`` to reject a field.
"""

import logging
from datetime import datetime

from remote_ui import (
    handler, view, refresh, back, goto, close, message, error,
)

logger = logging.getLogger('TitanNetRemoteUI')

# Stand-in for whatever a real service reads - a database table, an API, a
# queue. The point is that this data never has to reach the client as
# anything but rows of text.
_NOTICES = {
    'general': [
        {'id': 'n1', 'title': 'Server maintenance on Sunday',
         'author': 'Titan-Net', 'body': 'Expect a short outage around 02:00.'},
        {'id': 'n2', 'title': 'New audio theme available',
         'author': 'Titan-Net', 'body': 'Try it under Settings, Sound.'},
    ],
    'wanted': [
        {'id': 'w1', 'title': 'Looking for testers',
         'author': 'ala', 'body': 'Anyone with a gamepad, please get in touch.'},
    ],
}

TABS = [
    {'id': 'general', 'label': 'Announcements'},
    {'id': 'wanted', 'label': 'Wanted'},
]

MENUS = [
    {
        'label': 'Notice',
        'items': [
            {'id': 'new_notice', 'label': 'Write a notice...'},
            {'id': 'delete_notice', 'label': 'Delete this notice',
             'confirm': 'Delete the selected notice?'},
            '-',
            {'id': 'close', 'label': 'Close', 'action': 'close'},
        ],
    },
    {
        'label': 'View',
        'items': [
            {'id': 'refresh', 'label': 'Refresh', 'action': 'refresh'},
        ],
    },
]


def _board(tab: str, note: str = None):
    """Build the list for one tab. This IS the service's main screen."""
    notices = _NOTICES.get(tab, [])
    rows = [{
        'id': notice['id'],
        'label': notice['title'],
        # Spoken after the label - the detail that would not fit in a list.
        'sublabel': f"by {notice['author']}",
        'action': 'read',
        # Anything you attach here comes back untouched as ctx.row['data'].
        'data': {'tab': tab},
    } for notice in notices]

    status = note or f"{len(rows)} notices"
    return view(
        title='Noticeboard',
        items=rows,
        tabs=TABS,
        active_tab=tab,
        menus=MENUS,
        status=status,
        empty='Nothing posted here yet.',
        fields=[{'type': 'text', 'id': 'search', 'label': 'Search'}],
        buttons=[{'id': 'do_search', 'label': 'Search', 'action': 'submit'}],
    )


def _find(notice_id: str):
    for tab, notices in _NOTICES.items():
        for notice in notices:
            if notice['id'] == notice_id:
                return tab, notice
    return None, None


@handler('example_service')
def example_service(ctx):
    action = ctx.action

    # --- entering the service -------------------------------------------
    if action == 'open':
        return _board(TABS[0]['id'])

    # --- the tab bar was cycled -----------------------------------------
    if action == 'tab':
        return _board(ctx.values.get('tab') or TABS[0]['id'])

    # --- F5 / the auto-refresh timer ------------------------------------
    if action == 'refresh':
        # refresh() updates the list in place, so the user does not lose
        # their position - which matters enormously when the list is being
        # read aloud.
        tab = (ctx.row or {}).get('data', {}).get('tab') or TABS[0]['id']
        rows = [{'id': n['id'], 'label': n['title'],
                 'sublabel': f"by {n['author']}", 'action': 'read'}
                for n in _NOTICES.get(tab, [])]
        return refresh(items=rows,
                       status=f"{len(rows)} notices, checked at "
                              f"{datetime.now().strftime('%H:%M:%S')}")

    # --- Enter on a row: go one level deeper ----------------------------
    if action == 'read':
        _tab, notice = _find(ctx.item)
        if notice is None:
            return refresh(status='That notice is gone.')
        # Another view, so Escape brings the user straight back to the list.
        return view(
            title=notice['title'],
            items=[{'id': 'reply', 'label': 'Reply to this notice',
                    'action': 'reply_form'}],
            status=f"by {notice['author']}",
            description=notice['body'],
            menus=[{'label': 'Notice', 'items': [
                {'id': 'back', 'label': 'Back to the list'},
                {'id': 'close', 'label': 'Close', 'action': 'close'},
            ]}],
        )

    if action == 'back':
        return back()

    # --- a row opening a FORM rather than another list -------------------
    if action in ('reply_form', 'new_notice'):
        return goto({
            'title': 'Write a notice' if action == 'new_notice' else 'Reply',
            'fields': [
                {'type': 'text', 'id': 'subject', 'label': 'Subject',
                 'required': True, 'max_length': 120},
                {'type': 'multiline', 'id': 'body', 'label': 'Message',
                 'required': True},
            ],
            'buttons': [
                {'id': 'post', 'label': 'Post', 'action': 'submit', 'default': True},
                {'id': 'cancel', 'label': 'Cancel', 'action': 'cancel'},
            ],
        })

    if action == 'post':
        subject = (ctx.values.get('subject') or '').strip()
        if len(subject) < 3:
            return error({'subject': 'Give the notice a real subject'})
        logger.info(f"[REMOTE-UI] {ctx.username} posted a notice: {subject}")
        # Do the real work here, then close the form. The service window
        # underneath refreshes itself when the form closes.
        return close(message='Posted.', sound='notify')

    # --- the search box + its button ------------------------------------
    if action == 'do_search':
        query = (ctx.values.get('search') or '').strip().lower()
        if not query:
            return _board(TABS[0]['id'], note='Type something to search for.')
        hits = [{'id': n['id'], 'label': n['title'],
                 'sublabel': f"by {n['author']}", 'action': 'read'}
                for notices in _NOTICES.values() for n in notices
                if query in n['title'].lower() or query in n['body'].lower()]
        return view(title=f"Search: {query}", items=hits,
                    status=f"{len(hits)} matches",
                    empty='Nothing matched.')

    # --- a menu item acting on the focused row --------------------------
    if action == 'delete_notice':
        if not ctx.item:
            return refresh(status='Select a notice first.')
        tab, notice = _find(ctx.item)
        if notice is None:
            return refresh(status='That notice is gone.')
        # Real services would check permissions here - ctx.is_moderator,
        # ctx.db, whatever applies. The client cannot bypass any of it.
        if not ctx.is_moderator and notice['author'] != ctx.username:
            return refresh(status='That is not your notice.')
        _NOTICES[tab] = [n for n in _NOTICES[tab] if n['id'] != ctx.item]
        return _board(tab, note='Deleted.')

    return message(f"'{action}' is not wired up in this example yet.")
