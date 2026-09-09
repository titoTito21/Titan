# -*- coding: utf-8 -*-
"""Make the add-on's auditory icons.

    python nvda-addon/make_sounds.py

**Emacspeak's oldest idea, and the one it is right about.** An auditory
icon is a sound under a quarter of a second that says what KIND of thing
just happened before a word of it is spoken - you know you are on a button,
that something opened, that a change was refused, while the synthesizer is
still drawing breath. T. V. Raman's own set is a folder of `.ogg` files
whose base names ARE the icon names (`select-object`, `task-done`,
`warn-user`), and every module asks for a name rather than a file, so a
theme is a folder that can be swapped.

The names here are Emacspeak's own, taken from its `sounds/chimes` theme,
so anybody who has used Emacspeak already knows what they mean and a theme
written for one could be dropped in for the other.

**They are made rather than collected**, and that is a deliberate choice:

* The add-on carries its own sounds, so an icon plays with no Titan
  running, no Titan Access installed and no sound theme - the user asked
  for exactly this ("te ikony dźwiękowe to już w samym addonie"), and it
  is the same rule NVDA's own sounds follow.
* A generated icon is auditable. A binary nobody can read is a thing
  shipped on trust; this is a table of frequencies anybody can change, and
  running this script again is the whole of "make them different".
* The standard library alone (`wave`, `math`, `struct`) makes them, so
  building the add-on needs nothing installed.

The shape of each one is chosen to be TOLD APART, which is the only thing
that matters: going in rises and coming out falls, yes is bright and no is
low, a refusal is rough where everything else is a clean chime, and the
sounds for things that happen constantly (moving onto a control, a row)
are the shortest and quietest.
"""

import math
import os
import struct
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
WHERE = os.path.join(HERE, 'addon', 'globalPlugins', 'titanEnhancements',
                     'sounds')

RATE = 44100
#: Loud enough to be heard under speech, quiet enough not to be the thing
#: you notice. An icon that makes somebody flinch is one they turn off.
LEVEL = 0.20

#: name -> (notes, kind). A note is (frequency in Hz, milliseconds, gain).
#: `kind` is how it is made: 'chime' is a sine with two quiet partials and a
#: fast decay; 'pure' is one sine; 'rough' adds a beating second tone, which
#: is what makes a refusal sound wrong rather than merely low.
ICONS = {
    # -------------------------------------------------- moving about
    # The ones that happen on every arrow key: short, quiet, unobtrusive.
    'select-object': ([(880, 28, 0.55)], 'pure'),
    'item': ([(740, 26, 0.45)], 'pure'),
    'button': ([(523, 34, 0.7)], 'chime'),
    'large-movement': ([(660, 26, 0.5), (990, 34, 0.5)], 'pure'),
    'ellipses': ([(1200, 18, 0.35), (1200, 18, 0.35)], 'pure'),
    # -------------------------------------------------- in and out
    'open-object': ([(523, 42, 0.7), (784, 58, 0.7)], 'chime'),
    'close-object': ([(784, 42, 0.7), (523, 58, 0.7)], 'chime'),
    'section': ([(392, 40, 0.6), (588, 40, 0.6)], 'chime'),
    'paragraph': ([(494, 34, 0.5)], 'chime'),
    # -------------------------------------------------- on and off
    'on': ([(660, 34, 0.7), (990, 46, 0.7)], 'chime'),
    'off': ([(990, 34, 0.7), (660, 46, 0.7)], 'chime'),
    'mark-object': ([(1046, 30, 0.7), (1318, 44, 0.7)], 'chime'),
    'deselect-object': ([(587, 30, 0.5)], 'pure'),
    # -------------------------------------------------- what happened
    'task-done': ([(523, 34, 0.7), (659, 34, 0.7), (880, 60, 0.8)], 'chime'),
    'save-object': ([(698, 36, 0.7), (1046, 60, 0.7)], 'chime'),
    'delete-object': ([(440, 34, 0.7), (330, 50, 0.7)], 'chime'),
    'modified-object': ([(587, 30, 0.6)], 'chime'),
    'unmodified-object': ([(392, 30, 0.5)], 'chime'),
    'yank-object': ([(880, 26, 0.6), (1174, 40, 0.6)], 'pure'),
    # -------------------------------------------------- being told things
    'warn-user': ([(233, 70, 0.8), (233, 70, 0.8)], 'rough'),
    'alert-user': ([(196, 110, 0.9)], 'rough'),
    'ask-question': ([(587, 40, 0.7), (880, 56, 0.7)], 'chime'),
    'help': ([(659, 30, 0.6), (784, 30, 0.6), (988, 40, 0.6)], 'pure'),
    'new-mail': ([(1046, 40, 0.7), (784, 40, 0.7), (1046, 56, 0.7)], 'chime'),
    'progress': ([(440, 22, 0.4)], 'pure'),
    'search-hit': ([(988, 34, 0.7), (1318, 46, 0.7)], 'chime'),
    'search-miss': ([(392, 44, 0.7), (294, 60, 0.7)], 'rough'),
    'yes-answer': ([(880, 40, 0.7), (1318, 50, 0.7)], 'chime'),
    'no-answer': ([(440, 40, 0.7), (294, 56, 0.7)], 'chime'),
}


def note(frequency, milliseconds, gain, kind):
    """One note as a list of samples between -1 and 1.

    The envelope matters more than the waveform: a chime is an instant
    attack and an exponential decay, and anything with a slow attack reads
    as a smear rather than an event. A 3 ms fade in stops the click a
    hard-edged start makes.
    """
    count = int(RATE * milliseconds / 1000.0)
    samples = []
    fade = max(1, int(RATE * 0.003))
    for index in range(count):
        where = index / float(count)
        # Exponential decay, so it is gone before it can be in the way.
        envelope = math.exp(-4.5 * where)
        if index < fade:
            envelope *= index / float(fade)
        angle = 2.0 * math.pi * frequency * index / RATE
        if kind == 'pure':
            value = math.sin(angle)
        elif kind == 'rough':
            # Two tones a few Hz apart beat against each other, which is
            # what makes this one sound wrong rather than merely low.
            value = 0.6 * math.sin(angle) + 0.6 * math.sin(angle * 1.06)
        else:
            value = (math.sin(angle)
                     + 0.28 * math.sin(2 * angle)
                     + 0.12 * math.sin(3 * angle))
        samples.append(value * envelope * gain)
    return samples


def build(notes, kind):
    made = []
    for frequency, milliseconds, gain in notes:
        made.extend(note(frequency, milliseconds, gain, kind))
    peak = max((abs(value) for value in made), default=1.0) or 1.0
    return [value / peak * LEVEL for value in made]


def write(path, samples):
    with wave.open(path, 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(b''.join(
            struct.pack('<h', int(max(-1.0, min(1.0, value)) * 32767))
            for value in samples))


def main():
    if not os.path.isdir(WHERE):
        os.makedirs(WHERE)
    for name, (notes, kind) in sorted(ICONS.items()):
        path = os.path.join(WHERE, name + '.wav')
        write(path, build(notes, kind))
        print('%-20s %6d bytes' % (name, os.path.getsize(path)))
    print('%d auditory icons in %s' % (len(ICONS), WHERE))


if __name__ == '__main__':
    main()
