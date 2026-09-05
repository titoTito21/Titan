# Titan's widgets, used from Elten.
#
# A widget is not a thing to look at - it is a small interactive surface
# with a cursor in it: the quick settings, the system desktop, the taskbar.
# In Titan's non-visual interface you move through it with the arrows and
# press Enter, and whatever it says is spoken. That is exactly what this is,
# with two differences that matter: the moving happens in Titan (the widget
# is its object, with its own state), and the SPEAKING happens here, in
# Elten's own voice, because the words are being read to somebody sitting in
# Elten.
#
# The surface is a `Static`. It is the one Elten control that consumes no
# keys at all, so every arrow belongs to the widget rather than to the
# control - which is what makes a widget feel like a widget.

require "json"

class TitanWidgets
  MOVES = {
    :key_up => "up", :key_down => "down",
    :key_left => "left", :key_right => "right",
  }.freeze

  def initialize(bus)
    @bus = bus
  end

  def open
    return if !TitanUI.require_tce(@bus)
    TitanUI::Screen.new(@bus, _("Widgets"),
                        [[_("Widgets"), proc { rows }]],
                        :on_open => method(:use)).open
  end

  def rows
    answer = TitanUI.ask(@bus, "titan", "widgets", {}, :title => _("Reading Titan..."))
    return [[answer.text.to_s, nil]] if !answer.ok?
    data = JSON.parse(answer.text) rescue nil
    (data.is_a?(Hash) ? (data["widgets"] || []) : []).map do |widget|
      label = widget["name"].to_s
      label = _("%s (does not load)") % label if widget["error"]
      [label, widget["error"] ? nil : {"name" => widget["name"].to_s,
                                       "type" => widget["type"].to_s}]
    end
  end

  # One widget, live: the arrows move its cursor, Enter presses what the
  # cursor is on, and every answer is read out.
  def use(value, label)
    return if !value.is_a?(Hash)
    name = value["name"].to_s
    TitanSounds.play(TitanSounds::WIDGET)
    surface = Static.new(label)
    activate = Button.new(_("Press it"))
    back = Button.new(_("Back"))
    form = Form.new([surface, activate, back])
    form.cancel_button = back
    running = true
    back.on(:press) { running = false }

    show = proc do |text|
      words = text.to_s.strip
      words = label if words == ""
      surface.label = words
      speak(words)
    end

    press = proc do
      answer = TitanUI.ask(@bus, "titan", "activate_widget", {"widget" => name},
                           :title => label)
      show.call(answer.text)
    end
    activate.on(:press) { press.call }

    answer = TitanUI.ask(@bus, "titan", "widget_read", {"widget" => name},
                         :title => label)
    show.call(answer.text)

    form.focus
    while running
      loop_update
      form.update
      MOVES.each do |key, direction|
        next if !key_pressed?(key)
        moved = TitanUI.ask(@bus, "titan", "widget_move",
                            {"widget" => name, "direction" => direction},
                            :title => label)
        show.call(moved.text)
      end
      press.call if key_pressed?(:key_enter) && form.index == 0
    end
  end
end
