# -*- coding: utf-8 -*-
"""tk_access -- make a Tkinter application readable by Titan Access (and any
screen reader).

Tkinter draws all its widgets inside a single top-level HWND, so UI Automation /
MSAA expose nothing a screen reader can read -- a Tk app is silent under NVDA,
Titan Access, etc. This module fixes that with a *push* model: it watches the Tk
app's own focus / selection / value events, describes the focused widget, and
pushes that description to the reader.

Drop this one file into any Tkinter application and call::

    import tk_access
    tk_access.enable(root)            # root is your Tk() / Toplevel

That's all. Optionally give un-labelled widgets a name::

    tk_access.set_name(search_entry, "Search")

How it reaches the reader
-------------------------
* **In-process** (the app runs inside the Titan process, like the TCE launcher):
  the description is pushed to Titan Access via ``titan_access.host_bridge``,
  where it flows through the **app-modules** pipeline and the standard announcer
  -- exactly like a UIA focus event. No Tk logic lives in the core reader.
* **Stand-alone** (the app is its own process): it falls back to
  ``accessible_output3``, which speaks through whatever reader is active
  (Titan Access via its NVDA-controller bridge, NVDA, SAPI, ...).

Everything degrades gracefully: with no reader and no accessible_output3 the
calls are cheap no-ops, so shipping this module never breaks an app.
"""

import time
import weakref

# --------------------------------------------------------------------------- #
# Roles / state words (override ROLES / STATES, or pass translate= to enable())
# --------------------------------------------------------------------------- #
ROLES = {
    "button": "button", "checkbox": "check box", "radio": "radio button",
    "edit": "edit", "spinner": "spin box", "combobox": "combo box",
    "list": "list", "listitem": "", "slider": "slider", "tree": "tree",
    "tabcontrol": "tab control", "tab": "tab", "progressbar": "progress bar",
    "scrollbar": "scroll bar", "menu": "menu", "menuitem": "menu item",
    "label": "", "window": "window", "text": "edit",
}
STATES = {
    "checked": "checked", "unchecked": "not checked",
    "partially_checked": "partially checked",
    "selected": "selected", "unavailable": "unavailable",
    "readonly": "read only", "expanded": "expanded", "collapsed": "collapsed",
}

# Tk/ttk widget class (winfo_class) -> accessible role.
_ROLE_MAP = {
    "Button": "button", "TButton": "button",
    "Menubutton": "button", "TMenubutton": "button",
    "Label": "label", "TLabel": "label",
    "Entry": "edit", "TEntry": "edit",
    "Spinbox": "spinner", "TSpinbox": "spinner",
    "TCombobox": "combobox",
    "Checkbutton": "checkbox", "TCheckbutton": "checkbox",
    "Radiobutton": "radio", "TRadiobutton": "radio",
    "Listbox": "list",
    "Text": "text",
    "Scale": "slider", "TScale": "slider",
    "Treeview": "tree",
    "TNotebook": "tabcontrol",
    "TProgressbar": "progressbar",
    "Scrollbar": "scrollbar", "TScrollbar": "scrollbar",
    "Toplevel": "window", "Tk": "window",
}

# Per-widget accessible names supplied by the app (Entry/Listbox have no label).
_names = weakref.WeakKeyDictionary()


def set_name(widget, name):
    """Give a widget an accessible name (for unlabelled Entry / Listbox / ...)."""
    try:
        _names[widget] = name
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Reader output
# --------------------------------------------------------------------------- #
_ao = None
_ao_tried = False
_translate = None
_last = ("", 0.0)


