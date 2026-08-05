"""The nine add-on kinds, and which transport each one uses.

This table is the single place that knows where a kind lives on disk and
whether its code runs inside Titan's process or in one of its own. Both
``src/ai/titan_tools.py`` and the action registry read it, so the two can never
drift apart.
"""

# kind id -> (label, subdir under data/, top-level resource dir?, default transport)
ADDON_KINDS = {
    'app':              ("Applications",      'applications',      False, 'process'),
    'game':             ("Games",             'games',             False, 'process'),
    'component':        ("Components",        'components',        False, 'inproc'),
    'launcher':         ("Launchers",         'launchers',         False, 'inproc'),
    'im_module':        ("Titan IM modules",  'titanIM_modules',   False, 'inproc'),
    'gamepad_mode':     ("Gamepad modes",     'gamepad/modes',     False, 'inproc'),
    'tts_engine':       ("TTS engines",       'titantts engines',  False, 'inproc'),
    'widget':           ("Widgets",           'applets',           False, 'inproc'),
    'statusbar_applet': ("Statusbar applets", 'statusbar_applets', False, 'inproc'),
    'language':         ("Languages",         'languages',         True,  None),
}

# Kinds whose add-ons can declare actions. Languages are data, not code.
ACTIONABLE_KINDS = tuple(k for k, v in ADDON_KINDS.items() if v[3])


def kind_label(kind):
    entry = ADDON_KINDS.get(kind)
    return entry[0] if entry else kind


def kind_subdir(kind):
    entry = ADDON_KINDS.get(kind)
    return entry[1] if entry else None


def kind_is_resource(kind):
    entry = ADDON_KINDS.get(kind)
    return bool(entry[2]) if entry else False


def default_transport(kind):
    entry = ADDON_KINDS.get(kind)
    return entry[3] if entry else 'inproc'


def discover_kind(kind):
    """{entry name -> absolute path} for one kind, across bundled and user
    roots, with packaged .TCA/.TCD add-ons transparently extracted."""
    subdir = kind_subdir(kind)
    if not subdir:
        return {}
    try:
        from src import platform_utils
        if kind_is_resource(kind):
            return platform_utils.discover_resource_entries(subdir)
        return platform_utils.discover_data_entries(subdir)
    except Exception as e:
        print(f"[actions] Could not discover {kind}: {e}")
        return {}
