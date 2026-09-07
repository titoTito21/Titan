# encoding: utf-8
#
# TCE on Elten's own main screen - a widget, in Elten's sense of one.
#
# Everything else this add-on has is behind opening it: the user goes to
# their programs, finds the TCE bridge, and works Titan inside it. What
# was missing is the thing a widget is for - TCE being THERE, on the
# screen Elten opens on, without anybody having gone looking for it.
#
# Elten's extension API has exactly this and it is what the weather
# applications use: `extension.main_tab` contributes one more section to
# the main screen, beside Notifications, Quick actions and the Feed, and
# the block returns a CONTROL that lives in it. So the widget is an
# ordinary `ListBox` - Elten's reader already knows how to read one, the
# arrows walk it and Enter presses it, with none of that written here.
#
#   TCE: connected            press to ask it how it is
#   TCE applications          Titan's own programs, as Elten screens
#   Titan AI                  the assistant, the agent, one question
#
# Three things about it are deliberate:
#
# - **It is built once and kept.** `build_control` is called on EVERY
#   frame the tab has the focus, and `current_control` is what was
#   returned last time precisely so it can be handed straight back. A
#   control rebuilt per frame is a control whose cursor never moves.
# - **Nothing here asks Titan on a frame.** The status line is
#   `bus.connected?`, which is a flag this add-on already keeps - no
#   pipe, no round trip, no worker. Asking Titan how it is takes a call,
#   so it happens when the user presses the row, which is when they have
#   asked for it.
# - **Pressing a row opens the screen that already exists.** The widget
#   is a way IN and not a second implementation: the applications row
#   opens the same `TitanApps` the areas list opens, and the AI row the
#   same `TitanAI`. Elten's own quick actions call their block straight
#   out of the main scene's update, so opening a screen from here is the
#   pattern Elten itself uses.

