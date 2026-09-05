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
    [[_("Open the assistant"), {"do" => "chat"}],
     [_("Ask one question"), {"do" => "ask"}],
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
    when "chat"   then chat
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

  # The assistant, as a conversation rather than as a question and an
  # answer that is then gone. Titan keeps ONE conversation - the assistant
  # and the agent share it, and it survives a restart - so the chat opens
  # with what was already said and adds to it. A row read in full is one
  # message; the whole thing is a list, which is what a screen reader can
  # move through.
  def chat
    return if !TitanUI.require_tce(@bus)
    # Asked once, and this is the screen the question is ABOUT - somebody
    # who reached the assistant through a quick action rather than through
    # the add-on's own window has not been asked yet. It is idempotent: an
    # answer already given is not asked for again, and No does not stop the
    # assistant, which is Titan's and works without Elten's data.
    TitanConsent.ensure_answered if defined?(TitanConsent)
    list = TitanSounds.cued(ListBox.new([], :header => _("Titan AI")))
    entry = EditBox.new(_("Say something"))
    send_button = Button.new(_("Send"))
    act_button = Button.new(_("Send, and let it act"))
    back = Button.new(_("Back"))
    form = Form.new([list, entry, send_button, act_button, back])
    form.cancel_button = back
    form.accept_button = send_button
    running = true
    messages = []

    refresh = proc do
      messages = history
      list.options = messages.map { |entry_| entry_[0] }
      list.header = _("Titan AI")
      list.index = [messages.size - 1, 0].max
    end

    say_it = proc do |act|
      text = entry.text.to_s
      next if text.strip == ""
      # TCE keeps the AI its own set of sounds and plays them for exactly
      # these three moments - the question going out, the answer arriving,
      # and the AI failing to act. This is Titan's AI, so it makes Titan's
      # noises here too.
      TitanSounds.event(:ai_sent)
      answer = TitanUI.ask(@bus, "titan", "ask_ai",
                           {"question" => text, "act" => act ? "true" : "false"},
                           :title => _("Asking the AI..."))
      if answer.ok?
        entry.set_text("")
        TitanSounds.event(:ai_answer)
      else
        TitanSounds.event(:ai_error)
      end
      refresh.call
      # Spoken as well as listed, unless the user turned that off: a reader
      # should not have to go looking for what it just asked for, but
      # somebody who reads the list themselves should not hear it twice.
      speak(answer.text.to_s) if TitanPrefs.speak_answers?
    end

    list.on(:select) do
      index = list.index.to_i
      display_text(messages[index][1].to_s, :header => _("Titan AI")) if messages[index]
    end
    send_button.on(:press) { say_it.call(false) }
    act_button.on(:press) do
      say_it.call(true) if confirm(_("Let the AI use Titan's own functions to do this?"))
    end
    back.on(:press) { running = false }

    TitanSounds.event(:ai_ready)
    refresh.call
    form.focus
    while running
      loop_update
      form.update
      if key_pressed?(TitanUI::KEY_REFRESH)
        refresh.call
        speak(_("Refreshed."))
      end
      if key_pressed?(:key_context_menu)
        chosen = select_action([["clear", _("Start the conversation again")],
                                ["window", _("Open the assistant in Titan")]],
                               :header => _("Titan AI"))
        if chosen == "clear" && confirm(_("Clear everything the AI remembers of this conversation?"))
          TitanUI.perform(@bus, "titan", "ai_forget_conversation", {},
                          :title => _("Titan AI"))
          refresh.call
        elsif chosen == "window"
          TitanUI.perform(@bus, "titan", "menu_run", {"entry" => "ai_assistant"},
                          :title => _("Titan AI"))
        end
      end
    end
  end

  # [what the row says, the whole message] for each turn, oldest first.
  def history
    answer = TitanUI.ask(@bus, "titan", "ai_history", {"limit" => "30"},
                         :title => _("Reading the conversation..."))
    return [[answer.text.to_s, answer.text.to_s]] if !answer.ok?
    data = JSON.parse(answer.text) rescue nil
    return [[_("The AI remembers nothing yet."), ""]] if !data.is_a?(Hash)
    if data["enabled"] == false
      return [[_("Titan is not keeping the conversation."), ""]]
    end
    rows = (data["exchanges"] || []).map do |turn|
      who = turn["role"].to_s == "user" ? _("You") : _("Titan")
      body = turn["text"].to_s.gsub("\n", " ")
      short = body.length > 120 ? body[0, 120] + "..." : body
      ["#{who}: #{short}", "#{who}\n\n#{turn['text']}"]
    end
    rows.empty? ? [[_("The AI remembers nothing yet."), ""]] : rows
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
