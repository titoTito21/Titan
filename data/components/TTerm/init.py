import wx
import os
import subprocess
import platform
import threading
from src.titan_core.sound import play_sound

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

        threading.Thread(target=self.run_command, args=(command,), daemon=True).start()

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

# ===========================================================================
# Titan actions - what Titan, its AI and other add-ons can ask this component
# ===========================================================================
# A terminal is the last resort of every other add-on: something that has no
# API but does have a command line is still reachable if somebody can run the
# command and read what came back. So the useful action is not "open the
# window" - it is "run this and tell me what it said", which needs no window at
# all. Opening the window stays available for the user's own use.

try:
    from src.titan_core.actions import fails, needs
except Exception:                       # Titan not importable - actions unused
    def fails(reason):
        return reason

    def needs(name, prompt, options=None, kind='string', default=''):
        return prompt


def _shell_for(command):
    system = platform.system()
    if system == "Windows":
        return ['cmd.exe', '/C', command]
    if system == "Darwin":
        return ['bash', '-c', command]
    return ['sh', '-c', command]


def action_run_command(command, timeout=30):
    """Run a shell command and return what it printed."""
    command = str(command or '').strip()
    if not command:
        return needs('command', "Which command should be run?")
    try:
        seconds = max(1, min(int(timeout or 30), 300))
    except (TypeError, ValueError):
        seconds = 30
    try:
        result = subprocess.run(_shell_for(command), capture_output=True,
                                text=True, timeout=seconds)
    except subprocess.TimeoutExpired:
        return fails(f"'{command}' was still running after {seconds} seconds "
                     f"and was stopped.")
    except Exception as e:
        return fails(f"Could not run '{command}': {e}")
    output = (result.stdout or '').strip() or (result.stderr or '').strip()
    if len(output) > 6000:
        output = output[:6000].rstrip() + "\n(output truncated)"
    status = ("" if result.returncode == 0
              else f" (exit code {result.returncode})")
    if not output:
        return f"'{command}' finished with nothing to say{status}."
    return f"{command}{status}\n{output}"


def action_open_terminal():
    """Open the terminal window for the user."""
    try:
        show_terminal()
    except Exception as e:
        return fails(f"The terminal could not be opened: {e}")
    return "The terminal is open."


TITAN_ACTIONS = [
    {'name': 'run_command',
     'summary': "Run a command in the system shell and return its output. "
                "This is how anything with a command line but no interface can "
                "still be driven.",
     'params': {'command': {'type': 'string', 'required': True,
                            'description': "The command line to run."},
                'timeout': {'type': 'integer',
                            'description': "Seconds to wait before giving up "
                                           "(default 30, at most 300)."}},
     'risk': 'always_confirm', 'run': action_run_command},
    {'name': 'open_terminal',
     'summary': "Open the Titan terminal window.",
     'risk': 'confirm', 'run': action_open_terminal},
]
