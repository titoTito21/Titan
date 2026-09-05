# The pieces every TCE bridge screen is built out of.
#
# Two rules hold this together, and both come from TCE itself:
#
# ONE, a screen is TCE's OWN screen. Somebody opening "Applications" wants
# the list of applications they know from TCE - not a list of functions an
# application happens to expose. The action layer underneath is plumbing and
# never appears on the screen: what appears is a list of applications, a
# list of components, the settings in their categories.
#
# TWO, nothing waits on Elten's own thread. Every call into TCE goes through
# `Tasks.run`, which runs it on a worker while the owner thread carries on
# pumping the interface - so a TCE that is busy, or that has just exited,
# leaves Elten responsive and says so.

module TitanUI
  # Elten does not use the function keys anywhere - its interaction is the
  # arrows, Enter, Escape and the context-menu key, and it has no NAME for
  # F5 for that reason. Somebody who came here from TCE still presses it to
  # refresh a list, and `key_pressed?` takes a raw virtual key code, so the
  # key is asked for by number: VK_F5.
  KEY_REFRESH = 0x74

  module_function

  # Ask TCE for something, with Elten's own progress window if it takes a
  # moment. Returns a TitanBus::Answer - never nil, never an exception.
  def ask(bus, addon, action, args = {}, title: nil)
    label = title || _("Waiting for TCE...")
    outcome = Tasks.run(:title => label) do |_progress, _token|
      bus.call_sync(addon, action, args)
    end
    answer = outcome.respond_to?(:value) ? outcome.value : outcome
    answer.is_a?(TitanBus::Answer) ? answer :
      TitanBus::Answer.new(false, _("TCE did not answer."), nil, nil)
  rescue Exception => e
    TitanBus::Answer.new(false, "#{e.class}: #{e.message}", nil, nil)
  end

  # Every add-on TCE can reach, as TCE itself lists them.
  def ask_list(bus, title: nil)
    label = title || _("Reading TCE...")
    outcome = Tasks.run(:title => label) { |_progress, _token| bus.list_sync }
    value = outcome.respond_to?(:value) ? outcome.value : outcome
    value.is_a?(Array) ? value : []
  rescue Exception
    []
  end

  # Run an action and tell the user what happened, answering TCE's own
  # questions as they come. A pending answer is not a failure: it is TCE
  # asking for something it needs, which is exactly how TCE's own dialogs
  # behave, so it is asked here and the action is tried again.
  def perform(bus, addon, action, args = {}, title: nil)
    args = (args || {}).dup
    6.times do
      answer = ask(bus, addon, action, args, :title => title)
      if answer.pending?
        reply = answer_question(answer.question)
        return nil if reply == nil                 # the user cancelled
        args[answer.question["name"].to_s] = reply
        next
      end
      return answer
    end
    TitanBus::Answer.new(false, _("TCE kept asking for more information."), nil, nil)
  end

  # One question from TCE, asked with Elten's own controls: a list when the
  # answer is one of a few things, a field when it is not.
  def answer_question(question)
    prompt = question["prompt"].to_s
    options = question["options"]
    if options.is_a?(Array) && options.size > 0
      chosen = selector(options.map { |option| option.to_s },
                        :header => prompt, :cancel_index => -1)
      return nil if chosen == nil || chosen < 0
      return options[chosen].to_s
    end
    text = input_text(prompt, :text => question["default"].to_s,
                      :escapable => true)
    text == nil ? nil : text.to_s
  end

  # What TCE answered, said the way its length deserves: a sentence is
  # spoken, a page is a page to read - with the reader's own cursor,
  # say-all and copy working on it.
  def tell(answer, title = "")
    text = answer.respond_to?(:text) ? answer.text.to_s : answer.to_s
    return alert(_("Done.")) if text.strip == ""
    if text.length > 200 || text.include?("\n")
      display_text(text, :header => title.to_s)
    else
      alert(text)
    end
  end

  # The one thing a user must be told plainly, and the reason this add-on
  # can do nothing on its own.
  def require_tce(bus)
    return true if bus != nil && bus.connected?
    alert(_("This add-on needs TCE. Start Titan, then open this again."))
    false
  end

  # A TCE-style list screen: a tab bar walked with Left and Right, the rows
  # under it, Enter to open, F5 to read again, Escape to leave. Exactly the
  # interaction of TCE's own windows, in Elten's own controls.
  #
  # `tabs` is [[label, block], ...] where the block returns the rows as
  # [text, value] pairs; `on_open` is given the value of the chosen row.
  class Screen
    attr_reader :bus

    def initialize(bus, title, tabs, on_open: nil, on_menu: nil)
      @bus = bus
      @title = title
      @tabs = tabs
      @on_open = on_open
      @on_menu = on_menu
      @tab = 0
      @rows = []
      @running = false
    end

    def open
      @list = ListBox.new([], :header => @title)
      @back = Button.new(_("Back"))
      @form = Form.new([@list, @back])
      @form.cancel_button = @back
      @back.on(:press) { @running = false }
      # Left and Right on a vertical list arrive as Elten's :collapse and
      # :expand, which is what makes the tab bar possible without inventing
      # a control: the categories cycle and the list under them follows.
      @list.on(:expand) { cycle(1) }
      @list.on(:collapse) { cycle(-1) }
      @list.on(:select) { open_row }
      fill
      pump
    end

    private

    def header
      "#{@title} - #{@tabs[@tab][0]} (#{@rows.size})"
    end

    def cycle(direction)
      return if @tabs.size < 2
      @tab = (@tab + direction) % @tabs.size
      fill
      speak(header)
    end

    def fill
      rows = @tabs[@tab][1].call
      @rows = rows.is_a?(Array) ? rows : []
      @list.options = @rows.map { |row| row[0].to_s }
      @list.header = header
      @list.index = 0 if @list.index.to_i >= @rows.size
    rescue Exception => e
      @rows = []
      @list.options = []
      @list.header = header
      alert(_("That could not be read: %s") % "#{e.class}: #{e.message}")
    end

    def current
      index = @list.index.to_i
      return nil if index < 0 || index >= @rows.size
      @rows[index]
    end

    def open_row
      return if @on_open == nil
      row = current
      return if row == nil
      @on_open.call(row[1], row[0])
      fill
    end

    # Elten's own Form#wait is `focus` and then loop_update plus update.
    # This is that loop, with the two keys a TCE window answers everywhere:
    # F5 reads the list again, and the context-menu key opens the row's own
    # menu. Writing the loop out is what makes room for them - Form#wait
    # has no way to hand a key back.
    def pump
      @running = true
      @form.focus
      while @running
        loop_update
        @form.update
        if key_pressed?(TitanUI::KEY_REFRESH)
          fill
          speak(_("Refreshed. %s") % header)
        end
        if @on_menu != nil && key_pressed?(:key_context_menu)
          row = current
          if row != nil
            @on_menu.call(row[1], row[0])
            fill
          end
        end
      end
    end
  end
end
