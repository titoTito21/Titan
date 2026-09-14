Earcon kits for the speech-and-sound schemes (ChromeVox, TalkBack,
VoiceOver). A kit is a folder here with one sound per control kind
(button.ogg, checkbox.ogg, link.ogg ... - the kind keys of
speechSchemes.KIND_KEYS), OR a single focus.ogg (and focus_actionable.ogg)
that plays on every control the way TalkBack and VoiceOver do.

How a kit sound is found (speechSchemes._play_kit), in order:
  1. <kit>/<kind>.ogg or .wav here, in the add-on's own data
  2. the same under a theme's reader/earcons/<kit>/
  3. <kit>/focus_actionable.ogg (actionable kinds) or <kit>/focus.ogg here
  4. the reader's own focus earcon for the kind

So a scheme works whatever the kit has: a full per-role kit (ChromeVox), a
one-focus-sound kit (TalkBack, VoiceOver), or an empty folder (the
reader's own earcons stand in). Drop a kit in and it is used at once.

  talkback   - bundled, from google/talkback (Apache 2.0). focus.ogg,
               focus_actionable.ogg, view_entered.ogg, long_clicked.ogg,
               hyperlink.ogg, chime_up/down.ogg. See talkback/LICENSE.txt.
  chromevox  - EMPTY. ChromeVox is open source (BSD); its earcons are in
               the Chromium source under the ChromeVox resources. Drop the
               per-role .ogg files here (button.ogg, link.ogg, ...), or a
               focus.ogg, to use them; the reader's own earcons stand in
               meanwhile.
  voiceover  - EMPTY. VoiceOver's earcons are Apple's and are NOT bundled.
               Put your own VoiceOver sound kit here (a focus.ogg is
               enough; per-kind files if you have them). Until then the
               reader's own earcons stand in.
