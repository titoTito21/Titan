# -*- coding: utf-8 -*-
"""
Titan's settings, described - read out of the settings window itself.

This is what makes a settings interface possible at all.  Somebody who wants
Titan's settings in HTML, in Qt, on a console or read out one question at a
time needs to know what the settings ARE: what each one is called in the
user's language, what kind of thing it is, what it may be set to, and what
it is set to now.

The obvious way to give them that is a second table describing every
setting - and it is the wrong way, because then every setting has to be
added twice, the table drifts from the window within a release, and a
setting a component registered at runtime is in neither.  So there is no
table.  **The description is taken from Titan's own settings window**: its
categories are the categories, its controls are the settings, and their
labels are the labels - the same `_("...")` strings, already translated,
already the words the user has learnt.

    frame = the real SettingsFrame (hidden if nobody asked to see it)
    model = SettingsModel(frame)
    model.categories()      -> [{'name': ..., 'items': [...]}, ...]
    model.set(item_id, value)
    model.save()            -> the window's own OnSave, side effects and all

What that buys, none of which a hand-written table would have given:

- **A setting is added once.**  A new checkbox in `settingsgui.py` appears in
  every settings interface installed, in the user's language, with no
  interface being changed.
- **Component categories are there too.**  `ComponentManager.register_settings_category`
  hands the frame a panel; this walks whatever is on it, so an add-on's own
  settings are in the HTML interface without the add-on knowing one exists.
- **The values are the live ones.**  The voices, the skins, the sound themes
  and the TTS engines are lists Titan fills in at run time; reading the
  control is reading exactly what the user would see.
- **Saving is Titan's own save**, with everything that hangs off it - the
  SAPI registration, restarting the system monitor, re-hooking the shell,
  rebuilding the menu bar.  An interface that wrote the ini file itself
  would set the value and change nothing.

The cost is that this is introspection, and introspection has to be honest
about what it cannot know: a control with no label near it, or one whose
meaning lives in the code around it, is reported as best it can be and never
invented.  `kind` is what the CONTROL is, so an interface renders what Titan
renders rather than guessing from a key name.
"""

import wx

KIND_BOOL = 'bool'
KIND_CHOICE = 'choice'
KIND_NUMBER = 'number'
KIND_TEXT = 'text'
KIND_SECRET = 'secret'
KIND_COMMAND = 'command'
KIND_LIST = 'list'
KIND_MULTI = 'multi'
KIND_INFO = 'info'

# Buttons that are the window's own furniture rather than a setting.  They
# are matched by wx id, not by their words, because their words are
# translated.
_FURNITURE_IDS = (wx.ID_OK, wx.ID_CANCEL, wx.ID_SAVE, wx.ID_CLOSE,
                  wx.ID_APPLY)


