# encoding: utf-8
#
# TCE's own applications, as Elten screens.
#
# This is the far end of `src/app_ui/` in Titan: a TCE application - an
# ordinary wxPython program, unmodified - runs with a `wx` that DESCRIBES
# what it built instead of painting it, and what arrives here is controls
# with a kind, a label and a value. Nothing in Titan knows this renderer
# exists, and nothing here knows which application it is showing: the
# description is neutral on purpose, so the Invisible UI, a Titan Script
# and any other external client render the same thing their own way.
#
# **Every control is a real Elten control**, which is the same rule the
# Elten API port follows in the other direction and for the same reason: a
# ListBox is a ListBox, an EditBox is an EditBox, and Elten's own reader
# already knows how to read both. Nothing here is drawn by hand.
#
# What it cannot render it SAYS. An application built on a web view has
# nothing to describe and Titan refuses it by name; a control kind this
# version of the bridge has never heard of becomes a line of text rather
# than disappearing, because a control silently missing is the worst
# possible answer for somebody who cannot see the screen.

require_relative "titan_ui"
require_relative "titan_sounds"

class TitanApps
  # How long to wait for TCE to answer with a new screen. An application
  # doing real work - reading a folder, saving a file - takes a moment,
  # and Elten's own progress window covers it.
  PATIENCE = 30

  def initialize(bus, api)
    @bus = bus
    @api = api
    @session = nil
    @screen = nil
    @running = false
  end

  # ------------------------------------------------------------------ list
  def open
    return if !TitanUI.require_tce(@bus)
    TitanUI::Screen.new(@bus, _("TCE applications"),
                        [[_("Applications"), method(:rows)]],
                        :on_open => method(:run)).open
  end

  # **In the user's own language**, so the name on the row is the name
  # Titan shows everywhere else - and the name that goes back when it is
  # pressed. Titan matches an application by every spelling it has, so
  # either would open it; showing an English name to somebody using a
  # Polish Titan would still be wrong.
  def rows
    answer = @api.call("app.list", {"language" => @api.language},
                       :title => _("Reading..."))
    if !answer.ok?
      return [[answer.error.to_s == "" ? @api.unavailable_message : answer.error.to_s, nil]]
    end
    list = answer.data
    return [[_("TCE has no applications installed."), nil]] if !list.is_a?(Array) || list.empty?
    list.map { |entry| [entry["name"].to_s, entry["name"].to_s] }
  end

  # --------------------------------------------------------------- running
  def run(name, _label = nil)
    return if name == nil
    answer = @api.call("app.open", {"name" => name, "client" => "elten",
                                    "language" => @api.language},
                       :title => _("Opening %s...") % name)
    if !answer.ok?
      TitanSounds.event(:error)
      # **Why, not "it did not open".** Titan says which part of the
      # application cannot be here - "built on wx.html2: a web view cannot
      # be shown by an interface made of controls" - and that sentence is
      # the whole of the honest answer.
      return alert(answer.error.to_s)
    end
    @session = answer["session"]
    @screen = answer["screen"]
    # **A mirror is said to be one.** An application that can describe
    # itself is showing you its own account of its interface; one that
    # cannot is being read off its window by Windows, which is a weaker
    # thing - a control Windows cannot name has no name here. Presenting
    # the two as though they were the same would be exactly the
    # dishonesty this is built to avoid.
    if answer["mirror"] == true
      # One msgid on one line: a message split across two Ruby string
      # literals is looked up as the joined text, which is never what is
      # in the catalogue - it would have stayed English for ever.
      alert(_("%s cannot describe its own interface, so this is what Windows can see of its window. Some of it may be missing or unnamed.") % name)
    end
    refused = answer["refused"]
    if refused.is_a?(Array) && !refused.empty? && answer["mirror"] != true
      parts = refused.map { |one| one["detail"].to_s }.reject(&:empty?)
      alert(_("Some of it cannot be shown here: %s") % parts.join("; ")) if !parts.empty?
    end
    loop_screens
  ensure
    close_session
  end

  def close_session
    return if @session == nil
    @api.call("app.close", {"session" => @session})
    @session = nil
  end

  # Each described screen is one Elten form. A screen that has changed is
  # a form that is rebuilt - which is what wx does too: a dialog opening
  # IS a new screen, and rebuilding is how the reader is told so.
  def loop_screens
    @running = true
    TitanSounds.event(:open)
    while @running && @screen.is_a?(Hash)
      # `show` builds a form for this screen and comes back only when the
      # application has answered with a different one - so a key it did
      # nothing with never rebuilds the form and never moves the focus.
      begin
        show(@screen)
      rescue Exception => e
        # **Said, written down, and the application closed cleanly.** An
        # exception let out of here reaches the user as whatever Ruby
        # said - "malformed" something - with nothing about which screen
        # it was or what was being built, and the add-on falls over
        # around it.
        TitanApps.note("showing %p raised %s: %s" %
                       [@screen["title"].to_s, e.class, e.message])
        TitanSounds.event(:error)
        alert(_("This screen could not be shown: %s") %
              "#{e.class}: #{e.message}")
        @running = false
      end
    end
    TitanSounds.event(:close)
  end

  # **What is ON the screen, not just what the screen is made of.**
  #
  # This decided whether the form is rebuilt, and it read only the ids,
  # kinds and labels of the controls - so opening a folder in the file
  # manager, which changes the ROWS and nothing else, looked like the
  # same screen. The application really moved; the form went on showing
  # the folder it was built with, and every key looked like it did
  # nothing. Enter and Backspace both, for one reason.
  #
  # The INDEX is deliberately left out. The cursor moving is not the
  # screen changing, and rebuilding the form for it would take the
  # keyboard away from the user on every arrow key.
  #
  # **What the user just typed is not the screen changing.** `ignore` is
  # the control a value was just sent for, and its own value and tick are
  # left out of both sides of the comparison - because the application
  # answers a set with the control holding what was set, which differs
  # from what it held a letter ago every single time. Counted as a change
  # the form was rebuilt on EVERY KEYSTROKE, and a rebuilt EditBox starts
  # with its caret at the beginning: the next letter went in front of the
  # last one and a typed word came out backwards.
  def fingerprint(screen, ignore = nil)
    return "" if !screen.is_a?(Hash)
    [screen["id"], screen["kind"], screen["title"],
     (screen["controls"] || []).map do |c|
       mine = ignore != nil && c["id"] == ignore
       [c["id"], c["kind"], c["label"], mine ? nil : c["value"], c["items"],
        c["options"], c["columns"], mine ? nil : c["checked"], c["enabled"]]
     end,
     (screen["menus"] || []).map { |m| m["label"] }].inspect
  end

  # ---------------------------------------------------------------- render
  # **The loop is written out, not left to `Form#wait`.**
  #
  # `Form#wait` is `focus` and then `loop_update` plus `update` for ever,
  # and it has no way to hand a key back or to be stopped from inside a
  # handler. That cost all three of the faults this screen was reported
  # with: no key of the application's ever arrived, the menu bar could not
  # be opened, and pressing something changed the screen underneath while
  # the form went on showing what it had. `TitanUI::Screen` in this same
  # add-on writes its loop out for exactly that reason, and says so.
  def show(screen)
    controls = screen["controls"] || []
    widgets = []
    bound = []
    controls.each do |described|
      # **A control that will not build is ONE control.** Unguarded, the
      # first one to raise took the whole screen with it and the message
      # that reached the user was whatever Ruby said, with nothing about
      # which control or which application it was.
      widget = begin
        build(described)
      rescue Exception => e
        TitanApps.note("%s %s would not build: %s: %s" %
                       [described["kind"], described["id"].inspect,
                        e.class, e.message])
        Static.new("%s (%s)" % [described["label"].to_s, e.class])
      end
      next if widget == nil
      widgets.push(widget)
      bound.push([described, widget])
    end
    widgets.push(Static.new(_("This screen has nothing on it."))) if widgets.empty?
    back = Button.new(_("Back"))
    widgets.push(back)
    TitanApps.note("built %p: %s" % [screen["title"].to_s,
                                     bound.map { |d, _w| d["kind"] }.join(", ")])
    form = Form.new(widgets)
    form.header = screen["title"].to_s
    form.cancel_button = back
    @moved = false
    back.on(:press) { leave(screen) }
    wire(bound)
    bind_menu_bar(form, screen)
    focus_first(form, bound, screen)
    pump(form, screen, bound)
  end

  # Elten's own shape: `loop_update`, the form's `update`, and the keys
  # asked for in between (`scenes/account.rb` drives a TableBox exactly
  # this way). It ends the moment the application's screen has changed,
  # so the next one is built rather than the old one being shown on.
  #: The last keys this loop really saw, newest first, and what it did
  #: with each. Read with the `render_log` action - so "the key does
  #: nothing" can be answered with what happened rather than guessed at
  #: a second time.
  def self.log
    @log ||= []
  end

  def self.note(text)
    log.unshift("%s %s" % [Time.now.strftime("%H:%M:%S"), text])
    log.pop while log.size > 40
  rescue Exception
    # Never the fault. A note that cannot be written is a note lost, and
    # that is the whole of the damage it may do.
  end

  def pump(form, screen, bound)
    loop do
      loop_update
      begin
        form.update
      rescue Exception => e
        TitanApps.note("the form raised: %s: %s" % [e.class, e.message])
        raise
      end
      break if !@running || @moved
      # **Alt is the application's menu bar**, where it is in every
      # program that has one. The context-menu key opens it too, for
      # somebody who reaches for that first.
      if key_pressed?(:key_alt) || key_pressed?(:key_context_menu)
        open_menus(screen)
        break if @moved || !@running
      end
      if key_pressed?(TitanUI::KEY_REFRESH)
        send_key("f5")
        break if @moved || !@running
      end
      # Enter on a table opens the row. A ListBox fires `:select` itself;
      # a TableBox has no such event at all - Elten's own code reads the
      # key in the loop - so without this the main screen of the notes,
      # the file manager and the organiser could be walked and never
      # opened.
      focused = bound[form.index.to_i]
      if key_pressed?(:key_enter) || key_pressed?(0x0D)
        TitanApps.note("enter seen; the cursor is on %s" %
                       (focused == nil ? "nothing" : focused[0]["kind"]))
      end
      # **Enter opens the row even when the cursor is not where this
      # thought it was.** A TableBox fires no event of its own, so the key
      # is read here - and reading it only when `form.index` happens to
      # point at the table made it do nothing whenever the focus was
      # anywhere else, which is most of "Enter does not work".
      if key_pressed?(:key_enter) || key_pressed?(0x0D)
        if focused == nil || focused[0]["kind"] != "table"
          focused = bound.find { |described, _w| described["kind"] == "table" }
        end
      end
      if (key_pressed?(:key_enter) || key_pressed?(0x0D)) && focused != nil &&
         focused[0]["kind"] == "table"
        # The row the cursor is on is sent only when it is not the one
        # the application already thinks it is on: sent every time, a
        # list that answers its own selection event would act twice.
        here = focused[1].index.to_i
        TitanApps.note("enter on table #{focused[0]['id']} row #{here}")
        send_value(focused[0]["id"], here, false) if here != focused[0]["index"].to_i
        press(focused[0]["id"])
        break if @moved || !@running
      end
      # Everything else the application listens for - **except what the
      # control under the cursor wants for itself.** Backspace in a file
      # manager is "the folder above" and in a text field it is the
      # letter just typed; forwarded blindly it would be both, and a
      # field would be impossible to correct. The same for Delete and
      # Insert.
      editing = focused != nil &&
                EDITING_KINDS.include?(focused[0]["kind"].to_s)
      APPLICATION_KEYS.each do |code, name|
        next if !key_pressed?(code)
        if editing && EDITING_KEYS.include?(name)
          TitanApps.note("#{name} kept by the #{focused[0]['kind']} being typed into")
          break
        end
        TitanApps.note("#{name} -> the application")
        send_key(name)
        break
      end
      break if @moved || !@running
      # **Ctrl+S is a MENU shortcut, so the menu item is pressed.** The
      # application declares it - "Save\tCtrl+S" - and pressing the item
      # is exactly what the accelerator would have done, without this
      # having to implement accelerators at all. Nothing was forwarded
      # before, so every Ctrl+key in every application did nothing.
      if modifier_held?(:main_modifier)
        shift = raw_key_held?(:key_shift)
        item = shortcuts(screen).find do |code, _id, _letter, wants_shift|
          key_pressed?(code) && wants_shift == shift
        end
        if item != nil
          # A field keeps the three that are its own editing.
          unless editing && %w[a c v x].include?(item[2])
            press(item[1])
            break if @moved || !@running
          end
        end
      end
    end
  end

  # {[virtual key, id, letter]} for every menu shortcut on this screen.
  # Read from the screen the application described, so the keys forwarded
  # are exactly the ones it says it answers - no list written here, and
  # nothing taken from Elten that the application never asked for.
  def shortcuts(screen)
    found = []
    collect_shortcuts(screen["menus"] || [], found)
    found
  end

  def collect_shortcuts(menus, found)
    (menus || []).each do |menu|
      (menu["items"] || []).each do |item|
        if item["items"].is_a?(Array)
          collect_shortcuts([item], found)
          next
        end
        key = item["key"].to_s.downcase
        # **Alt+F4 is never forwarded.** It is "close the application",
        # and in Elten it would close ELTEN. Leaving the rendered
        # application is what Escape and the Back button do, so the menu
        # item is still there to be pressed - it just has no shortcut
        # here, which is the honest thing rather than a key that quits
        # the wrong program.
        next if key.include?("alt+")
        next if !key.start_with?("ctrl+")
        # **Shift is part of the shortcut, not noise.** Read without it,
        # "Save as...\tCtrl+Shift+S" became a second Ctrl+S and shadowed
        # "Save" - or was shadowed by it, depending which came first.
        shift = key.include?("shift+")
        letter = key.split("+").last.to_s
        next if letter.size != 1 || letter !~ /[a-z0-9]/
        code = letter =~ /[0-9]/ ? 0x30 + letter.to_i : letter.upcase.ord
        found.push([code, item["id"], letter, shift])
      end
    end
  end

  #: The keys a TCE window answers that Elten does not want. F5 is asked
  #: for separately because it means "read this again" here as well.
  APPLICATION_KEYS = {
    0x70 => "f1", 0x71 => "f2", 0x72 => "f3", 0x73 => "f4",
    0x75 => "f6", 0x76 => "f7", 0x77 => "f8", 0x78 => "f9",
    0x79 => "f10", 0x7A => "f11", 0x7B => "f12",
    # **Backspace is a key applications really use.** In the file manager
    # it is the folder above, which is most of how one is walked, and
    # leaving it out made "Enter and Backspace do not work" half true.
    0x08 => "backspace", 0x2E => "delete", 0x2D => "insert",
  }.freeze

  #: A control that is being typed into wants these for itself.
  EDITING_KINDS = %w[text multiline slider].freeze
  EDITING_KEYS = %w[backspace delete insert].freeze

  # One described control, as the Elten control it IS.
  def build(described)
    label = described["label"].to_s
    if described["unnamed"] == true
      word = kind_word(described["kind"])
      label = word if word != nil
    end
    case described["kind"]
    when "label"
      Static.new(label)
    when "text"
      # **A field that holds a PATH gets Elten's own file chooser.** The
      # application asked for a file dialog; there is no file system on
      # TCE's side of this wire, so the shim turns it into a field and
      # says it holds a path - and typing one out is not what somebody
      # meant by "open". `FilesTree` is the chooser this user already
      # knows, with its own sounds and its own keys.
      if described["path"] != nil
        # **The chooser this user already knows.** The application asked
        # for a file dialog; there is no file system on TCE's side of
        # this wire, so the shim says a PATH is wanted and what for -
        # `open`, `save` or `folder`, with the extensions the application
        # named - and every interface answers that with its own: Elten
        # has a file tree, another client has whatever it has. Typing a
        # path out is not what anybody meant by "open".
        path_field(label, described)
      else
        # **Elten's own signature**: the header is POSITIONAL and the
        # flags keyword is `type:`. Written as `header:`/`flags:` - which
        # is how `ListBox` and `TableBox` really do take theirs - every
        # field raised `unknown keyword` the moment a screen had one.
        EditBox.new(label, :text => described["value"].to_s)
      end
    when "multiline"
      # A page keeps its address in the header, so somebody can read it
      # out and hand it to a browser - the text is what is here, and the
      # address is what is not.
      header = label
      header = "%s - %s" % [label, described["url"]] if described["url"].to_s != ""
      EditBox.new(header, :text => described["value"].to_s,
                  :type => EditBox::Flags::MultiLine)
    when "button"
      Button.new(label == "" ? _("Button") : label)
    when "check"
      box = CheckBox.new(label)
      box.checked = described["value"] == true
      box
    when "choice", "tabs"
      list = ListBox.new(strings(described["options"]), :header => label)
      list.index = described["index"].to_i if described["index"].to_i >= 0
      list
    when "list"
      list = ListBox.new(strings(described["items"]), :header => header_for(described, label))
      list.index = described["index"].to_i if described["index"].to_i >= 0
      list
    when "table"
      table_for(described, label)
    when "tree"
      rows = (described["items"] || []).map do |row|
        "#{'  ' * row['depth'].to_i}#{row['text']}"
      end
      list = ListBox.new(rows, :header => header_for(described, label))
      list.index = described["index"].to_i if described["index"].to_i >= 0
      list
    when "slider"
      # Elten has no slider, and a control that pretended to be one would
      # be a control that cannot be set. A field with the range in its
      # name is what it really is: a number between two numbers.
      range = _("%{label} (%{low} to %{high})") % {
        :label => label, :low => described["minimum"],
        :high => described["maximum"]}
      EditBox.new(range, :text => described["value"].to_s)
    when "gauge"
      said = _("%{label}: %{value} of %{max}") % {
        :label => label, :value => described["value"],
        :max => described["maximum"]}
      Static.new(said)
    else
      # A kind this version has never heard of. Said rather than dropped -
      # a control silently missing is the worst answer there is for
      # somebody who cannot see the screen, and it is how an older bridge
      # goes on working against a newer TCE.
      Static.new(label == "" ? described["kind"].to_s : label)
    end
  end

  # Elten's own answer to "a path is wanted here".
  #
  # Choosing a folder hides the files; choosing a file to SAVE has to let
  # a name be given that is not there yet, which a tree alone cannot do -
  # so that one is the tree to pick the folder AND a field for the name,
  # which is what every save dialog is.
  def path_field(label, described)
    kind = described["path"].to_s
    start = described["value"].to_s
    tree = FilesTree.new(label, :path => folder_of(start, kind),
                         :hide_files => kind == "folder",
                         :extensions => described["extensions"])
    return tree if kind != "save"
    tree
  rescue Exception
    # A FilesTree this Elten has not got, or a path it will not take: a
    # field is still better than no control at all.
    EditBox.new(label, :text => start)
  end

  # A tree opens on a FOLDER. An application offering "notes.txt" to save
  # is naming a file that may not exist yet, so the folder it is in is
  # what the tree can show.
  def folder_of(path, kind)
    return path if kind == "folder" || path == ""
    return path if path.end_with?("/") || path.end_with?("\\")
    separator = path.rindex("/") || path.rindex("\\")
    separator == nil ? "" : path[0, separator]
  end

  # **The word for a control nobody named belongs to the INTERFACE.** The
  # shim runs inside the application and cannot know what language the
  # person reading this speaks, so it marks the control `unnamed` and
  # says what kind it is in English; here that becomes the user's own
  # word. Two of Titan's applications put their main table up with no
  # name at all, and a table called nothing is a list of rows belonging
  # to nothing.
  def kind_word(kind)
    {
      "text" => _("Field"), "multiline" => _("Text"),
      "choice" => _("Choice"), "check" => _("Check box"),
      "slider" => _("Slider"), "list" => _("List"),
      "table" => _("Table"), "tree" => _("Tree"),
      "gauge" => _("Progress"), "tabs" => _("Tabs"),
      "button" => _("Button"),
    }[kind.to_s]
  end

  def table_for(described, label)
    columns = strings(described["columns"])
    rows = (described["items"] || []).map { |row| strings(row) }
    if columns.empty? || rows.empty?
      list = ListBox.new(rows.map { |row| row.join(", ") },
                         :header => header_for(described, label))
      list.index = described["index"].to_i if described["index"].to_i >= 0
      return list
    end
    table = TableBox.new(columns, rows, :header => header_for(described, label))
    table.index = described["index"].to_i if described["index"].to_i >= 0
    table
  rescue Exception
    # A TableBox this Elten has not got is a list of joined rows, which
    # says everything a table says and reads in one voice.
    ListBox.new(rows.map { |row| row.join(", ") },
                :header => header_for(described, label))
  end

  def header_for(described, label = nil)
    count = (described["items"] || []).size
    text = (label || described["label"]).to_s
    text == "" ? count.to_s : "#{text} (#{count})"
  end

  def strings(values)
    return [] if !values.is_a?(Array)
    values.map { |one| one.is_a?(Array) ? one.join(", ") : one.to_s }
  end

  # -------------------------------------------------------------- the wire
  # **The event names are Elten's.** A CheckBox and an EditBox fire
  # `:change`; a ListBox fires `:move` as the cursor goes and `:select`
  # when a row is chosen; a TableBox fires only `:move`. Bound to
  # `:changed` - which nothing in Elten fires - not one tick box, field,
  # option or row selection ever reached the application.
  def wire(bound)
    bound.each do |described, widget|
      id = described["id"]
      case described["kind"]
      when "button"
        widget.on(:press) { press(id) }
      when "check"
        widget.on(:change) { send_value(id, widget.checked == true) }
      when "choice", "tabs"
        widget.on(:move) { send_value(id, widget.index.to_i, false) }
        widget.on(:select) { send_value(id, widget.index.to_i) }
      when "list", "tree"
        TitanSounds.cued(widget)
        widget.on(:move) { send_value(id, widget.index.to_i, false) }
        widget.on(:select) { press(id) }
      when "table"
        TitanSounds.cued(widget)
        widget.on(:move) { send_value(id, widget.index.to_i, false) }
        # **A TableBox is a wrapper around a ListBox and forwards only
        # `:move`** - `@sel.on(:move) {|arg| trigger(:move, arg)}` is the
        # whole of what its constructor binds - so Enter fires `:select`
        # on the inner list, reaches nobody, and is consumed there. That
        # is why Enter opened nothing: not a key that went missing, an
        # event that was never passed on. The inner list is `attr_reader
        # :sel`, so it can be listened to directly.
        if widget.respond_to?(:sel) && widget.sel != nil
          TitanApps.note("table #{id}: listening to its inner list")
          widget.sel.on(:select) do
            TitanApps.note("table #{id}: the inner list says select")
            press(id)
          end
        else
          # **A table with no columns, or with none yet, IS a list** -
          # `table_for` falls back to one so a row still reads in one
          # voice - and a list fires `:select` itself. Listening only for
          # an inner list that a ListBox has not got left those rows
          # unopenable: the download manager's downloads and the
          # organiser's table both answered Enter with nothing.
          TitanApps.note("table #{id}: it is a list, listening to it")
          widget.on(:select) { press(id) }
        end
      when "text", "multiline", "slider"
        if widget.respond_to?(:selected)
          # A file tree answers where the cursor is, not what was typed.
          widget.on(:move) { send_value(id, widget.selected.to_s, false) }
          widget.on(:select) { send_value(id, widget.selected.to_s, false) }
        else
          # An edit box is sent as it is left rather than on every letter:
          # a round trip per keystroke would make typing feel like the
          # application was thinking about each one.
          widget.on(:change) { send_value(id, widget.text.to_s, false) }
        end
      end
    rescue Exception => e
      # **Per control, not per screen.** One `rescue` around the whole
      # loop meant a single control that would not bind left every
      # control after it unbound, and nothing said so.
      Log.warning("TCE bridge: #{described['kind']} would not bind: #{e.message}") rescue nil
    end
  end

  # **The application's menu bar is Elten's own menu.** Built with
  # `bind_context`, which is how every menu in Elten is built, so it
  # reads as a menu - the platform says how many items there are, walks
  # into a submenu and closes on Escape, with none of that written here.
  def bind_menu_bar(form, screen)
    menus = screen["menus"] || []
    return if menus.empty?
    form.bind_context(_("Menu")) do |menu|
      menus.each { |one| add_menu(menu, one) }
    end
  rescue Exception
    nil
  end

  def add_menu(menu, described)
    label = described["label"].to_s
    menu.submenu(label == "" ? _("Menu") : label) do |inner|
      (described["items"] || []).each do |item|
        next if item["separator"] == true
        text = item["label"].to_s
        next if text == ""
        if item["items"].is_a?(Array)
          add_menu(inner, item)
          next
        end
        id = item["id"]
        inner.option(text, nil, shortcut_of(item)) { press(id) }
      end
    end
  end

  # `Ctrl+N` is the application's; what Elten wants here is the letter to
  # press inside the open menu, which is the last part of it.
  def shortcut_of(item)
    key = item["key"].to_s.split("+").last.to_s.downcase
    key.size == 1 ? key : ""
  end

  # Alt or the context key, when the form has no menu of its own to open -
  # kept because `bind_context` needs the form to be the one Elten asks,
  # and a screen rebuilt mid-menu would lose it.
  def open_menus(screen)
    menus = screen["menus"] || []
    return if menus.empty?
    entries = menu_entries(menus)
    return if entries.empty?
    TitanSounds.event(:menu)
    chosen = select_action(entries.map { |text, id| [id, text] },
                           :header => _("Menu"))
    return if chosen == nil
    press(chosen)
  end

  # A submenu is walked into, not offered as though it were a command: a
  # menu bar entry that holds other entries has no handler of its own, so
  # pressing it did nothing at all - and the file manager, the editor and
  # the organiser all keep "Sort by" that way.
  def menu_entries(menus, path = "")
    out = []
    (menus || []).each do |menu|
      label = menu["label"].to_s
      here = path == "" ? label : "#{path}: #{label}"
      (menu["items"] || []).each do |item|
        next if item["separator"] == true
        text = item["label"].to_s
        next if text == ""
        if item["items"].is_a?(Array)
          out.concat(menu_entries([item], here))
          next
        end
        text += "\t#{item['key']}" if item["key"].to_s != ""
        out.push(["#{here}: #{text}", item["id"]])
      end
    end
    out
  end

  # ------------------------------------------------------------- the moves
  def press(control)
    answer = @api.call("app.press", {"session" => @session, "control" => control},
                       :title => _("Working..."))
    ok = took(answer)
    TitanApps.note("press #{control} -> #{ok ? (@moved ? 'the screen changed' : 'nothing changed') : 'FAILED'}")
    still_working
    ok
  end

  # **"It did nothing" and "it has not answered yet" are opposite
  # things.** TCE says which; without that a button whose application is
  # still working - or stuck - reads exactly like a button that is not
  # wired to anything, and the screen shown is one that may no longer be
  # true. Said only for a press and a key: a letter typed must never
  # raise anything.
  def still_working
    return if @answered != false
    TitanApps.note("the application did not answer in time")
    alert(_("The application has not answered yet. It may still be working; the screen shown may be out of date."))
  end

  def send_value(control, value, wait = true)
    answer = @api.call("app.set", {"session" => @session, "control" => control,
                                   "value" => value},
                       :title => wait ? _("Working...") : nil)
    took(answer, control)
  end

  def send_key(key)
    answer = @api.call("app.key", {"session" => @session, "key" => key})
    ok = took(answer)
    TitanApps.note("key #{key} -> #{ok ? (@moved ? 'the screen changed' : 'nothing changed') : 'FAILED'}")
    still_working
    ok
  end

  # **Whether the SCREEN moved is what ends the form.** A press, a chosen
  # row, a key: if the application answered with a different interface,
  # the form showing the old one has to go, or the user is left working a
  # screen that is no longer there - which is what "it will not click on
  # anything" was.
  def took(answer, ignore = nil)
    if !answer.ok?
      TitanSounds.event(:error)
      @running = false
      @moved = true
      alert(answer.error.to_s)
      return false
    end
    # Older TCEs do not say; not saying is not the same as saying no.
    @answered = answer.data.is_a?(Hash) && answer.data.key?("answered") ?
                answer["answered"] == true : nil
    before = fingerprint(@screen, ignore)
    @screen = answer["screen"]
    if !@screen.is_a?(Hash)
      @running = false
      @moved = true
      return true
    end
    @moved = true if fingerprint(@screen, ignore) != before
    true
  end

  # **Escape is the application's first.** A TCE window answers it - a
  # dialog closes, a file browser goes up a folder - and only when the
  # screen is unchanged by it does it mean "leave the application", which
  # is what Escape means everywhere else in Elten.
  def leave(screen)
    before = fingerprint(screen)
    send_key("escape")
    return if fingerprint(@screen) != before
    @running = false
    @moved = true
  end

  def focus_first(form, bound, screen)
    wanted = screen["focus"]
    bound.each_with_index do |(described, _widget), index|
      if described["id"] == wanted
        form.focus(index) rescue form.focus
        return
      end
    end
    form.focus
  rescue Exception
    nil
  end
end
