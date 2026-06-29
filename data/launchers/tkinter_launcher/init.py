# -*- coding: utf-8 -*-
"""Tkinter Launcher for TCE -- demonstrates the Launcher API using Tkinter.

Mirrors the PyQt example launcher (application / game lists, Titan IM, a status
bar section, Help / Settings / Exit, minimize and Invisible UI support) but is
built with the standard-library ``tkinter`` so it needs no third-party GUI
dependency.

Accessibility
-------------
Tkinter widgets are invisible to UI Automation, so this launcher ships
``tk_access`` (next to this file) and calls ``tk_access.enable(root)``: focus,
selection and value changes are pushed to Titan Access (in-process) or any
active screen reader (accessible_output3). The same ``tk_access`` module can be
dropped into any Tkinter application to make it readable.

Threading
---------
Tk requires its event loop on the thread that created the root. The launcher
manager calls start() on the MAIN thread, so we run Tk there (this also lets a
screen reader read the window like a normal app). We pump pending wx events from
a Tk ``after`` timer so the wx-based Settings / dialogs keep working.
"""

import os
import sys

_api = None
_root = None

# Make the bundled tk_access importable regardless of how init.py was loaded.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)


def start(api):
    """Run the Tkinter launcher on the main thread (blocks until it exits)."""
    global _api
    _api = api
    try:
        import tkinter  # noqa: F401
    except Exception:
        msg = "Tkinter Launcher requires tkinter, which is not available."
        print(f"[tkinter_launcher] {msg}")
        _notify_failure(msg)
        return
    try:
        _run_tk_ui()
    except Exception:
        import traceback
        print("[tkinter_launcher] UI crashed:\n" + traceback.format_exc())
        _notify_failure("The Tkinter launcher failed to start. See the console for details.")


def _notify_failure(message):
    try:
        speaker = getattr(_api, "speaker", None)
        if speaker is not None:
            speaker.speak(message)
    except Exception:
        pass


