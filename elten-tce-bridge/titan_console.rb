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
    @api = TitanAPI.new(bus)
    @inventory = {}
    @addons = nil
    @views = nil
    @tab = 0
    @rows = []
    @running = false
  end

  def open
    return if !TitanUI.require_tce(@bus)
    # The screen opening, not the keyboard arriving on the list - that one
    # is `applist`, and the list itself plays it the moment it is given the
    # keyboard. Playing it here as well was the same arrival twice.
    TitanSounds.event(:open)
    @views = read_views + [{"id" => "widgets", "short_name" => _("Widgets")},
                           {"id" => "components", "short_name" => _("Components")}]
    # With Titan replacing the desktop, taskbar and Start menu, that desktop
    # is not one more add-on - it is what the user is sitting at, so it is a
    # view of its own here too.
    @shell ||= TitanShell.new(@bus)
    @views.push({"id" => "shell", "short_name" => _("System desktop")}) if @shell.running?
    # **`applist` for the list and `statusbar` for the status bar.** Those
    # are the two sounds TCE plays for exactly these two arrivals in its own
    # main window, and this IS that window.
    @list = TitanSounds.cued(ListBox.new([], :header => _("Titan")))
    @status = TitanSounds.cued(ListBox.new([], :header => _("Status bar")),
                               TitanSounds::STATUS)
    @menu = Button.new(_("Menu"))
    @assistant = Button.new(_("AI Assistant"))
    @more = Button.new(_("Everything else"))
    @back = Button.new(_("Close"))
    @form = Form.new([@list, @status, @menu, @assistant, @more, @back])
    @form.cancel_button = @back

    @list.on(:expand) { cycle(1) }
    @list.on(:collapse) { cycle(-1) }
    @list.on(:select) { open_row }
    @status.on(:select) { activate_status_row }
    @menu.on(:press) { program_menu }
    # Titan's own AI assistant, opened as a conversation here rather than
    # as a window over there - and it is the SAME conversation.
    @assistant.on(:press) { TitanAI.new(@bus).chat }
    @more.on(:press) { TitanAreas.new(@bus).open }
    @back.on(:press) { @running = false }

    fill
    fill_status
    pump
    TitanSounds.event(:close)
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

  # Titan's own labels arrive in TITAN's language. The view ids are stable,
  # so the ones this add-on knows are named in Elten's language; a view a
  # component registered keeps Titan's wording, which is the only wording
  # there is for it.
  VIEW_NAMES = {
    "apps" => "Applications", "games" => "Games", "network" => "Titan IM",
    "widgets" => "Widgets", "components" => "Components",
    "shell" => "System desktop",
  }.freeze

  def view
    @views[@tab] || {}
  end

  def view_name(entry)
    known = VIEW_NAMES[entry["id"].to_s]
    known ? _(known) : entry["short_name"].to_s
  end

  def header
    "#{view_name(view)} (#{@rows.size})"
  end

  def cycle(direction)
    return if @views.size < 2
    @tab = (@tab + direction) % @views.size
    fill
    # The same sound TCE plays when its own tab bar moves.
    TitanSounds.event(:switch)
    speak(header)
  end

  # One of Titan's lists on its own - what Elten's main menu opens when
  # somebody chooses "TCE applications" or "TCE games". The same rows and
  # the same Enter as the tab inside the main window; there is simply
  # nothing else on the screen.
  def open_view(kind, label)
    return if !TitanUI.require_tce(@bus)
    rows = proc do
      inventory(kind).map { |name| [name, {"do" => "launch", "name" => name,
                                          "kind" => kind}] }
    end
    TitanUI::Screen.new(@bus, label, [[label, rows]],
                        :on_open => proc { |value, row_label|
                          launch(value["name"].to_s, value["kind"]) if value.is_a?(Hash)
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
              inventory(kind).map { |name| [name, {"do" => "launch", "name" => name,
                                                 "kind" => kind}] }
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

  # Titan's own lists, from Titan's own managers. The action path below is
  # kept for a Titan that has not been restarted since this add-on was
  # installed - it answers with folder names, which is why the typed one
  # exists.
  def inventory(kind)
    return @inventory[kind] if @inventory.key?(kind)
    if @api.available?
      call, key = case kind
                  when "app"       then ["apps.list", "applications"]
                  when "game"      then ["games.list", "games"]
                  when "im_module" then ["im.modules", "modules"]
                  end
      if call
        data = @api.data(call, {"language" => @api.language},
                         :title => _("Reading Titan..."))
        entries = data.is_a?(Hash) ? data[key] : nil
        if entries.is_a?(Array)
          return @inventory[kind] = entries.map { |entry| entry["name"].to_s }
        end
      end
    end
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
    when "launch"    then launch(value["name"].to_s, value["kind"])
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
    when "module"    then launch(value["name"].to_s, "im_module")
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

  # Opened by the name the list gave, through the manager that owns it -
  # not by matching a name against a page of text.
  def launch(name, kind = nil)
    return if TitanPrefs.confirm_launch? && !confirm(_("Start %s?") % name)
    if @api.available?
      call = {"app" => "apps.open", "game" => "games.open",
              "im_module" => "im.open"}[kind.to_s]
      call ||= "apps.open"
      answer = @api.call(call, {"name" => name},
                         :title => _("Starting %s...") % name)
      return alert(_("Started %s.") % answer["opened"].to_s) if answer.ok?
      # A name this manager does not have is worth trying elsewhere before
      # giving up: the tab knows what kind it is, but a row may come from a
      # menu that does not.
      if kind == nil
        ["games.open", "im.open"].each do |other|
          second = @api.call(other, {"name" => name})
          return alert(_("Started %s.") % second["opened"].to_s) if second.ok?
        end
      end
      return alert(answer.error.to_s)
    end
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
    # Titan's status bar is not only a reading: pressing the volume opens
    # the volume, pressing the network opens the network. The rows that are
    # readings and nothing else - the clock, the battery - say themselves.
    case key
    when "volume"  then return TitanSystem.new(@bus).sound
    when "network" then return TitanSystem.new(@bus).network
    end
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
  # **The same menu as every other face of Titan.**
  # `src/ui/program_menu.py` is the module Titan's graphical window, its
  # Invisible UI and Klango mode all build their menu from, and all three
  # present it as GROUPS you enter - Program, AI, Programmer - because
  # sixteen entries in one list is a longer menu rather than the same one.
  # This flattened them into "Program: Settings", "AI: AI Agent",
  # "Programmer: ..." in a single list, which is neither Titan's menu nor a
  # menu: it was the group name repeated down the screen with the entries
  # interleaved. So the group is chosen first and its entries second, and
  # Escape at the second level comes back to the first, exactly as leaving
  # a subcategory does in the Invisible UI.
  def program_menu
    answer = TitanUI.ask(@bus, "titan", "menu", {}, :title => _("Menu"))
    return alert(answer.text.to_s) if !answer.ok?
    data = JSON.parse(answer.text) rescue nil
    groups = menu_groups(data.is_a?(Hash) ? (data["groups"] || []) : [])
    return alert(_("Titan's menu is empty.")) if groups.empty?
    loop do
      chosen_group = select_action(groups.map { |group| [group[0], group[1]] },
                                   :header => _("Titan menu"))
      return if chosen_group == nil
      group = groups.find { |entry| entry[0] == chosen_group }
      next if group == nil
      TitanSounds.event(:menu)
      chosen = select_action(group[2].map { |entry| [entry[0], entry[1]] },
                             :header => group[1])
      # Escape inside a group is one level back, not out of the menu - the
      # same as Escape anywhere else in this add-on.
      next if chosen == nil
      return run_menu_entry(chosen)
    end
  end

  # Titan's own ids for its menu groups and the entries this add-on knows,
  # so they are said in ELTEN's language. Titan translated them into its
  # own, and the ids are what is stable.
  GROUP_NAMES = {"program" => "Program", "ai" => "AI",
                 "programmer" => "Programmer"}.freeze
  ENTRY_NAMES = {"install_package" => "Install data package",
                 "ai_agent" => "AI Agent", "ai_assistant" => "AI Assistant",
                 "ai_assistant_live" => "AI Assistant (live)",
                 "ai_ocr" => "AI OCR", "ai_projects" => "Projects"}.freeze

  # [[id, label, [[entry id, entry label], ...]], ...]
  def menu_groups(groups)
    out = []
    groups.each do |group|
      id = group["id"].to_s
      label = GROUP_NAMES[id]
      label = label ? _(label) : group["label"].to_s
      entries = (group["entries"] || []).map do |entry|
        name = ENTRY_NAMES[entry["id"].to_s]
        [entry["id"].to_s, name ? _(name) : entry["label"].to_s]
      end
      out.push([id, label, entries])
    end
    program = out.find { |group| group[0] == "program" }
    if program == nil
      program = ["program", _("Program"), []]
      out.unshift(program)
    end
    # The rest of the Program menu: what Titan's menu module hands over is
    # only what every face SHARES, and each face adds its own settings,
    # component manager and help. So does this one.
    program[2].push(["__settings__", _("Settings")])
    program[2].push(["__components__", _("Component Manager")])
    program[2].push(["__help__", _("Help")])
    # **One entry, not two.** Which of them applies is a question about
    # where Titan is right now - hidden with a tray icon and the Invisible
    # UI answering the keyboard, or in front of the user - and offering
    # both means offering one that does nothing.
    state = @api.data("window.state", {}) || {}
    if state["has_window"] == true
      program[2].push(state["away"] == true ?
                        ["__restore__", _("Bring Titan back")] :
                        ["__minimize__", _("Minimize")])
    end
    out
  end

  def run_menu_entry(chosen)
    case chosen
    when "__settings__"
      return TitanSettings.new(@bus).open
    when "__components__"
      return TitanComponents.new(@bus).open
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
