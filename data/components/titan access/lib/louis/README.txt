liblouis, bundled here so Titan Access's braille works on a machine that has
never had NVDA - a feature may require Titan, never Titan Access, and
Titan Access may require nothing outside its own folder.

  liblouis.dll   ..\liblouis.dll   the translator (LGPL 2.1 or later)
  louis/tables   the braille tables it reads (each carries its own licence
                 header; most are LGPL 3 or GPL 3)

Source and licences: https://github.com/liblouis/liblouis

titan_access/braille.py looks here FIRST (then a copy in an installed NVDA),
so the user's own or a newer liblouis is never overridden and a machine
with neither NVDA nor this bundle still gets the words, untranslated.
