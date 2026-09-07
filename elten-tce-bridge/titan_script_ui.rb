# encoding: utf-8
#
# Writing one Titan Script here, and running it.
#
# The Macro Manager screen next door is the user's SAVED macros - listed,
# with shortcuts, edited and deleted. This is the other thing somebody
# wants: a script written for one job, run now, with what it answered
# read back - and kept only if it turns out to be worth keeping.
#
# **It is a scratchpad, and that is what makes it useful.** A macro is a
# thing in Titan's macro manager with a name and a shortcut; making one
# to find out whether three lines do what you meant leaves the user's
# list full of experiments. So nothing here writes anything until the
# user says to, and "keep this as a macro" is one entry rather than the
# way in.
#
# **Checked before it runs, because a script is a program.** Titan's own
# check knows what would stop it and what would run and looks wrong,
# reported by line and in the user's own language - so the answer to "why
# did nothing happen" is here rather than in a transcript.
#
# The same three things an application gets through `EltenAPI::Titan`,
# with a screen in front of them: this file and that one are deliberately
# the same capability twice, for a person and for a program.

class TitanScriptUI
  # What a new scratchpad starts with. Real statements rather than a
  # comment saying what to write: somebody who cannot see the screen
  # should be able to press Run first and hear that it works.
  TEMPLATE = "say \"Hello from Elten\"\nreturn now(\"%H:%M\")\n".freeze

  def initialize(bus)
    @bus = bus
    @api = TitanAPI.new(bus)
    @script = TEMPLATE.dup
  end

  def open
    return if !TitanUI.require_tce(@bus)
    TitanUI::Screen.new(@bus, _("Titan Script"),
                        [[_("Script"), method(:rows)]],
                        :on_open => method(:open_row)).open
  end

  def rows
    [[_("Write the script..."), {"do" => "write"}],
     [_("Run it"), {"do" => "run"}],
     [_("Check it"), {"do" => "check"}],
     [_("Keep it as a macro..."), {"do" => "save"}],
     [_("The Titan Script language"), {"do" => "language"}],
     [_("What a script can call"), {"do" => "actions"}]]
  end

  def open_row(value, _label = nil)
    return if !value.is_a?(Hash)
    case value["do"]
    when "write"    then write
    when "run"      then run
    when "check"    then page("check_macro", {"script" => @script,
                                              "use_ai" => "false"},
                              _("Check it"))
    when "save"     then save
    when "language" then page("macro_language", {}, _("The Titan Script language"))
    when "actions"  then page("macro_actions", {}, _("What a script can call"))
    end
  end

  # A real editing field - many lines, the reader's own cursor, say-all
  # and Ctrl+C - because a script is text somebody reads back as much as
  # text they type.
  def write
    box = EditBox.new(_("The script"), :type => EditBox::Flags::MultiLine,
                      :text => @script)
    keep = Button.new(_("Keep"))
    cancel = Button.new(_("Cancel"))
    form = Form.new([box, keep, cancel])
    form.header = _("Titan Script")
    form.cancel_button = cancel
    done = false
    keep.on(:press) { @script = box.text.to_s; done = true }
    cancel.on(:press) { done = true }
    form.focus
    until done
      loop_update
      form.update
    end
  end

  # **Run through the same action an application would call**, so what
  # happens here and what happens inside an `.eltenapp` cannot drift
  # apart. The two sounds Titan plays around a macro of its own are
  # played too, so a script run from Elten is heard beginning and ending
  # the way it would over there.
  def run
    return alert(_("There is nothing to run yet.")) if @script.strip == ""
    TitanSounds.event(:macro_start)
    answer = EltenAPI::Titan.script(@script, :title => _("Titan Script"))
    TitanSounds.event(:macro_end)
    if answer.needs_consent?
      # Not a failure and not something to try again: Titan is asking its
      # own user whether this bridge may act, and the answer is over
      # there.
      return alert(answer.error.to_s)
    end
    return alert(answer.error.to_s) if !answer.ok?
    text = answer.value.to_s
    return alert(_("The script finished and said nothing.")) if text.strip == ""
    display_text(text, :header => _("What the script answered"))
  end

  def save
    name = input_text(_("What should the macro be called?"), :escapable => true)
    return if name == nil || name.to_s.strip == ""
    answer = EltenAPI::Titan.save_macro(name.to_s.strip, @script)
    alert(answer.to_s)
  end

  def page(action, args, header)
    answer = TitanUI.ask(@bus, "macros", action, args, :title => header)
    text = answer.text.to_s
    text = _("Nothing came back.") if text.strip == ""
    display_text(text, :header => header)
  end
end
