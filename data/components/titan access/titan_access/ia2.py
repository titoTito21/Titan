# -*- coding: utf-8 -*-
"""IAccessible2 (IA2) support for Titan Access.

IAccessible2 is the richest accessibility API for Chromium (Chrome / Edge /
WebView2) and Firefox/Gecko: on top of MSAA's ``IAccessible`` it exposes the real
web semantics — the HTML ``tag`` (``h1``..``h6``), ARIA ``xml-roles``
(landmarks, headings), heading ``level``, group position, IA2 roles
(paragraph / section / …) and a richer state set. Port grounded on NVDA's
``source/IAccessibleHandler`` + ``comInterfaces/IAccessible2Lib`` and the C#
``Interop/IAccessible2Interop.cs`` in this component.

Two things are provided:

* :func:`to_ia2` — obtain an ``IAccessible2`` from a plain ``IAccessible`` via
  ``IServiceProvider::QueryService`` (the standard NVDA route), and accessors
  (:func:`attributes`, :func:`role`, :func:`states`, :func:`group_position`).
* :func:`enrich_object` — fold IA2 facts (web role / heading level / landmark)
  into a Titan :class:`~titan_access.contracts.AccessibleObject`.

Everything is lazily initialised and fully guarded: if comtypes / oleacc is
missing, or an element does not implement IA2, the helpers return ``None`` /
leave the object unchanged, so the reader keeps working on UIA + MSAA alone.
"""

import ctypes

from titan_access.contracts import ROLE_HEADING

# contracts has no ROLE_PARAGRAPH constant; browse_mode/quick_nav use the literal
# "paragraph". Define the keys we map onto locally to avoid import churn.
ROLE_PARAGRAPH = "paragraph"
ROLE_LANDMARK = "group"     # landmarks are announced as named groups
ROLE_SECTION = "group"

_OK = False
_IAccessible2 = None
_IServiceProvider = None
_GUID = None
_IID_IA2 = None


