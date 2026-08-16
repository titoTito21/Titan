"""Every Titan setting, described well enough for the AI to find the right one.

``titan_list_settings`` / ``titan_get_setting`` / ``titan_set_setting`` already
read and write the settings file. The problem they leave is *discovery*: the
file only contains keys the user has already changed, so a setting left at its
default is invisible, and a key like ``alt_f4_action`` says nothing about what
its values mean. An AI asked to "make Titan speak faster" then has nothing to
go on.

So this module adds a schema: what a setting is called, which section it lives
in, what kind of value it takes, what the values mean, and words a user might
use for it. The schema is a help, never a gate - a key that is not listed here
can still be read and written, because components and add-ons add settings of
their own.
"""

from src.settings.settings import get_setting, load_settings, set_setting

# section, key -> (type, description, values, synonyms)
# 'values' is a human phrase, not a validator: Titan stores most settings as
# strings and the honest thing to tell the model is what the strings mean.
SCHEMA = {
    # ---------------------------------------------------------------- general
    ('general', 'language'): (
        'string', "Titan's interface language.", "'pl' or 'en'",
        "language, jezyk, translation"),
    ('general', 'skin'): (
        'string', "The visual skin.", "a skin name from the skins folder",
        "theme, appearance, colours"),
    ('general', 'invisible_interface'): (
        'boolean', "Use the Invisible UI (the non-visual interface) instead of "
        "the visual window.", "true or false",
        "invisible interface, iui, non-visual"),
    ('general', 'quick_start'): (
        'boolean', "Skip the startup animation and sound.", "true or false",
        "fast start, startup"),
    ('general', 'alt_f4_action'): (
        'string', "What Alt+F4 does to Titan.",
        "'close', 'minimize' or 'ask'", "alt f4, closing"),
    ('general', 'minimize_action'): (
        'string', "What minimising Titan does.", "'tray' or 'taskbar'",
        "minimise, tray"),
    ('general', 'gamepad_detection'): (
        'string', "What Titan does when a gamepad is plugged in.",
        "'full' (full gamepad support), 'announce' (only say it was "
        "connected or disconnected) or 'nothing'",
        "gamepad, controller, joystick, pad"),
    ('general', 'titan_ui_key'): (
        'string', "The global hotkey that brings Titan's interface up.",
        "a shortcut such as 'ctrl+alt+t'", "hotkey, shortcut, bring up titan"),
    ('general', 'windows_e_hook'): (
        'boolean', "Open Titan's file manager instead of Explorer on Win+E.",
        "true or false", "win e, explorer, file manager"),
    ('general', 'announce_screen_lock'): (
        'boolean', "Say when the computer locks and unlocks.", "true or false",
        "lock screen"),
    ('general', 'developer_tools'): (
        'boolean', "Show the Programmer menu and developer tools.",
        "true or false", "developer, programmer menu"),
    ('general', 'visible_categories'): (
        'string', "Which categories the main list shows.",
        "a comma-separated list", "categories, main list"),
    # ------------------------------------------------------------------ sound
    ('general', 'volume'): (
        'number', "Titan's own sound volume.", "0 to 100", "volume, loudness"),
    ('general', 'sound_mode'): (
        'string', "How Titan positions its sounds.",
        "'none', 'stereo' or '3d'", "sound positioning, 3d audio, hrtf"),
    ('general', 'stereo_sound'): (
        'boolean', "Pan Titan's sound cues to match where things are.",
        "true or false", "stereo, panning"),
    ('general', 'reverb_enabled'): (
        'boolean', "Add room reverb to positioned sound.", "true or false",
        "reverb, room"),
    # -------------------------------------------------------------- speech/TTS
    ('general', 'tts_engine'): (
        'string', "Which Titan TTS engine speaks.",
        "an engine name - list them with titan_list_tts_engines",
        "voice engine, synthesizer, speech engine"),
    ('general', 'voice'): (
        'string', "The voice within the current engine.", "a voice name",
        "voice, speaker"),
    ('general', 'rate'): (
        'number', "How fast Titan speaks.", "engine-dependent, often 0 to 100",
        "speed, rate, faster, slower"),
    ('general', 'pitch'): (
        'number', "The pitch of the speech.", "engine-dependent",
        "pitch, tone, higher, lower"),
    ('invisible_interface', 'stereo_speech'): (
        'boolean', "Pan speech left and right to show where the focus is.",
        "true or false", "stereo speech"),
    ('invisible_interface', 'announce_index'): (
        'boolean', "Say the position in the list ('3 of 12').",
        "true or false", "index, position, item number"),
    ('invisible_interface', 'announce_widget_type'): (
        'boolean', "Say what kind of control has the focus.", "true or false",
        "control type, widget type"),
    ('invisible_interface', 'announce_first_item'): (
        'boolean', "Announce the first item when a list opens.",
        "true or false", "first item"),
    ('invisible_interface', 'buffer_system_enabled'): (
        'boolean', "Turn the Titan Buffer System on.", "true or false",
        "buffers, buffer system"),
    # --------------------------------------------------------------- AI (ai.*)
    ('ai', 'enabled'): (
        'boolean', "Turn Titan's AI features on.", "true or false",
        "ai, artificial intelligence"),
    ('ai', 'provider'): (
        'string', "Which AI provider Titan uses.",
        "'anthropic', 'gemini' or 'openai'", "provider, model provider"),
    ('ai', 'method'): (
        'string', "How the creation kit talks to the AI.",
        "'api' or 'cli'", "api, cli"),
    ('ai', 'agent_confirm'): (
        'string', "How often the AI agent asks before acting.",
        "'tiered' (default), 'always' or 'never'",
        "confirmation, ask before, permission"),
    ('ai', 'addon_actions'): (
        'boolean', "Let the AI use the functions add-ons offer through the "
        "Titan Action API.", "true or false",
        "add-on actions, app functions, let ai control apps"),
    ('ai', 'addon_actions_blocked'): (
        'string', "Add-ons the AI may not drive.",
        "a comma-separated list of add-on ids", "blocked add-ons, exclude"),
    ('ai', 'memory_enabled'): (
        'boolean', "Let the AI remember earlier conversations.",
        "true or false", "memory, remember, context, history"),
    ('ai', 'memory_turns'): (
        'number', "How many earlier exchanges the AI carries into a new one.",
        "0 to 100 (default 20)", "memory length, history length"),
    ('ai', 'assistant_hotkey'): (
        'string', "The global hotkey for the voice assistant.",
        "a shortcut", "assistant hotkey, voice hotkey"),
    ('ai', 'assistant_tts'): (
        'string', "Which voice the assistant speaks with.",
        "'auto', 'titan' or a provider voice", "assistant voice"),
    ('ai', 'ocr_enabled'): (
        'boolean', "Turn AI OCR on (reading inaccessible windows).",
        "true or false", "ocr, read the screen, inaccessible"),
    ('ai', 'ocr_can_act'): (
        'boolean', "Let AI OCR press the controls it has read.",
        "true or false", "ocr clicking, press controls"),
    ('ai', 'ocr_open_as'): (
        'string', "Where AI OCR puts the controls it finds.",
        "'overlay' (on the real window) or 'list'", "overlay, reading list"),
    ('ai', 'ocr_scope'): (
        'string', "How much of the screen AI OCR reads.",
        "'window' or 'screen'", "ocr scope"),
    ('ai', 'ocr_live_seconds'): (
        'number', "How often AI OCR re-reads while watching, in seconds "
        "(0 turns watching off).", "0 to 60", "live ocr, watch screen"),
    ('ai', 'reminder_announce'): (
        'string', "How due reminders are announced.",
        "'voice', 'text' or 'off'", "reminders, announcements"),
    # ---------------------------------------------------------------- gamepad
    ('general', 'vibration_enabled'): (
        'boolean', "Let the gamepad vibrate.", "true or false",
        "vibration, rumble, haptics"),
    ('general', 'vibration_strength'): (
        'number', "How strong the vibration is.", "0 to 100",
        "vibration strength"),
    ('general', 'haptic_mode'): (
        'string', "What the gamepad vibrates for.",
        "'off', 'events' or 'audio'", "haptic mode"),
    ('general', 'speech_haptic_sync'): (
        'boolean', "Vibrate in time with speech.", "true or false",
        "speech haptics"),
    # --------------------------------------------------------- system monitor
    ('system_monitor', 'battery_low_threshold'): (
        'number', "Battery percentage that counts as low.", "1 to 100",
        "battery, low battery"),
    ('system_monitor', 'battery_critical_threshold'): (
        'number', "Battery percentage that counts as critical.", "1 to 100",
        "battery critical"),
    ('system_monitor', 'battery_announce_interval'): (
        'number', "Minutes between battery announcements.", "1 to 120",
        "battery announcements"),
    ('system_monitor', 'volume_monitor'): (
        'boolean', "Announce system volume changes.", "true or false",
        "volume announcements"),
    # -------------------------------------------------------------- Titan-Net
    ('general', 'titannet_server_sounds'): (
        'boolean', "Allow sounds sent by the Titan-Net server.",
        "true or false", "server sounds"),
    ('general', 'mail_compose_format'): (
        'string', "The format the Mail composer starts in.",
        "'text', 'markdown' or 'html'", "mail format"),
}

