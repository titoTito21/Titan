# -*- coding: utf-8 -*-
"""NVDA's `controlTypes`: roles and states, named as NVDA names them and
worded as the reader words them. An object's role in Titan Access compares
equal to the member of the same name, so ``obj.role == Role.BUTTON`` and
``State.CHECKED in obj.states`` mean in an add-on what they mean in NVDA."""

from enum import Enum

_ROLES = (
    'UNKNOWN', 'WINDOW', 'TITLEBAR', 'PANE', 'DIALOG', 'CHECKBOX',
    'RADIOBUTTON', 'STATICTEXT', 'EDITABLETEXT', 'BUTTON', 'MENUBAR',
    'MENUITEM', 'POPUPMENU', 'COMBOBOX', 'LIST', 'LISTITEM', 'GRAPHIC',
    'HELPBALLOON', 'TOOLTIP', 'LINK', 'TREEVIEW', 'TREEVIEWITEM', 'TAB',
    'TABCONTROL', 'SLIDER', 'PROGRESSBAR', 'SCROLLBAR', 'STATUSBAR',
    'TABLE', 'TABLECELL', 'TABLECOLUMN', 'TABLEROW', 'TABLECOLUMNHEADER',
    'TABLEROWHEADER', 'FRAME', 'TOOLBAR', 'DROPDOWNBUTTON', 'CLOCK',
    'SEPARATOR', 'FORM', 'HEADING', 'HEADING1', 'HEADING2', 'HEADING3',
    'HEADING4', 'HEADING5', 'HEADING6', 'PARAGRAPH', 'BLOCKQUOTE',
    'TABLEHEADER', 'TABLEBODY', 'TABLEFOOTER', 'DOCUMENT', 'ANIMATION',
    'APPLICATION', 'BOX', 'GROUPING', 'PROPERTYPAGE', 'CANVAS', 'CAPTION',
    'CHECKMENUITEM', 'DATEEDITOR', 'ICON', 'DIRECTORYPANE', 'EMBEDDEDOBJECT',
    'ENDNOTE', 'FOOTER', 'FOOTNOTE', 'GLASSPANE', 'HEADER', 'IMAGEMAP',
    'INPUTWINDOW', 'LABEL', 'NOTE', 'PAGE', 'RADIOMENUITEM', 'LAYEREDPANE',
    'REDUNDANTOBJECT', 'ROOTPANE', 'EDITBAR', 'TERMINAL', 'RICHEDIT',
    'RULER', 'SCROLLPANE', 'SECTION', 'SHAPE', 'SPLITPANE', 'VIEWPORT',
    'TEAROFFMENU', 'TEXTFRAME', 'TOGGLEBUTTON', 'BORDER', 'CARET',
    'CHARACTER', 'CHART', 'CURSOR', 'DIAGRAM', 'DIAL', 'DROPLIST',
    'SPLITBUTTON', 'MENUBUTTON', 'DROPDOWNBUTTONGRID', 'MATH', 'EQUATION',
    'GRIP', 'HOTKEYFIELD', 'INDICATOR', 'SPINBUTTON', 'SOUND', 'WHITESPACE',
    'TREEVIEWBUTTON', 'IPADDRESS', 'DESKTOPICON', 'INTERNALFRAME',
    'DESKTOPPANE', 'OPTIONPANE', 'COLORCHOOSER', 'FILECHOOSER', 'FILLER',
    'MENU', 'PANEL', 'PASSWORDEDIT', 'FONTCHOOSER', 'LINE', 'FONTNAME',
    'FONTSIZE', 'BOLD', 'ITALIC', 'UNDERLINE', 'FGCOLOR', 'BGCOLOR',
    'SUPERSCRIPT', 'SUBSCRIPT', 'STYLE', 'INDENT', 'ALIGNMENT', 'ALERT',
    'DATAGRID', 'DATAITEM', 'HEADERITEM', 'THUMB', 'CALENDAR', 'VIDEO',
    'AUDIO', 'CHARTELEMENT', 'DELETED_CONTENT', 'INSERTED_CONTENT',
    'LANDMARK', 'ARTICLE', 'REGION', 'FIGURE', 'MARKED_CONTENT', 'BUSY_INDICATOR',
    'COMMENT', 'SUGGESTION', 'DEFINITION', 'SWITCH')

_STATES = (
    'UNAVAILABLE', 'FOCUSED', 'SELECTED', 'BUSY', 'PRESSED', 'CHECKED',
    'HALFCHECKED', 'READONLY', 'EXPANDED', 'COLLAPSED', 'INVISIBLE',
    'VISITED', 'LINKED', 'HASPOPUP', 'PROTECTED', 'REQUIRED', 'DEFUNCT',
    'INVALID_ENTRY', 'MODAL', 'AUTOCOMPLETE', 'MULTILINE', 'ICONIFIED',
    'OFFSCREEN', 'SELECTABLE', 'FOCUSABLE', 'CLICKABLE', 'EDITABLE',
    'CHECKABLE', 'DRAGGABLE', 'DRAGGING', 'DROPTARGET', 'SORTED',
    'SORTED_ASCENDING', 'SORTED_DESCENDING', 'HASLONGDESC', 'PINNED',
    'HASFORMULA', 'HASCOMMENT', 'OBSCURED', 'CROPPED', 'OVERFLOWING',
    'UNLOCKED', 'HAS_ARIA_DETAILS', 'HASNOTE', 'INDETERMINATE',
    'HALF_PRESSED', 'ON')


class _Named(Enum):
    def __eq__(self, other):
        return str(getattr(other, 'name', other)) == self.name

    def __hash__(self):
        return hash(self.name)

    @property
    def displayString(self):
        try:
            from titan_access import nvda_shape
            word = nvda_shape._Named(self.name).displayString
            if word:
                return word
        except Exception:                            # noqa: BLE001
            pass
        return self.name.lower().replace('_', ' ')

    @property
    def negativeDisplayString(self):
        if self.name == 'CHECKED':
            try:
                from titan_access import localization
                return localization.state_label('unchecked')
            except Exception:                        # noqa: BLE001
                pass
        return 'not ' + self.displayString


Role = _Named('Role', [(name, index) for index, name in enumerate(_ROLES)])
State = _Named('State', [(name, 1 << index)
                         for index, name in enumerate(_STATES)])

for _name in _ROLES:
    globals()['ROLE_' + _name] = Role[_name]
for _name in _STATES:
    globals()['STATE_' + _name] = State[_name]

roleLabels = {member: member.displayString for member in Role}
stateLabels = {member: member.displayString for member in State}
negativeStateLabels = {State.CHECKED: State.CHECKED.negativeDisplayString}


class OutputReason(Enum):
    FOCUS = 1
    MOUSE = 2
    QUERY = 3
    CHANGE = 4
    MESSAGE = 5
    SAYALL = 6
    CARET = 7
    ONLYCACHE = 8
    FOCUSENTERED = 9
    QUICKNAV = 10


REASON_FOCUS = OutputReason.FOCUS
REASON_CHANGE = OutputReason.CHANGE
REASON_QUERY = OutputReason.QUERY


def isTypingProtected(role=None, states=None):
    return role == Role.PASSWORDEDIT or (states and State.PROTECTED in states)


def processAndLabelStates(role, states, reason, positiveStates=None,
                          negativeStates=None, positiveStateLabelDict=None,
                          negativeStateLabelDict=None):
    return [getattr(state, 'displayString', str(state))
            for state in (positiveStates or states or ())]


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
