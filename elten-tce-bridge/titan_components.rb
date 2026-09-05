# The Component Manager, in Elten - `src/ui/componentmanagergui.py`.
#
# Titan's window is one list: every installed component with whether it is
# switched on, Space or Enter toggles it, and a component's own menu offers
# Run and Settings. This is that window. The list and the states are read
# from Titan (`titan.components`), so a component installed since this was
# written is in it.

require "json"

class TitanComponents
  def initialize(bus)
    @bus = bus
  end

  def open
    return if !TitanUI.require_tce(@bus)
    TitanUI::Screen.new(@bus, _("Component Manager"),
                        [[_("Installed components"), proc { rows }]],
                        :on_open => method(:toggle),
                        :on_menu => method(:component_menu)).open
  end

  def rows
    answer = TitanUI.ask(@bus, "titan", "components", {}, :title => _("Reading Titan..."))
    return [[answer.text.to_s, nil]] if !answer.ok?
    data = JSON.parse(answer.text) rescue nil
    components = data.is_a?(Hash) ? (data["components"] || []) : []
    components.map do |component|
      name = component["name"].to_s
      state = component["enabled"] == true ? _("Enabled") : _("Disabled")
      ["#{name} (#{state})",
       {"folder" => component["folder"].to_s, "name" => name,
        "enabled" => component["enabled"] == true}]
    end
  end

  # Enter is what it is in Titan's own window: it switches the component on
  # or off. It asks first, because a component being switched off takes its
  # part of Titan with it.
  def toggle(value, label)
    return if !value.is_a?(Hash)
    on = value["enabled"] == true
    return if !confirm(on ? _("Switch %s off?") % value["name"] :
                            _("Switch %s on?") % value["name"])
    answer = TitanUI.perform(@bus, value["folder"].to_s, on ? "disable" : "enable",
                             {}, :title => label)
    TitanUI.tell(answer, label) if answer != nil
  end

  def component_menu(value, label)
    return if !value.is_a?(Hash)
    chosen = select_action([["run", _("Run")],
                            ["settings", _("Settings")],
                            ["status", _("What it is doing")],
                            ["actions", _("Everything it can do")]],
                           :header => label)
    return if chosen == nil
    case chosen
    when "run"
      # Titan's Run is the entry the component puts in the Components menu.
      answer = TitanUI.perform(@bus, "titan", "run_component_action",
                               {"action" => value["name"]}, :title => label)
      TitanUI.tell(answer, label) if answer != nil
    when "settings"
      # A component registers its settings as a category of Titan's own
      # settings window, so that is where they are opened.
      TitanSettings.new(@bus).open(value["name"].to_s)
    when "status"
      answer = TitanUI.ask(@bus, value["folder"].to_s, "status", {}, :title => label)
      TitanUI.tell(answer, label)
    when "actions"
      TitanActions.new(@bus).open(value["folder"].to_s, label)
    end
  end
end
