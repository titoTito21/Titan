# The Macro Manager, in Elten.
#
# Titan's own window is a list of macros with their shortcuts, and what one
# does with a macro: run it, read it, change it, give it a shortcut, check
# it, delete it. This is that window - the list is the macros, Enter runs
# the one under the cursor, and everything else is on the context-menu key,
# which is where Titan puts it too.
#
# A Titan Script is a program, so the two things that make writing one
# possible are here as well: the language reference (`macros.macro_language`,
# in the user's own language) and what a script may call
# (`macros.macro_actions`). Both are read from the Macro Manager itself, so
# a statement added to the language appears here without this file changing.

class TitanMacros
  def initialize(bus)
    @bus = bus
  end

  def open
    return if !TitanUI.require_tce(@bus)
    tabs = [[_("Macros"), proc { rows }],
            [_("Titan Script"), proc { reference_rows }]]
    TitanUI::Screen.new(@bus, _("Macro Manager"), tabs,
                        :on_open => method(:open_row),
                        :on_menu => method(:row_menu)).open
  end

  def rows
    answer = TitanUI.ask(@bus, "macros", "list_macros", {}, :title => _("Reading..."))
    return [[answer.text.to_s, nil]] if !answer.ok?
    lines = answer.text.to_s.split("\n").map { |line| line.strip }.reject(&:empty?)
    out = lines.map do |line|
      name = line.sub(/\A\d+\.\s*/, "").split(/\s+[-\u2013]\s+|\s{2,}/).first.to_s
      [line, {"do" => "run", "name" => name}]
    end
    out.push([_("Write a new macro..."), {"do" => "new"}])
    out
  end

  def reference_rows
    [[_("The Titan Script language"), {"do" => "language"}],
     [_("What a script can call"), {"do" => "actions"}]]
  end

  def open_row(value, label)
    return if !value.is_a?(Hash)
    case value["do"]
    when "run"      then run(value["name"].to_s, label)
    when "new"      then write_new
    when "language" then page("macro_language", {}, _("The Titan Script language"))
    when "actions"  then page("macro_actions", {}, _("What a script can call"))
    end
  end

  def run(name, label)
    return if !confirm(_("Run %s?") % name)
    answer = TitanUI.perform(@bus, "macros", "run_macro", {"name" => name},
                             :title => label)
    TitanUI.tell(answer, label) if answer != nil
  end

  # Everything else a macro can have done to it.
  def row_menu(value, label)
    return if !value.is_a?(Hash) || value["do"] != "run"
    name = value["name"].to_s
    chosen = select_action([["read", _("Read it")],
                            ["edit", _("Change it")],
                            ["check", _("Check it")],
                            ["fix", _("Check it and mend it")],
                            ["hotkey", _("Give it a shortcut")],
                            ["delete", _("Delete it")]],
                           :header => label)
    return if chosen == nil
    case chosen
    when "read"   then page("read_macro", {"name" => name}, name)
    when "edit"   then edit(name)
    when "check"  then page("check_macro", {"name" => name, "use_ai" => "false"}, name)
    when "fix"
      # `apply` is what makes this write, so it is asked for plainly.
      return if !confirm(_("Let Titan mend %s and save the result?") % name)
      page("fix_macro", {"name" => name, "apply" => "true"}, name)
    when "hotkey"
      keys = ask(_("Which shortcut? For example ctrl+alt+n:"))
      return if keys == nil
      answer = TitanUI.perform(@bus, "macros", "set_macro_hotkey",
                               {"name" => name, "hotkey" => keys}, :title => name)
      TitanUI.tell(answer, name) if answer != nil
    when "delete"
      return if !confirm(_("Delete the macro %s?") % name)
      answer = TitanUI.perform(@bus, "macros", "delete_macro", {"name" => name},
                               :title => name)
      TitanUI.tell(answer, name) if answer != nil
    end
  end

  # A script is written in a real editing field - many lines, the reader's
  # own cursor - and checked before it is saved, which is what the Macro
  # Manager does with a new one.
  def write_new
    name = ask(_("What should the macro be called?"))
    return if name == nil
    script = edit_text(_("The script"), template)
    return if script == nil
    answer = TitanUI.perform(@bus, "macros", "create_macro",
                             {"name" => name, "script" => script, "kind" => "tcs"},
                             :title => name)
    TitanUI.tell(answer, name) if answer != nil
  end

  def edit(name)
    answer = TitanUI.ask(@bus, "macros", "read_macro", {"name" => name},
                         :title => name)
    return alert(answer.text.to_s) if !answer.ok?
    script = edit_text(name, answer.text.to_s)
    return if script == nil
    written = TitanUI.perform(@bus, "macros", "edit_macro",
                              {"name" => name, "script" => script}, :title => name)
    TitanUI.tell(written, name) if written != nil
  end

  def template
    "say \"Hello\"\n"
  end

  def edit_text(header, text)
    box = EditBox.new(header, :type => EditBox::Flags::MultiLine, :text => text.to_s)
    ok = Button.new(_("Save"))
    cancel = Button.new(_("Cancel"))
    form = Form.new([box, ok, cancel])
    form.cancel_button = cancel
    answered = nil
    done = false
    ok.on(:press) { answered = box.text.to_s; done = true }
    cancel.on(:press) { done = true }
    form.focus
    until done
      loop_update
      form.update
    end
    answered
  end

  def page(action, args, header)
    answer = TitanUI.ask(@bus, "macros", action, args, :title => header)
    text = answer.text.to_s
    text = _("Nothing came back.") if text.strip == ""
    display_text(text, :header => header)
  end

  def ask(prompt)
    text = input_text(prompt, :escapable => true)
    text == nil || text.to_s.strip == "" ? nil : text.to_s
  end
end
