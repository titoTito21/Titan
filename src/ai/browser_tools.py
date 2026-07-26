"""Web-browser automation tools for the Titan AI Agent and voice assistant.

These give the AI a *real* browser it can drive: open a page, read the page's
text and its interactive elements (links, form fields, buttons, drop-downs),
fill in form fields by their label, choose drop-down options, click links and
buttons, submit forms and go back. This is what lets the assistant "walk around
websites and fill in forms" rather than only opening a URL.

The browser is a single persistent Selenium session (visible, not headless, so a
low-vision user - or the screenshot / computer-use tools - can also see it). It
is created lazily on the first browser action and reused across the whole turn.

Selenium is an OPTIONAL dependency. If it (or a supported browser) is missing,
every tool returns a clear message telling the user to ``pip install selenium``
and the model is told, via the system prompt, to fall back to opening the page
in the normal browser and using its screen-reading / clicking tools instead.

Tool result strings are plain English (untranslated), matching
:mod:`src.ai.agent_tools`; the human-readable action descriptions used for
narration / confirm dialogs live in ``agent_tools.describe_action``.
"""

import threading

from src.ai.agent_tools import _tool


# --------------------------------------------------------------------------- #
# Persistent browser session
# --------------------------------------------------------------------------- #
_driver = None
_lock = threading.Lock()

# The interactive-element catalogue produced by the last browser_read, so the
# model can refer to an element by its number (e.g. "#3"). Descriptors only -
# live WebElements are re-fetched fresh on every action (they go stale across
# navigation), so the number stays valid as long as the page has not changed.
_last_catalog = []

_SELENIUM_HINT = (
    "Browser automation needs the 'selenium' package (and a Chrome, Edge or "
    "Firefox browser installed). Install it with: pip install selenium. Until "
    "then, open the page in the normal browser instead (launch the URL) and use "
    "the screen-reading and clicking tools.")


def _make_driver():
    """Create a visible Selenium WebDriver, trying Chrome, then Edge, then
    Firefox. Selenium 4.6+ downloads the matching driver automatically (Selenium
    Manager), so no separate driver install is needed. Raises RuntimeError with a
    friendly message if selenium or every browser is unavailable."""
    try:
        from selenium import webdriver
    except Exception:
        raise RuntimeError(_SELENIUM_HINT)

    errors = []
    # Chrome.
    try:
        opts = webdriver.ChromeOptions()
        opts.add_argument('--start-maximized')
        opts.add_experimental_option('excludeSwitches', ['enable-logging'])
        return webdriver.Chrome(options=opts)
    except Exception as e:
        errors.append(f"Chrome: {e}")
    # Edge.
    try:
        opts = webdriver.EdgeOptions()
        opts.add_argument('--start-maximized')
        opts.add_experimental_option('excludeSwitches', ['enable-logging'])
        return webdriver.Edge(options=opts)
    except Exception as e:
        errors.append(f"Edge: {e}")
    # Firefox.
    try:
        return webdriver.Firefox()
    except Exception as e:
        errors.append(f"Firefox: {e}")
    raise RuntimeError("Could not start a browser. " + _SELENIUM_HINT
                       + " Details: " + " | ".join(errors))


def _get_driver(create=True):
    """Return the shared driver, creating it if needed. Returns None if the
    driver is gone / not created and ``create`` is False."""
    global _driver
    with _lock:
        if _driver is not None:
            try:
                _ = _driver.current_url  # touch it - raises if the window closed
                return _driver
            except Exception:
                try:
                    _driver.quit()
                except Exception:
                    pass
                _driver = None
        if not create:
            return None
        _driver = _make_driver()
        return _driver


def is_browser_open():
    return _get_driver(create=False) is not None


def close_browser_session():
    """Quit the shared browser if one is open (best effort). Called on shutdown /
    from the browser_close tool."""
    global _driver
    with _lock:
        if _driver is not None:
            try:
                _driver.quit()
            except Exception:
                pass
            _driver = None


# --------------------------------------------------------------------------- #
# Reading the page: text + interactive elements
# --------------------------------------------------------------------------- #
_ELEMENT_SELECTOR = "a[href], button, input, textarea, select, [role='button']"


def _text_of(el):
    try:
        t = (el.text or '').strip()
    except Exception:
        t = ''
    if t:
        return t
    for attr in ('aria-label', 'value', 'title', 'alt', 'placeholder', 'name'):
        try:
            v = (el.get_attribute(attr) or '').strip()
        except Exception:
            v = ''
        if v:
            return v
    return ''


