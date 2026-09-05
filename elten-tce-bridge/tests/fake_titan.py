"""A stand-in Titan: the real action names, answering the real shapes."""
import ctypes, importlib.util, json, os, sys, time
from ctypes import wintypes

REPO = r"C:\Users\Tito\OneDrive\projects\gitHub projects\Titan"
spec = importlib.util.spec_from_file_location(
    "titan_actions", os.path.join(REPO, "src", "titan_core", "titan_actions.py"))
ta = importlib.util.module_from_spec(spec); spec.loader.exec_module(ta)

PIPE = r"\\.\pipe\TitanBusProbe"
k32 = ctypes.windll.kernel32
create = k32.CreateNamedPipeW
create.restype = wintypes.HANDLE
create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                   wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]

SPOKEN = []
WIDGET = ["Szybki start: Wylaczony", 0]

ADDONS = [
    {"id": "titan", "label": "Titan", "kind": "builtin", "kind_label": "Titan",
     "description": "Titan itself", "actions": ["launch", "inventory", "views"]},
    {"id": "tedit", "label": "Text Editor", "kind": "app", "kind_label": "Application",
     "description": "", "actions": ["open_file", "save", "get_text"]},
    {"id": "macros", "label": "Macro Manager", "kind": "component",
     "kind_label": "Component", "description": "", "actions": ["status", "enable", "disable"]},
    {"id": "system_information", "label": "System information", "kind": "statusbar_applet",
     "kind_label": "Statusbar applet", "description": "", "actions": ["read", "activate"]},
    {"id": "supertonic", "label": "Supertonic", "kind": "tts_engine",
     "kind_label": "TTS engine", "description": "", "actions": ["status", "list_voices", "set_voice", "use"]},
    {"id": "shell", "label": "System shell", "kind": "builtin", "kind_label": "Titan",
     "description": "", "actions": ["status", "windows", "list_desktop"]},
    {"id": "titannet", "label": "Titan-Net", "kind": "builtin", "kind_label": "Titan",
     "description": "", "actions": ["rooms", "whoami"]},
]

