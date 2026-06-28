# Titan Access — application modules (external / downloadable)

Drop a `*.py` file here, or in the screen reader's own settings folder
`%APPDATA%\titosoft\Titan\screenreader\app_modules\`, to customise how Titan
Access behaves inside one application. Modules are discovered and loaded
automatically when the screen reader starts. This mirrors how NVDA loads
`appModules\<exe>.py`.

## Minimal module

Name the file after the executable (without `.exe`), e.g. `winword.py`:

```python
from titan_access.app_modules.base import AppModuleBase

class AppModule(AppModuleBase):
    process_name = "winword"          # optional; inferred from the file name

    def on_gain_focus(self, obj):
        self._announce_welcome_once("Microsoft Word")

    def customize_object(self, obj):
        # Mutate obj in place before it is announced.
        return obj

    def should_announce(self, obj):
        return True                   # return False to suppress the announcement

    def get_gestures(self):
        # Gestures active only while this app is in the foreground.
        return {"control+shift+i": self._say_info}

    def _say_info(self, *a):
        self.engine.speak("Document info")
```

## The API you get

* `self.engine` — the live screen reader:
  * `self.engine.speak(text, interrupt=True, pitch_offset=0)`
  * `self.engine.play(sound_name)` — sounds from the component `sfx/` folder
  * `self.engine.announce_object(obj)` — full announcement (keeps sound cues + hierarchy)
  * `self.engine.current_object` — the focused `AccessibleObject`
  * `self.engine.provider` — accessibility provider (UIA primary, MSAA fallback)
* `obj` — an `AccessibleObject` (`titan_access.contracts`): `name`, `role`, `value`,
  `states`, `bounds`, `process_id`, and `native` (a vendored `uiautomation.Control`
  for UIA-sourced objects; `None` for MSAA-sourced ones).

## Hooks (all optional)

| method | when |
| --- | --- |
| `on_gain_focus(obj)` | app became active / each element focus |
| `on_lose_focus(obj)` | app lost the foreground |
| `customize_object(obj)` | mutate the object before it is announced |
| `should_announce(obj)` | return `False` to suppress the standard announcement |
| `event_value_change(obj)` | the focused value changed |
| `event_name_change(obj)` | the focused name/label changed |
| `event_alert(obj)` | an alert surfaced |
| `get_gestures()` | `{key_spec: callable}` app-only gestures |

## Porting an NVDA app module

NVDA modules subclass `appModuleHandler.AppModule` and overlay `NVDAObject`
classes, so they do **not** load as-is. The shapes are close, though: move
`event_gainFocus` logic into `on_gain_focus` / `customize_object`, `event_*`
handlers into the matching hooks, and `__gestures` into `get_gestures()`. The
`obj.native` UIA control replaces NVDA's `obj.UIAElement`.