class SettingsItem:
    """One control of the settings window, described.

    `set` writes into the real control and then fires the event the control
    would have fired if the user had done it, because that is where Titan
    applies things live - the speech rate slider, the sound theme, the
    switch that makes the Titan shell category appear.  Setting the value
    silently would leave the window and the program disagreeing.
    """

    def __init__(self, identifier, category, control, label, kind,
                 options=(), minimum=None, maximum=None, description=''):
        self.id = identifier
        self.category = category
        self.control = control
        self.label = label
        self.kind = kind
        self.options = list(options)
        self.minimum = minimum
        self.maximum = maximum
        self.description = description

    # -- reading ---------------------------------------------------------
    def value(self):
        control = self.control
        try:
            if self.kind == KIND_BOOL:
                return bool(control.GetValue())
            if self.kind == KIND_CHOICE:
                if isinstance(control, wx.RadioBox):
                    index = control.GetSelection()
                    return (control.GetString(index)
                            if index != wx.NOT_FOUND else '')
                return control.GetStringSelection()
            if self.kind == KIND_NUMBER:
                return int(control.GetValue())
            if self.kind in (KIND_TEXT, KIND_SECRET):
                return control.GetValue()
            if self.kind == KIND_LIST:
                return control.GetStringSelection()
            if self.kind == KIND_MULTI:
                return [control.GetString(index)
                        for index in range(control.GetCount())
                        if control.IsChecked(index)]
            if self.kind == KIND_INFO:
                return control.GetValue() if hasattr(control, 'GetValue') \
                    else control.GetLabel()
        except RuntimeError:
            return None
        except Exception as error:
            print(f"[SettingsModel] could not read {self.id}: {error}")
        return None

    def enabled(self):
        try:
            return bool(self.control.IsEnabled())
        except Exception:
            return True

    def describe(self):
        """The item as plain data - what an HTML or CLI interface renders."""
        return {'id': self.id, 'category': self.category, 'label': self.label,
                'kind': self.kind, 'value': self.value(),
                'options': list(self.options), 'minimum': self.minimum,
                'maximum': self.maximum, 'enabled': self.enabled(),
                'description': self.description}

    # -- writing ---------------------------------------------------------
    def set(self, value):
        control = self.control
        try:
            if self.kind == KIND_BOOL:
                control.SetValue(_as_bool(value))
                _fire(control, wx.EVT_CHECKBOX.typeId)
                return True
            if self.kind == KIND_CHOICE:
                index = self._option_index(value)
                if index is None:
                    return False
                control.SetSelection(index)
                _fire(control,
                      wx.EVT_RADIOBOX.typeId if isinstance(control, wx.RadioBox)
                      else wx.EVT_CHOICE.typeId)
                return True
            if self.kind == KIND_NUMBER:
                number = int(float(value))
                if self.minimum is not None:
                    number = max(self.minimum, number)
                if self.maximum is not None:
                    number = min(self.maximum, number)
                control.SetValue(number)
                _fire(control,
                      wx.EVT_SPINCTRL.typeId if isinstance(control, wx.SpinCtrl)
                      else wx.EVT_SLIDER.typeId)
                return True
            if self.kind in (KIND_TEXT, KIND_SECRET):
                control.SetValue('' if value is None else str(value))
                _fire(control, wx.EVT_TEXT.typeId)
                return True
            if self.kind == KIND_LIST:
                index = self._option_index(value)
                if index is None:
                    return False
                control.SetSelection(index)
                _fire(control, wx.EVT_LISTBOX.typeId)
                return True
            if self.kind == KIND_MULTI:
                wanted = {str(item) for item in (value or [])}
                for index in range(control.GetCount()):
                    control.Check(index, control.GetString(index) in wanted)
                _fire(control, wx.EVT_CHECKLISTBOX.typeId)
                return True
            if self.kind == KIND_COMMAND:
                # A button is not a value; pressing it is what it is for,
                # and an interface asks for that explicitly.
                return False
        except Exception as error:
            print(f"[SettingsModel] could not set {self.id}: {error}")
        return False

    def press(self):
        """Press a button - the settings that are a dialog, not a value."""
        if self.kind != KIND_COMMAND:
            return False
        try:
            _fire(self.control, wx.EVT_BUTTON.typeId)
            return True
        except Exception as error:
            print(f"[SettingsModel] could not press {self.id}: {error}")
            return False

    def _option_index(self, value):
        """Which option was meant - by its words, or by its number."""
        options = self.options
        if not options:
            return None
        text = str(value)
        for index, option in enumerate(options):
            if option == text:
                return index
        lowered = text.strip().lower()
        for index, option in enumerate(options):
            if option.strip().lower() == lowered:
                return index
        # A number is how a console interface answers a list of choices, and
        # it is one-based there because that is how the list was printed.
        try:
            number = int(text)
        except (TypeError, ValueError):
            return None
        if 1 <= number <= len(options):
            return number - 1
        return None


