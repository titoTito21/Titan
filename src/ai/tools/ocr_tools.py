"""AI OCR for the AI - reading a window that has no accessibility at all.

AI OCR was built as something the *user* triggers with a hotkey. It is just as
useful as something the agent or the assistant reaches for on its own: when
``read_focused_window`` comes back empty because the program draws its own
widgets, this is the only way to find out what is on screen, and the only way
to press anything in it.

The tools mirror what the mimic does, minus the interface:

- ``ocr_read_window`` - photograph and read the window into structured text;
- ``ocr_ask`` - the same reading, aimed at one question ("is there a Skip
  button?"), which keeps the answer short and the request cheap;
- ``ocr_press`` / ``ocr_type`` / ``ocr_toggle`` / ``ocr_send_key`` - act on
  what was read;
- ``ocr_show_overlay`` - hand the whole thing to the user as real accessible
  controls placed over the real window.

Two safeguards are inherited rather than reimplemented, which is the point of
going through ``src/ai/ocr/actions.py``: a control is only ever pressed in the
window that was actually read, and only when the user has left "Let AI OCR
press controls" on.
"""

import threading

_last = {'screen': None, 'hwnd': 0}
_lock = threading.Lock()


def _remember(screen):
    with _lock:
        _last['screen'] = screen
        try:
            _last['hwnd'] = getattr(screen.capture, 'hwnd', 0) or 0
        except Exception:
            _last['hwnd'] = 0


def _screen(require=True):
    with _lock:
        screen = _last['screen']
    if screen is None and require:
        return None, ("Nothing has been read yet. Use ocr_read_window first.")
    return screen, ''


def _enabled():
    from src.settings.settings import get_setting
    value = get_setting('ocr_enabled', False, section='ai')
    if str(value).strip().lower() in ('1', 'true', 'yes', 'on'):
        return ''
    return ("AI OCR is switched off. Turn it on in Settings -> AI features "
            "('Enable AI OCR'). It sends a picture of the screen to the "
            "configured AI provider, which is why it is off by default.")


def _find_element(screen, name):
    """The element the user means, matched the way a person would name it."""
    wanted = str(name or '').strip().lower()
    if not wanted:
        return None, "Say which control."
    elements = screen.elements
    for element in elements:
        if str(getattr(element, 'name', '')).strip().lower() == wanted:
            return element, ''
    for element in elements:
        if wanted in str(getattr(element, 'name', '')).strip().lower():
            return element, ''
    names = ", ".join(str(getattr(e, 'name', '')) for e in elements
                      if str(getattr(e, 'name', '')).strip())[:400]
    return None, (f"There is no control called '{name}' in the reading. "
                  f"It has: {names or '(nothing named)'}.")


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
def ocr_read_window(scope="window", question="", **_):
    """Photograph the focused window and read it into structured text."""
    blocked = _enabled()
    if blocked:
        return blocked
    try:
        from src.ai.ocr import model as model_mod, recognizer
    except Exception as e:
        return f"AI OCR is not available: {e}"
    try:
        from src.ai.ai_provider import vision_unavailable_reason
        reason = vision_unavailable_reason()
        if reason:
            return reason
    except Exception:
        pass
    with _lock:
        previous = _last['screen']
    try:
        screen = recognizer.read_screen(
            scope=scope or 'window', previous=previous,
            question=question or '')
    except Exception as e:
        return f"Could not read the screen: {e}"
    _remember(screen)
    lines = model_mod.elements_as_lines(screen)
    if screen.warnings:
        lines.append('')
        lines.append("Notes: " + "; ".join(screen.warnings))
    lines.append('')
    lines.append("Act on this with ocr_press, ocr_type, ocr_toggle or "
                 "ocr_send_key, or hand it to the user with ocr_show_overlay.")
    return "\n".join(lines)


def ocr_ask(question, scope="window", **_):
    """Read the screen with one question in mind."""
    if not str(question).strip():
        return "Say what to look for on the screen."
    return ocr_read_window(scope=scope, question=question)


def ocr_last_reading(**_):
    """The last reading again, without spending another request."""
    screen, error = _screen()
    if error:
        return error
    from src.ai.ocr import model as model_mod
    return "\n".join(model_mod.elements_as_lines(screen))


