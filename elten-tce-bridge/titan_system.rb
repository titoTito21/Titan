# The computer's own settings, as panels.
#
# Three design decisions, and they are what make this a bridge rather than a
# remote control:
#
# A VALUE you change is a panel, not a question. Volume and brightness are
# moved with the arrows and the new value is said at once - asking "volume,
# 0 to 100?" makes somebody guess where they are and then type a number.
# The surface is a `Static`, the one Elten control that consumes no keys, so
# every arrow belongs to the value.
#
# A CHOICE is a list, with the current one marked. Playback devices, power
# plans, Wi-Fi networks: they are read from the computer and offered, never
# typed from memory.
#
# A SWITCH is a switch. Mute and "start with Windows" are tick boxes that
# show what is true now.
#
# Every panel reads its value before it offers to change it, so it can say
# what IS rather than what it is about to be.

class TitanSystem
  STEP = 5

  def initialize(bus)
    @bus = bus
  end

  def open
    return if !TitanUI.require_tce(@bus)
    loop do
      chosen = select_action([["sound", _("Sound")],
                              ["screen", _("Screen")],
                              ["power", _("Power")],
                              ["appearance", _("Light or dark")],
                              ["network", _("Network")],
                              ["startup", _("Titan at startup")]],
                             :header => _("The computer"))
      return if chosen == nil
      case chosen
      when "sound"      then sound
      when "screen"     then screen
      when "power"      then power
      when "appearance" then appearance
      when "network"    then network
      when "startup"    then startup
      end
    end
  end

  # ---------------------------------------------------------------- sound
  def sound
    level = number_in(read("get_volume"), 50)
    muted = read("get_volume").to_s.downcase.include?("mute")
    surface = Static.new(volume_label(level))
    mute = CheckBox.new(_("Silence"), :checked => muted)
    device = Button.new(_("Playback device"))
    back = Button.new(_("Back"))
    form = Form.new([surface, mute, device, back])
    form.cancel_button = back
    running = true
    back.on(:press) { running = false }
    mute.on(:change) do
      run("set_mute", {"muted" => mute.checked == true ? "true" : "false"})
    end
    device.on(:press) { choose_device }

    form.focus
    while running
      loop_update
      form.update
      moved = 0
      moved = STEP if key_pressed?(:key_right) || key_pressed?(:key_up)
      moved = -STEP if key_pressed?(:key_left) || key_pressed?(:key_down)
      next if moved == 0 || form.index != 0
      level = [[level + moved, 0].max, 100].min
      run("set_volume", {"percent" => level.to_s})
      # TCE plays this whenever the volume moves, and the volume moving
      # here is the same event on the same machine.
      TitanSounds.event(:volume)
      surface.label = volume_label(level)
      speak(surface.label)
    end
  end

  def volume_label(level)
    _("Volume: %d percent") % level
  end

  def choose_device
    answer = TitanUI.ask(@bus, "system", "list_audio_devices", {},
                         :title => _("Playback device"))
    return alert(answer.text.to_s) if !answer.ok?
    devices = lines(answer.text)
    return alert(_("Nothing to choose from.")) if devices.empty?
    index = selector(devices, :header => _("Playback device"), :cancel_index => -1)
    return if index == nil || index < 0
    # The listing marks the one in use; the NAME is what the computer takes.
    name = devices[index].sub(/\s*\[.*\]\s*\z/, "").strip
    run("set_audio_device", {"name" => name})
  end

  # --------------------------------------------------------------- screen
  def screen
    level = number_in(read("get_brightness"), 50)
    surface = Static.new(brightness_label(level))
    back = Button.new(_("Back"))
    form = Form.new([surface, back])
    form.cancel_button = back
    running = true
    back.on(:press) { running = false }
    form.focus
    while running
      loop_update
      form.update
      moved = 0
      moved = STEP if key_pressed?(:key_right) || key_pressed?(:key_up)
      moved = -STEP if key_pressed?(:key_left) || key_pressed?(:key_down)
      next if moved == 0 || form.index != 0
      level = [[level + moved, 0].max, 100].min
      run("set_brightness", {"percent" => level.to_s})
      surface.label = brightness_label(level)
      speak(surface.label)
    end
  end

  def brightness_label(level)
    _("Brightness: %d percent") % level
  end

  # ---------------------------------------------------------------- power
  def power
    answer = TitanUI.ask(@bus, "system", "list_power_plans", {}, :title => _("Power"))
    return alert(answer.text.to_s) if !answer.ok?
    plans = lines(answer.text)
    return alert(answer.text.to_s) if plans.empty?
    index = selector(plans, :header => read("get_power_plan"), :cancel_index => -1)
    return if index == nil || index < 0
    run("set_power_plan", {"name" => plans[index].sub(/\s*\[.*\]\s*\z/, "").strip})
  end

  # ----------------------------------------------------------- appearance
  def appearance
    index = selector([_("Light"), _("Dark")], :header => _("Light or dark"),
                     :cancel_index => -1)
    return if index == nil || index < 0
    run("set_theme", {"mode" => index == 0 ? "light" : "dark"})
  end

  # -------------------------------------------------------------- network
  # The networks in range as a list, with what is connected now in the
  # header. A password is asked for only when the computer says it needs
  # one - an open network should not put up a password box.
  def network
    status = read("network_status")
    answer = TitanUI.ask(@bus, "system", "list_wifi", {}, :title => _("Network"))
    networks = answer.ok? ? lines(answer.text) : []
    rows = networks + [_("What the connection is doing")]
    index = selector(rows, :header => status.split("\n").first.to_s, :cancel_index => -1)
    return if index == nil || index < 0
    if index >= networks.size
      display_text(status, :header => _("Network"))
      return
    end
    name = networks[index].sub(/\s*\(.*\)\s*\z/, "").strip
    password = input_text(_("Password (empty if it has none):"), :escapable => true)
    return if password == nil
    args = {"name" => name}
    args["password"] = password.to_s if password.to_s != ""
    run("connect_wifi", args)
  end

  # -------------------------------------------------------------- startup
  def startup
    now = read("get_autostart")
    on = !now.to_s.downcase.include?("does not")
    box = CheckBox.new(_("Start Titan with Windows"), :checked => on)
    back = Button.new(_("Back"))
    form = Form.new([box, back])
    form.cancel_button = back
    running = true
    back.on(:press) { running = false }
    box.on(:change) do
      run("set_autostart", {"enabled" => box.checked == true ? "true" : "false"})
    end
    form.focus
    while running
      loop_update
      form.update
    end
  end

  # --------------------------------------------------------------- shared
  def read(action)
    answer = TitanUI.ask(@bus, "system", action, {})
    answer.ok? ? answer.text.to_s : ""
  end

  def run(action, args)
    answer = TitanUI.perform(@bus, "system", action, args, :title => _("The computer"))
    return if answer == nil
    text = answer.text.to_s
    alert(text) if !answer.ok? && text != ""
  end

  def number_in(text, fallback)
    found = text.to_s[/\d+/]
    found ? found.to_i : fallback
  end

  def lines(text)
    text.to_s.split("\n").map { |line| line.strip.sub(/\A[-\u2022]\s*/, "") }
        .reject { |line| line.empty? || line.end_with?(":") }
  end
end