def _t(s):
    if _translate and s:
        try:
            return _translate(s)
        except Exception:
            return s
    return s


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _format(fields):
    """Build a plain announcement string from a description (fallback path)."""
    parts = []
    if fields.get("name"):
        parts.append(str(fields["name"]))
    role_word = _t(ROLES.get(fields.get("role", ""), ""))
    if role_word:
        parts.append(role_word)
    if fields.get("value"):
        parts.append(str(fields["value"]))
    for st in fields.get("states", ()):  # checked / selected / ...
        w = _t(STATES.get(st, ""))
        if w:
            parts.append(w)
    sz = fields.get("size_of_set") or 0
    pos = fields.get("pos_in_set") or 0
    if sz and pos:
        parts.append(_t("{0} of {1}").format(pos, sz))
    return ", ".join(p for p in parts if p)


def _speak(fields):
    """Push a description to the reader; dedupe rapid duplicates."""
    global _ao, _ao_tried, _last
    summary = "{}|{}|{}|{}|{}".format(
        fields.get("name"), fields.get("role"), fields.get("value"),
        sorted(fields.get("states", ())), fields.get("pos_in_set"))
    now = time.time()
    if summary == _last[0] and (now - _last[1]) < 0.25:
        return
    _last = (summary, now)

    # 1. In-process Titan Access -> normal focus pipeline (app modules apply).
    try:
        from titan_access.host_bridge import push_focus, is_active
        if is_active() and push_focus(**fields):
            return
    except Exception:
        pass

    # 2. Fallback: speak the formatted string via the active reader.
    text = _format(fields)
    if not text:
        return
    if not _ao_tried:
        _ao_tried = True
        try:
            import accessible_output3.outputs.auto
            _ao = accessible_output3.outputs.auto.Auto()
        except Exception:
            _ao = None
    if _ao is not None:
        try:
            _ao.speak(text, interrupt=True)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Widget introspection
# --------------------------------------------------------------------------- #
def _is_ttk(widget):
    return _safe(lambda: widget.winfo_class().startswith("T"), False)


def _name_of(widget, text_fallback=True):
    n = _names.get(widget)
    if n:
        return n
    if text_fallback:
        return _safe(lambda: widget.cget("text"), "") or ""
    return ""


def _checkbox_states(widget):
    """Resolve checked / unchecked (or selected for radios) for a
    Checkbutton / Radiobutton, classic or ttk."""
    is_radio = _safe(lambda: widget.winfo_class(), "").endswith("Radiobutton")
    # ttk exposes the 'selected' state directly.
    if _is_ttk(widget):
        sel = _safe(lambda: bool(widget.instate(["selected"])), None)
        if sel is not None:
            if is_radio:
                return {"selected"} if sel else set()
            return {"checked" if sel else "unchecked"}
    # Classic widgets compare the linked variable to value (radio) / onvalue.
    varname = _safe(lambda: widget.cget("variable"), "")
    if varname:
        cur = _safe(lambda: widget.getvar(varname), None)
        if cur is None:
            return set()
        if is_radio:
            rval = _safe(lambda: widget.cget("value"), None)
            if rval is not None:
                return {"selected"} if str(cur) == str(rval) else set()
            return set()
        tri = _safe(lambda: widget.cget("tristatevalue"), None)
        if tri is not None and str(cur) == str(tri):
            return {"partially_checked"}
        on = _safe(lambda: widget.cget("onvalue"), None)
        if on is not None:
            return {"checked" if str(cur) == str(on) else "unchecked"}
    return set()


def _disabled(widget):
    if _is_ttk(widget):
        return bool(_safe(lambda: widget.instate(["disabled"]), False))
    state = _safe(lambda: str(widget.cget("state")), "")
    return state == "disabled"