def answer(addon, action, args):
    key = f"{addon}.{action}"
    if key == "probe.spoken":
        return json.dumps(SPOKEN)
    if key == "probe.forget":
        SPOKEN.clear()
        return "[]"
    if key == "titan.views":
        return json.dumps({"views": [{"id": "apps", "label": "Application List:", "short_name": "Applications"},
                                     {"id": "games", "label": "Game List:", "short_name": "Games"},
                                     {"id": "network", "label": "Titan IM:", "short_name": "Titan IM"},
                                     {"id": "cling", "label": "Cling:", "short_name": "Cling"}]})
    if key == "titan.inventory":
        kind = args.get("kind", "app")
        entries = {"app": ["tEdit", "TFM", "tNotes"], "game": ["Snake", "Quiz"],
                   "im_module": ["ExampleIM"]}.get(kind, [])
        return json.dumps({"kinds": [{"kind": kind, "label": kind, "entries": entries}]})
    if key == "titan.status_bar":
        return json.dumps({"items": [{"key": "time", "text": "Clock: 14:05"},
                                     {"key": "volume", "text": "Volume: 45%"},
                                     {"key": "applet:system_information", "text": "CPU 12%"}]})
    if key == "titan.menu":
        return json.dumps({"groups": [{"id": "program", "label": "Program",
                                       "entries": [{"id": "install_package", "label": "Install data package"}]},
                                      {"id": "ai", "label": "AI",
                                       "entries": [{"id": "ai_agent", "label": "AI Agent"}]}]})
    if key == "titan.menu_run":
        return f"Opened {args.get('entry')}."
    if key == "titan.launch":
        return f"Opened {args.get('name')}."
    if key == "titan.addon_actions":
        return json.dumps({"addon": args.get("addon"), "actions": [
            {"name": "open_file", "summary": "Open a file in the editor. It is shown at once.",
             "risk": "auto", "needs_ai": False,
             "params": [{"name": "path", "type": "string", "description": "The file to open.",
                         "required": True, "enum": []}]},
            {"name": "save", "summary": "Save the document.", "risk": "auto",
             "needs_ai": False, "params": []}]})
    if key == "titan.speaking":
        return "yes" if SPOKEN and SPOKEN[-1][0] == "reader_speak" else "no"
    if key == "titan.reader_speak":
        # What the real one does: start the speech and return at once.
        SPOKEN.append(("reader_speak", args.get("text"), args.get("interrupt")))
        return "Speaking."
    if key == "titan.set_speech_rate":
        SPOKEN.append(("set_rate", args.get("rate"), None))
        return "0"
    if key == "titan.get_speech_rate":
        return "0"
    if key == "titan.speak":
        # The rate-borrowing path waits for the whole line to be spoken.
        # Nothing in the bridge may use it for reading: that is the bug this
        # delay exists to catch.
        SPOKEN.append(("speak", args.get("text"), args.get("interrupt")))
        if args.get("rate") is not None:
            time.sleep(1.5)
        return "Said it."
    if key == "titan.stop_speech":
        SPOKEN.append(("stop", None, None))
        return "Stopped speaking."
    if key == "settings.screen":
        return json.dumps({"categories": [
            {"name": "General", "items": [
                {"id": "c1", "category": "General", "label": "Confirm exit from Titan",
                 "kind": "bool", "value": True, "options": [], "enabled": True, "description": ""},
                {"id": "c2", "category": "General", "label": "Language", "kind": "choice",
                 "value": "English", "options": ["English", "Polski"], "enabled": True, "description": ""},
                {"id": "c3", "category": "General", "label": "User name", "kind": "text",
                 "value": "Tito", "options": [], "enabled": True, "description": ""}]},
            {"name": "Sounds", "items": [
                {"id": "c4", "category": "Sounds", "label": "Sound theme", "kind": "choice",
                 "value": "default", "options": ["default", "longhorn"], "enabled": True, "description": ""}]}]})
    if key == "settings.set_value":
        return f"{args.get('item')} is now {args.get('value')}. Nothing is written until you save."
    if key == "settings.save":
        return "Saved."
    if key == "titannet.whoami":
        return json.dumps({"username": "tito", "user_id": 7})
    if key == "titannet.rooms":
        return json.dumps({"rooms": [{"id": 1, "name": "General", "type": "text", "has_password": False},
                                     {"id": 2, "name": "Help", "type": "voice", "has_password": True}]})
    if key == "titannet.online":
        return json.dumps({"users": [{"id": 7, "username": "tito"}, {"id": 9, "username": "ala"}]})
    if key == "titannet.people":
        return json.dumps({"users": [{"id": 7, "username": "tito"}, {"id": 9, "username": "ala"},
                                     {"id": 11, "username": "borys"}]})
    if key == "titannet.room_messages":
        return json.dumps({"messages": [{"sender": "ala", "message": "Hello everybody",
                                         "timestamp": "14:01"},
                                        {"sender": "tito", "message": "Hi", "timestamp": "14:02"}]})
    if key == "titannet.conversation":
        return json.dumps({"messages": [{"sender": "ala", "message": "Are you there?",
                                         "timestamp": "13:55"}]})
    if key == "titannet.topics":
        return json.dumps({"topics": [{"id": 3, "title": "Welcome", "author": "tito",
                                       "reply_count": 2}]})
    if key == "titannet.topic":
        return json.dumps({"topic": {"id": 3, "title": "Welcome", "author": "tito",
                                     "created_at": "yesterday", "content": "Hello and welcome."},
                           "replies": [{"author": "ala", "created_at": "today", "content": "Thanks!"}]})
    if key == "titannet.mailbox":
        return json.dumps({"mail": [{"id": 5, "subject": "A letter", "from": "ala@titan",
                                     "date": "today", "read": False}]})
    if key == "titannet.mail":
        return json.dumps({"mail": {"id": 5, "subject": "A letter", "from": "ala@titan",
                                    "date": "today", "body": "The whole message."}})
    if key == "titannet.feedback":
        items = [{"id": 4, "title": "Wiecej glosow", "item_type": "idea",
                  "status": "open", "votes": 3, "username": "tito"},
                 {"id": 5, "title": "Blad w oknie", "item_type": "bug",
                  "status": "fixed", "votes": 1, "username": "ala"}]
        kind = (args.get("kind") or "").strip()
        if kind:
            items = [i for i in items if i["item_type"] == kind]
        return json.dumps({"items": items})
    if key == "titannet.feedback_item":
        return json.dumps({"item": {"id": 4, "title": "Wiecej glosow",
                                    "username": "tito", "created_at": "today",
                                    "status": "open", "content": "Prosze o wiecej glosow.",
                                    "comments": [{"username": "ala", "content": "Popieram"}]}})
    if key in ("titannet.feedback_new", "titannet.feedback_upvote"):
        SPOKEN.append((action, args.get("title") or args.get("item"), None))
        return "Done."
    if key == "titannet.repository":
        return json.dumps({"apps": [{"id": 2, "name": "tCalc", "version": "1.2",
                                     "author": "tito"}]})
    if key == "titannet.repository_item":
        return json.dumps({"app": {"id": 2, "name": "tCalc", "version": "1.2",
                                   "description": "Kalkulator."}})
    if key == "titannet.repository_download":
        SPOKEN.append(("download", args.get("app"), None))
        return "Downloaded."
    if key == "titannet.announcements":
        return json.dumps({"files": [{"name": "2026-09-01.txt"}]})
    if key == "titannet.announcement":
        return json.dumps({"content": "Serwer bedzie wylaczony w nocy."})
    if key == "titannet.send_room_message":
        return "Sent."
    if key == "titan.widgets":
        return json.dumps({"widgets": [{"id": "quick_settings", "name": "Szybkie ustawienia", "type": "grid"},
                                       {"id": "example_button", "name": "Example button", "type": "button"}]})
    if key == "titan.components":
        return json.dumps({"components": [{"name": "Macro Manager", "folder": "macros", "enabled": True}],
                           "menu_actions": ["Macro Manager...", "Tips"]})
    if key == "titan.widget_read":
        return WIDGET[0]
    if key == "titan.widget_move":
        WIDGET[1] = (WIDGET[1] + (1 if args.get("direction") in ("down", "right", "next") else -1)) % 3
        WIDGET[0] = ["Szybki start: Wylaczony", "Jezyk: Polski", "Motyw: Ciemny"][WIDGET[1]]
        return WIDGET[0]
    if key == "titan.activate_widget":
        return f"Pressed {args.get('widget')}."
    if key == "titan.run_component_action":
        return f"Ran {args.get('action')}."
    if key == "titan.buffers":
        return json.dumps({"categories": [{"id": "titannet", "name": "Titan-Net", "live": False,
                                           "buffers": [{"id": "pm", "name": "Private", "kind": "message", "count": 3}]}]})
    if key == "titan.buffer":
        return json.dumps({"elements": [{"buffer": "Private", "text": "hello there",
                                         "author": "ala", "kind": "message",
                                         "timestamp": 1}]})
    if key == "titan.clear_notifications":
        return "Cleared the notifications."
    if key == "titan.open_help":
        return "Opened Titan's help."
    if key == "titan.window":
        return f"Titan was {args.get('action')}d."
    if key.startswith("titan_access."):
        return f"reader {action}: done."
    if key == "titan.notifications":
        return json.dumps({"notifications": [{"date": "today", "time": "14:00",
                                              "appname": "Titan-Net", "content": "A new message"}]})
    if key == "shell.state":
        return json.dumps({"running": True, "windows_shell": True})
    if key == "macros.list_macros":
        return "1. Poranek - ctrl+alt+p\n2. Notatka - (no shortcut)"
    if key == "macros.read_macro":
        return 'say "Dzien dobry"\nwait 1s\n'
    if key == "macros.run_macro":
        SPOKEN.append(("run_macro", args.get("name"), None))
        return f"Ran {args.get('name')}."
    if key in ("macros.create_macro", "macros.edit_macro"):
        SPOKEN.append((action, args.get("name"), args.get("script")))
        return "Saved the macro."
    if key == "macros.macro_language":
        return "The Titan Script language\n\nsay \"...\"  speaks a line."
    if key == "macros.macro_actions":
        return "titan.speak, macros.run_macro, ..."
    if key == "macros.check_macro":
        return "The macro is fine."
    if key == "cling.list_applications":
        return "1. Mole No More - grid_hunt\n2. Klango Piano - instrument"
    if key == "cling.run":
        SPOKEN.append(("cling_run", args.get("name"), None))
        return f"Started {args.get('name')}."
    if key in ("cling.details", "cling.scores", "cling.account", "cling.status", "cling.emulate"):
        return f"cling {action}: something readable."
    if key == "titan.ai_available":
        return "yes"
    if key == "titan.ask_ai":
        SPOKEN.append(("ask_ai", args.get("question"), args.get("act")))
        return "The AI says: hello."
    if key == "memory.list_notes":
        return "1. Tito likes short answers"
    if key in ("memory.remember", "memory.forget"):
        return "Done."
    if key in ("ocr.read_window", "ocr.ask", "ocr.last_reading"):
        return "The window says: OK, Cancel."
    if key == "titan.list_im_contacts":
        return "1. Ala\n2. Borys"
    if key == "titan.send_message":
        SPOKEN.append(("send_message", args.get("recipient"), args.get("message")))
        return "Sent."
    if key == "elten.list_conversations":
        return "1. Ala - hi\n2. Borys - hello"
    if key == "elten.read_conversation":
        return "Ala: hi\nyou: hello"
    if key == "im.status":
        return f"{args.get('service')} is signed in."
    if key == "im.list_chats":
        return "1. Ala - hello there\n2. Family group - see you"
    if key == "im.read_chat":
        return "Ala: hello there\nyou: hi"
    if key == "im.send":
        SPOKEN.append(("im_send", args.get("chat"), args.get("text")))
        return "Sent."
    if key == "shell.status":
        return "The Titan shell is running: desktop, taskbar and Start menu."
    if key == "shell.windows":
        return json.dumps({"windows": [{"title": "Titan", "active": True, "minimized": False},
                                       {"title": "Notepad", "active": False, "minimized": True}]})
    if key == "shell.list_desktop":
        return "1. This PC\n2. Recycle Bin\n3. Titan"
    if key == "shell.list_tray":
        return "1. Volume\n2. Network"
    if key == "shell.list_drives":
        return "C: 500 GB, 120 GB free\nD: 1 TB, 800 GB free"
    if key == "shell.list_folder":
        return "Documents  <folder>  today\nreadme.txt  2 KB  yesterday"
    if key == "shell.search_programs":
        return "1. Notepad\n2. Notepad++"
    if key == "shell.power_options":
        return "1. Log off\n2. Shut down\n3. Turn off TCE"
    if key == "shell.list_settings":
        return "taskbar_position = bottom\nshow_clock = yes"
    if key.startswith("system."):
        return {"system.get_volume": "Volume: 45%", "system.get_power_plan": "Power plan: Balanced",
                "system.network_status": "Connected to HomeWiFi",
                "system.get_autostart": "Titan does not start with Windows",
                "system.list_audio_devices": "1. Speakers\n2. Headphones"}.get(key, "Done.")
    if action in ("enable", "disable"):
        SPOKEN.append((action, addon, None))
        return f"{addon}: {action}d."
    if action in ("read", "activate", "status", "list_voices", "use", "set_voice"):
        return f"{addon}: {action} done."
    return f"{addon}.{action} did something."

