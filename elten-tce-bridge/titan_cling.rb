# Cling, in Elten - the Klango applications Titan can run.
#
# Titan's own Cling window is a list of the applications it has found, with
# what each one is and how it scored; this is that list. Running one starts
# it in TITAN, where the sound is: a Klango application is heard, not read,
# and Titan is the platform underneath it. What Elten gets is the list, the
# details, the scores and the account - the parts that are words.

class TitanCling
  def initialize(bus)
    @bus = bus
    @api = TitanAPI.new(bus)
  end

  def open
    return if !TitanUI.require_tce(@bus)
    tabs = [[_("Applications"), proc { rows }],
            [_("Cling"), proc { about_rows }]]
    TitanUI::Screen.new(@bus, _("Cling"), tabs,
                        :on_open => method(:open_row),
                        :on_menu => method(:row_menu)).open
  end

  # **The identifier is what goes back, not the line.**
  # `cling.list_applications` answers the prose a model reads - a heading
  # and then "- Mole No More (mole, grid_hunt): a game of moles" - and
  # splitting that up handed the whole line back as the name, so every
  # application opened as "There is no Cling application called '- Mole No
  # More (mole, grid_hunt): ...'". `cling.list` gives each application's own
  # `id`, which is the first thing Cling matches on.
  def rows
    answer = @api.call("cling.list", {}, :title => _("Reading..."))
    if !answer.ok?
      return [[answer.error.to_s == "" ? @api.unavailable_message : answer.error.to_s,
               nil]]
    end
    found = answer["applications"] || []
    return [[_("No Klango applications are installed."), nil]] if found.empty?
    found.map do |app|
      label = app["name"].to_s
      label += " - %s" % app["summary"].to_s if app["summary"].to_s != ""
      # An application Cling has found but cannot start says so on its own
      # row rather than failing when it is pressed.
      label = "%s (%s)" % [label, app["why"].to_s] if app["locked"] == true
      [label, app["locked"] == true ? nil : {"do" => "run",
                                             "name" => app["id"].to_s,
                                             "label" => app["name"].to_s}]
    end
  end

  def about_rows
    [[_("My account and scores"), {"do" => "account"}],
     [_("Is Cling working"), {"do" => "status"}],
     [_("Install a Klango application..."), {"do" => "install"}]]
  end

  def open_row(value, label)
    return if !value.is_a?(Hash)
    case value["do"]
    when "run"
      return if !confirm(_("Start %s in Titan?") % (value["label"] || value["name"]))
      answer = TitanUI.perform(@bus, "cling", "run", {"name" => value["name"]},
                               :title => label)
      TitanUI.tell(answer, label) if answer != nil
    when "account" then page("account", {}, _("My account and scores"))
    when "status"  then page("status", {}, _("Cling"))
    when "install"
      path = input_text(_("The folder to install from:"), :escapable => true)
      return if path == nil || path.to_s.strip == ""
      answer = TitanUI.perform(@bus, "cling", "install", {"path" => path.to_s},
                               :title => _("Installing..."))
      TitanUI.tell(answer, _("Cling")) if answer != nil
    end
  end

  def row_menu(value, label)
    return if !value.is_a?(Hash) || value["do"] != "run"
    name = value["name"].to_s
    chosen = select_action([["details", _("What it is")],
                            ["scores", _("Its scores")],
                            ["emulate", _("Run its own Klango code")]],
                           :header => label)
    return if chosen == nil
    page(chosen, {"name" => name}, label)
  end

  def page(action, args, header)
    answer = TitanUI.ask(@bus, "cling", action, args, :title => header)
    text = answer.text.to_s
    text = _("Nothing came back.") if text.strip == ""
    display_text(text, :header => header)
  end
end