def _init():
    """Build the IServiceProvider + IAccessible2 comtypes interfaces (lazy)."""
    global _OK, _IAccessible2, _IServiceProvider, _GUID, _IID_IA2
    if _OK:
        return True
    try:
        import comtypes
        import comtypes.client
        from comtypes import IUnknown, GUID, COMMETHOD, BSTR
        from ctypes import POINTER, c_int, c_void_p, HRESULT

        oleacc = comtypes.client.GetModule("oleacc.dll")
        IAccessible = oleacc.IAccessible

        class IServiceProvider(IUnknown):
            _iid_ = GUID("{6D5140C1-7436-11CE-8034-00AA006009FA}")
            _methods_ = [
                COMMETHOD([], HRESULT, "QueryService",
                          (["in"], POINTER(GUID), "guidService"),
                          (["in"], POINTER(GUID), "riid"),
                          (["out"], POINTER(POINTER(IUnknown)), "ppvObject")),
            ]

        class IAccessible2(IAccessible):
            _iid_ = GUID("{E89F726E-C4F4-4C19-BB19-B647D7FA8478}")
            _methods_ = [
                COMMETHOD([], HRESULT, "get_nRelations",
                          (["out"], POINTER(c_int), "n")),
                COMMETHOD([], HRESULT, "get_relation",
                          (["in"], c_int, "i"),
                          (["out"], POINTER(POINTER(IUnknown)), "rel")),
                COMMETHOD([], HRESULT, "get_relations",
                          (["in"], c_int, "maxRel"),
                          (["out"], POINTER(POINTER(IUnknown)), "rel"),
                          (["out"], POINTER(c_int), "n")),
                COMMETHOD([], HRESULT, "role", (["out"], POINTER(c_int), "role")),
                COMMETHOD([], HRESULT, "scrollTo", (["in"], c_int, "type")),
                COMMETHOD([], HRESULT, "scrollToPoint",
                          (["in"], c_int, "coord"), (["in"], c_int, "x"),
                          (["in"], c_int, "y")),
                COMMETHOD([], HRESULT, "get_groupPosition",
                          (["out"], POINTER(c_int), "groupLevel"),
                          (["out"], POINTER(c_int), "similarItems"),
                          (["out"], POINTER(c_int), "positionInGroup")),
                COMMETHOD([], HRESULT, "get_states",
                          (["out"], POINTER(c_int), "states")),
                COMMETHOD([], HRESULT, "get_extendedRole",
                          (["out"], POINTER(BSTR), "role")),
                COMMETHOD([], HRESULT, "get_localizedExtendedRole",
                          (["out"], POINTER(BSTR), "role")),
                COMMETHOD([], HRESULT, "get_nExtendedStates",
                          (["out"], POINTER(c_int), "n")),
                COMMETHOD([], HRESULT, "get_extendedStates",
                          (["in"], c_int, "maxStates"),
                          (["out"], POINTER(POINTER(BSTR)), "states"),
                          (["out"], POINTER(c_int), "n")),
                COMMETHOD([], HRESULT, "get_localizedExtendedStates",
                          (["in"], c_int, "maxStates"),
                          (["out"], POINTER(POINTER(BSTR)), "states"),
                          (["out"], POINTER(c_int), "n")),
                COMMETHOD([], HRESULT, "get_uniqueID",
                          (["out"], POINTER(c_int), "id")),
                COMMETHOD([], HRESULT, "get_windowHandle",
                          (["out"], POINTER(c_void_p), "hwnd")),
                COMMETHOD([], HRESULT, "get_indexInParent",
                          (["out"], POINTER(c_int), "idx")),
                COMMETHOD([], HRESULT, "get_locale",
                          (["out"], POINTER(c_void_p), "locale")),
                COMMETHOD([], HRESULT, "get_attributes",
                          (["out"], POINTER(BSTR), "attributes")),
            ]

        _IServiceProvider = IServiceProvider
        _IAccessible2 = IAccessible2
        _GUID = GUID
        _IID_IA2 = GUID("{E89F726E-C4F4-4C19-BB19-B647D7FA8478}")
        _OK = True
    except Exception as e:  # pragma: no cover - comtypes/oleacc missing
        print(f"[TitanAccess] ia2: init failed: {e}")
        _OK = False
    return _OK


# --------------------------------------------------------------------------- #
# IA2 acquisition + accessors
# --------------------------------------------------------------------------- #
def to_ia2(iaccessible):
    """Return the ``IAccessible2`` for *iaccessible*, or ``None``."""
    if iaccessible is None or not _init():
        return None
    try:
        sp = iaccessible.QueryInterface(_IServiceProvider)
        unk = sp.QueryService(_IID_IA2, _IID_IA2)
        if not unk:
            return None
        return unk.QueryInterface(_IAccessible2)
    except Exception:
        return None


def attributes(ia2):
    """Parse the IA2 ``attributes`` BSTR ("k:v;k:v;") into a lower-cased dict."""
    if ia2 is None:
        return {}
    try:
        raw = ia2.get_attributes()
    except Exception:
        return {}
    out = {}
    for part in (raw or "").split(";"):
        if ":" in part:
            k, _s, v = part.partition(":")
            out[k.strip().lower()] = v.strip()
    return out


def role(ia2):
    """IA2 role integer, or 0."""
    if ia2 is None:
        return 0
    try:
        return int(ia2.role())
    except Exception:
        return 0


def group_position(ia2):
    """(group_level, similar_items_in_group, position_in_group) or (0, 0, 0)."""
    if ia2 is None:
        return (0, 0, 0)
    try:
        lvl, similar, pos = ia2.get_groupPosition()
        return (int(lvl), int(similar), int(pos))
    except Exception:
        return (0, 0, 0)