class SettingsModel:
    """Every category and every control of the settings window."""

    def __init__(self, frame):
        self.frame = frame
        self._items = {}
        self._order = []
        self.read()

    # ------------------------------------------------------------------
    def read(self):
        """Walk the window again - after a save, or a category appearing."""
        self._items = {}
        self._order = []
        frame = self.frame
        names = _control_names(frame)
        for category in _category_order(frame):
            panel = _category_panel(frame, category)
            if panel is None:
                continue
            items = []
            for control in _walk(panel):
                item = _describe_control(control, category, names,
                                         len(self._items))
                if item is None:
                    continue
                self._items[item.id] = item
                items.append(item.id)
            self._order.append((category, items))
        return self._order

    def categories(self):
        """The window as plain data, category by category."""
        result = []
        for name, item_ids in self._order:
            result.append({
                'name': name,
                'items': [self._items[i].describe() for i in item_ids
                          if i in self._items],
            })
        return result

    def item(self, identifier):
        return self._items.get(identifier)

    def items(self):
        return [self._items[i] for _name, ids in self._order for i in ids
                if i in self._items]

    def get(self, identifier):
        item = self.item(identifier)
        return item.value() if item is not None else None

    def set(self, identifier, value):
        item = self.item(identifier)
        return bool(item is not None and item.set(value))

    def press(self, identifier):
        item = self.item(identifier)
        return bool(item is not None and item.press())

    def find(self, text):
        """The settings whose label matches what somebody typed."""
        needle = (text or '').strip().lower()
        if not needle:
            return []
        return [item for item in self.items()
                if needle in (item.label or '').lower()
                or needle in (item.category or '').lower()]

    # ------------------------------------------------------------------
    def save(self):
        """Titan's own save, with everything that hangs off it.

        `OnSave` ends by closing the window, which for this frame means
        hiding it - so an interface that saves does not have to put the
        settings window away itself.
        """
        try:
            self.frame.OnSave(None)
            return True
        except Exception as error:
            print(f"[SettingsModel] save failed: {error}")
            import traceback
            traceback.print_exc()
            return False

    def cancel(self):
        try:
            self.frame.Hide()
            return True
        except Exception:
            return False


# --------------------------------------------------------------------------
# Reading the window
# --------------------------------------------------------------------------
def _category_order(frame):
    order = list(getattr(frame, 'category_order', []) or [])
    known = getattr(frame, 'categories', {}) or {}
    # `category_order` is what the list shows; anything registered without
    # making it into that list (a component that registered late) is added
    # after it rather than being lost.
    for name in known:
        if name not in order:
            order.append(name)
    return [name for name in order if name in known]


def _category_panel(frame, category):
    panel = (getattr(frame, 'categories', {}) or {}).get(category)
    try:
        if panel is not None and not panel.IsBeingDeleted():
            return panel
    except RuntimeError:
        return None
    return None


def _walk(parent, depth=0):
    """Every control on a panel, in the order the window has them.

    Depth-first, because that is the order a `wx.BoxSizer` lays out and
    therefore the order the user tabs through - a settings interface that
    listed them in any other order would be describing a different window.
    """
    if depth > 8:
        return
    try:
        children = list(parent.GetChildren())
    except RuntimeError:
        return
    for child in children:
        yield child
        for grandchild in _walk(child, depth + 1):
            yield grandchild


def _control_names(frame):
    """wx object -> the name the window's own code calls it.

    `self.quick_start_cb` is a far better identifier for a setting than
    "the third checkbox on the General panel": it survives a control being
    moved, and it is what a person reading `settingsgui.py` would call it.
    Controls kept in a dictionary (the shell's checkboxes are) are named
    `attribute.key`, which is just as stable.
    """
    names = {}
    try:
        attributes = dict(vars(frame))
    except Exception:
        return names
    for attribute, value in attributes.items():
        if attribute.startswith('__'):
            continue
        if isinstance(value, wx.Window):
            names.setdefault(id(value), attribute)
        elif isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, wx.Window):
                    names.setdefault(id(item), f"{attribute}.{key}")
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                if isinstance(item, wx.Window):
                    names.setdefault(id(item), f"{attribute}.{index}")
    return names