def _label_of(driver, el):
    """Best-effort human label for a form field: an associated <label> (whether
    ``<label for=id>`` or a <label> wrapping the field), else aria-label /
    placeholder / name / id."""
    from selenium.webdriver.common.by import By
    # <label for="id">
    try:
        eid = el.get_attribute('id')
        if eid:
            labels = driver.find_elements(By.CSS_SELECTOR, f"label[for='{eid}']")
            for lb in labels:
                txt = (lb.text or '').strip()
                if txt:
                    return txt
    except Exception:
        pass
    # <label> wrapping the field (input nested inside the label - very common,
    # and has no 'for' attribute). The label's text is the field's caption.
    try:
        lbls = el.find_elements(By.XPATH, './ancestor::label[1]')
        if lbls:
            # First non-empty line = the caption (a wrapping <select>'s options
            # show up as later lines; keep only the caption).
            for line in (lbls[0].text or '').splitlines():
                line = line.strip()
                if line:
                    return line
    except Exception:
        pass
    for attr in ('aria-label', 'placeholder', 'name', 'title', 'id'):
        try:
            v = (el.get_attribute(attr) or '').strip()
        except Exception:
            v = ''
        if v:
            return v
    return ''


def _classify(driver, el):
    """Return a catalogue entry dict for an element, or None to skip it."""
    try:
        if not el.is_displayed():
            return None
    except Exception:
        return None
    try:
        tag = (el.tag_name or '').lower()
    except Exception:
        return None
    try:
        etype = (el.get_attribute('type') or '').lower()
    except Exception:
        etype = ''
    role = ''
    try:
        role = (el.get_attribute('role') or '').lower()
    except Exception:
        pass

    if tag == 'a':
        text = _text_of(el)
        return {'kind': 'link', 'label': text, 'text': text, 'tag': tag, 'type': etype} if text else None
    if tag == 'select':
        return {'kind': 'select', 'label': _label_of(driver, el), 'text': '', 'tag': tag, 'type': etype}
    if tag == 'textarea':
        return {'kind': 'input', 'label': _label_of(driver, el), 'text': '', 'tag': tag, 'type': 'textarea'}
    if tag == 'button' or role == 'button':
        text = _text_of(el)
        return {'kind': 'button', 'label': text, 'text': text, 'tag': tag, 'type': etype}
    if tag == 'input':
        if etype in ('hidden',):
            return None
        if etype in ('submit', 'button', 'reset', 'image'):
            return {'kind': 'button', 'label': _text_of(el), 'text': _text_of(el), 'tag': tag, 'type': etype}
        if etype in ('checkbox', 'radio'):
            return {'kind': 'checkbox', 'label': _label_of(driver, el), 'text': '', 'tag': tag, 'type': etype}
        return {'kind': 'input', 'label': _label_of(driver, el), 'text': '', 'tag': tag, 'type': etype or 'text'}
    return None


def _collect(driver, max_items=140):
    """Scan the current page, returning (entries, live_elements) in document
    order. ``entries`` are descriptor dicts (each with an 'idx'); ``live_elements``
    are the matching Selenium WebElements at the same indices."""
    from selenium.webdriver.common.by import By
    els = driver.find_elements(By.CSS_SELECTOR, _ELEMENT_SELECTOR)
    entries, live = [], []
    idx = 0
    for el in els:
        entry = _classify(driver, el)
        if entry is None:
            continue
        entry['idx'] = idx
        entries.append(entry)
        live.append(el)
        idx += 1
        if idx >= max_items:
            break
    return entries, live


def _page_text(driver, limit=1800):
    try:
        from selenium.webdriver.common.by import By
        body = driver.find_element(By.TAG_NAME, 'body')
        txt = ' '.join((body.text or '').split())
    except Exception:
        txt = ''
    if len(txt) > limit:
        txt = txt[:limit] + ' ...'
    return txt