# IA2 role constants we map (subset; full list in the IA2 spec).
IA2_ROLE_PARAGRAPH = 0x41C
IA2_ROLE_HEADING = 0x40F
IA2_ROLE_SECTION = 0x420
IA2_ROLE_LANDMARK = 0x40D


def enrich_object(obj, iaccessible):
    """Fold IA2 web semantics into a Titan ``AccessibleObject`` (in place).

    Adds: heading role + level (from ``tag``/``level``/IA2 heading role),
    landmark naming (``xml-roles``), and paragraph/section roles. Safe no-op when
    the element has no IA2. Returns ``obj``.
    """
    ia2 = to_ia2(iaccessible)
    if ia2 is None:
        return obj
    attrs = attributes(ia2)

    # Heading: HTML tag h1..h6 or ARIA role heading + aria-level.
    tag = (attrs.get("tag") or "").lower()
    xml_roles = (attrs.get("xml-roles") or "").lower()
    level = 0
    if tag[:1] == "h" and tag[1:].isdigit():
        level = int(tag[1:])
    elif attrs.get("level", "").isdigit():
        level = int(attrs["level"])
    ia2role = role(ia2)

    if level and (tag[:1] == "h" or "heading" in xml_roles or ia2role == IA2_ROLE_HEADING):
        obj.role = ROLE_HEADING
        obj.level = level
    elif "heading" in xml_roles or ia2role == IA2_ROLE_HEADING:
        obj.role = ROLE_HEADING
    elif ia2role == IA2_ROLE_PARAGRAPH:
        if obj.role in ("text", "unknown", "pane"):
            obj.role = ROLE_PARAGRAPH
    elif xml_roles and any(lm in xml_roles for lm in (
            "navigation", "main", "banner", "contentinfo", "complementary",
            "search", "region", "form")):
        # Landmark: announce as a (named) group; keep the name if present.
        obj.role = ROLE_LANDMARK
        if not obj.name:
            obj.name = xml_roles.split()[0]

    # Group position fills list position / hierarchy level when UIA/MSAA didn't.
    if not obj.level or not obj.pos_in_set:
        lvl, similar, pos = group_position(ia2)
        if lvl and not obj.level:
            obj.level = lvl
        if similar and pos and not obj.size_of_set:
            obj.size_of_set = similar
            obj.pos_in_set = pos
    return obj


def available():
    return _init()


# --------------------------------------------------------------------------- #
# IA2 document buffer (fallback web reading when UIA exposes nothing)
# --------------------------------------------------------------------------- #
# Web-host window classes whose client object is the document root IAccessible.
_DOC_WINDOW_CLASSES = (
    "Chrome_RenderWidgetHostHWND",   # Chromium (Chrome / Edge / WebView2)
    "MozillaWindowClass",            # Firefox / Gecko
    "MozillaContentWindowClass",
)

# MSAA ROLE_SYSTEM_* values that are worth a buffer node (content), reused from
# the MSAA role map but kept local so this module is self-contained.
_CONTENT_MSAA_ROLES = {
    0x0C, 0x1E, 0x21, 0x22, 0x23, 0x24, 0x25, 0x28, 0x29, 0x2A, 0x2B, 0x2C,
    0x2D, 0x2E, 0x2F, 0x30, 0x33, 0x34, 0x0F, 0x12, 0x14,
}

# Titan role keys that are pure grouping / layout WRAPPERS, not real content.
# NVDA presents the web buffer flat -- you arrow through the actual links,
# headings, list items, etc., NOT through the anonymous <div>/section/landmark
# groups that merely contain them. Emitting those wrappers as their own buffer
# stops made navigation land "in groups", which the user found unintuitive, so
# they are dropped from the buffer while their content still flows through. Their
# children are walked as usual, so nothing real is lost. (Structural containers
# with dedicated quick-nav -- lists / tables / trees -- are intentionally kept.)
_SKIP_ROLES = {"group", "document", "dialog", "pane", "window"}

_MAX_DEPTH = 30
_MAX_NODES = 3000

_oleacc_dll = None


