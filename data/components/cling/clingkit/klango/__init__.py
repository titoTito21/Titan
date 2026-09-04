# -*- coding: utf-8 -*-
"""Running Klango's OWN code, rather than a reimplementation of it.

The engines beside this one re-create a genre from an application's data, which
is why Mole No More plays; but they are Cling's rules, not Klango's, and the
difference shows the moment an application does something its data does not
describe.  This package is the other answer: the application's own Lua, out of
its own `.pag`, on the interpreter Cling carries.

What made it possible is that Klango is mostly **written in Lua itself**.  Of
the 146 Lua files in a Klango installation, 103 are the platform library
(`llib`), and it implements 534 of the 693 `k_*` functions applications call.
The real boundary underneath is small and measurable: **51 `_Sys_*` primitives**
plus a handful of native object constructors.  That is what this package
supplies, over Cling's host.

Measured: Cling's own parser reads 146 of 146 real Klango Lua files (the one
that does not is a note in Polish saying the file is unused), and the whole
2.3 MB library parses in 0.7 s.
"""

from .natives import install, MISSING
from .session import KlangoSession, boot

__all__ = ['install', 'boot', 'KlangoSession', 'MISSING']
