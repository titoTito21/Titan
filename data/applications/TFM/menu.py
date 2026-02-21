# TFM/menu.py
import wx
from translation import _

# Define a custom ID for the Rename menu item
ID_RENAME = wx.NewIdRef()

def create_file_menu(parent):
    file_menu = wx.Menu()
    new_file = file_menu.Append(wx.ID_NEW, _("&New file\tCtrl+N"))
    new_folder = file_menu.Append(wx.ID_ANY, _("New folder\tCtrl+Shift+N"))
    file_menu.AppendSeparator()
    settings = file_menu.Append(wx.ID_ANY, _("Settings\tCtrl+S"))
    file_menu.AppendSeparator()
    exit_item = file_menu.Append(wx.ID_EXIT, _("Exit"))

    parent.Bind(wx.EVT_MENU, parent.on_new_file, new_file)
    parent.Bind(wx.EVT_MENU, parent.on_new_folder, new_folder)
    parent.Bind(wx.EVT_MENU, parent.on_settings, settings)
    parent.Bind(wx.EVT_MENU, parent.on_exit, exit_item)

    return file_menu

def create_edit_menu(parent):
    edit_menu = wx.Menu()
    copy = edit_menu.Append(wx.ID_COPY, _("Copy\tCtrl+C"))
    cut = edit_menu.Append(wx.ID_CUT, _("Cut\tCtrl+X"))
    paste = edit_menu.Append(wx.ID_PASTE, _("Paste\tCtrl+V"))
    edit_menu.AppendSeparator()
    select_all = edit_menu.Append(wx.ID_SELECTALL, _("Select all\tCtrl+A"))
    rename = edit_menu.Append(ID_RENAME, _("Rename\tF2"))
    delete = edit_menu.Append(wx.ID_DELETE, _("Delete\tDelete"))

    parent.Bind(wx.EVT_MENU, parent.on_copy, copy)
    parent.Bind(wx.EVT_MENU, parent.on_cut, cut)
    parent.Bind(wx.EVT_MENU, parent.on_paste, paste)
    parent.Bind(wx.EVT_MENU, parent.on_select_all, select_all)
    parent.Bind(wx.EVT_MENU, parent.on_delete, delete)
    parent.Bind(wx.EVT_MENU, parent.on_rename, id=ID_RENAME)

    return edit_menu

def create_view_menu(parent):
    view_menu = wx.Menu()
    sort_menu = wx.Menu()
    sort_name = sort_menu.Append(wx.ID_ANY, _("Name"))
    sort_date = sort_menu.Append(wx.ID_ANY, _("Date modified"))
    sort_type = sort_menu.Append(wx.ID_ANY, _("Type"))

    parent.Bind(wx.EVT_MENU, parent.on_sort_by_name, sort_name)
    parent.Bind(wx.EVT_MENU, parent.on_sort_by_date, sort_date)
    parent.Bind(wx.EVT_MENU, parent.on_sort_by_type, sort_type)

    view_menu.AppendSubMenu(sort_menu, _("Sort by"))

    return view_menu