def _run_tk_ui():
    global _root
    import tkinter as tk
    from tkinter import ttk

    try:
        import tk_access
    except Exception as e:
        tk_access = None
        print(f"[tkinter_launcher] tk_access unavailable: {e}")

    _ = _api._  # translation function

    root = tk.Tk()
    _root = root
    root.title(f"TCE - {_api._config.name} v{_api.version}")
    root.geometry("700x600")

    # Accessibility: push focus / selection to the screen reader.
    if tk_access is not None:
        try:
            tk_access.enable(root, app_name=_api._config.name, translate=_)
        except Exception as e:
            print(f"[tkinter_launcher] tk_access.enable failed: {e}")

    container = ttk.Frame(root, padding=10)
    container.pack(fill="both", expand=True)

    apps, games, im_items = [], [], []

    def _section_label(text):
        lbl = ttk.Label(container, text=text, font=("Segoe UI", 11, "bold"))
        lbl.pack(anchor="w", pady=(8, 2))
        return lbl

    def _make_list(name):
        lb = tk.Listbox(container, exportselection=False, height=6,
                        activestyle="dotbox")
        lb.pack(fill="both", expand=True)
        if tk_access is not None:
            tk_access.set_name(lb, name)
        return lb

    def _wire_list(lb, items, on_activate):
        def _focus_select(_e=None):
            if lb.size() and not lb.curselection():
                lb.selection_set(0)
                lb.activate(0)
            try:
                _api.play_focus_sound()
            except Exception:
                pass
        lb.bind("<FocusIn>", _focus_select, add="+")
        lb.bind("<<ListboxSelect>>", lambda _e: _safe_play_focus(), add="+")

        def _activate(_e=None):
            sel = lb.curselection()
            if not sel:
                return
            idx = sel[0]
            if 0 <= idx < len(items):
                try:
                    _api.play_select_sound()
                except Exception:
                    pass
                on_activate(idx)
        lb.bind("<Return>", _activate, add="+")
        lb.bind("<Double-Button-1>", _activate, add="+")

    def _safe_play_focus():
        try:
            _api.play_focus_sound()
        except Exception:
            pass

    # --- Applications ---
    if _api.get_applications:
        apps = _api.get_applications() or []
        if apps:
            _section_label(_("Applications"))
            app_lb = _make_list(_("Applications"))
            for app in apps:
                app_lb.insert("end", app.get("name", app.get("name_en", "Unknown")))
            _wire_list(app_lb, apps, lambda i: _api.open_application(apps[i]))

    # --- Games ---
    if _api.get_games:
        games = _api.get_games() or []
        if games:
            _section_label(_("Games"))
            game_lb = _make_list(_("Games"))
            for game in games:
                nm = game.get("name", "Unknown")
                plat = game.get("platform", "")
                game_lb.insert("end", f"{nm} ({plat})" if plat else nm)
            _wire_list(game_lb, games, lambda i: _api.open_game(games[i]))

    # --- Titan IM ---
    if _api.has_feature("titan_im"):
        _section_label(_("Titan IM"))
        im_lb = _make_list(_("Titan IM"))
        if _api.titan_net_client:
            im_items.append(("titannet", None)); im_lb.insert("end", _("Titan-Net (Beta)"))
        im_items.append(("telegram", None));  im_lb.insert("end", _("Telegram"))
        im_items.append(("messenger", None)); im_lb.insert("end", _("Facebook Messenger"))
        im_items.append(("whatsapp", None));  im_lb.insert("end", _("WhatsApp"))
        im_items.append(("eltenlink", None)); im_lb.insert("end", _("EltenLink"))
        if _api.im_module_manager:
            for info in _api.im_module_manager.modules:
                status = _api.im_module_manager.get_status_text(info["id"])
                disp = f"{info['name']} {status}" if status else info["name"]
                im_items.append(("im_module", info["id"]))
                im_lb.insert("end", disp)

        def _open_im(i):
            kind, im_id = im_items[i]
            if kind == "titannet": _api.open_titannet()
            elif kind == "telegram": _api.open_telegram()
            elif kind == "messenger": _api.open_messenger()
            elif kind == "whatsapp": _api.open_whatsapp()
            elif kind == "eltenlink": _api.open_eltenlink()
            elif kind == "im_module" and _api.im_module_manager:
                _api.im_module_manager.open_module(im_id, None)
        _wire_list(im_lb, im_items, _open_im)

    # --- Status Bar (built-in items + applets) ---
    builtin_count = 4
    sb_lb = None
    if _api.statusbar_applet_manager:
        _section_label(_("Status Bar"))
        sb_lb = _make_list(_("Status Bar"))
        for text in _api.statusbar_applet_manager.get_statusbar_items():
            sb_lb.insert("end", text)
        sb_lb.bind("<FocusIn>", lambda _e: _safe_play_statusbar(), add="+")
        sb_lb.bind("<<ListboxSelect>>", lambda _e: _safe_play_statusbar(), add="+")

        def _activate_sb(_e=None):
            sel = sb_lb.curselection()
            if not sel:
                return
            applet_idx = sel[0] - builtin_count
            names = _api.statusbar_applet_manager.get_applet_names()
            if 0 <= applet_idx < len(names):
                try:
                    _api.play_select_sound()
                except Exception:
                    pass
                _api.statusbar_applet_manager.activate_applet(names[applet_idx])
        sb_lb.bind("<Return>", _activate_sb, add="+")

    def _safe_play_statusbar():
        try:
            _api.play_statusbar_sound()
        except Exception:
            pass

    # Live-update the status bar every 2 seconds.
    def _update_statusbar():
        if sb_lb is not None:
            try:
                items = _api.statusbar_applet_manager.get_statusbar_items()
                for i, text in enumerate(items):
                    if i < sb_lb.size():
                        if sb_lb.get(i) != text:
                            cur = sb_lb.curselection()
                            sb_lb.delete(i)
                            sb_lb.insert(i, text)
                            if cur and cur[0] == i:
                                sb_lb.selection_set(i)
                    else:
                        sb_lb.insert("end", text)
            except Exception:
                pass
        root.after(2000, _update_statusbar)
    if sb_lb is not None:
        root.after(2000, _update_statusbar)

    # --- Buttons ---
    btn_row = ttk.Frame(container)
    btn_row.pack(fill="x", pady=(10, 0))

    if _api.show_help:
        def _on_help():
            try: _api.play_dialog_sound()
            except Exception: pass
            _api.show_help()
        hb = ttk.Button(btn_row, text=_("Help"), command=_on_help)
        hb.pack(side="left", padx=5)

    def _on_settings():
        try: _api.play_dialog_sound()
        except Exception: pass
        _api.show_settings()
    ttk.Button(btn_row, text=_("Settings"), command=_on_settings).pack(side="left", padx=5)

    def _on_exit():
        try: _api.play_sound("ui/dialogclose.ogg")
        except Exception: pass
        try: root.destroy()
        except Exception: pass
        _api.force_exit()
    ttk.Button(btn_row, text=_("Exit"), command=_on_exit).pack(side="left", padx=5)

    # --- Minimize / restore ---
    _api.register_minimize_handler(lambda: root.withdraw())

    def _restore():
        root.deiconify(); root.lift(); root.focus_force()
    _api.register_restore_handler(_restore)

    root.bind("<Escape>", lambda _e: _api.minimize_launcher())
    root.protocol("WM_DELETE_WINDOW", _on_exit)

    # --- wx pump: keep Settings / dialogs alive while Tk owns the main thread ---
    def _pump_wx():
        try:
            import wx
            app = wx.GetApp()
            if app is not None:
                app.ProcessPendingEvents()
                wx.YieldIfNeeded()
        except Exception:
            pass
        root.after(40, _pump_wx)
    root.after(40, _pump_wx)

    # Focus the first list.
    first = next((w for w in container.winfo_children()
                  if isinstance(w, tk.Listbox)), None)
    if first is not None:
        first.focus_set()
        if first.size():
            first.selection_set(0); first.activate(0)

    try:
        _api.start_invisible_ui()
    except Exception:
        pass

    root.mainloop()


def shutdown():
    """Cleanup when the launcher is stopped."""
    global _root
    try:
        if _api:
            _api.stop_invisible_ui()
    except Exception:
        pass
    try:
        if _root is not None:
            _root.destroy()
    except Exception:
        pass
    _root = None
    print("[tkinter_launcher] Shutdown complete")