def _oleacc():
    global _oleacc_dll
    if _oleacc_dll is not None:
        return _oleacc_dll
    try:
        from ctypes import wintypes, POINTER
        from comtypes.automation import VARIANT
        dll = ctypes.WinDLL("oleacc", use_last_error=True)
        dll.AccessibleObjectFromWindow.restype = ctypes.c_long
        dll.AccessibleObjectFromWindow.argtypes = [
            wintypes.HWND, wintypes.DWORD, POINTER(_GUID),
            POINTER(POINTER(_IAccessible2.__mro__[1])),  # POINTER(IAccessible)
        ]
        dll.AccessibleChildren.restype = ctypes.c_long
        dll.AccessibleChildren.argtypes = [
            ctypes.c_void_p, ctypes.c_long, ctypes.c_long,
            POINTER(VARIANT), POINTER(ctypes.c_long),
        ]
        _oleacc_dll = dll
    except Exception as e:
        print(f"[TitanAccess] ia2: oleacc bind failed: {e}")
        _oleacc_dll = False
    return _oleacc_dll


def _document_accessibles(hwnd):
    """Return the document-root IAccessible objects under window *hwnd*."""
    from ctypes import wintypes, POINTER, byref
    found = []

    user32 = ctypes.windll.user32
    IAccessible = _IAccessible2.__mro__[1]
    iid = _GUID("{618736E0-3C3D-11CF-810C-00AA00389B71}")
    dll = _oleacc()
    if not dll:
        return found

    def _class(h):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, buf, 256)
        return buf.value

    targets = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                     wintypes.LPARAM)

    def _enum(h, _l):
        try:
            if _class(h) in _DOC_WINDOW_CLASSES:
                targets.append(h)
        except Exception:
            pass
        return True

    try:
        if _class(hwnd) in _DOC_WINDOW_CLASSES:
            targets.append(hwnd)
        user32.EnumChildWindows(hwnd, WNDENUMPROC(_enum), 0)
    except Exception:
        pass

    for h in targets:
        try:
            p = POINTER(IAccessible)()
            hr = dll.AccessibleObjectFromWindow(h, 0xFFFFFFFC, byref(iid),
                                                byref(p))
            if hr == 0 and p:
                found.append(p)
        except Exception:
            continue
    return found


def _children(acc):
    """Enumerate child IAccessible objects of *acc* via AccessibleChildren."""
    from ctypes import byref, c_long
    from comtypes.automation import VARIANT
    dll = _oleacc()
    out = []
    if not dll:
        return out
    try:
        count = acc.accChildCount
    except Exception:
        return out
    if not count or count <= 0:
        return out
    count = min(int(count), 500)
    try:
        arr = (VARIANT * count)()
        obtained = c_long()
        # acc is a comtypes pointer; pass its raw COM pointer.
        ptr = ctypes.cast(acc, ctypes.c_void_p)
        if dll.AccessibleChildren(ptr, 0, count, arr, byref(obtained)) != 0:
            return out
        for i in range(obtained.value):
            v = arr[i]
            try:
                child = v.value
                if child is None:
                    continue
                # VT_DISPATCH -> an IAccessible object; QI it.
                if hasattr(child, "QueryInterface"):
                    out.append(child.QueryInterface(
                        _IAccessible2.__mro__[1]))
            except Exception:
                continue
    except Exception:
        return out
    return out