# --------------------------------------------------------------------------- #
# Acting
# --------------------------------------------------------------------------- #
def _act(runner):
    screen, error = _screen()
    if error:
        return error
    try:
        from src.ai.ocr import actions as ocr_actions
    except Exception as e:
        return f"AI OCR cannot act: {e}"
    if not ocr_actions.can_act():
        return ("AI OCR is not allowed to press controls. Turn on "
                "'Let AI OCR press controls' in Settings -> AI features.")
    try:
        return runner(screen, ocr_actions)
    except Exception as e:
        return f"That did not work: {e}"


def ocr_press(name, **_):
    """Press a control that AI OCR has read."""
    def run(screen, ocr_actions):
        element, error = _find_element(screen, name)
        if error:
            return error
        return ocr_actions.activate(screen, element)
    return _act(run)


def ocr_type(name, text, **_):
    """Type into a field that AI OCR has read."""
    def run(screen, ocr_actions):
        element, error = _find_element(screen, name)
        if error:
            return error
        return ocr_actions.set_text(screen, element, text or '')
    return _act(run)


def ocr_toggle(name, **_):
    """Tick or untick a box that AI OCR has read."""
    def run(screen, ocr_actions):
        element, error = _find_element(screen, name)
        if error:
            return error
        return ocr_actions.toggle(screen, element)
    return _act(run)


def ocr_send_key(key, **_):
    """Send a whole key to the window that was read - no coordinates needed."""
    def run(screen, ocr_actions):
        return ocr_actions.send_key(screen, key)
    return _act(run)


def ocr_show_overlay(**_):
    """Put the reading on the real window as real accessible controls."""
    blocked = _enabled()
    if blocked:
        return blocked
    screen, error = _screen()
    if error:
        return error
    try:
        from src.ai.ocr import overlay
        from src.titan_core.actions.inproc import run_on_gui
    except Exception as e:
        return f"The AI OCR overlay is not available: {e}"
    with _lock:
        target_hwnd = _last['hwnd']
    value, failure = run_on_gui(
        lambda: overlay.show_overlay(screen, target_hwnd=target_hwnd,
                                     target_title=screen.title))
    if failure:
        return f"Could not show the overlay: {failure}"
    if value is None:
        return ("The overlay could not attach to that window. The reading is "
                "still available with ocr_last_reading.")
    return ("The reading is now on the window itself, as real controls the "
            "user can Tab through. Escape removes it.")


def get_ocr_tools():
    from src.ai.agent_tools import _tool
    S = {'type': 'string'}
    return [
        _tool('ocr_read_window',
              "Read a window that has no accessibility - a game menu, a custom "
              "installer, an app that exposes nothing. Takes a picture and "
              "returns its controls and text as structured lines. Use this "
              "when read_focused_window or list_elements comes back empty or "
              "useless.", ocr_read_window, risk='confirm',
              properties={'scope': dict(S, description="'window' (default) or 'screen'."),
                          'question': dict(S, description="Optional: what to look for.")}),
        _tool('ocr_ask',
              "Ask one question about what is on the screen right now ('is "
              "there a Skip button?', 'what does the error say?'). Reads the "
              "screen with that question in mind.", ocr_ask, risk='confirm',
              properties={'question': dict(S, description="The question."),
                          'scope': dict(S, description="'window' (default) or 'screen'.")},
              required=['question']),
        _tool('ocr_last_reading',
              "The last AI OCR reading again, without reading the screen "
              "afresh.", ocr_last_reading),
        _tool('ocr_press',
              "Press a control AI OCR has read, by its name.", ocr_press,
              risk='confirm',
              properties={'name': dict(S, description="The control's name as it was read.")},
              required=['name']),
        _tool('ocr_type', "Type into a field AI OCR has read.", ocr_type,
              risk='confirm',
              properties={'name': dict(S, description="The field's name."),
                          'text': dict(S, description="What to type.")},
              required=['name', 'text']),
        _tool('ocr_toggle', "Tick or untick a box AI OCR has read.",
              ocr_toggle, risk='confirm',
              properties={'name': dict(S, description="The box's name.")},
              required=['name']),
        _tool('ocr_send_key',
              "Send a whole key (Escape, Enter, an arrow) to the window AI OCR "
              "read. Needs no coordinates, so it works even when the reading "
              "could not place a control.", ocr_send_key, risk='confirm',
              properties={'key': dict(S, description="Key name, e.g. 'escape', 'enter', 'down'.")},
              required=['key']),
        _tool('ocr_show_overlay',
              "Hand the reading to the user: the controls appear on the real "
              "window as real accessible controls they can Tab through. Use "
              "this when the user should take over.", ocr_show_overlay,
              risk='confirm'),
    ]
