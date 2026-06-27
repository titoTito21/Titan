# -*- coding: utf-8 -*-
"""Windows Calculator application module.

Python port of ``ScreenReader/AppModules/CalculatorModule.cs``. Announces the
display readout when it changes. Unlike the C# version (which translated English
UIA button names to Polish) the button names are already English here, so they
are left as the default announcement.

# LOCALE KEYS TO ADD: calculator.appName = Calculator
# LOCALE KEYS TO ADD: calculator.display = Display: {0}
"""

from titan_access.localization import L
from titan_access.app_modules.base import AppModuleBase
from titan_access.contracts import ROLE_TEXT


class CalculatorModule(AppModuleBase):
    process_name = "calculatorapp"

    def __init__(self, engine):
        super().__init__(engine)
        self._last_display = None

    @property
    def app_name(self):
        return L("calculator.appName")

    def on_lose_focus(self, obj):
        self._last_display = None
        super().on_lose_focus(obj)

    def customize_object(self, obj):
        if obj is None:
            return obj
        try:
            # The result/display field is a Text control whose AutomationId
            # contains "Display"; announce its value only when it changes.
            if obj.role == ROLE_TEXT and "Display" in (obj.automation_id or ""):
                name = obj.name or obj.value
                if name and name != self._last_display:
                    self._last_display = name
                    obj.description = self._append(obj.description,
                                                   L("calculator.display", name))
        except Exception:
            pass
        return obj

    @staticmethod
    def _append(description, detail):
        if not detail:
            return description
        return f"{description}, {detail}" if description else detail