def describe(widget):
    """Return a description dict for *widget*, or None if it is not worth
    announcing (a bare container / scrollbar / un-named label)."""
    if widget is None:
        return None
    cls = _safe(lambda: widget.winfo_class(), "") or ""
    role = _ROLE_MAP.get(cls, "")
    if role in ("", "scrollbar"):
        return None

    fields = {"role": role, "states": set()}
    if _disabled(widget):
        fields["states"].add("unavailable")

    if role in ("button",):
        fields["name"] = _name_of(widget)

    elif role in ("checkbox", "radio"):
        fields["name"] = _name_of(widget)
        fields["states"] |= _checkbox_states(widget)

    elif role in ("edit", "spinner", "combobox"):
        fields["name"] = _name_of(widget, text_fallback=False)
        fields["value"] = _safe(lambda: widget.get(), "") or ""

    elif role == "text":
        fields["role"] = "edit"
        fields["name"] = _name_of(widget, text_fallback=False)
        # First line only, so focusing a big editor is not a wall of speech.
        line = _safe(lambda: widget.get("1.0", "1.end"), "") or ""
        fields["value"] = line

    elif role == "slider":
        fields["name"] = _name_of(widget) or _safe(lambda: widget.cget("label"), "") or ""
        fields["value"] = str(_safe(lambda: widget.get(), "") or "")

    elif role == "list":
        sel = _safe(lambda: widget.curselection(), ()) or ()
        count = _safe(lambda: widget.size(), 0) or 0
        if sel:
            idx = sel[0]
            fields["role"] = "listitem"
            fields["name"] = _safe(lambda: widget.get(idx), "") or ""
            fields["pos_in_set"] = idx + 1
            fields["size_of_set"] = count
        else:
            fields["name"] = _name_of(widget, text_fallback=False)

    elif role == "tree":
        rows = _safe(lambda: widget.selection(), ()) or ()
        focus_row = rows[0] if rows else _safe(lambda: widget.focus(), "")
        if focus_row:
            txt = _safe(lambda: widget.item(focus_row, "text"), "") or ""
            vals = _safe(lambda: widget.item(focus_row, "values"), ()) or ()
            fields["role"] = "treeitem"
            fields["name"] = " ".join([txt] + [str(v) for v in vals]).strip()
        else:
            fields["name"] = _name_of(widget, text_fallback=False)

    elif role == "tabcontrol":
        cur = _safe(lambda: widget.select(), "")
        if cur:
            fields["role"] = "tab"
            fields["name"] = _safe(lambda: widget.tab(cur, "text"), "") or ""

    elif role == "window":
        fields["name"] = _safe(lambda: widget.title(), "") or ""

    else:  # label and anything else: only announce if it carries text
        fields["name"] = _name_of(widget)

    if not fields.get("name") and not fields.get("value"):
        return None
    return fields


# --------------------------------------------------------------------------- #
# Event wiring
# --------------------------------------------------------------------------- #
def _announce_widget(widget):
    fields = describe(widget)
    if fields:
        _speak(fields)


def _on_focus_in(event):
    _announce_widget(event.widget)


def _on_select(event):
    _announce_widget(event.widget)


def _on_scale_change(event):
    w = event.widget
    if _ROLE_MAP.get(_safe(lambda: w.winfo_class(), ""), "") == "slider":
        _announce_widget(w)


def enable(root, app_name=None, translate=None):
    """Make every widget under *root* speak its focus / selection / value.

    Args:
        root: the Tk root or Toplevel.
        app_name: optional friendly name (currently informational).
        translate: optional gettext-style ``_`` for role / state words.
    """
    global _translate
    if translate is not None:
        _translate = translate

    # Focus moves (Tab navigation) -- the core of keyboard accessibility.
    root.bind_all("<FocusIn>", _on_focus_in, add="+")
    # Selection / value changes the reader cannot otherwise see.
    for seq in ("<<ListboxSelect>>", "<<ComboboxSelected>>",
                "<<TreeviewSelect>>", "<<NotebookTabChanged>>"):
        root.bind_all(seq, _on_select, add="+")
    # Slider value changes via keyboard / drag.
    for cls in ("Scale", "TScale"):
        for seq in ("<KeyRelease>", "<ButtonRelease-1>", "<B1-Motion>"):
            _safe(lambda c=cls, s=seq: root.bind_class(c, s, _on_scale_change, add="+"))
    return root