def build_document_nodes(hwnd):
    """Walk the web document under *hwnd* via IA2/IAccessible and return a flat
    list of buffer nodes: ``{name, role, level, states}``. Bounded and fully
    guarded; returns ``[]`` on any trouble so the caller falls back to UIA."""
    if not _init():
        return []
    roots = _document_accessibles(hwnd)
    if not roots:
        return []
    nodes = []

    def _walk(acc, depth):
        if depth > _MAX_DEPTH or len(nodes) >= _MAX_NODES:
            return
        try:
            name = (acc.accName(0) or "").strip()
        except Exception:
            name = ""
        try:
            role_raw = acc.accRole(0)
            role_int = int(role_raw) if isinstance(role_raw, int) else 0
        except Exception:
            role_int = 0
        node = {"name": name, "role": _role_key(role_int), "level": 0,
                "states": set()}
        # IA2 enrichment (heading level, landmark, paragraph).
        try:
            from titan_access.contracts import AccessibleObject
            tmp = AccessibleObject(name=name, role=node["role"])
            enrich_object(tmp, acc)
            node["role"] = tmp.role
            node["level"] = tmp.level
        except Exception:
            pass
        # Flat, NVDA-style buffer: skip anonymous grouping / layout wrappers so
        # navigation lands on real content, never "inside a group". Their
        # children are still walked below, so their content is preserved.
        if node["role"] not in _SKIP_ROLES and (
                name or role_int in _CONTENT_MSAA_ROLES):
            nodes.append(node)
        for child in _children(acc):
            _walk(child, depth + 1)

    for root in roots:
        try:
            _walk(root, 0)
        except Exception:
            continue
    return nodes


# MSAA role int -> Titan role key (subset; mirrors msaa_focus).
def _role_key(role_int):
    from titan_access.contracts import (
        ROLE_BUTTON, ROLE_LINK, ROLE_LISTITEM, ROLE_EDIT, ROLE_CHECKBOX,
        ROLE_RADIO, ROLE_COMBOBOX, ROLE_TEXT, ROLE_IMAGE, ROLE_HEADING as RH,
        ROLE_MENUITEM, ROLE_LISTBOX, ROLE_TREE, ROLE_TREEITEM, ROLE_TAB,
        ROLE_SLIDER, ROLE_PROGRESSBAR, ROLE_DOCUMENT, ROLE_DIALOG, ROLE_GROUP,
        ROLE_UNKNOWN,
    )
    return {
        0x0C: ROLE_MENUITEM, 0x1E: ROLE_LINK, 0x21: ROLE_LISTBOX,
        0x22: ROLE_LISTITEM, 0x23: ROLE_TREE, 0x24: ROLE_TREEITEM,
        0x25: ROLE_TAB, 0x28: ROLE_IMAGE, 0x29: ROLE_TEXT, 0x2A: ROLE_EDIT,
        0x2B: ROLE_BUTTON, 0x2C: ROLE_CHECKBOX, 0x2D: ROLE_RADIO,
        0x2E: ROLE_COMBOBOX, 0x2F: ROLE_COMBOBOX, 0x30: ROLE_PROGRESSBAR,
        0x33: ROLE_SLIDER, 0x0F: ROLE_DOCUMENT, 0x12: ROLE_DIALOG,
        0x14: ROLE_GROUP,
    }.get(role_int, ROLE_UNKNOWN)


