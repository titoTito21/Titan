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

def on_tterm_menu_action(parent_frame):
    show_terminal()

def add_menu(component_manager):
    platform_name = platform.system()
    menu_label = "Terminal"
    if platform_name == "Windows":
        menu_label += " (Windows)"
    elif platform_name == "Darwin":
        menu_label += " (Mac OS)"
    else:
        menu_label += " (Bash)"
    component_manager.register_menu_function(menu_label, on_tterm_menu_action)

def on_open_terminal(event):
    play_sound('ui/terminal.ogg')
    wx.CallAfter(show_terminal)

def show_terminal():
    terminal_frame = TerminalFrame(None)
    terminal_frame.Show()

def initialize(app):
    pass