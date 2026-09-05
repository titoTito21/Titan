# Titan's AI, in Elten - and only when Titan actually has it.
#
# In Titan the AI is a menu: the Agent, the Assistant, AI OCR, what it
# remembers, and the creation kit. Some of those are windows with a
# conversation in them and some are things that answer once. This screen
# keeps that shape: asking a question is answered HERE, in a page a reader
# can move through; the windows that are conversations are opened in Titan,
# because that is where they live.
#
# It is offered only when `titan.ai_available` says yes - a screen full of
# entries that answer "AI features are off" is worse than no screen.

class TitanAI
  def initialize(bus)
    @bus = bus
  end

  def available?
    answer = TitanUI.ask(@bus, "titan", "ai_available", {})
    answer.ok? && answer.text.to_s.strip.downcase == "yes"
  end

  def open
    return if !TitanUI.require_tce(@bus)
    tabs = [[_("Ask"), proc { ask_rows }],
            [_("Reading the screen"), proc { ocr_rows }],
            [_("What it remembers"), proc { memory_rows }],
            [_("Windows in Titan"), proc { window_rows }]]
    TitanUI::Screen.new(@bus, _("Titan AI"), tabs,
                        :on_open => method(:open_row)).open
  end

  def ask_rows
    [[_("Ask a question"), {"do" => "ask"}],
     [_("Ask, and let it do what is needed"), {"do" => "act"}]]
  end

  def ocr_rows
    [[_("Read the window in front"), {"do" => "read_window"}],
     [_("Ask about the window in front"), {"do" => "ocr_ask"}],
     [_("What it read last time"), {"do" => "last_reading"}]]
  end

  def memory_rows
    answer = TitanUI.ask(@bus, "memory", "list_notes", {}, :title => _("Reading..."))
    rows = [[_("Remember something new..."), {"do" => "remember"}]]
    return rows if !answer.ok?
    answer.text.to_s.split("\n").map { |line| line.strip }.reject(&:empty?).each do |line|
      rows.push([line, {"do" => "note", "text" => line.sub(/\A\d+\.\s*/, "")}])
    end
    rows
  end

  # The AI windows are conversations, and a conversation belongs where it
  # can be had: these open in Titan, through Titan's own Program menu.
  def window_rows
    answer = TitanUI.ask(@bus, "titan", "menu", {}, :title => _("Reading Titan..."))
    return [] if !answer.ok?
    data = JSON.parse(answer.text) rescue nil
    groups = data.is_a?(Hash) ? (data["groups"] || []) : []
    rows = []
    groups.each do |group|
      next if group["id"].to_s != "ai" && group["id"].to_s != "programmer"
      (group["entries"] || []).each do |entry|
        rows.push(["#{group['label']}: #{entry['label']}",
                   {"do" => "open_window", "entry" => entry["id"].to_s}])
      end
    end
    rows
  end

  def open_row(value, label)
    return if !value.is_a?(Hash)
    case value["do"]
    when "ask"    then ask_ai(false)
    when "act"    then ask_ai(true)
    when "read_window" then page("ocr", "read_window", {}, _("The window in front"))
    when "ocr_ask"
      question = ask_for(_("What do you want to know about it?"))
      page("ocr", "ask", {"question" => question}, _("The window in front")) if question != nil
    when "last_reading" then page("ocr", "last_reading", {}, _("What it read last time"))
    when "remember"
      text = ask_for(_("What should it remember?"))
      return if text == nil
      answer = TitanUI.perform(@bus, "memory", "remember", {"text" => text},
                               :title => _("Remembering..."))
      TitanUI.tell(answer, _("What it remembers")) if answer != nil
    when "note"
      chosen = select_action([["forget", _("Forget this")]], :header => label)
      return if chosen == nil
      return if !confirm(_("Forget this note?"))
      answer = TitanUI.perform(@bus, "memory", "forget", {"text" => value["text"]},
                               :title => label)
      TitanUI.tell(answer, label) if answer != nil
    when "open_window"
      answer = TitanUI.perform(@bus, "titan", "menu_run", {"entry" => value["entry"]},
                               :title => label)
      alert(answer.text.to_s) if answer != nil
    end
  end

  # A model takes seconds, so the question goes through Tasks.run like every
  # other call and the answer arrives as a page to read rather than as
  # something spoken once and gone.
  def ask_ai(act)
    question = ask_for(act ? _("What should it do?") : _("What do you want to ask?"))
    return if question == nil
    if act && !confirm(_("Let the AI use Titan's own functions to do this?"))
      return
    end
    answer = TitanUI.ask(@bus, "titan", "ask_ai",
                         {"question" => question, "act" => act ? "true" : "false"},
                         :title => _("Asking the AI..."))
    display_text(answer.text.to_s, :header => _("Titan AI"))
  end

  def page(addon, action, args, header)
    answer = TitanUI.ask(@bus, addon, action, args, :title => header)
    text = answer.text.to_s
    text = _("Nothing came back.") if text.strip == ""
    display_text(text, :header => header)
  end

  def ask_for(prompt)
    text = input_text(prompt, :escapable => true)
    text == nil || text.to_s.strip == "" ? nil : text.to_s
  end
end
