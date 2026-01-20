# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('data', 'data'), ('languages', 'languages'), ('sfx', 'sfx'), ('skins', 'skins')]
binaries = []
hiddenimports = ['accessible_output3', 'accessible_output3.outputs', 'accessible_output3.outputs.auto', 'accessible_output3.outputs.sapi5', 'accessible_output3.outputs.nvda', 'accessible_output3.outputs.jaws', 'wx', 'wx.adv', 'wx.html', 'wx.html2', 'wx.lib', 'wx.lib.agw', 'wx.lib.newevent', 'pygame', 'pygame.mixer', 'comtypes', 'comtypes.client', 'comtypes.stream', 'win32com', 'win32com.client', 'pythoncom', 'pywintypes', 'win32api', 'win32con', 'win32gui', 'win32process', 'pywin32_system32', 'pycaw', 'pycaw.pycaw', 'websockets', 'websockets.client', 'websockets.server', 'aiohttp', 'requests', 'asyncio', 'asyncio.windows_events', 'speech_recognition', 'keyboard', 'pywinctl', 'psutil', 'wmi', 'babel', 'babel.numbers', 'babel.dates', 'babel.core', 'gettext', 'configparser', 'json', 'cryptography', 'bcrypt', 'telethon', 'google.generativeai', 'gtts', 'typing', 'platform', 'threading', 'time', 'os', 'sys', 'signal', 'gc', 'warnings', 'argparse', 'random', 'glob', 'src', 'src.ui', 'src.ui.gui', 'src.ui.invisibleui', 'src.ui.menu', 'src.ui.settingsgui', 'src.ui.componentmanagergui', 'src.ui.notificationcenter', 'src.ui.shutdown_question', 'src.ui.help', 'src.ui.classic_start_menu', 'src.settings', 'src.settings.settings', 'src.settings.titan_im_config', 'src.network', 'src.network.titan_net', 'src.network.titan_net_gui', 'src.network.telegram_client', 'src.network.telegram_gui', 'src.network.run_messenger', 'src.titan_core', 'src.titan_core.app_manager', 'src.titan_core.game_manager', 'src.titan_core.component_manager', 'src.titan_core.tce_system', 'src.titan_core.tce_system_net', 'src.titan_core.translation', 'src.titan_core.sound', 'src.titan_core.tsounds', 'src.titan_core.stereo_speech', 'src.system', 'src.system.system_monitor', 'src.system.notifications', 'src.system.updater', 'src.system.lockscreen_monitor_improved', 'src.system.klangomode', 'src.system.com_fix', 'src.system.fix_com_cache', 'src.system.key_blocker', 'src.system.wifi_safe_wrapper', 'src.system.system_tray_list', 'src.controller', 'src.controller.controller_ui', 'src.controller.controller_modes', 'src.controller.controller_vibrations', 'MediaCatalog', 'PyPDF2', 'Settings', 'YoutubeSearch', 'bs4', 'clonegen', 'copy_move', 'database', 'docx', 'elevenlabs', 'enchant', 'feedparser', 'generator', 'gui', 'key_dialog', 'menu', 'menu_bar', 'player', 'pypandoc', 'pyttsx3', 'settings', 'sound', 'support_dialog', 'tfm_settings', 'tplayer', 'translation', 'vlc', 'webbrowser', 'yt_dlp']
tmp_ret = collect_all('accessible_output3')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('babel')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('wx')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('cryptography')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TCE Launcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TCE Launcher',
)