_SECRET_HINTS = ('key', 'token', 'password', 'secret')


def _is_secret(key):
    lowered = str(key).lower()
    return any(hint in lowered for hint in _SECRET_HINTS)


def _describe(section, key):
    entry = SCHEMA.get((section, key))
    if not entry:
        return None
    kind, description, values, _synonyms = entry
    return f"{section}.{key} ({kind}) - {description} Values: {values}."


def _current(section, key):
    if _is_secret(key):
        value = get_setting(key, None, section=section)
        return '(set)' if value else '(not set)'
    return get_setting(key, None, section=section)


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
def titan_find_setting(query, **_):
    """Find the setting that matches what the user asked for."""
    words = [w for w in str(query or '').lower().replace(',', ' ').split() if w]
    if not words:
        return "Say what you are looking for, e.g. 'speech speed' or 'battery'."
    scored = []
    for (section, key), (kind, description, values, synonyms) in SCHEMA.items():
        haystack = f"{section} {key} {description} {values} {synonyms}".lower()
        score = sum(1 for word in words if word in haystack)
        if score:
            scored.append((score, section, key))
    # Anything the user has actually set, even if it is not in the schema.
    try:
        stored = load_settings() or {}
    except Exception:
        stored = {}
    for section, values in stored.items():
        if not isinstance(values, dict):
            continue
        for key in values:
            if (section, key) in SCHEMA:
                continue
            if any(word in f"{section} {key}".lower() for word in words):
                scored.append((1, section, key))
    if not scored:
        return (f"Nothing matches '{query}'. titan_list_settings shows "
                f"everything that has been set.")
    scored.sort(key=lambda item: -item[0])
    lines = [f"Settings matching '{query}':"]
    for _score, section, key in scored[:12]:
        described = _describe(section, key) or f"{section}.{key}"
        lines.append(f"- {described} Currently: {_current(section, key)!r}")
    lines.append("Change one with titan_set_setting(key, value, section).")
    return "\n".join(lines)


