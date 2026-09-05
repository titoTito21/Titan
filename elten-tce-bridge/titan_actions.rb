# Everything else an add-on can do - behind the context-menu key.
#
# This screen is the one place actions appear as actions, and it is
# deliberately not on the way to anything: a user looking for their
# applications never meets it, and somebody who wants what tEdit or the
# macro manager can be told to do presses the context-menu key on its row
# and finds it. The parameters are asked for as a form, because TCE
# describes them - name, what it is for, whether it is required.

require "json"

class TitanActions
  def initialize(bus)
    @bus = bus
  end

  def open(addon_id, label)
    actions = describe(addon_id)
    if actions.empty?
      alert(_("%s offers nothing else here.") % label)
      return
    end
    entries = actions.map do |action|
      summary = action["summary"].to_s
      text = summary == "" ? action["name"].to_s :
        "#{action['name']}: #{first_sentence(summary)}"
      [action["name"].to_s, text]
    end
    loop do
      chosen = select_action(entries, :header => label)
      return if chosen == nil
      action = actions.find { |candidate| candidate["name"].to_s == chosen }
      run(addon_id, action) if action != nil
    end
  end

  private

  def describe(addon_id)
    answer = TitanUI.ask(@bus, "titan", "addon_actions", {"addon" => addon_id},
                         :title => _("Reading..."))
    return [] if !answer.ok?
    data = JSON.parse(answer.text) rescue nil
    data.is_a?(Hash) ? (data["actions"] || []) : []
  rescue Exception
    []
  end

  def first_sentence(text)
    stop = text.index(". ")
    stop == nil ? text : text[0..stop]
  end

  def run(addon_id, action)
    params = action["params"] || []
    args = {}
    if params.size > 0
      args = collect(action, params)
      return if args == nil
    end
    answer = TitanUI.perform(@bus, addon_id, action["name"].to_s, args,
                             :title => action["name"].to_s)
    return if answer == nil
    text = answer.text.to_s
    return alert(_("Done.")) if text.strip == ""
    # A long answer is a page to read, a short one is something to be told.
    if text.length > 200 || text.include?("\n")
      display_text(text, :header => action["name"].to_s)
    else
      alert(text)
    end
  end

  # One field per parameter, in the order TCE declares them. A parameter
  # with a fixed set of values is a choice; everything else is a field.
  def collect(action, params)
    controls = []
    fields = params.map do |param|
      label = param["description"].to_s
      label = param["name"].to_s if label == ""
      label = _("%s (required)") % label if param["required"] == true
      values = (param["enum"] || []).map(&:to_s)
      control = if values.size > 0
                  ChoiceListBox.new([[label, values, 0]])
                elsif param["type"].to_s == "boolean"
                  ChoiceListBox.new([[label, [_("No"), _("Yes")], 0]])
                else
                  EditBox.new(label)
                end
      controls.push(control)
      [param, control, values]
    end
    ok = Button.new(_("Run"))
    cancel = Button.new(_("Cancel"))
    form = Form.new(controls + [ok, cancel])
    form.cancel_button = cancel
    form.accept_button = ok
    answered = nil
    done = false
    ok.on(:press) do
      answered = {}
      fields.each do |param, control, values|
        name = param["name"].to_s
        if control.is_a?(EditBox)
          text = control.text.to_s
          answered[name] = text if text != ""
        else
          row = control.rows[0]
          next if row == nil
          answered[name] = values.size > 0 ? (row.options[row.value.to_i]).to_s :
            (row.value.to_i == 1 ? "true" : "false")
        end
      end
      done = true
    end
    cancel.on(:press) { done = true }
    form.focus
    until done
      loop_update
      form.update
    end
    answered
  end
end