# =========================================================================== #
# The IAccessible2 COM proxy: is it there, and can it be registered here?
# =========================================================================== #
# **Why a screen reader needs a DLL it did not write.** IAccessible2 is a COM
# interface, and a COM call across processes - from this reader into Chrome
# or Firefox - needs a PROXY/STUB that knows how to marshal the interface's
# arguments. NVDA builds `IAccessible2Proxy.dll` from the IA2 IDL and
# registers it per process (DllGetClassObject -> CoRegisterClassObject ->
# CoRegisterPSClsid, no registry write) inside every process it injects
# into; Firefox ships the same thing as `ia2marshal.dll` beside its
# `AccessibleMarshal.dll`; an installed NVDA registers it system-wide. The
# IA2 community decided long ago that APPLICATIONS must never register it in
# the registry, because uninstalling one would silently break every other.
#
# So this does what NVDA does, in this process only: look in the registry
# first (an installed NVDA or Firefox has done the work), and otherwise take
# a proxy DLL already on the machine and register it for this process.
# Nothing is copied and nothing is written to the registry.
IA2_INTERFACES = {
    'IAccessible2': '{E89F726E-C4F4-4C19-BB19-B647D7FA8478}',
    'IAccessible2_2': '{6C9430E9-299D-4E6F-BD01-A82A1E88D3FF}',
    'IAccessible2_3': '{5BE18059-762E-4E73-9476-ABA294FED411}',
    'IAccessibleAction': '{B70D9F59-3B5A-4DBA-AB9E-22012F607DF5}',
    'IAccessibleApplication': '{D49DED83-5B25-43F4-9B95-93B44595979E}',
    'IAccessibleComponent': '{1546D4B0-4C98-4BDA-89AE-9A64748BDDE4}',
    'IAccessibleEditableText': '{A59AA09A-7011-4B65-939D-32B1FB5547E3}',
    'IAccessibleHyperlink': '{01C20F2B-3DD2-400F-949F-AD00BDAB1D41}',
    'IAccessibleHypertext': '{6B4F8BBF-F1F2-418E-B11B-DA9AA7A19D2A}',
    'IAccessibleHypertext2': '{CF64D89F-8287-4B44-8501-A827453A6077}',
    'IAccessibleImage': '{FE5ABB3D-615E-4F7C-909A-D9C0D1E8DC42}',
    'IAccessibleRelation': '{7CDF86EE-C3DA-496A-BDA4-281B336E1FDC}',
    'IAccessibleTable': '{35AD8070-C20C-4FB4-B094-F4F7275DD469}',
    'IAccessibleTable2': '{6167F295-06F0-4CDD-A1FA-02E25153D869}',
    'IAccessibleTableCell': '{594116B1-C99F-4847-AD06-0A7A86ECE645}',
    'IAccessibleText': '{24FD2FFB-3AAD-4A08-8335-A3AD89C0FB4B}',
    'IAccessibleValue': '{35855B5B-C566-4FD0-A7B1-E65465600394}',
    'IAccessibleDocument': '{C48C7FCF-4AB5-4056-AFA6-902D6E1D1149}',
}

#: Where a proxy DLL may be. **Titan Access's own first**: built from the
#: IA2 IDL (BSD) by `helper/ia2proxy/build.bat` into `lib/`, so a machine
#: with neither NVDA nor Firefox has one too.
import os as _os
OWN_PROXY = _os.path.join(_os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))), 'lib', 'IAccessible2Proxy.dll')

PROXY_FILES = (
    (_os.path.dirname(OWN_PROXY), 'IAccessible2Proxy.dll'),
    (r'%ProgramFiles%\NVDA', 'IAccessible2Proxy.dll'),
    (r'%ProgramFiles(x86)%\NVDA', 'IAccessible2Proxy.dll'),
    (r'%ProgramFiles%\Mozilla Firefox', 'ia2marshal.dll'),
    (r'%ProgramFiles(x86)%\Mozilla Firefox', 'ia2marshal.dll'),
    (r'%ProgramFiles%\Mozilla Firefox', 'AccessibleMarshal.dll'),
)

_proxy_state = {'how': '', 'path': '', 'why': '', 'registered': []}


def proxy_registered(iid=None):
    """Whether Windows knows a proxy for this interface (the registry).

    ``ProxyStubClsid32`` under ``HKCR\\Interface\\{iid}`` is the whole
    test: it is what an installed NVDA or Firefox writes.
    """
    iid = iid or IA2_INTERFACES['IAccessible2']
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                            r'Interface\%s\ProxyStubClsid32' % iid) as key:
            value, _kind = winreg.QueryValueEx(key, '')
            return bool(value)
    except Exception:                                # noqa: BLE001
        return False


def proxy_candidates():
    """Proxy DLLs that exist on this machine, in the order to try them."""
    import os
    found = []
    for folder, name in PROXY_FILES:
        path = os.path.join(os.path.expandvars(folder), name)
        if os.path.isfile(path) and path not in found:
            found.append(path)
    return found


