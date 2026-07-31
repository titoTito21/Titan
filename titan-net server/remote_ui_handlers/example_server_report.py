"""
Example Remote UI handler - copy this file to build your own server screen.

Every ``.py`` in this directory is imported once at server start, and any
handler it registers becomes available to screens whose ``handler`` column
names it. The point of the whole mechanism: everything interesting happens
HERE, on the server, while clients only ever render the JSON you hand back.
So you can add a new Titan-Net tool - a form, a report, a moderation action -
without a single user updating their Titan.

To publish the screen that uses this handler::

    python remote_ui_admin.py save remote_ui_handlers/example_server_report.json \\
           --slug server_report --handler example_server_report

Then it appears in every client's "Server" menu, with no client update.

For a whole multi-screen SERVICE - menu bar, tabs, lists, drill-down - copy
``example_service.py`` instead; this file is the single-form case.
"""

import logging

from remote_ui import handler, close, error, message

logger = logging.getLogger('TitanNetRemoteUI')


@handler('example_server_report')
def example_server_report(ctx):
    """A two-mode screen: fill it in on open, act on it when submitted.

    ``ctx.action`` is ``'open'`` the first time and the pressed button's id
    afterwards. ``ctx.values`` holds the field values, already validated
    against the screen's own definition, so anything present here is a value
    the screen actually declared.
    """
    if ctx.action == 'open':
        # Populate the screen with live data. The client had no idea these
        # options existed until this moment - that is the whole trick.
        try:
            users = ctx.db.get_all_users() or []
        except Exception as e:
            logger.error(f"[REMOTE-UI] example: could not list users: {e}")
            users = []
        usernames = sorted(u['username'] for u in users if u.get('username'))
        return ctx.fill({
            'about_user': {'items': usernames or ['(nobody)']},
            'summary': {'text': f"{len(usernames)} accounts exist on this server."},
        })

    if ctx.action == 'send':
        details = (ctx.values.get('details') or '').strip()
        if len(details) < 10:
            # Field-level rejection: the client focuses that field and speaks
            # the reason, exactly like a hand-written dialog would.
            return error({'details': 'Please describe the problem in at least 10 characters'})

        subject = ctx.values.get('about_user') or '(nobody)'
        logger.info(f"[REMOTE-UI] {ctx.username} reported {subject}: {details[:120]}")

        # Do whatever the component actually needs to do here - write to the
        # database, mail a moderator, jail someone - then tell the client how
        # to finish. Any registered server sound can be played by name.
        return close(message="Report received. A moderator will look at it.",
                     sound="notify")

    if ctx.action == 'refresh':
        # Update the OPEN screen instead of closing it.
        from remote_ui import update
        try:
            online = len(getattr(ctx.server, 'clients', {}) or {})
        except Exception:
            online = 0
        return update({}, text=f"{online} clients are connected right now.")

    return message("That button is not wired up yet.")