# Named `elten_*` like every other file here that is ELTEN's side of the
# bridge - `elten_news`, `elten_screen`, `elten_keys`. `titan_widgets.rb`
# next door is the opposite thing: TITAN's widgets, shown in Elten.
module EltenWidget
  # How stale the status line may be. It costs a flag read, so this is
  # about not re-rendering a list sixty times a second rather than about
  # the reading being expensive.
  FRESH_SECONDS = 2.0

  module_function

  # Called from the add-on's own `extension` block. One tab; whether it
  # is worth showing is not conditional, because a TCE that is not
  # running is exactly when somebody wants to be told so.
  #
  # **Asked for, and never allowed to raise.** Everything an extension
  # declares is declared inside one block, and an exception anywhere in
  # that block abandons the WHOLE declaration - the tick, the news and
  # the marshaller with it. This add-on has already paid for that once,
  # with a second `extension.tick` that raised and left nothing ticking
  # at all. `main_tab` arrived in Elten after the version this add-on's
  # manifest asks for, so on an older client it is simply not there:
  # asking first is what makes the widget the only thing that is missing
  # rather than the add-on.
  def declare(extension)
    return false if !extension.respond_to?(:main_tab)
    extension.main_tab("tce", :label => _("TCE"),
                       :visible => proc { TitanPrefs.widget? }) do |context|
      control(context)
    end
    true
  rescue Exception
    false
  end

  # **`is_a?(ListBox)`, not `== nil`.** What comes back is whatever was
  # returned last time, and a control of another kind - handed over by a
  # future version of this, or by Elten falling back - would be updated
  # as though it were a list. Elten's own weather widget asks the same
  # way. `quiet` is its other detail: a list announces itself when it is
  # built, and building one is not the user arriving at it.
  def control(context)
    list = context.current_control
    if !list.is_a?(ListBox)
      list = ListBox.new(rows, :header => _("TCE"), :quiet => true)
      bind(list, context.state)
      context.state[:rows] = rows
      context.state[:at] = Time.now.to_f
      return list
    end
    # **Before the list updates, not inside it.** See `open_pending`.
    open_pending(list, context.state)
    refresh(list, context.state)
    list
  end

  # **What a chosen row does happens OUTSIDE the list's own update, and
  # that is not a detail.**
  #
  # `:select` is fired from inside `ListBox#update`, so opening a screen
  # there means starting a whole nested Elten loop - `TitanUI::Screen`'s
  # `loop_update` plus `form.update` - from inside the update of the
  # control that is being pumped by the loop above it. Elten's own main
  # screen never does that: `quick_actions_update` asks `@acsel.selected?`
  # from the SCENE and calls the action there, one level out.
  #
  # So the row is remembered and acted on at the top of the next frame,
  # where `build_control` runs - which is the same depth Elten's own quick
  # actions run at. It costs one frame, which nobody can hear, and it is
  # the difference between a row that opens something and a row that
  # appears to do nothing at all.
  def open_pending(list, state)
    wanted = state.delete(:open)
    return if wanted == nil
    note("opening row #{wanted}")
    case wanted
    when 0 then status
    when 1 then applications
    when 2 then ai
    end
    # The nested screen had the keyboard; the widget is what the user
    # comes back to.
    list.focus rescue nil
  end

  # Into Elten's own log, so "nothing happens" is a report with evidence
  # in it rather than a second round of guessing.
  def note(text)
    Log.info("TCE widget: #{text}")
  rescue Exception
    nil
  end

  # **Only when it has really changed.** `options=` clears the list and
  # puts it back, which moves the cursor and clears the item states - so
  # doing it on a frame because a clock ticked would make the widget
  # impossible to sit still in.
  def refresh(list, state)
    now = Time.now.to_f
    return if state[:at] != nil && now - state[:at] < FRESH_SECONDS
    state[:at] = now
    fresh = rows
    return if fresh == state[:rows]
    index = list.index
    list.options = fresh
    list.index = [index, fresh.size - 1].min
    state[:rows] = fresh
  end

  def rows
    [status_line, _("TCE applications"), _("Titan AI")]
  end

  # Said in one line, from what this add-on already knows. Anything more
  # than "is the pipe open" is a call, and a widget must not make one on
  # a frame.
  def status_line
    bus.connected? ? _("TCE: connected") : _("TCE is not running")
  end

  # **Remembers into the state the next frame reads.** `state` is the
  # hash Elten keeps per contribution and hands back with
  # `context.state`, which is the only place both halves of this can
  # see - written here, taken by `open_pending` at the top of the next
  # frame.
  def bind(list, state)
    list.on(:select) do |index|
      note("row #{index.inspect} chosen")
      state[:open] = index.is_a?(Array) ? index.first : index
    end
  end

  # ------------------------------------------------------------ the rows
  # Pressed, so a real call is what was asked for: Titan's own account of
  # itself, read in a page rather than said and gone.
  def status
    answer = TitanUI.ask(bus, "titan", "inventory", {}, :title => _("TCE"))
    return alert(answer.text.to_s) if !answer.ok?
    text = answer.text.to_s
    text = _("TCE is running.") if text.strip == ""
    display_text(text, :header => _("TCE"))
  rescue Exception => e
    alert("#{e.class}: #{e.message}")
  end

  def applications
    return if !TitanUI.require_tce(bus)
    TitanApps.new(bus, TitanAPI.new(bus)).open
  rescue Exception => e
    alert("#{e.class}: #{e.message}")
  end

  def ai
    return if !TitanUI.require_tce(bus)
    screen = TitanAI.new(bus)
    # The AI screen is offered only when Titan really has it: a screen
    # full of entries that answer "AI features are off" is worse than
    # being told so in one sentence.
    return alert(_("TCE's AI features are switched off.")) if !screen.available?
    screen.open
  rescue Exception => e
    alert("#{e.class}: #{e.message}")
  end

  def bus
    ProgramTCEBridge.bus
  end
end