def proxy_status():
    return dict(_proxy_state, in_registry=proxy_registered(),
                candidates=proxy_candidates())


def ensure_proxy():
    """Make the IA2 interfaces marshallable in THIS process. ``(how, detail)``.

    ``how`` is 'registry' when Windows already has a proxy, 'process' when
    one was registered here from a DLL found on the machine, and '' when
    neither could be done - in which case IA2 calls into a browser fail and
    UI Automation, which needs no proxy, is what the reader has.
    """
    if _proxy_state['how']:
        return _proxy_state['how'], _proxy_state['path']
    if proxy_registered():
        _proxy_state['how'] = 'registry'
        return 'registry', ''
    candidates = proxy_candidates()
    if not candidates:
        _proxy_state['why'] = 'no IA2 proxy DLL on this machine'
        return '', _proxy_state['why']
    for path in candidates:
        ok, why = _register_in_process(path)
        if ok:
            _proxy_state['how'] = 'process'
            _proxy_state['path'] = path
            return 'process', path
        _proxy_state['why'] = why
    return '', _proxy_state['why']


_kept = []      # the class factory and the library, alive for the process


def _register_in_process(path):
    """DllGetClassObject -> CoRegisterClassObject -> CoRegisterPSClsid."""
    import ctypes
    from ctypes import wintypes
    try:
        from comtypes import GUID, IUnknown
        from comtypes.server import IClassFactory  # noqa: F401
        import comtypes
    except Exception as error:                       # noqa: BLE001
        return False, 'comtypes is not here: %s' % error
    try:
        library = ctypes.WinDLL(path)
        get_class_object = library.DllGetClassObject
    except Exception as error:                       # noqa: BLE001
        return False, '%s would not load: %s' % (path, error)
    ole32 = ctypes.windll.ole32
    # **The proxy's class id is one of the interfaces it proxies** - MIDL
    # makes it the FIRST interface in the file unless told otherwise, and
    # which one that is differs between NVDA's build, Firefox's and ours.
    # So every IA2 interface id is tried as the class id until the DLL
    # answers with a factory; asking is free and the right one is certain.
    # A proxy/stub class object is an IPSFactoryBuffer, not an IClassFactory.
    iid_factory = GUID('{D5F569D0-593B-101A-B569-08002B2DBF7A}')
    factory = ctypes.c_void_p()
    clsid = None
    last = 0
    for candidate in ([IA2_INTERFACES['IAccessibleHyperlink']]
                      + list(IA2_INTERFACES.values())):
        trial = GUID(candidate)
        try:
            result = get_class_object(ctypes.byref(trial),
                                      ctypes.byref(iid_factory),
                                      ctypes.byref(factory))
        except Exception as error:                   # noqa: BLE001
            return False, 'DllGetClassObject raised: %s' % error
        if result == 0 and factory:
            clsid = trial
            break
        last = result
    if clsid is None:
        return False, 'DllGetClassObject answered 0x%08X for every class id' % (
            last & 0xFFFFFFFF)
    CLSCTX_INPROC_SERVER, REGCLS_MULTIPLEUSE = 1, 1
    cookie = wintypes.DWORD()
    result = ole32.CoRegisterClassObject(ctypes.byref(clsid), factory,
                                         CLSCTX_INPROC_SERVER, REGCLS_MULTIPLEUSE,
                                         ctypes.byref(cookie))
    if result != 0:
        return False, 'CoRegisterClassObject answered 0x%08X' % (result & 0xFFFFFFFF)
    _kept.append((library, factory, cookie))
    done = []
    for name, iid in IA2_INTERFACES.items():
        try:
            if ole32.CoRegisterPSClsid(ctypes.byref(GUID(iid)),
                                       ctypes.byref(clsid)) == 0:
                done.append(name)
        except Exception:                            # noqa: BLE001
            continue
    _proxy_state['registered'] = done
    return bool(done), '' if done else 'CoRegisterPSClsid refused every interface'
