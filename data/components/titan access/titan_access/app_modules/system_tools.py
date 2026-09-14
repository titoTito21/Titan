# -*- coding: utf-8 -*-
"""Windows' administrative tools and the two-panel file managers.

In the spirit of NVDA's ``taskmgr``, ``mmc``, ``regedit`` and ``totalcmd``
modules. What these programs have in common is a report-mode list whose
columns carry the meaning - a process's CPU and memory, a service's status,
a registry value's type and data - and a tree whose depth is the place.
The columns are read by :mod:`titan_access.semantics` for every list on
the machine; what a module adds is the name of the program, the tree
depth where the tree does not report its own level, and, for Total
Commander, the owner-drawn rows whose cells arrive tab-separated.
"""

from titan_access.localization import L
from titan_access.app_modules.base import AppModuleBase
from titan_access.contracts import ROLE_TREEITEM, ROLE_LISTITEM


def _tree_level(obj):
    """Count tree-item ancestors of a tree item through the live element."""
    native = getattr(obj, "native", None)
    if native is None:
        return 0
    level = 0
    node = native
    for _depth in range(40):
        try:
            node = node.GetParentControl()
            if node is None:
                break
            kind = node.ControlTypeName
        except Exception:
            break
        if kind == "TreeItemControl":
            level += 1
        elif kind == "TreeControl":
            break
    return level


class _TreeAndListModule(AppModuleBase):
    """A tree on the left, a report list on the right (mmc, regedit)."""

    welcome_key = ""

    @property
    def app_name(self):
        return L(self.welcome_key) if self.welcome_key else self.process_name

    def on_gain_focus(self, obj):
        self._announce_welcome_once(self.app_name)

    def customize_object(self, obj):
        if obj is None:
            return obj
        try:
            if obj.role == ROLE_TREEITEM and not obj.level:
                level = _tree_level(obj)
                if level > 0:
                    obj.level = level
        except Exception:
            pass
        return obj


class TaskManagerModule(_TreeAndListModule):
    process_name = "taskmgr"
    welcome_key = "tools.taskManager"


class ManagementConsoleModule(_TreeAndListModule):
    """mmc and every snap-in started by name: services, the event viewer,
    device manager, computer management, the task scheduler."""
    process_names = {"mmc", "eventvwr", "services", "compmgmt", "devmgmt",
                     "taskschd", "diskmgmt", "gpedit", "secpol", "lusrmgr",
                     "certmgr", "perfmon", "wf"}
    process_name = "mmc"
    welcome_key = "tools.managementConsole"


class RegistryEditorModule(_TreeAndListModule):
    process_name = "regedit"
    welcome_key = "tools.registryEditor"

    def customize_object(self, obj):
        obj = super().customize_object(obj)
        # The address bar holds the key's full path; say it as the place.
        try:
            if obj is not None and obj.role == "edit" and obj.value \
                    and obj.value.upper().startswith(("HKEY_", "COMPUTER\\")):
                obj.description = L("tools.registryPath", obj.value)
        except Exception:
            pass
        return obj


class SevenZipModule(_TreeAndListModule):
    process_names = {"7zfm", "7zg"}
    process_name = "7zfm"
    welcome_key = "tools.sevenZip"


class TotalCommanderModule(AppModuleBase):
    """Total Commander: two owner-drawn panels (``TMyListBox``).

    A row arrives through MSAA as one string with its cells separated by
    tabs - name, extension, size, date, attributes - which a synthesizer
    runs together. They are read as cells, with the extension put back on
    the name, the way the row looks.
    """
    process_names = {"totalcmd", "totalcmd64"}
    process_name = "totalcmd"

    @property
    def app_name(self):
        return L("tools.totalCommander")

    def on_gain_focus(self, obj):
        self._announce_welcome_once(self.app_name)

    @staticmethod
    def split_row(text):
        """``[name, size, date, ...]`` out of a tab-separated row."""
        cells = [one.strip() for one in str(text or "").split("\t")]
        cells = [one for one in cells if one]
        if len(cells) >= 2 and cells[1] and "." not in cells[0] \
                and len(cells[1]) <= 8 and cells[1].isalnum() \
                and not cells[1][0].isdigit():
            # name, ext -> name.ext
            cells = [cells[0] + "." + cells[1]] + cells[2:]
        return cells

    def customize_object(self, obj):
        if obj is None:
            return obj
        try:
            if obj.role == ROLE_LISTITEM and "\t" in (obj.name or ""):
                cells = self.split_row(obj.name)
                if cells:
                    obj.name = cells[0]
                    rest = ", ".join(cells[1:])
                    if rest:
                        obj.description = rest
        except Exception:
            pass
        return obj