print("fake Titan listening", flush=True)
while True:
    handle = create(PIPE, 0x00000003 | 0x40000000, 0, 255, 65536, 65536, 0, None)
    ov = (ctypes.c_void_p * 8)()
    if not k32.ConnectNamedPipe(handle, ctypes.byref(ov)):
        err = k32.GetLastError()
        if err == 997:
            got = wintypes.DWORD(0)
            while not k32.GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(got), False):
                time.sleep(0.02)
        elif err != 535:
            continue
    io = ta.PipeChannel(handle)
    while True:
        line = io.read_line()
        if line is None:
            break
        try:
            msg = json.loads(line.decode("utf-8"))
        except Exception:
            continue
        if msg.get("type") == "hello":
            io.write_line({"type": "welcome", "ok": True, "protocol": 1})
        elif msg.get("type") == "list":
            io.write_line({"type": "list_result", "id": msg.get("id"), "ok": True, "addons": ADDONS})
        elif msg.get("type") == "spoken":
            io.write_line({"type": "call_result", "id": msg.get("id"), "ok": True,
                           "result": json.dumps(SPOKEN)})
        elif msg.get("type") == "call":
            try:
                result = answer(msg.get("addon"), msg.get("action"), msg.get("args") or {})
                io.write_line({"type": "call_result", "id": msg.get("id"), "ok": True, "result": result})
            except Exception as e:
                io.write_line({"type": "call_result", "id": msg.get("id"), "ok": False,
                               "error": f"{type(e).__name__}: {e}"})
    try: io.close()
    except Exception: pass