def _label_of(control):
    """What this control is called, in the user's language.

    A checkbox, a radio group and a button carry their own words.  A choice,
    a slider, a text field and a list do not - Titan puts a `wx.StaticText`
    in front of them, exactly as every wx program does - so the label is the
    nearest static text before it among its siblings, and failing that the
    static box it is inside.  A trailing colon goes, because "Language:" is
    a caption and the setting is called Language.
    """
    try:
        if isinstance(control, (wx.CheckBox, wx.RadioBox, wx.Button,
                                wx.ToggleButton)):
            return _tidy(control.GetLabel())
    except Exception:
        pass
    try:
        siblings = list(control.GetParent().GetChildren())
        index = siblings.index(control)
    except Exception:
        siblings, index = [], -1
    for previous in reversed(siblings[:index]):
        if isinstance(previous, wx.StaticText):
            text = _tidy(previous.GetLabel())
            if text:
                return text
    # Inside a static box, the box's own caption is the name of the group
    # and the best answer left.
    try:
        parent = control.GetParent()
        if isinstance(parent, wx.StaticBox):
            return _tidy(parent.GetLabel())
    except Exception:
        pass
    return ''


def _tidy(text):
    text = (text or '').replace('&', '').strip()
    return text[:-1].strip() if text.endswith(':') else text


def _describe_control(control, category, names, ordinal):
    """One wx control as a setting, or None when it is not one."""
    try:
        if not control.IsShownOnScreen() and not control.IsEnabled():
            pass  # hidden-and-disabled is still described: it may be live
    except Exception:
        pass

    kind = options = None
    minimum = maximum = None

    if isinstance(control, wx.CheckListBox):
        kind = KIND_MULTI
        options = [control.GetString(i) for i in range(control.GetCount())]
    elif isinstance(control, wx.RadioBox):
        kind = KIND_CHOICE
        options = [control.GetString(i) for i in range(control.GetCount())]
    elif isinstance(control, wx.Choice):
        kind = KIND_CHOICE
        options = list(control.GetStrings())
    elif isinstance(control, wx.ComboBox):
        kind = KIND_CHOICE
        options = list(control.GetStrings())
    elif isinstance(control, wx.ListBox):
        kind = KIND_LIST
        options = [control.GetString(i) for i in range(control.GetCount())]
    elif isinstance(control, wx.Slider):
        kind = KIND_NUMBER
        minimum, maximum = control.GetMin(), control.GetMax()
    elif isinstance(control, wx.SpinCtrl):
        kind = KIND_NUMBER
        minimum, maximum = control.GetMin(), control.GetMax()
    elif isinstance(control, wx.CheckBox):
        kind = KIND_BOOL
    elif isinstance(control, wx.TextCtrl):
        style = control.GetWindowStyleFlag()
        if style & wx.TE_READONLY:
            # Read-only text is what the window uses to EXPLAIN something -
            # the launcher's description, a warning - so it is offered as
            # what it is rather than as a setting somebody can type into.
            kind = KIND_INFO
        elif style & wx.TE_PASSWORD:
            kind = KIND_SECRET
        else:
            kind = KIND_TEXT
    elif isinstance(control, wx.Button):
        if control.GetId() in _FURNITURE_IDS:
            return None
        kind = KIND_COMMAND
    else:
        return None

    label = _label_of(control)
    if not label:
        # A control nobody named cannot be offered: an interface would show
        # a box with no words next to it, which is worse than not showing
        # it - and the setting is still reachable in Titan's own window.
        return None

    identifier = names.get(id(control)) or f"item_{ordinal}"
    return SettingsItem(identifier, category, control, label, kind,
                        options or (), minimum, maximum)


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on', 'tak')


def _fire(control, event_type):
    """Tell the window the user changed this control.

    `wx.PostEvent` rather than calling the handler: the window binds these
    normally, several handlers may be listening, and one of them changing
    the window (the system-interface switch rebuilds the category list) has
    to happen in the event loop rather than inside somebody's `set`.
    """
    try:
        event = wx.CommandEvent(event_type, control.GetId())
        event.SetEventObject(control)
        wx.PostEvent(control, event)
    except Exception as error:
        print(f"[SettingsModel] could not fire an event: {error}")
