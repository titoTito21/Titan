Empty of audio. ChromeVox is open source (BSD-3-Clause, part of Chromium),
so its earcons MAY be bundled with attribution - drop them in here and the
"Like ChromeVox" scheme uses them at once; until then the reader's own
earcons stand in.

Where they are: the Chromium source, under the ChromeVox resources at
common/earcons/ (chrome/browser/resources/chromeos/accessibility/chromevox/
.../common/earcons/). The names come from earcon_engine.ts's WavSoundFile
and OggSoundFile and its per-role switch.

Rename each ChromeVox file to this add-on's control-kind key (the file's
own extension, .wav or .ogg, is kept):

  button.wav        -> button.wav
  link              -> link
  check_on          -> checkbox.<ext>   (the ticked earcon)
  check_off         -> radio.<ext>
  list_item         -> listitem.<ext>
  editable_text     -> edit.<ext>
  pop_up_button     -> combobox.<ext>
  object_enter      -> window.<ext>
  object_select     -> tab.<ext>
  control.wav       -> other.wav        (ChromeVox's base sound for most
                                         controls - or name it focus.wav to
                                         cover every kind at once)

A single focus.wav (a copy of control.wav) is enough: the scheme falls back
to <kit>/focus for any kind without its own file.

BSD-3-Clause requires the licence and copyright notice be kept with the
files; put Chromium's LICENSE beside them here as LICENSE.txt.
