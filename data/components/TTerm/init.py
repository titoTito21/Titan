import wx
import os
import subprocess
import platform
import threading
from sound import play_sound

class TerminalFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(TerminalFrame, self).__init__(*args, **kwargs)
        self.InitUI()

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.command_input = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.command_input.Bind(wx.EVT_TEXT_ENTER, self.OnEnter)

        self.output_display = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)

        vbox.Add(self.command_input, flag=wx.EXPAND | wx.ALL, border=10)
        vbox.Add(self.output_display, proportion=1, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        panel.SetSizer(vbox)

        self.SetSize((700, 500))
        self.SetTitle("Titan Terminal Emulator (TTerm)")
        self.Centre()

    def OnEnter(self, event):
        command = self.command_input.GetValue()
        self.command_input.SetValue("")

        threading.Thread(target=self.run_command, args=(command,)).start()

    def run_command(self, command):
        if platform.system() == "Windows":
            result = subprocess.run(['cmd.exe', '/C', command], capture_output=True, text=True)
        elif platform.system() == "Darwin":
            result = subprocess.run(['bash', '-c', command], capture_output=True, text=True)
        else:
            result = subprocess.run(['sh', '-c', command], capture_output=True, text=True)

        output = result.stdout if result.stdout else result.stderr
        wx.CallAfter(self.output_display.AppendText, f"{command}\n{output}\n")

def add_menu(menubar):
    system_tools_menu = wx.Menu()
    platform_name = platform.system()
    if platform_name == "Windows":
        terminal_item = system_tools_menu.Append(wx.ID_ANY, "Terminal (Windows)")
    elif platform_name == "Darwin":
        terminal_item = system_tools_menu.Append(wx.ID_ANY, "Terminal (Mac OS)")
    else:
        terminal_item = system_tools_menu.Append(wx.ID_ANY, "Terminal (Bash)")

    menubar.Append(system_tools_menu, "Narzędzia systemowe")
    menubar.Bind(wx.EVT_MENU, on_open_terminal, terminal_item)

def on_open_terminal(event):
    play_sound('terminal.ogg')
    wx.CallAfter(show_terminal)

def show_terminal():
    terminal_frame = TerminalFrame(None)
    terminal_frame.Show()

def initialize(app):
    pass
