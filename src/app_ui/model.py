# -*- coding: utf-8 -*-
"""What an application's interface IS, with nothing about how it looks.

This is the reverse of `data/components/elten_bridge/`: that one runs
Elten's applications inside Titan's interface, and this one lets Titan's
own applications be worn by somebody else's - Elten's, the Invisible UI's,
a launcher's, a script's. The application is never modified. It goes on
being an ordinary wxPython program; what changes is which `wx` it imports.

**The description is neutral on purpose.** It would have been shorter to
describe a screen the way Elten wants one, and it would have been the
mistake this repository has already made once and fixed: Titan's settings
are described by `src/settings/ui_model.py` without the description
knowing what a settings interface is, which is why a setting added to
`settingsgui.py` appears in every installed interface without any of them
changing. The same rule here buys the same thing - one shim, and the
application is in Elten AND in the Invisible UI AND in Titan Script.

A screen is a list of controls, because that is what every interface this
serves can render. Layout is deliberately absent: a sizer says where a
button is on a rectangle nobody is looking at, and an interface made of
speech has no rectangle. `wx.BoxSizer` and its whole family are therefore
a sink in the shim rather than something described here.
"""

#: What a control IS, which is the only thing an interface needs to render
#: it. Chosen to be the intersection of what Titan's applications really
#: use (measured: 17 widget classes across all of them) and what an
#: interface built out of speech can carry.
KINDS = (
    'label',      # text that is read, not edited
    'text',       # one line the user types into
    'multiline',  # a page they type into
    'button',     # something to press
    'check',      # on or off
    'choice',     # one of a few
    'list',       # rows, one chosen
    'table',      # rows with columns - a ListCtrl in report mode
    'tree',       # rows that nest
    'slider',     # a number between two numbers
    'gauge',      # a number being reported, not set
    'tabs',       # a notebook's pages
)

#: A screen is one of these. A `dialog` is answered and left; a `window`
#: is where the application lives.
SCREENS = ('window', 'dialog', 'message', 'question', 'entry', 'pick')


def control(identifier, kind, label='', **rest):
    """One control, as an interface will be given it.

    Only `id`, `kind` and `label` are always there. Everything else is
    per kind and absent when it does not apply, so an interface renders
    what it is given and skips what it does not recognise - which is what
    keeps an older renderer working against a newer shim, the same rule
    Titan-Net's remote UI is built on.
    """
    described = {'id': int(identifier), 'kind': str(kind),
                 'label': str(label or '')}
    for name, value in rest.items():
        if value is not None:
            described[name] = value
    return described


def screen(identifier, kind='window', title='', controls=(), menus=(),
           focus=None, modal=False):
    """A window or a dialog, as an interface will be given it."""
    return {'id': int(identifier), 'kind': str(kind), 'title': str(title or ''),
            'controls': list(controls), 'menus': list(menus),
            'focus': focus, 'modal': bool(modal)}


def menu(label, items):
    """A menu and what is on it. An item with no `id` is a separator."""
    return {'label': str(label or ''), 'items': list(items)}


def readable(entry):
    """One control as a sentence, for an interface that has only sentences.

    The floor under every renderer: a caller that cannot build a real
    control can still say what is there, and something said is always
    better than a control silently missing.
    """
    kind = entry.get('kind', '')
    label = entry.get('label', '') or _kind_word(kind)
    if kind in ('list', 'table', 'tree'):
        rows = entry.get('items') or []
        index = entry.get('index')
        where = ''
        if isinstance(index, int) and 0 <= index < len(rows):
            where = ', %s' % _row_text(rows[index])
        return '%s, %d%s' % (label, len(rows), where)
    if kind == 'check':
        return '%s, %s' % (label, 'checked' if entry.get('value') else 'unchecked')
    if kind == 'choice':
        options = entry.get('options') or []
        index = entry.get('index')
        if isinstance(index, int) and 0 <= index < len(options):
            return '%s, %s' % (label, options[index])
        return label
    if kind in ('text', 'multiline'):
        return '%s, %s' % (label, entry.get('value') or '')
    if kind in ('slider', 'gauge'):
        return '%s, %s' % (label, entry.get('value'))
    return label


def _row_text(row):
    if isinstance(row, (list, tuple)):
        return ', '.join(str(cell) for cell in row)
    return str(row)


def _kind_word(kind):
    return {'button': 'button', 'label': 'text', 'check': 'check box',
            'choice': 'choice', 'list': 'list', 'table': 'table',
            'tree': 'tree', 'slider': 'slider', 'gauge': 'progress',
            'text': 'field', 'multiline': 'text'}.get(kind, kind or 'control')
