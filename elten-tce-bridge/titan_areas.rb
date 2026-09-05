# The rest of Titan: everything its window does not put on the tab bar.
#
# Four of these are screens in their own right, because they are things
# people do rather than functions they call - the computer's own settings,
# the open windows, the media library, and which voice Titan speaks with.
# Everything else opens as what it is: that add-on's own actions, with its
# summaries and its parameters asked for properly. That is deliberate. A
# screen invented for an add-on nobody has would be a worse answer than the
# add-on's own list, and this way NOTHING Titan can do is unreachable from
# Elten - including an add-on installed after this was written.

require "json"

class TitanAreas
  def initialize(bus)
    @bus = bus
    @addons = nil
  end

  def open
    return if !TitanUI.require_tce(@bus)
    @shell_running = TitanShell.new(@bus).running?
    # The AI is offered only when Titan really has it: a screen whose every
    # entry answers "AI features are off" is worse than no screen.
    @ai_available = TitanAI.new(@bus).available?
    loop do
      chosen = select_action(areas, :header => _("Titan"))
      return if chosen == nil
      case chosen
      when "system"   then system_screen
      when "windows"  then windows_screen
      when "media"    then media_screen
      when "voices"   then voices_screen
      when "addons"   then addons_screen
      when "shell_view" then TitanShell.new(@bus).open
      when "macros_view" then TitanMacros.new(@bus).open
      when "cling_view"  then TitanCling.new(@bus).open
      when "ai_view"     then TitanAI.new(@bus).open
      when "components_view" then TitanComponents.new(@bus).open
      when "widgets"     then TitanWidgets.new(@bus).open
      when "gamepad_view"  then TitanTools.new(@bus).gamepad
      when "clock_view"    then TitanTools.new(@bus).clock
      when "terminal_view" then TitanTools.new(@bus).terminal
      when "article_view"  then TitanTools.new(@bus).article
      when "files_view"    then TitanTools.new(@bus).files
      when "browser_view"  then TitanTools.new(@bus).browser
      when "buffers"     then buffers_screen
      when "reader"      then reader_screen
      else generic(chosen)
      end
    end
  end

  def areas
    list = [["system", _("The computer (sound, screen, power, network)")],
            ["windows", _("Open windows and the desktop")],
            ["media", _("Media library and radio")],
            ["voices", _("Voices and speech engines")]]
    # These are offered only when Titan really has them, so the menu never
    # promises something that answers "there is no such add-on".
    # These four have screens of their own, because they are things people
    # DO - writing a macro, playing a Klango application, asking the AI -
    # rather than functions they call.
    list.push(["macros_view", _("Macros")]) if addon("macros") != nil
    list.push(["cling_view", _("Cling (Klango applications)")]) if addon("cling") != nil
    list.push(["ai_view", _("Titan AI")]) if @ai_available
    list.push(["widgets", _("Widgets")])
    list.push(["components_view", _("Component Manager")])
    list.push(["buffers", _("Messages and notifications")])
    list.push(["reader", _("Screen reader")]) if addon("titan_access") != nil
    # Each of these is a screen of its own: a gamepad mode is something to
    # choose, a terminal is a line to type, an article is a page to read.
    # The generic list of an add-on's functions is still there, one key
    # away on a row and under "Everything installed", which is where a list
    # of functions belongs.
    {"gamepad" => ["gamepad_view", _("Gamepad modes")],
     "zegarynka" => ["clock_view", _("The talking clock")],
     "tterm" => ["terminal_view", _("Terminal")],
     "tarticle" => ["article_view", _("Read a page")],
     "desktop" => ["files_view", _("Files and programs")],
     "web" => ["browser_view", _("The browser")],
     "im" => ["im", _("WhatsApp and Messenger")],
     }.each do |id, entry|
      list.push([entry[0], entry[1]]) if addon(id) != nil
    end
    # With Titan replacing the desktop, taskbar and Start menu, the shell is
    # not one more add-on with actions - it is the desktop the user is
    # sitting at, so it gets a view of its own. With the shell off, those
    # same actions still read Windows, and they are offered as actions.
    if addon("shell") != nil
      list.push(@shell_running ? ["shell_view", _("The Titan desktop, taskbar and Start menu")]
                               : ["shell", _("Windows, the desktop and the Start menu")])
    end
    list.push(["addons", _("Everything installed")])
    list
  end

  def addons
    @addons = TitanUI.ask_list(@bus) if @addons == nil
    @addons || []
  end

  def addon(id)
    addons.find { |candidate| candidate["id"].to_s == id }
  end

  def generic(id)
    found = addon(id)
    return alert(_("Titan has no '%s'.") % id) if found == nil
    TitanActions.new(@bus).open(id, found["label"].to_s)
  end

  # ------------------------------------------------- messages and notifications
  # The Buffer System is one of the things a Titan user reaches for
  # constantly and that nothing else exposes: every message, notification
  # and call that arrived while its window was closed is in there. Its
  # categories are the tab bar, its buffers are the rows, and opening one
  # shows what is in it.
  def buffers_screen
    tabs = [[_("Messages"), proc { buffer_rows }],
            [_("Notifications"), proc { notification_rows }],
            [_("New on Titan-Net"), proc { news_rows }]]
    TitanUI::Screen.new(@bus, _("Messages and notifications"), tabs,
                        :on_open => method(:buffers_open)).open
  end

  def buffer_rows
    answer = TitanUI.ask(@bus, "titan", "buffers", {}, :title => _("Reading..."))
    return [[answer.text.to_s, nil]] if !answer.ok?
    data = JSON.parse(answer.text) rescue nil
    rows = []
    (data.is_a?(Hash) ? (data["categories"] || []) : []).each do |category|
      buffers = category["buffers"] || []
      if buffers.empty?
        rows.push(["#{category['name']} (#{_('empty')})", nil])
        next
      end
      buffers.each do |buffer|
        rows.push(["#{category['name']}: #{buffer['name']} (#{buffer['count']})",
                   {"do" => "buffer", "category" => category["id"].to_s,
                    "buffer" => buffer["id"].to_s}])
      end
    end
    rows
  end

  def notification_rows
    answer = TitanUI.ask(@bus, "titan", "notifications", {}, :title => _("Reading..."))
    return [[answer.text.to_s, nil]] if !answer.ok?
    data = JSON.parse(answer.text) rescue nil
    items = data.is_a?(Hash) ? (data["notifications"] || []) : []
    rows = items.map do |item|
      text = item.is_a?(Hash) ?
        "#{item['appname']}: #{item['content']} (#{item['date']} #{item['time']})" :
        item.to_s
      [text, nil]
    end
    rows.push([_("Empty the notification centre"), {"do" => "clear"}]) if rows.size > 0
    rows.empty? ? [[_("Nothing here yet."), nil]] : rows
  end

  # What Titan-Net says is waiting: unread messages, unread topics, new
  # applications. The same numbers the add-on watches in the background, so
  # what was announced can be looked at afterwards.
  def news_rows
    answer = TitanUI.ask(@bus, "titannet", "news", {}, :title => _("Reading..."))
    return [[answer.text.to_s, nil]] if !answer.ok?
    counts = JSON.parse(answer.text) rescue nil
    return [[_("Nothing new."), nil]] if !counts.is_a?(Hash)
    rows = []
    rows.push([_("%d unread messages") % counts["unread_messages"].to_i,
               {"open" => "private"}]) if counts["unread_messages"].to_i > 0
    rows.push([_("%d unread letters") % counts["unread_mail"].to_i,
               {"open" => "mail"}]) if counts["unread_mail"].to_i > 0
    rows.push([_("%d unread topics") % counts["unread_forum_topics"].to_i,
               {"open" => "forum"}]) if counts["unread_forum_topics"].to_i > 0
    rows.push([_("%d new applications") % counts["new_apps"].to_i, nil]) if counts["new_apps"].to_i > 0
    rows.push([_("%d updates") % counts["app_updates"].to_i, nil]) if counts["app_updates"].to_i > 0
    rows.empty? ? [[_("Nothing new."), nil]] : rows
  end

  def buffers_open(value, label)
    # A row about Titan-Net opens Titan-Net where the thing actually is.
    if value.is_a?(Hash) && value["open"] != nil
      client = TitanNetClient.new(@bus)
      case value["open"]
      when "private" then return client.online
      when "mail"    then return client.mail
      when "forum"   then return client.forum
      end
    end
    return if !value.is_a?(Hash)
    case value["do"]
    when "buffer"
      answer = TitanUI.ask(@bus, "titan", "buffer",
                           {"category" => value["category"], "buffer" => value["buffer"]},
                           :title => label)
      return alert(answer.text.to_s) if !answer.ok?
      data = JSON.parse(answer.text) rescue nil
      elements = data.is_a?(Hash) ? (data["elements"] || []) : []
      return alert(_("Nothing here yet.")) if elements.empty?
      text = elements.map do |element|
        who = element["author"].to_s
        who == "" ? element["text"].to_s : "#{who}: #{element['text']}"
      end.join("\n")
      display_text(text, :header => label)
    when "clear"
      return if !confirm(_("Empty the notification centre?"))
      answer = TitanUI.perform(@bus, "titan", "clear_notifications", {},
                               :title => label)
      TitanUI.tell(answer, label) if answer != nil
    end
  end

  # ------------------------------------------------------------ the reader
  # Titan Access is the one part of Titan that can say what is on the screen
  # of a program that is not Titan, so this is what it is for: reading the
  # window in front, and the reader's own modes.
  def reader_screen
    loop do
      chosen = pick(_("Screen reader"),
                    [["read_screen", _("Read the window in front")],
                     ["read_focused", _("Read what has the keyboard")],
                     ["window_title", _("What window is in front")],
                     ["say_all", _("Read it all")],
                     ["stop_speech", _("Stop reading")],
                     ["scan_mode", _("Scan mode on or off")],
                     ["status", _("Is the reader running")]])
      return if chosen == nil
      case chosen
      when "read_screen", "read_focused", "window_title", "status"
        show("titan_access", chosen, {}, _("Screen reader"))
      else
        run("titan_access", chosen, {})
      end
    end
  end

  # ------------------------------------------------------------- the computer
  # Volume, brightness, the playback device, the power plan, Wi-Fi: panels
  # of their own, in `titan_system.rb`. A value one changes is moved with
  # the arrows and said at once; a choice is a list with the current one
  # marked. Asking "volume, 0 to 100?" made somebody guess where they were
  # and then type a number.
  def system_screen
    TitanSystem.new(@bus).open
  end

  # --------------------------------------------------------------- the windows
  def windows_screen
    tabs = [[_("Windows"), proc { window_rows }],
            [_("Desktop"), proc { desktop_rows }],
            [_("Notification area"), proc { tray_rows }]]
    TitanUI::Screen.new(@bus, _("Windows and the desktop"), tabs,
                        :on_open => method(:window_open)).open
  end

  def window_rows
    answer = TitanUI.ask(@bus, "shell", "windows", {}, :title => _("Reading..."))
    return [[answer.text.to_s, nil]] if !answer.ok?
    data = JSON.parse(answer.text) rescue nil
    windows = data.is_a?(Hash) ? (data["windows"] || []) : []
    windows.map do |window|
      state = []
      state.push(_("active")) if window["active"] == true
      state.push(_("minimised")) if window["minimized"] == true
      label = window["title"].to_s
      label += " (#{state.join(', ')})" if state.size > 0
      [label, {"do" => "window", "title" => window["title"].to_s}]
    end
  rescue Exception => e
    [["#{e.class}: #{e.message}", nil]]
  end

  def desktop_rows
    lines("shell", "list_desktop", {}) { |line| [line, {"do" => "desktop", "name" => line}] }
  end

  def tray_rows
    lines("shell", "list_tray", {}) { |line| [line, {"do" => "tray", "name" => line}] }
  end

  # Several shell actions answer one thing per line, which is a list even
  # when it arrives as a page.
  def lines(addon_id, action, args)
    answer = TitanUI.ask(@bus, addon_id, action, args, :title => _("Reading..."))
    return [[answer.text.to_s, nil]] if !answer.ok?
    answer.text.to_s.split("\n").map { |line| line.strip }.reject(&:empty?).map do |line|
      yield(line.sub(/\A\d+\.\s*/, ""))
    end
  end

  def window_open(value, label)
    return if !value.is_a?(Hash)
    case value["do"]
    when "window"
      chosen = pick(label, [["activate_window", _("Bring it to the front")],
                            ["minimize_window", _("Minimise it")],
                            ["close_window", _("Close it")]])
      run("shell", chosen, {"title" => value["title"]}) if chosen != nil
    when "desktop" then run("shell", "open_desktop_item", {"name" => value["name"]})
    when "tray"    then run("shell", "activate_tray_icon", {"name" => value["name"]})
    end
  end

  # ----------------------------------------------------------------- the media
  def media_screen
    loop do
      chosen = pick(_("Media"), [["search", _("Find something and play it")],
                                 ["radio", _("Play a radio station")],
                                 ["book", _("Play an audiobook")],
                                 ["resume", _("Carry on where I stopped")],
                                 ["bookmarks", _("My bookmarks")],
                                 ["catalogs", _("My catalogues")]])
      return if chosen == nil
      case chosen
      when "search"
        query = ask_text(_("What are you looking for?"))
        next if query == nil
        answer = TitanUI.ask(@bus, "titan", "search_media", {"query" => query},
                             :title => _("Searching..."))
        display_text(answer.text.to_s, :header => _("Found"))
        what = ask_text(_("Which one? Paste its location, or leave empty:"))
        run("titan", "play_media", {"url" => what}) if what != nil
      when "radio"
        station = ask_text(_("Which station?"))
        run("titan", "play_radio", {"station" => station}) if station != nil
      when "book"
        book = ask_text(_("Which book?"))
        run("titan", "play_audiobook", {"name" => book}) if book != nil
      when "resume"    then run("titan", "resume_media", {})
      when "bookmarks" then show("titan", "list_media_bookmarks", {}, _("Bookmarks"))
      when "catalogs"  then show("titan", "list_media_catalogs", {}, _("Catalogues"))
      end
    end
  end

  # ---------------------------------------------------------------- the voices
  # Which voice Titan speaks with, from Elten. This is the one screen whose
  # effect is felt in BOTH programs: the Elten speech output speaks through
  # whatever is chosen here.
  def voices_screen
    engines = addons.select { |candidate| candidate["kind"].to_s == "tts_engine" }
    return alert(_("Titan has no speech engines installed.")) if engines.empty?
    loop do
      rows = engines.map { |engine| [engine["id"].to_s, engine["label"].to_s] }
      chosen = select_action(rows, :header => _("Speech engines"))
      return if chosen == nil
      engine_screen(chosen, engines.find { |e| e["id"].to_s == chosen })
    end
  end

  def engine_screen(id, engine)
    label = engine["label"].to_s
    loop do
      chosen = pick(label, [["status", _("What it is")],
                            ["voices", _("Its voices")],
                            ["use", _("Make Titan speak with it")],
                            ["settings", _("Its settings")]])
      return if chosen == nil
      case chosen
      when "status" then show(id, "status", {}, label)
      when "voices"
        answer = TitanUI.ask(@bus, id, "list_voices", {}, :title => label)
        display_text(answer.text.to_s, :header => label)
        voice = ask_text(_("Which voice? (empty to leave it)"))
        run(id, "set_voice", {"voice" => voice}) if voice != nil
      when "use"      then run(id, "use", {})
      when "settings" then TitanActions.new(@bus).open(id, label)
      end
    end
  end

  # ------------------------------------------------------------ everything else
  def addons_screen
    rows = addons.map do |candidate|
      ["#{candidate['label']} (#{candidate['kind_label'] || candidate['kind']})",
       candidate["id"].to_s]
    end
    return alert(_("Titan lists no add-ons.")) if rows.empty?
    loop do
      index = selector(rows.map { |row| row[0] }, :header => _("Everything installed"),
                       :cancel_index => -1)
      return if index == nil || index < 0
      id = rows[index][1]
      TitanActions.new(@bus).open(id, rows[index][0])
    end
  end

  # ---------------------------------------------------------------- the asking
  def run(addon_id, action, args)
    answer = TitanUI.perform(@bus, addon_id, action, args, :title => action.to_s)
    TitanUI.tell(answer, action.to_s) if answer != nil
  end

  def show(addon_id, action, args, header)
    answer = TitanUI.ask(@bus, addon_id, action, args, :title => header)
    display_text(answer.text.to_s, :header => header)
  end

  def choose_from(addon_id, list_action, set_action, argument, header)
    answer = TitanUI.ask(@bus, addon_id, list_action, {}, :title => header)
    return alert(answer.text.to_s) if !answer.ok?
    options = answer.text.to_s.split("\n").map { |line| line.strip.sub(/\A\d+\.\s*/, "") }
    options = options.reject(&:empty?)
    return alert(_("Nothing to choose from.")) if options.empty?
    index = selector(options, :header => header, :cancel_index => -1)
    return if index == nil || index < 0
    run(addon_id, set_action, {argument => options[index]})
  end

  def pick(header, options)
    select_action(options, :header => header)
  end

  def ask_text(prompt)
    text = input_text(prompt, :escapable => true)
    text == nil || text.to_s.strip == "" ? nil : text.to_s
  end

  def ask_number(prompt)
    text = ask_text(prompt)
    text == nil ? nil : text.to_i.to_s
  end
end