def _format_catalog(entries):
    if not entries:
        return "(no interactive elements found)"
    lines = []
    for e in entries:
        label = (e.get('label') or e.get('text') or '').strip()
        label = label if len(label) <= 60 else label[:60] + '...'
        extra = ''
        if e['kind'] == 'input' and e.get('type') not in ('', 'text'):
            extra = f" ({e['type']})"
        lines.append(f"[{e['idx']}] {e['kind']} \"{label}\"{extra}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Element resolution (by number "#N" or by text / label)
# --------------------------------------------------------------------------- #
def _resolve(entries, live, target, kinds=None):
    """Return the live WebElement for ``target`` (a "#N" index or a text/label
    substring), restricted to ``kinds`` if given. Returns (element, entry) or
    (None, None)."""
    t = (str(target) if target is not None else '').strip()
    if not t:
        return None, None

    def _ok(entry):
        return kinds is None or entry['kind'] in kinds

    # "#N" or a bare number -> index into the freshly collected list.
    num = t[1:] if t.startswith('#') else t
    if num.isdigit():
        i = int(num)
        for entry, el in zip(entries, live):
            if entry['idx'] == i and _ok(entry):
                return el, entry
        # index out of the filtered set - fall through to text match

    # Text / label match: exact first, then substring, case-insensitive.
    tl = t.lower()
    best = None
    for entry, el in zip(entries, live):
        if not _ok(entry):
            continue
        hay = ((entry.get('label') or '') + ' ' + (entry.get('text') or '')).strip().lower()
        if hay == tl:
            return el, entry
        if best is None and tl in hay:
            best = (el, entry)
    if best:
        return best
    return None, None


# --------------------------------------------------------------------------- #
# Tools (each returns a plain-English result string)
# --------------------------------------------------------------------------- #
def browser_open(url, **_):
    """Open a URL in the browser (starting it if needed) and summarise the page."""
    try:
        u = (url or '').strip()
        if not u:
            return "Give a URL to open."
        if '://' not in u:
            u = 'https://' + u
        driver = _get_driver()
        driver.get(u)
        return browser_read()
    except Exception as e:
        return f"Could not open the page: {e}"


def browser_read(**_):
    """Read the current page: its title, URL, visible text and a numbered list of
    interactive elements (links, form fields, buttons, drop-downs)."""
    global _last_catalog
    driver = _get_driver(create=False)
    if driver is None:
        return "No browser is open. Open a page first."
    try:
        entries, _live = _collect(driver)
        _last_catalog = entries
        title = ''
        try:
            title = driver.title or ''
        except Exception:
            pass
        return (f"Page: {title}\nURL: {driver.current_url}\n"
                f"--- Text ---\n{_page_text(driver)}\n"
                f"--- Interactive elements ---\n{_format_catalog(entries)}\n"
                "Refer to an element by its number (e.g. #3) or by its visible "
                "text/label when filling, selecting or clicking.")
    except Exception as e:
        return f"Could not read the page: {e}"


def browser_fill(field, value, submit=False, **_):
    """Type ``value`` into the form field identified by ``field`` (its label,
    placeholder, name or #number). Set ``submit`` true to press Enter after."""
    driver = _get_driver(create=False)
    if driver is None:
        return "No browser is open. Open a page first."
    try:
        entries, live = _collect(driver)
        el, entry = _resolve(entries, live, field, kinds={'input'})
        if el is None:
            return (f"No text field matching '{field}'. Read the page to see the "
                    f"available fields and their numbers.")
        try:
            el.clear()
        except Exception:
            pass
        el.click()
        el.send_keys(str(value))
        if submit:
            from selenium.webdriver.common.keys import Keys
            el.send_keys(Keys.ENTER)
            return f"Filled '{entry.get('label') or field}' and submitted."
        return f"Filled '{entry.get('label') or field}'."
    except Exception as e:
        return f"Could not fill '{field}': {e}"


def browser_select(field, option, **_):
    """Choose ``option`` in the drop-down (<select>) identified by ``field``."""
    driver = _get_driver(create=False)
    if driver is None:
        return "No browser is open. Open a page first."
    try:
        from selenium.webdriver.support.ui import Select
        entries, live = _collect(driver)
        el, entry = _resolve(entries, live, field, kinds={'select'})
        if el is None:
            return f"No drop-down matching '{field}'. Read the page to see the choices."
        sel = Select(el)
        try:
            sel.select_by_visible_text(str(option))
        except Exception:
            # Fall back to a case-insensitive partial match on the options.
            wanted = str(option).strip().lower()
            for opt in sel.options:
                if wanted in (opt.text or '').strip().lower():
                    sel.select_by_visible_text(opt.text)
                    break
            else:
                return (f"'{option}' is not an option for '{field}'. Options: "
                        + ", ".join((o.text or '').strip() for o in sel.options[:30]))
        return f"Chose '{option}' for '{entry.get('label') or field}'."
    except Exception as e:
        return f"Could not choose '{option}' for '{field}': {e}"


def browser_check(field, checked=True, **_):
    """Tick or untick a checkbox / choose a radio button identified by ``field``."""
    driver = _get_driver(create=False)
    if driver is None:
        return "No browser is open. Open a page first."
    try:
        entries, live = _collect(driver)
        el, entry = _resolve(entries, live, field, kinds={'checkbox'})
        if el is None:
            return f"No checkbox or radio button matching '{field}'."
        want = str(checked).lower() not in ('false', '0', 'no', 'off')
        is_on = el.is_selected()
        if want != is_on:
            el.click()
        return f"{'Ticked' if want else 'Unticked'} '{entry.get('label') or field}'."
    except Exception as e:
        return f"Could not change '{field}': {e}"


def browser_click(target, **_):
    """Click a link or button identified by ``target`` (its visible text or
    #number)."""
    driver = _get_driver(create=False)
    if driver is None:
        return "No browser is open. Open a page first."
    try:
        entries, live = _collect(driver)
        el, entry = _resolve(entries, live, target, kinds={'link', 'button'})
        if el is None:
            # Allow clicking anything with matching text as a last resort.
            el, entry = _resolve(entries, live, target)
        if el is None:
            return (f"Nothing matching '{target}' to click. Read the page to see "
                    f"the links and buttons and their numbers.")
        label = entry.get('label') or entry.get('text') or target
        try:
            el.click()
        except Exception:
            driver.execute_script("arguments[0].click();", el)
        return f"Clicked '{label}'. " + _short_where(driver)
    except Exception as e:
        return f"Could not click '{target}': {e}"


def browser_submit(**_):
    """Submit the form on the page (presses Enter in the first text field, or
    submits the form element)."""
    driver = _get_driver(create=False)
    if driver is None:
        return "No browser is open. Open a page first."
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        # Prefer pressing Enter in the first visible text field.
        for el in driver.find_elements(By.CSS_SELECTOR, "input, textarea"):
            try:
                if el.is_displayed() and (el.get_attribute('type') or 'text').lower() \
                        not in ('hidden', 'submit', 'button', 'checkbox', 'radio'):
                    el.send_keys(Keys.ENTER)
                    return "Submitted the form. " + _short_where(driver)
            except Exception:
                continue
        # Otherwise submit the first form element.
        forms = driver.find_elements(By.TAG_NAME, 'form')
        if forms:
            forms[0].submit()
            return "Submitted the form. " + _short_where(driver)
        return "No form found to submit. Try clicking the submit button instead."
    except Exception as e:
        return f"Could not submit the form: {e}"


def browser_back(**_):
    """Go back to the previous page."""
    driver = _get_driver(create=False)
    if driver is None:
        return "No browser is open."
    try:
        driver.back()
        return "Went back. " + _short_where(driver)
    except Exception as e:
        return f"Could not go back: {e}"


def browser_close(**_):
    """Close the browser."""
    if not is_browser_open():
        return "No browser is open."
    close_browser_session()
    return "Closed the browser."


def _short_where(driver):
    try:
        return f"Now on: {driver.title or driver.current_url}."
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def get_browser_tools():
    """The web-browser toolset. Reading / navigation is auto-tier; submitting a
    form is confirm-tier (it is the irreversible step)."""
    S = {'type': 'string'}
    B = {'type': 'boolean'}
    return [
        _tool('browser_open',
              "Open a web page (URL) in the browser and read it. Starts the "
              "browser if needed.", browser_open,
              properties={'url': dict(S, description="The web address to open.")},
              required=['url']),
        _tool('browser_read',
              "Read the current web page: its title, text and a numbered list of "
              "links, form fields, buttons and drop-downs.", browser_read),
        _tool('browser_fill',
              "Type a value into a form field on the page (identified by its "
              "label, placeholder, name or #number).", browser_fill,
              properties={'field': dict(S, description="Field label / name / #number."),
                          'value': dict(S, description="The value to type."),
                          'submit': dict(B, description="Press Enter after typing (optional).")},
              required=['field', 'value']),
        _tool('browser_select',
              "Choose an option in a drop-down (select) on the page.", browser_select,
              properties={'field': dict(S, description="Drop-down label / name / #number."),
                          'option': dict(S, description="The option text to choose.")},
              required=['field', 'option']),
        _tool('browser_check',
              "Tick/untick a checkbox or choose a radio button on the page.",
              browser_check,
              properties={'field': dict(S, description="Checkbox / radio label / #number."),
                          'checked': dict(B, description="True to tick (default), false to untick.")},
              required=['field']),
        _tool('browser_click',
              "Click a link or button on the page (by its visible text or "
              "#number).", browser_click,
              properties={'target': dict(S, description="Link/button text or #number.")},
              required=['target']),
        _tool('browser_submit',
              "Submit the form on the current page.", browser_submit, risk='confirm'),
        _tool('browser_back', "Go back to the previous page.", browser_back),
        _tool('browser_close', "Close the browser.", browser_close),
    ]
