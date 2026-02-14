# -*- coding: utf-8 -*-
"""
Example Launcher for TCE - Demonstrates the Launcher API using PyQt5.

This launcher creates a PyQt5 window with application and game lists,
Titan IM communicators, a statusbar section showing built-in items and
applet data, sound feedback, settings access, and Invisible UI support.
It runs its own PyQt5 event loop in a daemon thread and returns from
start() immediately.

To enable this launcher:
1. Set status = 0 in __launcher__.TCE
2. Run: python main.py --startup-mode launcher --launcher example_launcher

Or set in settings:
    [general]
    startup_mode = launcher
    launcher = example_launcher
"""

import sys
import threading

_api = None
_window = None
_qt_app = None


def start(api):
    """Start the example launcher in a separate thread (PyQt5 has its own event loop)."""
    global _api
    _api = api

    # Start PyQt5 UI in a daemon thread
    ui_thread = threading.Thread(target=_run_pyqt_ui, daemon=True)
    ui_thread.start()


def _run_pyqt_ui():
    """Run the PyQt5 event loop."""
    global _window, _qt_app

    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QListWidget, QPushButton, QShortcut, QAbstractItemView
    )
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QKeySequence

    _ = _api._  # Translation function

    _qt_app = QApplication(sys.argv)
    _qt_app.setQuitOnLastWindowClosed(False)

    window = QMainWindow()
    _window = window
    window.setWindowTitle(f"TCE - {_api._config.name} v{_api.version}")
    window.resize(700, 600)

    central = QWidget()
    window.setCentralWidget(central)
    layout = QVBoxLayout(central)
    layout.setSpacing(8)
    layout.setContentsMargins(10, 10, 10, 10)

    # Track items for activation
    apps = []
    games = []
    im_items = []  # list of (display_name, im_type, im_id)

    # --- Applications section ---
    app_listwidget = None
    if _api.get_applications:
        apps = _api.get_applications()
        if apps:
            app_label = QLabel(_("Applications"))
            app_label.setStyleSheet("font-weight: bold; font-size: 13px;")
            layout.addWidget(app_label)

            app_listwidget = QListWidget()
            app_listwidget.setSelectionMode(QAbstractItemView.SingleSelection)
            for app in apps:
                name = app.get('name', app.get('name_en', 'Unknown'))
                app_listwidget.addItem(name)
            layout.addWidget(app_listwidget, stretch=2)

            def on_app_current_changed(current, previous):
                if current is not None:
                    _api.play_focus_sound()

            def on_app_activate(item):
                idx = app_listwidget.row(item)
                if 0 <= idx < len(apps):
                    _api.play_select_sound()
                    _api.open_application(apps[idx])

            app_listwidget.currentItemChanged.connect(on_app_current_changed)
            app_listwidget.itemActivated.connect(on_app_activate)

    # --- Games section ---
    game_listwidget = None
    if _api.get_games:
        games = _api.get_games()
        if games:
            game_label = QLabel(_("Games"))
            game_label.setStyleSheet("font-weight: bold; font-size: 13px;")
            layout.addWidget(game_label)

            game_listwidget = QListWidget()
            game_listwidget.setSelectionMode(QAbstractItemView.SingleSelection)
            for game in games:
                name = game.get('name', 'Unknown')
                platform = game.get('platform', '')
                display = f"{name} ({platform})" if platform else name
                game_listwidget.addItem(display)
            layout.addWidget(game_listwidget, stretch=2)

            def on_game_current_changed(current, previous):
                if current is not None:
                    _api.play_focus_sound()

            def on_game_activate(item):
                idx = game_listwidget.row(item)
                if 0 <= idx < len(games):
                    _api.play_select_sound()
                    _api.open_game(games[idx])

            game_listwidget.currentItemChanged.connect(on_game_current_changed)
            game_listwidget.itemActivated.connect(on_game_activate)

    # --- Titan IM section ---
    im_listwidget = None
    if _api.has_feature('titan_im'):
        im_label = QLabel(_("Titan IM"))
        im_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(im_label)

        im_listwidget = QListWidget()
        im_listwidget.setSelectionMode(QAbstractItemView.SingleSelection)

        # Built-in communicators (same as GUI and IUI)
        if _api.titan_net_client:
            im_items.append((_("Titan-Net (Beta)"), 'titannet', None))
            im_listwidget.addItem(_("Titan-Net (Beta)"))

        im_items.append((_("Telegram"), 'telegram', None))
        im_listwidget.addItem(_("Telegram"))

        im_items.append((_("Facebook Messenger"), 'messenger', None))
        im_listwidget.addItem(_("Facebook Messenger"))

        im_items.append((_("WhatsApp"), 'whatsapp', None))
        im_listwidget.addItem(_("WhatsApp"))

        im_items.append((_("EltenLink"), 'eltenlink', None))
        im_listwidget.addItem(_("EltenLink"))

        # External IM modules
        if _api.im_module_manager:
            for info in _api.im_module_manager.modules:
                name = info['name']
                status = _api.im_module_manager.get_status_text(info['id'])
                display = f"{name} {status}" if status else name
                im_items.append((display, 'im_module', info['id']))
                im_listwidget.addItem(display)

        if im_items:
            layout.addWidget(im_listwidget, stretch=1)

            def on_im_current_changed(current, previous):
                if current is not None:
                    _api.play_focus_sound()

            def on_im_activate(item):
                idx = im_listwidget.row(item)
                if 0 <= idx < len(im_items):
                    _, im_type, im_id = im_items[idx]
                    _api.play_select_sound()
                    if im_type == 'titannet':
                        _api.open_titannet()
                    elif im_type == 'telegram':
                        _api.open_telegram()
                    elif im_type == 'messenger':
                        _api.open_messenger()
                    elif im_type == 'whatsapp':
                        _api.open_whatsapp()
                    elif im_type == 'eltenlink':
                        _api.open_eltenlink()
                    elif im_type == 'im_module' and _api.im_module_manager:
                        _api.im_module_manager.open_module(im_id, None)

            im_listwidget.currentItemChanged.connect(on_im_current_changed)
            im_listwidget.itemActivated.connect(on_im_activate)
        else:
            im_label.hide()

    # --- Statusbar section (built-in items + applets) ---
    statusbar_listwidget = None
    # Number of built-in items (Clock, Battery, Volume, Network)
    builtin_count = 4
    if _api.statusbar_applet_manager:
        sb_label = QLabel(_("Status Bar"))
        sb_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(sb_label)

        statusbar_listwidget = QListWidget()
        statusbar_listwidget.setSelectionMode(QAbstractItemView.SingleSelection)

        # Populate with all items (built-in + applets)
        for text in _api.statusbar_applet_manager.get_statusbar_items():
            statusbar_listwidget.addItem(text)
        layout.addWidget(statusbar_listwidget, stretch=1)

        def on_sb_current_changed(current, previous):
            if current is not None:
                _api.play_statusbar_sound()

        def on_sb_activate(item):
            idx = statusbar_listwidget.row(item)
            # Only applet items (after built-in) are activatable
            applet_idx = idx - builtin_count
            current_applet_names = _api.statusbar_applet_manager.get_applet_names()
            if 0 <= applet_idx < len(current_applet_names):
                _api.play_select_sound()
                _api.statusbar_applet_manager.activate_applet(current_applet_names[applet_idx])

        statusbar_listwidget.currentItemChanged.connect(on_sb_current_changed)
        statusbar_listwidget.itemActivated.connect(on_sb_activate)

        # Timer to update all statusbar items every 2 seconds
        sb_timer = QTimer(window)

        def update_statusbar():
            items = _api.statusbar_applet_manager.get_statusbar_items()
            for i, text in enumerate(items):
                if i < statusbar_listwidget.count():
                    statusbar_listwidget.item(i).setText(text)
                else:
                    statusbar_listwidget.addItem(text)

        sb_timer.timeout.connect(update_statusbar)
        sb_timer.start(2000)

    # --- Bottom buttons ---
    button_layout = QHBoxLayout()
    button_layout.setSpacing(10)

    # Help button
    if _api.show_help:
        help_btn = QPushButton(_("Help"))
        help_btn.setMinimumWidth(100)

        def on_help():
            _api.play_dialog_sound()
            _api.show_help()

        help_btn.clicked.connect(on_help)
        button_layout.addWidget(help_btn)

    # Settings button (always available)
    settings_btn = QPushButton(_("Settings"))
    settings_btn.setMinimumWidth(100)

    def on_settings():
        _api.play_dialog_sound()
        _api.show_settings()

    settings_btn.clicked.connect(on_settings)
    button_layout.addWidget(settings_btn)

    # Exit button
    exit_btn = QPushButton(_("Exit"))
    exit_btn.setMinimumWidth(100)

    def on_exit():
        _api.play_sound('ui/dialogclose.ogg')
        _qt_app.quit()
        _api.force_exit()

    exit_btn.clicked.connect(on_exit)
    button_layout.addWidget(exit_btn)

    layout.addLayout(button_layout)

    # --- Minimize support ---
    def do_minimize():
        window.hide()

    def do_restore():
        window.show()
        window.raise_()
        window.activateWindow()

    _api.register_minimize_handler(do_minimize)
    _api.register_restore_handler(do_restore)

    # Escape key minimizes the launcher
    esc_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), window)
    esc_shortcut.activated.connect(lambda: _api.minimize_launcher())

    # Alt+F4 / window close button closes TCE entirely
    def closeEvent(event):
        event.ignore()
        on_exit()

    window.closeEvent = closeEvent

    # Focus first list
    if app_listwidget and app_listwidget.count() > 0:
        app_listwidget.setFocus()
        app_listwidget.setCurrentRow(0)
    elif game_listwidget and game_listwidget.count() > 0:
        game_listwidget.setFocus()
        game_listwidget.setCurrentRow(0)

    window.show()

    # Start Invisible UI (tilde key toggle) if enabled
    _api.start_invisible_ui()

    _qt_app.exec_()


def shutdown():
    """Cleanup when launcher is stopped."""
    global _window, _qt_app
    try:
        if _api:
            _api.stop_invisible_ui()
    except Exception:
        pass
    try:
        if _qt_app:
            _qt_app.quit()
    except Exception:
        pass
    _window = None
    _qt_app = None
    print("[example_launcher] Shutdown complete")
