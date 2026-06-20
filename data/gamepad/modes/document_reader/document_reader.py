"""
Document Reader - example custom gamepad mode for TCE.

Reads text into its OWN virtual buffer and navigates it with the gamepad. Only
Titan TTS / accessible_output3 speaks the text - the mode never drives the
focused application (no arrow keys, no caret movement, no selection changes).

Controls:

  * Up / Down      - read the previous / next line of the buffer
  * Left / Right   - spell the previous / next character
  * A button (0)   - read from the cursor to the end of the buffer
  * Y button (3)   - refresh the buffer from the current source
  * LB / RB (tap)  - switch the source and re-read it:
                     text field <-> clipboard
                     (HOLDING a bumper still changes the controller mode)

Two sources, each captured into the buffer (read-only):

  * Text field - the whole contents of the focused edit control, grabbed with
    WM_GETTEXT (no keystrokes, nothing moves). Works in standard edit controls
    (Notepad, many editors / text boxes); some web / UWP controls do not expose
    their text this way.
  * Clipboard - the current clipboard text, so you can review copied text
    anywhere, with nothing focused.

This folder doubles as a worked example of the gamepad mode API: a mode is a
package (folder) with a ``__mode__.TCE`` config, a main Python file and its own
``languages/`` folder, exactly like a component.
"""

from src.controller.gamepad_mode_api import (
    GamepadMode, setup_mode_translations, speak, play_mode_sound,
    get_clipboard_text, get_focused_window_text, is_edit_field_focused,
)

# This mode ships its own translations under ./languages (gettext domain
# "document_reader"), independent of the core translation domains.
_ = setup_mode_translations(__file__, 'document_reader')

# Reading sources, cycled with the bumpers.
SOURCE_TEXTFIELD = 'textfield'
SOURCE_CLIPBOARD = 'clipboard'
SOURCES = [SOURCE_TEXTFIELD, SOURCE_CLIPBOARD]


class DocumentReaderMode(GamepadMode):
    name = "Document reader"

    def __init__(self):
        self._source_index = 0
        self._lines = ['']
        self._line = 0
        self._col = 0

    def _source(self):
        return SOURCES[self._source_index]

    # -- virtual buffer ----------------------------------------------------- #
    def _grab_source_text(self):
        """Read the current source's text (read-only, no app control)."""
        if self._source() == SOURCE_CLIPBOARD:
            return get_clipboard_text() or ''
        return get_focused_window_text() or ''

    def _capture(self):
        """(Re)load the buffer from the current source and reset the cursor."""
        text = self._grab_source_text()
        self._lines = text.splitlines() or ['']
        self._line = 0
        self._col = 0

    def _current_line(self):
        self._line = max(0, min(self._line, len(self._lines) - 1))
        return self._lines[self._line]

    def _speak_char(self, ch):
        if ch == '' or ch is None:
            speak(_("Blank"))
        elif ch == ' ':
            speak(_("Space"))
        elif ch in ('\r', '\n', '\r\n'):
            speak(_("New line"))
        elif ch == '\t':
            speak(_("Tab"))
        else:
            speak(ch)

    # -- navigation (buffer only) ------------------------------------------- #
    def _read_line(self, direction):
        self._line = max(0, min(self._line + direction, len(self._lines) - 1))
        self._col = 0
        line = self._current_line()
        play_mode_sound('joystick/ui2.ogg')
        speak(line if line.strip() else _("Blank line"))

    def _spell_char(self, direction):
        line = self._current_line()
        self._col = max(0, min(self._col + direction, max(len(line) - 1, 0)))
        ch = line[self._col] if 0 <= self._col < len(line) else ''
        play_mode_sound('joystick/ui1.ogg')
        self._speak_char(ch)

    def _read_to_end(self):
        line = self._current_line()
        text = '\n'.join([line[self._col:]] + self._lines[self._line + 1:])
        play_mode_sound('joystick/ui2.ogg')
        speak(text if text.strip() else _("End of document"))

    def _source_name(self):
        return _("Clipboard") if self._source() == SOURCE_CLIPBOARD else _("Text field")

    def _announce_source(self):
        """Capture the source and read it (announce name + first line)."""
        self._capture()
        line = self._current_line()
        if self._source() == SOURCE_TEXTFIELD and not line.strip() \
                and not is_edit_field_focused():
            body = _("Not in a text field")
        else:
            body = line if line.strip() else _("Blank line")
        speak("{}. {}".format(self._source_name(), body))

    # -- API hooks ---------------------------------------------------------- #
    def on_activate(self, manager):
        self._capture()
        speak(_("Document reader. Up and down read lines, left and right spell "
                "characters, A reads to the end. Bumpers switch between text "
                "field and clipboard."))

    def handle_axis(self, axis_id, value):
        # Left stick only (axis 0 = X, axis 1 = Y).
        if axis_id == 1:  # vertical -> line navigation
            self._read_line(-1 if value < 0 else 1)
            return True
        elif axis_id == 0:  # horizontal -> character navigation
            self._spell_char(-1 if value < 0 else 1)
            return True
        return False

    def handle_hat(self, x, y):
        # Mirror the left stick on the d-pad.
        if y != 0:
            self._read_line(-1 if y > 0 else 1)  # hat y: +1 = up
            return True
        if x != 0:
            self._spell_char(-1 if x < 0 else 1)
            return True
        return False

    def handle_button(self, button_id):
        if button_id == 0:  # A -> read to end
            self._read_to_end()
            return True
        if button_id == 3:  # Y -> refresh buffer from current source
            play_mode_sound('joystick/ui1.ogg')
            self._announce_source()
            return True
        return False

    def handle_bumper(self, is_left):
        # Tap a bumper to switch the source (text field <-> clipboard) and read it.
        self._source_index = (self._source_index + (-1 if is_left else 1)) % len(SOURCES)
        play_mode_sound('joystick/ui1.ogg')
        self._announce_source()
        return True
