# -*- coding: utf-8 -*-
"""Cling - the Klango subsystem for Titan.

Cling runs Klango-shaped applications: it reads the directory layout Klango
applications already have, speaks with Titan's own voice, plays their sounds
where their own topology puts them, and gives them a keyboard and a place to
save.  See `catalog` for what an application is, `host` for what one can do,
`engines` for the ones Cling drives from data alone, and `lua` for the
interpreter the component carries so that an application with its own logic
needs nothing installed.
"""

VERSION = '1.0'

__all__ = ['catalog', 'engines', 'host', 'klango_lua', 'kpak', 'lua',
           'resources', 'runner', 'store', 'topology']
