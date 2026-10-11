# -*- coding: utf-8 -*-
"""A virtualised list is walked whole, a batch at a time.

A XAML ListView (Unigram's chats and messages, the Store, Settings, Mail)
creates elements only for the rows on the screen: the tree holds fifteen
of a few hundred chats, so scan mode and the virtual window ended where the
screen did. UI Automation has the answer - ``ItemContainerPattern`` finds
every item, a placeholder for the ones not yet created, and
``VirtualizedItemPattern.Realize`` creates one - but realising a whole
history of thousands of messages up front is minutes, and each Realize
scrolls the app.

So it is lazy: when the cursor reaches the last (or first) entry the
document has of such a list, the next ``BATCH`` items in that direction
are realised and put into the document right there - which is what
arrowing down the list in the app itself would do.
"""

import time

from . import contracts as C

ITEM_CONTAINER = 10019
VIRTUALIZED_ITEM = 10020
BATCH = 20
#: A batch never takes longer than this, however slow the app.
BUDGET_S = 3.0

_LIST_ROLES = (C.ROLE_LISTITEM, C.ROLE_TREEITEM, C.ROLE_GRIDITEM)


def _control_of(node):
    control = getattr(node, 'element', None)
    if control is not None:
        return control
    raw = getattr(node, 'raw', None)
    if raw is None:
        return None
    try:
        from titan_access import uia_cache as uc
        return uc.control_for(raw)
    except Exception:                                # noqa: BLE001
        return None


def _container(control):
    """The list a row belongs to, when it can find its other items."""
    try:
        parent = control.GetParentControl()
    except Exception:                                # noqa: BLE001
        return None, None
    for _step in range(3):
        if parent is None:
            return None, None
        try:
            pattern = parent.Element.GetCurrentPattern(ITEM_CONTAINER)
        except Exception:                            # noqa: BLE001
            pattern = None
        if pattern:
            try:
                import comtypes.client
                mod = comtypes.client.GetModule('UIAutomationCore.dll')
                return parent, pattern.QueryInterface(
                    mod.IUIAutomationItemContainerPattern)
            except Exception:                        # noqa: BLE001
                return None, None
        try:
            parent = parent.GetParentControl()
        except Exception:                            # noqa: BLE001
            return None, None
    return None, None


def _items(pattern, after=None, limit=10000, deadline=None):
    """Raw elements of the container in order, starting after ``after``."""
    import comtypes.automation
    empty = comtypes.automation.VARIANT()
    out = []
    current = after
    while len(out) < limit:
        if deadline and time.time() > deadline:
            break
        try:
            found = pattern.FindItemByProperty(current, 0, empty)
        except Exception:                            # noqa: BLE001
            break
        if not found:
            break
        out.append(found)
        current = found
    return out


def _same(a, b):
    try:
        from uiautomation.uiautomation import _AutomationClient
        return bool(_AutomationClient.instance().IUIAutomation.CompareElements(a, b))
    except Exception:                                # noqa: BLE001
        return False


def _realise(element):
    """A placeholder made into a real element; the element either way."""
    try:
        import comtypes.client
        mod = comtypes.client.GetModule('UIAutomationCore.dll')
        pattern = element.GetCurrentPattern(VIRTUALIZED_ITEM)
        if pattern:
            pattern.QueryInterface(mod.IUIAutomationVirtualizedItemPattern).Realize()
    except Exception:                                # noqa: BLE001
        pass
    return element


def _node(element, template):
    """A document entry for one realised item, shaped like its neighbours."""
    from uiautomation.uiautomation import Control
    from titan_access.virtual_buffer import VNode
    from titan_access import uwp
    control = Control.CreateControlFromElement(element)
    if control is None:
        return None
    try:
        name = (control.Name or '').strip()
    except Exception:                                # noqa: BLE001
        name = ''
    name = uwp.node_name(name, template.role, control,
                         getattr(control, 'FrameworkId', ''),
                         getattr(control, 'AutomationId', ''))
    if not name:
        return None
    rect = ()
    try:
        r = control.BoundingRectangle
        rect = (r.left, r.top, r.right, r.bottom)
    except Exception:                                # noqa: BLE001
        pass
    return VNode(name=name, role=template.role, source='uia', element=control,
                 rect=rect, landmark=getattr(template, 'landmark', ''))


def _raw_of(control):
    try:
        return control.Element
    except Exception:                                # noqa: BLE001
        return None


def is_list_edge(nodes, index, direction):
    """True when ``nodes[index]`` is a row and the entry beyond it in
    ``direction`` is not one (or there is none): where a list may go on."""
    if not (0 <= index < len(nodes)) or nodes[index].role not in _LIST_ROLES:
        return False
    beyond = index + direction
    return not (0 <= beyond < len(nodes)) or nodes[beyond].role not in _LIST_ROLES


def extend(nodes, index, direction, batch=BATCH):
    """Realise up to ``batch`` more rows of the list ``nodes[index]`` is in,
    beyond it in ``direction`` (+1 down, -1 up), and insert them into
    ``nodes``. Answers how many were inserted (0: the list has no more, or
    is not a virtualised one)."""
    if not is_list_edge(nodes, index, direction):
        return 0
    deadline = time.time() + BUDGET_S
    control = _control_of(nodes[index])
    if control is None:
        return 0
    _parent, pattern = _container(control)
    if pattern is None:
        return 0
    here = _raw_of(control)
    if here is None:
        return 0
    known = [n for n in nodes if n.role in _LIST_ROLES]
    if direction > 0:
        found = _items(pattern, after=here, limit=batch, deadline=deadline)
    else:
        before = []
        for item in _items(pattern, deadline=deadline):
            if _same(item, here):
                break
            before.append(item)
        found = list(reversed(before[-batch:]))
    added = []
    for element in found:
        if time.time() > deadline:
            break
        if any(_same(element, _raw_of(_control_of(n))) for n in known[-60:]):
            continue
        node = _node(_realise(element), nodes[index])
        if node is not None:
            added.append(node)
    if not added:
        return 0
    if direction > 0:
        nodes[index + 1:index + 1] = added
    else:
        nodes[index:index] = list(reversed(added))
    return len(added)