def titan_describe_setting(key, section="general", **_):
    """What one setting means, what it accepts and what it is now."""
    described = _describe(section, key)
    current = _current(section, key)
    if described:
        return f"{described}\nCurrently: {current!r}"
    return (f"{section}.{key} is not one of Titan's documented settings "
            f"(it may belong to a component or an add-on). Its current value "
            f"is {current!r}. It can still be read and written.")


def titan_list_setting_sections(**_):
    """The sections settings are grouped into."""
    try:
        stored = load_settings() or {}
    except Exception:
        stored = {}
    sections = {section for section, _key in SCHEMA}
    sections.update(k for k, v in stored.items() if isinstance(v, dict))
    lines = ["Titan settings sections:"]
    for section in sorted(sections):
        documented = sum(1 for s, _k in SCHEMA if s == section)
        present = len(stored.get(section, {}) or {})
        lines.append(f"- {section}: {documented} documented, {present} set")
    lines.append("Search with titan_find_setting, read one with "
                 "titan_describe_setting.")
    return "\n".join(lines)


def titan_reset_setting(key, section="general", **_):
    """Put a setting back to Titan's default by removing it."""
    try:
        from src.settings.settings import save_settings
        stored = load_settings() or {}
        if key not in (stored.get(section) or {}):
            return f"{section}.{key} is already at its default."
        del stored[section][key]
        save_settings(stored)
    except Exception as e:
        return f"Could not reset {section}.{key}: {e}"
    return (f"Reset {section}.{key} to Titan's default. Some settings need "
            f"Titan restarted to take effect.")


