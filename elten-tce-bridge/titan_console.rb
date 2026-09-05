# Titan's main window, rebuilt in Elten.
#
# It is laid out the way `src/ui/gui.py` lays it out, because it IS that
# window: a tab bar of the views Titan is showing, the list of whichever
# view is current, the status bar underneath, and the Program menu. All four
# are READ from Titan rather than copied here - `titan.views` is Titan's own
# view registry (so a view a component registered is on this tab bar too),
# `titan.status_bar` is what its applets are saying at this moment, and
# `titan.menu` comes from `src/ui/program_menu.py`, the module that exists
# precisely so every face of Titan offers the same menu.
#
# The interaction is Titan's: Left and Right move along the tab bar, Up and
# Down through the list, Enter opens, F5 reads it again, the context-menu
# key gives a row its own actions, Escape leaves. In Elten's own controls,
# so a screen reader announces all of it without a word being spoken here.

require "json"

class TitanConsole
  # Titan's three built-in views, and what each one lists. A view a
  # component registered is not in here and does not need to be: it falls
  # through to that component's own actions, which is what it has.
  VIEW_CONTENTS = {
    "apps" => "app",
    "games" => "game",
  }.freeze

  def initialize(bus)
    @bus = bus
    @inventory = {}
    @addons = nil
    @views = nil
    @tab = 0
    @rows = []
    @running = false
  end

  def open
    return if !TitanUI.require_tce(@bus)
    @views = read_views + [{"id" => "widgets", "short_name" => _("Widgets")},
                           {"id" => "components", "short_name" => _("Components")}]
    # With Titan replacing the desktop, taskbar and Start menu, that desktop
    # is not one more add-on - it is what the user is sitting at, so it is a
    # view of its own here too.
    @shell ||= TitanShell.new(@bus)
    @views.push({"id" => "shell", "short_name" => _("System desktop")}) if @shell.running?
    @list = ListBox.new([], :header => _("Titan"))
    @status = ListBox.new([], :header => _("Status bar"))
    @menu = Button.new(_("Menu"))
    @more = Button.new(_("Everything else"))
    @back = Button.new(_("Close"))
    @form = Form.new([@list, @status, @menu, @more, @back])
    @form.cancel_button = @back

    @list.on(:expand) { cycle(1) }
    @list.on(:collapse) { cycle(-1) }
    @list.on(:select) { open_row }
    @status.on(:select) { activate_status_row }
    @menu.on(:press) { program_menu }
    @more.on(:press) { TitanAreas.new(@bus).open }
    @back.on(:press) { @running = false }

    fill
    fill_status
    pump
  end

  # ------------------------------------------------------------- the tab bar
  def read_views
    answer = TitanUI.ask(@bus, "titan", "views", {}, :title => _("Reading Titan..."))
    if answer.ok?
      data = JSON.parse(answer.text) rescue nil
      views = data.is_a?(Hash) ? (data["views"] || []) : []
      return views if views.size > 0
    end
    # Titan is running but its window is not up (started minimised, or into
    # a launcher). The three built-in views are still what it has.
    [{"id" => "apps", "short_name" => _("Applications")},
     {"id" => "games", "short_name" => _("Games")},
     {"id" => "network", "short_name" => _("Titan IM")}]
  end

  def view
    @views[@tab] || {}
  end

  def header
    "#{view['short_name']} (#{@rows.size})"
  end

  def cycle(direction)
    return if @views.size < 2
    @tab = (@tab + direction) % @views.size
    fill
    speak(header)
  end

  # One of Titan's lists on its own - what Elten's main menu opens when
  # somebody chooses "TCE applications" or "TCE games". The same rows and
  # the same Enter as the tab inside the main window; there is simply
  # nothing else on the screen.
  def open_view(kind, label)
    return if !TitanUI.require_tce(@bus)
    rows = proc do
      inventory(kind).map { |name| [name, {"do" => "launch", "name" => name}] }
    end
    TitanUI::Screen.new(@bus, label, [[label, rows]],
                        :on_open => proc { |value, row_label|
                          launch(value["name"].to_s) if value.is_a?(Hash)
                        },
                        :on_menu => proc { |value, row_label|
                          actions_for([row_label, value]) if value.is_a?(Hash)
                        }).open
  end

  # ---------------------------------------------------------------- the list
  def fill
    id = view["id"].to_s
    kind = VIEW_CONTENTS[id]
    @rows = if kind != nil
              inventory(kind).map { |name| [name, {"do" => "launch", "name" => name}] }
            elsif id == "network"
              # Titan IM is the SERVICES, as Titan's own view lists them -
              # Telegram, Messenger, WhatsApp, Titan-Net, EltenLink - and
              # pressing one opens its conversations here rather than
              # opening a window in Titan.
              TitanIM.new(@bus).services.map do |label, value|
                [label, value.is_a?(Hash) && value["open"] == "service" ?
                   {"do" => "im_service"}.merge(value) : value]
              end
            elsif id == "shell"
              @shell ||= TitanShell.new(@bus)
              [[_("Desktop, taskbar and Start menu"), {"do" => "shell"}]] +
                @shell.start_rows.map { |label, value| [label, {"do" => "shell_start"}.merge(value)] }
            elsif id == "widgets"
              widget_rows
            elsif id == "components"
              component_rows
            else
              component_view_rows(id)
            end
    @list.options = @rows.map { |row| row[0].to_s }
    @list.header = header
    @list.index = 0 if @list.index.to_i >= @rows.size
  end

  # A view a component put on Titan's tab bar - Cling, the macros, the
  # Elten applications. It shows what that component HAS, never what it can
  # be told to do: somebody opening Cling wants their Klango applications,
  # and "list applications, run, details, scores" is a list written for a
  # programmer. The ones with a screen of their own open it; anything else
  # is listed through whatever the component calls its listing, and its
  # actions are one key away on the row.
  SCREENS = {"cling" => :cling, "macros" => :macros,
             "titan_access" => :reader}.freeze
  LISTINGS = %w[list_applications list_macros list_notes list_reminders
                list_downloads list_voices list_modes].freeze

  def component_view_rows(id)
    known = SCREENS[id.to_s.downcase]
    return [[_("Open %s") % id, {"do" => "screen", "screen" => known.to_s}]] if known

    addon = addons.find { |candidate| candidate["id"].to_s.casecmp(id) == 0 }
    return [] if addon == nil
    listing = (addon["actions"] || []).find { |name| LISTINGS.include?(name.to_s) }
    listing ||= (addon["actions"] || []).find { |name| name.to_s.start_with?("list_") }
    if listing == nil
      # Nothing it can be asked to list: offer the component itself rather
      # than a page of function names.
      return [[addon["label"].to_s, {"do" => "addon", "addon" => addon["id"].to_s}]]
    end
    answer = TitanUI.ask(@bus, addon["id"].to_s, listing.to_s, {},
                         :title => addon["label"].to_s)
    return [[answer.text.to_s, nil]] if !answer.ok?
    lines = answer.text.to_s.split("\n").map { |line| line.strip }.reject(&:empty?)
    return [[_("Nothing here yet."), nil]] if lines.empty?
    lines.map do |line|
      [line.sub(/\A\d+\.\s*/, ""),
       {"do" => "item", "addon" => addon["id"].to_s, "text" => line}]
    end
  end

  # Titan's own non-visual interface has these two categories and its tab
  # bar does not, so they are added to the tab bar here: a widget is
  # something to press, and a component's menu entry is what that component
  # puts in Titan's Components menu.
  def widget_rows
    TitanWidgets.new(@bus).rows.map do |label, value|
      [label, value.nil? ? nil : {"do" => "widget"}.merge(value)]
    end
  end

  def component_rows
    answer = TitanUI.ask(@bus, "titan", "components", {}, :title => _("Reading Titan..."))
    return [[answer.text.to_s, nil]] if !answer.ok?
    data = JSON.parse(answer.text) rescue nil
    return [] if !data.is_a?(Hash)
    (data["menu_actions"] || []).map do |name|
      [name.to_s, {"do" => "component_action", "name" => name.to_s}]
    end
  end

  def inventory(kind)
    return @inventory[kind] if @inventory.key?(kind)
    answer = TitanUI.ask(@bus, "titan", "inventory", {"kind" => kind},
                         :title => _("Reading Titan..."))
    names = []
    if answer.ok?
      data = JSON.parse(answer.text) rescue nil
      group = data.is_a?(Hash) ? (data["kinds"] || []).first : nil
      names = (group["entries"] || []).map(&:to_s) if group.is_a?(Hash)
    end
    @inventory[kind] = names
    names
  end

  def addons
    @addons = TitanUI.ask_list(@bus) if @addons == nil
    @addons || []
  end

  def open_row
    row = current
    return if row == nil
    value = row[1]
    # A row that is a message rather than a thing - "TCE is not running",
    # the reason a list could not be read - carries no value and does
    # nothing when it is pressed.
    return if !value.is_a?(Hash)
    case value["do"]
    when "launch"    then launch(value["name"].to_s)
    when "titan_im"  then TitanIM.new(@bus).open
    when "screen"
      case value["screen"]
      when "cling"  then TitanCling.new(@bus).open
      when "macros" then TitanMacros.new(@bus).open
      when "reader" then TitanAreas.new(@bus).reader_screen
      end
    when "addon"     then TitanActions.new(@bus).open(value["addon"].to_s, row[0].to_s)
    when "item"
      # A row from a component's own listing: read it in full, and its
      # actions are on the context-menu key.
      display_text(value["text"].to_s, :header => row[0].to_s)
    when "shell"     then @shell.open
    when "shell_start" then @shell.open_row(value, row[0].to_s)
    when "im_service"
      TitanIM.new(@bus).open_service(value["service"].to_s, value["kind"].to_s, row[0].to_s)
    when "module"    then launch(value["name"].to_s)
    when "widget"    then TitanWidgets.new(@bus).use(value, row[0].to_s)
    when "component_action"
      answer = TitanUI.perform(@bus, "titan", "run_component_action",
                               {"action" => value["name"]}, :title => row[0].to_s)
      TitanUI.tell(answer, row[0].to_s) if answer != nil
    when "action"
      answer = TitanUI.perform(@bus, value["addon"].to_s, value["action"].to_s,
                               {}, :title => row[0].to_s)
      TitanUI.tell(answer, row[0].to_s) if answer != nil
    end
    fill
  end

  def launch(name)
    answer = TitanUI.perform(@bus, "titan", "launch", {"name" => name},
                             :title => _("Starting %s...") % name)
    return if answer == nil
    alert(answer.text.to_s == "" ? _("Started.") : answer.text.to_s)
  end

  def current
    index = @list.index.to_i
    return nil if index < 0 || index >= @rows.size
    @rows[index]
  end

  # ---------------------------------------------------------- the status bar
  def fill_status
    answer = TitanUI.ask(@bus, "titan", "status_bar", {},
                         :title => _("Reading the status bar..."))
    @status_rows = []
    if answer.ok?
      data = JSON.parse(answer.text) rescue nil
      @status_rows = data.is_a?(Hash) ? (data["items"] || []) : []
    end
    @status.options = @status_rows.map { |item| item["text"].to_s }
    @status.header = _("Status bar")
  end

  # A statusbar applet does something when it is pressed in Titan; the
  # built-in slots (clock, battery, volume, network) are readings and do
  # nothing, which is also what they do in Titan.
  def activate_status_row
    index = @status.index.to_i
    item = (@status_rows || [])[index]
    return if item == nil
    key = item["key"].to_s
    return alert(item["text"].to_s) if !key.start_with?("applet:")
    name = key.sub("applet:", "")
    addon = addons.find do |candidate|
      candidate["kind"].to_s == "statusbar_applet" &&
        (candidate["id"].to_s.casecmp(name) == 0 || candidate["label"].to_s.casecmp(name) == 0)
    end
    return alert(item["text"].to_s) if addon == nil
    answer = TitanUI.perform(@bus, addon["id"].to_s, "activate", {},
                             :title => item["text"].to_s)
    TitanUI.tell(answer, item["text"].to_s) if answer != nil
    fill_status
  end

  # ----------------------------------------------------------- the menu bar
  def program_menu
    answer = TitanUI.ask(@bus, "titan", "menu", {}, :title => _("Menu"))
    return alert(answer.text.to_s) if !answer.ok?
    data = JSON.parse(answer.text) rescue nil
    groups = data.is_a?(Hash) ? (data["groups"] || []) : []
    return alert(_("Titan's menu is empty.")) if groups.empty?
    entries = []
    groups.each do |group|
      (group["entries"] || []).each do |entry|
        entries.push([entry["id"].to_s,
                      "#{group['label']}: #{entry['label']}"])
      end
    end
    # The entries every face of Titan has of its own - Titan's menu module
    # returns the ones that are shared, and these are the rest of the
    # Program menu: the settings, the help, and putting Titan away or
    # bringing it back.
    entries.push(["__settings__", _("Program: Settings")])
    entries.push(["__components__", _("Program: Component Manager")])
    entries.push(["__help__", _("Program: Help")])
    entries.push(["__minimize__", _("Program: Minimize")])
    entries.push(["__restore__", _("Program: Bring Titan back")])
    chosen = select_action(entries, :header => _("Titan menu"))
    return if chosen == nil
    case chosen
    when "__settings__"
      TitanSettings.new(@bus).open
      return
    when "__components__"
      TitanComponents.new(@bus).open
      return
    when "__help__"
      answer = TitanUI.perform(@bus, "titan", "open_help", {}, :title => _("Help"))
      alert(answer.text.to_s) if answer != nil
      return
    when "__minimize__", "__restore__"
      what = chosen == "__minimize__" ? "minimize" : "restore"
      answer = TitanUI.perform(@bus, "titan", "window", {"action" => what},
                               :title => _("Titan"))
      alert(answer.text.to_s) if answer != nil
      return
    end
    answer = TitanUI.perform(@bus, "titan", "menu_run", {"entry" => chosen},
                             :title => _("Opening..."))
    alert(answer.text.to_s) if answer != nil
  end

  # --------------------------------------------------------------- the loop
  def pump
    @running = true
    @form.focus
    while @running
      loop_update
      @form.update
      if key_pressed?(TitanUI::KEY_REFRESH)
        @inventory = {}
        @addons = nil
        fill
        fill_status
        speak(_("Refreshed. %s") % header)
      end
      if key_pressed?(:key_context_menu)
        row = current
        actions_for(row) if row != nil
      end
    end
  end

  # Everything else this row can do - out of the way of somebody who came
  # here for their applications, one key away for somebody who wants it.
  def actions_for(row)
    value = row[1]
    name = (value["name"] || value["addon"]).to_s
    addon = addons.find do |candidate|
      candidate["id"].to_s.casecmp(name) == 0 || candidate["label"].to_s.casecmp(name) == 0
    end
    return alert(_("%s offers nothing else here.") % row[0]) if addon == nil
    TitanActions.new(@bus).open(addon["id"].to_s, row[0].to_s)
  end
end
