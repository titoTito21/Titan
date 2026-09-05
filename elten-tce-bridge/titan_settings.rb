# TCE's settings, in Elten - the window from `src/ui/settingsgui.py`, made
# out of Elten's controls.
#
# Nothing about the settings is described here and there is deliberately no
# list of them in this file: `settings.screen` hands over what Titan's OWN
# settings window contains - its categories, its controls, their labels
# already translated, their live values - so a setting added to Titan
# appears here with nothing changed on this side. That is the contract
# Titan's own alternative settings interfaces work to.
#
# **A control appears as ITSELF or not at all.** A yes/no is a tick box, a
# choice is a choice with its own options, a tick LIST is a multi-selection
# list, a number is a field that takes numbers, a password is a password
# field, a button is a button. That is what `settingsgui.py` puts on the
# screen and it is what a screen reader is able to announce; a screen that
# poured all of them into one list would read as one control with a hundred
# rows. Anything this screen cannot honestly render is shown read-only,
# saying where it can be changed, rather than as an invented control that
# would set the wrong thing.

require "json"

class TitanSettings
  def initialize(bus)
    @bus = bus
    @screen = nil
  end

  # The categories, as rows for the main window's Settings tab.
  def categories_as_rows
    read.map do |category|
      [category["name"].to_s,
       {"do" => "settings", "category" => category["name"].to_s}]
    end
  end

  def open(category = "")
    return if !TitanUI.require_tce(@bus)
    if category.to_s != ""
      entry = read.find { |c| c["name"].to_s == category.to_s }
      return edit(entry) if entry != nil
    end
    # The categories are a screen of their own, so Escape and F5 behave the
    # way they behave everywhere else in the bridge.
    TitanUI::Screen.new(@bus, _("TCE settings"),
                        [[_("Categories"), proc { categories_as_rows }]],
                        :on_open => proc { |value, _label|
                          entry = read.find { |c| c["name"].to_s == value["category"].to_s }
                          edit(entry) if entry != nil
                        }).open
  end

  private

  def read(fresh: false)
    return @screen if @screen != nil && !fresh
    answer = TitanUI.ask(@bus, "settings", "screen", {},
                         :title => _("Reading the TCE settings..."))
    return (@screen = []) if !answer.ok?
    data = JSON.parse(answer.text) rescue nil
    @screen = data.is_a?(Hash) ? (data["categories"] || []) : []
  rescue Exception
    @screen = []
  end

  # ------------------------------------------------------------- the controls
  def edit(category)
    items = (category["items"] || []).select { |item| item.is_a?(Hash) }
    fields = []
    bound = []                   # [item, control] in Titan's own order
    commands = {}                # Button -> item id

    items.each do |item|
      control = control_for(item, commands)
      next if control == nil
      fields.push(control)
      bound.push([item, control])
    end

    save = Button.new(_("Save"))
    cancel = Button.new(_("Cancel"))
    fields.push(save, cancel)

    form = Form.new(fields)
    form.cancel_button = cancel
    done = false
    cancel.on(:press) { done = true }
    commands.each do |button, id|
      button.on(:press) do
        answer = TitanUI.perform(@bus, "settings", "press", {"item" => id},
                                 :title => button.label.to_s)
        alert(answer.text.to_s) if answer != nil
      end
    end
    save.on(:press) do
      apply(bound)
      done = true
    end

    form.focus
    until done
      loop_update
      form.update
    end
  end

  def control_for(item, commands)
    kind = item["kind"].to_s
    label = label_for(item)
    case kind
    when "bool"
      CheckBox.new(label, :checked => truth(item["value"]))
    when "choice", "list"
      options = options_of(item)
      ChoiceListBox.new([[label, options, options.index(item["value"].to_s) || 0]])
    when "multi"
      # Titan's own tick lists - the shell add-ons, the add-ons the AI may
      # drive, the startup categories. Elten's multi-selection list is the
      # same control: Space ticks a row and the reader says Ticked.
      options = options_of(item)
      list = ListBox.new(options, :header => label,
                         :flags => ListBox::Flags::MultiSelection)
      chosen = Array(item["value"]).map(&:to_s)
      indices = chosen.map { |value| options.index(value) }.compact
      list.select_multiselection_indices(indices) if indices.size > 0
      list
    when "number"
      EditBox.new(label, :type => EditBox::Flags::Numbers,
                  :text => item["value"].to_s)
    when "secret"
      # Never displayed: Titan keeps it encrypted and says only that it is
      # set, so an empty field means "leave it alone".
      EditBox.new(label, :type => EditBox::Flags::Password, :text => "")
    when "text"
      EditBox.new(label, :text => item["value"].to_s)
    when "command"
      button = Button.new(item["label"].to_s)
      commands[button] = item["id"].to_s
      button
    else
      EditBox.new(label, :type => EditBox::Flags::ReadOnly,
                  :text => value_text(item))
    end
  end

  def options_of(item)
    options = (item["options"] || []).map(&:to_s)
    options.empty? ? [item["value"].to_s] : options
  end

  def value_text(item)
    value = item["value"]
    value.is_a?(Array) ? value.join(", ") : value.to_s
  end

  def truth(value)
    value == true || value.to_s == "true" || value.to_s == "1"
  end

  def label_for(item)
    label = item["label"].to_s
    label = item["id"].to_s if label == ""
    return label if item["enabled"] != false
    # A control Titan has disabled is not hidden - the user should see it is
    # there and that something else has to be switched on first.
    _("%s (not available)") % label
  end

  # ---------------------------------------------------------------- saving
  # Only what actually changed is sent, and the save is Titan's own save,
  # with everything that hangs off it - the voice registration, the system
  # monitor, the shell hooks, the menu bar.
  def apply(bound)
    changed = 0
    bound.each do |item, control|
      value = read_control(item, control)
      next if value == nil
      changed += 1 if set(item["id"].to_s, value)
    end
    if changed == 0
      alert(_("Nothing was changed."))
      return
    end
    answer = TitanUI.ask(@bus, "settings", "save", {}, :title => _("Saving..."))
    read(:fresh => true)
    alert(answer.ok? ? _("Saved %d settings.") % changed : answer.text.to_s)
  end

  # What to send for this control, or nil when it is unchanged - which is
  # also what an untouched password field means, so a key that is already
  # there is never overwritten with nothing.
  def read_control(item, control)
    case item["kind"].to_s
    when "bool"
      now = control.checked == true
      now == truth(item["value"]) ? nil : (now ? "true" : "false")
    when "choice", "list"
      row = control.rows[0]
      return nil if row == nil
      now = (row.options[row.value.to_i] || "").to_s
      now == item["value"].to_s ? nil : now
    when "multi"
      options = options_of(item)
      now = control.multiselections.map { |index| options[index].to_s }
      was = Array(item["value"]).map(&:to_s)
      now.sort == was.sort ? nil : JSON.generate(now)
    when "number", "text"
      now = control.text.to_s
      now == item["value"].to_s ? nil : now
    when "secret"
      now = control.text.to_s
      now == "" ? nil : now
    else
      nil
    end
  rescue Exception
    nil
  end

  def set(id, value)
    answer = TitanUI.ask(@bus, "settings", "set_value",
                         {"item" => id, "value" => value})
    return true if answer.ok?
    alert(answer.text.to_s)
    false
  end
end