def titan_settings_interfaces(**_):
    """Which window Titan's settings open in, and what else is installed."""
    try:
        from src.settings.interfaces import manager
        described = manager().describe()
        chosen = manager().chosen()
    except Exception as e:
        return f"Could not read the settings interfaces: {e}"
    lines = ["Titan's settings open in: "
             + (chosen or "the classic window") + "."]
    if not described:
        lines.append("No other settings interfaces are installed. They go in "
                     "data/settings interfaces/ and show the same settings "
                     "the classic window does, rendered their own way.")
        return "\n".join(lines)
    lines.append("Installed:")
    for entry in described:
        state = "on" if entry['enabled'] else "off"
        lines.append(f"- {entry['name']} ({entry['id']}): {state}"
                     + (f", broken: {entry['error']}" if entry['error'] else ""))
        if entry['description']:
            lines.append(f"  {entry['description']}")
    lines.append("Choose one with titan_use_settings_interface, or '' for the "
                 "classic window.")
    return "\n".join(lines)


def titan_use_settings_interface(interface="", **_):
    """Open Titan's settings in a different interface from now on."""
    try:
        from src.settings.interfaces import manager
        ok, answer = manager().choose(interface)
    except Exception as e:
        return f"Could not change the settings interface: {e}"
    if not ok:
        return answer
    if not answer:
        return "Titan's settings will open in the classic window again."
    return (f"Titan's settings will now open in '{answer}'. Settings -> "
            f"Interface -> Settings interface changes it back.")


def get_settings_tools():
    from src.ai.agent_tools import _tool
    S = {'type': 'string'}
    return [
        _tool('titan_find_setting',
              "Find which Titan setting does what the user is asking about, "
              "in plain words ('speech speed', 'battery warning', 'let the AI "
              "control my apps'). Use this before titan_set_setting when you "
              "are not certain of the exact key.", titan_find_setting,
              properties={'query': dict(S, description="What the user wants to change.")},
              required=['query']),
        _tool('titan_describe_setting',
              "Explain one Titan setting: what it does, what values it takes "
              "and what it is set to now.", titan_describe_setting,
              properties={'key': dict(S, description="Setting key."),
                          'section': dict(S, description="Section (default 'general').")},
              required=['key']),
        _tool('titan_list_setting_sections',
              "List the sections Titan's settings are grouped into.",
              titan_list_setting_sections),
        _tool('titan_settings_interfaces',
              "Say which interface Titan's settings open in - the classic "
              "window or one installed in data/settings interfaces/ - and "
              "list the others.", titan_settings_interfaces),
        _tool('titan_use_settings_interface',
              "Open Titan's settings in a different interface from now on. "
              "Pass an empty name for the classic window.",
              titan_use_settings_interface, risk='confirm',
              properties={'interface': dict(S, description="The interface's "
                          "id, or '' for the classic window.")},
              required=['interface']),
        _tool('titan_reset_setting',
              "Put one Titan setting back to its default.",
              titan_reset_setting, risk='confirm',
              properties={'key': dict(S, description="Setting key."),
                          'section': dict(S, description="Section (default 'general').")},
              required=['key']),
    ]
