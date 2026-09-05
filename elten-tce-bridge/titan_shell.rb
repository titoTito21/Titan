# The Titan shell, from Elten - when Titan is the Windows shell.
#
# With "Replace the desktop, taskbar and Start menu" on, Titan IS the
# desktop: the icons, the taskbar, the notification area and the Start menu
# are its, not Explorer's. So they are reachable here as what they are - a
# tab for the desktop, one for the taskbar's window buttons, one for the
# notification area, one for the Start menu, one for the drives - each read
# from the running Titan, each acting on the real thing.
#
# The whole view is offered only when the shell is actually up (`shell
# status` says so). Offering somebody a desktop that is not theirs, on a
# machine where Explorer still owns the screen, would be a screen full of
# things that do nothing.

require "json"

class TitanShell
  def initialize(bus)
    @bus = bus
  end

  # Whether Titan is the shell right now. Read rather than assumed: it is a
  # setting the user can turn off while this window is open.
  # Asked as DATA, never as words. `shell.status` answers in the user's own
  # language - "Powloka Titana nie jest uruchomiona" - and a check written
  # against the English worked here and answered the exact opposite on a
  # Polish Titan, offering a desktop that was not there.
  def running?
    answer = TitanUI.ask(@bus, "shell", "state", {}, :title => _("The Titan shell"))
    return false if !answer.ok?
    data = JSON.parse(answer.text) rescue nil
    data.is_a?(Hash) && data["running"] == true
  rescue Exception
    false
  end

  def open
    return if !TitanUI.require_tce(@bus)
    tabs = [
      [_("Desktop"), proc { desktop_rows }],
      [_("Taskbar"), proc { window_rows }],
      [_("Notification area"), proc { tray_rows }],
      [_("Start menu"), proc { start_rows }],
      [_("Drives"), proc { drive_rows }],
    ]
    TitanUI::Screen.new(@bus, _("Titan shell"), tabs,
                        :on_open => method(:open_row),
                        :on_menu => method(:row_menu)).open
  end

  # ---------------------------------------------------------------- the rows
  def desktop_rows
    lines("list_desktop", {}) { |name| [name, {"where" => "desktop", "name" => name}] }
  end

  # The taskbar's window buttons, read as records so the state does not have
  # to be parsed out of a translated sentence.
  def window_rows
    answer = TitanUI.ask(@bus, "shell", "windows", {}, :title => _("Reading..."))
    return [[answer.text.to_s, nil]] if !answer.ok?
    data = JSON.parse(answer.text) rescue nil
    (data.is_a?(Hash) ? (data["windows"] || []) : []).map do |window|
      state = []
      state.push(_("active")) if window["active"] == true
      state.push(_("minimised")) if window["minimized"] == true
      label = window["title"].to_s
      label += " (#{state.join(', ')})" if state.size > 0
      [label, {"where" => "taskbar", "title" => window["title"].to_s}]
    end
  rescue Exception => e
    [["#{e.class}: #{e.message}", nil]]
  end

  def tray_rows
    lines("list_tray", {}) { |name| [name, {"where" => "tray", "name" => name}] }
  end

  # Titan's own Start menu, branch for branch: the things it starts are its
  # applications, its games, its Titan IM modules, its macros and its
  # settings, then everything the machine has, then the ways out. Its left
  # column is a tree the arrows walk, so here each branch opens as its own
  # list and Escape steps back - the same movement, in Elten's controls.
  def start_rows
    [[_("Search everything..."), {"where" => "search"}],
     [_("Applications"), {"where" => "branch", "kind" => "app"}],
     [_("Games"), {"where" => "branch", "kind" => "game"}],
     [_("Titan IM"), {"where" => "branch", "kind" => "im_module"}],
     [_("Macros"), {"where" => "macros"}],
     [_("Settings"), {"where" => "settings"}],
     [_("All Programs"), {"where" => "search"}],
     [_("Turn off, restart, log off"), {"where" => "power"}]]
  end

  # One branch of the Start menu: what Titan can start of that kind, opened
  # by pressing it, exactly as pressing it in Titan's own menu does.
  def branch(kind, label)
    rows = proc do
      answer = TitanUI.ask(@bus, "titan", "inventory", {"kind" => kind},
                           :title => label)
      names = []
      if answer.ok?
        data = JSON.parse(answer.text) rescue nil
        group = data.is_a?(Hash) ? (data["kinds"] || []).first : nil
        names = (group["entries"] || []).map(&:to_s) if group.is_a?(Hash)
      end
      names.map { |name| [name, {"where" => "start_titan", "name" => name}] }
    end
    TitanUI::Screen.new(@bus, label, [[label, rows]],
                        :on_open => method(:open_row)).open
  end

  def drive_rows
    lines("list_drives", {}) { |line| [line, {"where" => "drive", "name" => line}] }
  end

  def lines(action, args)
    answer = TitanUI.ask(@bus, "shell", action, args, :title => _("Reading..."))
    return [[answer.text.to_s, nil]] if !answer.ok?
    answer.text.to_s.split("\n").map { |line| line.strip }.reject(&:empty?).map do |line|
      yield(line.sub(/\A\d+\.\s*/, ""))
    end
  end

  # -------------------------------------------------------------- opening one
  def open_row(value, label)
    return if !value.is_a?(Hash)
    case value["where"]
    when "desktop" then run("open_desktop_item", {"name" => value["name"]})
    when "taskbar" then run("activate_window", {"title" => value["title"]})
    when "tray"    then run("activate_tray_icon", {"name" => value["name"]})
    when "search"  then search_start_menu
    when "program" then run("run_program", {"name" => value["name"]})
    when "branch"  then branch(value["kind"].to_s, label)
    when "macros"  then TitanMacros.new(@bus).open
    when "settings" then TitanSettings.new(@bus).open
    when "power"   then power
    when "start_titan"
      # Started through Titan, which is what the Start menu does with its
      # own applications, games and modules.
      answer = TitanUI.perform(@bus, "titan", "launch", {"name" => value["name"]},
                               :title => label)
      TitanUI.tell(answer, label) if answer != nil
    when "drive"   then browse(value["name"].to_s.split(" ").first.to_s)
    end
  end

  def search_start_menu
    query = ask(_("What are you looking for?"))
    return if query == nil
    answer = TitanUI.ask(@bus, "shell", "search_programs", {"query" => query},
                         :title => _("Searching..."))
    return alert(answer.text.to_s) if !answer.ok?
    names = answer.text.to_s.split("\n").map { |line| line.strip.sub(/\A\d+\.\s*/, "") }
    names = names.reject(&:empty?)
    return alert(_("Nothing matched.")) if names.empty?
    @found = names.map { |name| [name, {"where" => "program", "name" => name}] }
    index = selector(names, :header => _("Start"), :cancel_index => -1)
    return if index == nil || index < 0
    run("run_program", {"name" => names[index]})
  end

  # A folder, the way Titan's own file browser shows it, and one level in at
  # a time so a keyboard can follow it.
  def browse(path)
    here = path
    loop do
      answer = TitanUI.ask(@bus, "shell", "list_folder", {"path" => here},
                           :title => here)
      return alert(answer.text.to_s) if !answer.ok?
      entries = answer.text.to_s.split("\n").map { |line| line.strip }.reject(&:empty?)
      options = [_("Open this folder in Titan")] + entries
      index = selector(options, :header => here, :cancel_index => -1)
      return if index == nil || index < 0
      if index == 0
        run("open_explorer", {"path" => here})
        return
      end
      # A row is "name  size  type  date"; what can be walked into is the
      # name, and Titan answers plainly when it is not a folder.
      name = entries[index - 1].to_s.split(/\s{2,}/).first.to_s
      here = here.end_with?("\\") ? "#{here}#{name}" : "#{here}\\#{name}"
    end
  end

  # -------------------------------------------------------------- the menus
  def row_menu(value, label)
    return if !value.is_a?(Hash)
    case value["where"]
    when "desktop" then desktop_menu(value["name"].to_s, label)
    when "taskbar" then taskbar_menu(value["title"].to_s, label)
    else shell_menu
    end
  end

  def desktop_menu(name, label)
    chosen = select_action([["open_desktop_item", _("Open")],
                            ["desktop_item_target", _("What it points at")],
                            ["open_item_location", _("Open the folder it is in")],
                            ["desktop_item_properties", _("Properties")],
                            ["rename_desktop_item", _("Rename")],
                            ["delete_desktop_item", _("Delete")]],
                           :header => label)
    return if chosen == nil
    if chosen == "rename_desktop_item"
      new_name = ask(_("What should it be called?"))
      return if new_name == nil
      return run(chosen, {"name" => name, "new_name" => new_name})
    end
    if chosen == "delete_desktop_item"
      return if !confirm(_("Send %s to the Recycle Bin?") % label)
    end
    run(chosen, {"name" => name})
  end

  def taskbar_menu(title, label)
    chosen = select_action([["activate_window", _("Bring it to the front")],
                            ["minimize_window", _("Minimise")],
                            ["close_window", _("Close")]],
                           :header => label)
    return if chosen == nil
    return if chosen == "close_window" && !confirm(_("Close %s?") % label)
    run(chosen, {"title" => title})
  end

  # The shell itself: what Titan's own taskbar menu offers.
  def shell_menu
    chosen = select_action([["show_desktop", _("Show the desktop")],
                            ["arrange_windows", _("Arrange the windows")],
                            ["open_start_menu", _("Open the Start menu")],
                            ["get_time", _("What is the time")],
                            ["open_explorer", _("Open the file browser")],
                            ["settings", _("Shell settings")],
                            ["addons", _("Shell add-ons")],
                            ["power", _("Turn off, restart, log off")],
                            ["stop", _("Stop the Titan shell")]],
                           :header => _("Titan shell"))
    return if chosen == nil
    case chosen
    when "settings" then shell_settings
    when "addons"   then show("list_addons", {}, _("Shell add-ons"))
    when "power"    then power
    when "stop"
      run("stop", {}) if confirm(_("Give the desktop and taskbar back to Windows?"))
    else run(chosen, {})
    end
  end

  def shell_settings
    answer = TitanUI.ask(@bus, "shell", "list_settings", {}, :title => _("Shell settings"))
    display_text(answer.text.to_s, :header => _("Shell settings"))
    name = ask(_("Which setting? (empty to leave)"))
    return if name == nil
    value = ask(_("What should it be?"))
    return if value == nil
    run("set_setting", {"name" => name, "value" => value})
  end

  # Every one of these is confirmed twice - here, and by Titan itself, which
  # marks them always_confirm. Turning somebody's computer off from a list
  # is not something to get one keypress wrong.
  def power
    answer = TitanUI.ask(@bus, "shell", "power_options", {}, :title => _("Power"))
    options = answer.text.to_s.split("\n").map { |line| line.strip.sub(/\A\d+\.\s*/, "") }
    options = options.reject(&:empty?)
    return alert(answer.text.to_s) if options.empty?
    index = selector(options, :header => _("Power"), :cancel_index => -1)
    return if index == nil || index < 0
    what = options[index].split(/[\s-]/).first.to_s.downcase
    return if !confirm(_("Really: %s?") % options[index])
    run("power", {"action" => what})
  end

  def run(action, args)
    answer = TitanUI.perform(@bus, "shell", action, args, :title => action.to_s)
    TitanUI.tell(answer, action.to_s) if answer != nil
  end

  def show(action, args, header)
    answer = TitanUI.ask(@bus, "shell", action, args, :title => header)
    display_text(answer.text.to_s, :header => header)
  end

  def ask(prompt)
    text = input_text(prompt, :escapable => true)
    text == nil || text.to_s.strip == "" ? nil : text.to_s
  end
end
