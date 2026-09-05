# The rest of Titan's own tools, as screens rather than as lists of
# functions.
#
# Every one of these could be reached through the generic actions screen -
# and that is exactly what it should not be. A gamepad mode is a thing to
# choose, a terminal is a line to type and an answer to read, an article is
# a page. Somebody who opens "Gamepad modes" wants their modes, not
# `list_modes, get_mode, set_mode, cycle_mode`.

require "json"

class TitanTools
  def initialize(bus)
    @bus = bus
  end

  # ------------------------------------------------------------- the gamepad
  # The modes Titan has for the pad, with the one it is in named in the
  # header, and Enter switching to the one under the cursor.
  def gamepad
    return if !TitanUI.require_tce(@bus)
    TitanUI::Screen.new(@bus, _("Gamepad modes"),
                        [[_("Modes"), proc { gamepad_rows }]],
                        :on_open => proc { |value, label|
                          next if !value.is_a?(Hash)
                          answer = TitanUI.perform(@bus, "gamepad", "set_mode",
                                                   {"mode" => value["mode"]},
                                                   :title => label)
                          TitanUI.tell(answer, label) if answer != nil
                        }).open
  end

  def gamepad_rows
    answer = TitanUI.ask(@bus, "gamepad", "list_modes", {}, :title => _("Reading..."))
    return [[answer.text.to_s, nil]] if !answer.ok?
    lines(answer.text).map do |line|
      # The listing says which one is active; the name is what set_mode takes.
      name = line.sub(/\s*\(.*\)\s*\z/, "").strip
      [line, {"mode" => name}]
    end
  end

  # --------------------------------------------------------------- the clock
  def clock
    return if !TitanUI.require_tce(@bus)
    loop do
      state = TitanUI.ask(@bus, "zegarynka", "get_settings", {})
      chosen = select_action([["say", _("Say the time")],
                              ["on", _("Announce the time")],
                              ["off", _("Do not announce the time")],
                              ["interval", _("How often")]],
                             :header => state.ok? ? state.text.to_s : _("The clock"))
      return if chosen == nil
      case chosen
      when "say" then TitanUI.tell(TitanUI.ask(@bus, "zegarynka", "say_time", {}), _("The clock"))
      when "on", "off"
        answer = TitanUI.perform(@bus, "zegarynka", "set_enabled",
                                 {"enabled" => chosen == "on" ? "true" : "false"},
                                 :title => _("The clock"))
        TitanUI.tell(answer, _("The clock")) if answer != nil
      when "interval"
        minutes = ask(_("Every how many minutes?"))
        next if minutes == nil
        answer = TitanUI.perform(@bus, "zegarynka", "set_interval",
                                 {"minutes" => minutes}, :title => _("The clock"))
        TitanUI.tell(answer, _("The clock")) if answer != nil
      end
    end
  end

  # ------------------------------------------------------------ the terminal
  # A line to type and what came back, in a field a reader can move through.
  def terminal
    return if !TitanUI.require_tce(@bus)
    command = EditBox.new(_("Command"))
    output = EditBox.new(_("Output"),
                         :type => EditBox::Flags::ReadOnly | EditBox::Flags::MultiLine)
    run = Button.new(_("Run"))
    back = Button.new(_("Back"))
    form = Form.new([command, output, run, back])
    form.cancel_button = back
    form.accept_button = run
    running = true
    back.on(:press) { running = false }
    run.on(:press) do
      text = command.text.to_s
      if text.strip != ""
        answer = TitanUI.ask(@bus, "tterm", "run_command", {"command" => text},
                             :title => _("Terminal"))
        output.set_text(answer.text.to_s)
        speak(_("Finished."))
      end
    end
    form.focus
    while running
      loop_update
      form.update
    end
  end

  # ------------------------------------------------------------- the article
  def article
    return if !TitanUI.require_tce(@bus)
    url = ask(_("The address of the page:"))
    return if url == nil
    answer = TitanUI.ask(@bus, "tarticle", "read_article", {"url" => url},
                         :title => _("Reading..."))
    return alert(answer.text.to_s) if !answer.ok?
    display_text(answer.text.to_s, :header => url)
  end

  # ------------------------------------------------- files and programs
  # Titan's own view of the disk: a folder listed, a file read, a program
  # started. One level at a time, so a keyboard can follow it.
  def files(path = "")
    return if !TitanUI.require_tce(@bus)
    here = path.to_s
    loop do
      answer = TitanUI.ask(@bus, "desktop", "list_files",
                           here == "" ? {} : {"path" => here},
                           :title => here == "" ? _("Files") : here)
      return alert(answer.text.to_s) if !answer.ok?
      entries = lines(answer.text)
      options = [_("Read a file here..."), _("Start a program...")] + entries
      index = selector(options, :header => here == "" ? _("Files") : here,
                       :cancel_index => -1)
      return if index == nil || index < 0
      if index == 0
        name = ask(_("Which file?"))
        next if name == nil
        read = TitanUI.ask(@bus, "desktop", "read_file", {"path" => name},
                           :title => name)
        display_text(read.text.to_s, :header => name)
        next
      end
      if index == 1
        name = ask(_("Which program?"))
        next if name == nil
        started = TitanUI.perform(@bus, "desktop", "launch_program",
                                  {"name" => name}, :title => name)
        TitanUI.tell(started, name) if started != nil
        next
      end
      entry = entries[index - 2].to_s
      # A listing is "name  size  type"; what can be walked into is the name.
      name = entry.split(/\s{2,}/).first.to_s
      here = here.to_s == "" ? name : "#{here}\\#{name}"
    end
  end

  # -------------------------------------------------------------- the browser
  def browser
    return if !TitanUI.require_tce(@bus)
    url = ask(_("Which page?"))
    return if url == nil
    opened = TitanUI.perform(@bus, "web", "open", {"url" => url}, :title => url)
    return if opened == nil
    loop do
      chosen = select_action([["read", _("Read the page")],
                              ["click", _("Press something on it")],
                              ["back", _("Go back")],
                              ["close", _("Close it")]],
                             :header => url)
      return if chosen == nil
      case chosen
      when "read"
        answer = TitanUI.ask(@bus, "web", "read", {}, :title => url)
        display_text(answer.text.to_s, :header => url)
      when "click"
        what = ask(_("What should be pressed?"))
        next if what == nil
        answer = TitanUI.perform(@bus, "web", "click", {"target" => what}, :title => url)
        TitanUI.tell(answer, url) if answer != nil
      when "back"  then TitanUI.tell(TitanUI.ask(@bus, "web", "back", {}), url)
      when "close"
        TitanUI.ask(@bus, "web", "close", {})
        return
      end
    end
  end

  # ------------------------------------------------------------------ shared
  def lines(text)
    text.to_s.split("\n").map { |line| line.strip.sub(/\A\d+\.\s*/, "") }.reject(&:empty?)
  end

  def ask(prompt)
    text = input_text(prompt, :escapable => true)
    text == nil || text.to_s.strip == "" ? nil : text.to_s
  end
end
