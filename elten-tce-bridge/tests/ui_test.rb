# Drive every screen of the bridge against a stand-in Titan, with no Elten.
# What is being checked is not that it parses - it is that a user pressing
# Enter on a room gets that room's messages, that the settings screen shows
# the settings, and that nothing raises inside somebody else's program.

require "json"
require_relative "elten_stub"
BASE = File.expand_path("..", __dir__)
%w[titan_bus titan_ui titan_api titan_prefs titan_consent titan_sounds elten_main elten_news elten_screen titan_speech_output titan_watch titan_actions titan_settings
   titan_net titan_im titan_system titan_tools_ui titan_widgets titan_components titan_macros titan_cling titan_ai titan_shell
   titan_areas titan_console].each { |f| require_relative "#{BASE}/#{f}" }

REPORT = File.open(File.join(__dir__, "ui_test.txt"), "w")
def say(line) REPORT.puts(line); REPORT.flush; end
def check(name)
  $said = []; $pages = []
  yield
  say("PASS #{name}")
  $said.first(4).each { |line| say("     #{line}") }
rescue Exception => e
  say("FAIL #{name}: #{e.class}: #{e.message}")
  say("     #{e.backtrace.first(3).join("\n     ")}")
end

bus = TitanBus.new(:pipe => "\\\\.\\pipe\\TitanBusProbe")
# Before `start`, as the add-on does it: what this side SERVES travels
# in the hello, so a bus started first joins saying it serves nothing.
bus.serve(EltenNews.handlers)
bus.start
40.times { break if bus.connected?; sleep 0.1 }
say "connected to the stand-in Titan: #{bus.connected?}"
abort "no connection" if !bus.connected?

# --- the main window: the tab bar, the list, the status bar, launching ----
check("main window opens, lists applications, launches one") do
  console = TitanConsole.new(bus)
  console.instance_variable_set(:@views, console.read_views)
  console.instance_variable_set(:@list, ListBox.new)
  console.instance_variable_set(:@status, ListBox.new)
  console.fill
  console.fill_status
  rows = console.instance_variable_get(:@rows)
  raise "no applications" if rows.empty?
  # Titan's own name for it, from its own manager - not the folder.
  raise "wrong first app: #{rows[0][0]}" if rows[0][0] != "Edytor Tekstowy"
  status = console.instance_variable_get(:@status).options
  raise "no status bar" if status.size != 3
  console.instance_variable_get(:@list).index = 0
  console.open_row
  raise "did not launch" if !$said.any? { |l| l.include?("Edytor Tekstowy") }
end

check("the tab bar cycles through Titan's own views") do
  console = TitanConsole.new(bus)
  console.instance_variable_set(:@views, console.read_views)
  console.instance_variable_set(:@list, ListBox.new)
  console.fill
  names = []
  4.times do
    names.push(console.view["short_name"])
    console.cycle(1)
  end
  raise "wrong tabs: #{names.inspect}" if names != ["Applications", "Games", "Titan IM", "Cling"]
end

check("a component's own view falls through to its actions") do
  console = TitanConsole.new(bus)
  console.instance_variable_set(:@views, [{"id" => "macros", "short_name" => "Macros"}])
  console.instance_variable_set(:@list, ListBox.new)
  console.fill
  rows = console.instance_variable_get(:@rows)
  raise "no rows for a component view" if rows.empty?
end

# --- the settings -------------------------------------------------------
check("the settings screen reads Titan's own categories") do
  settings = TitanSettings.new(bus)
  rows = settings.categories_as_rows
  raise "wrong categories: #{rows.inspect}" if rows.map { |r| r[0] } != ["General", "Sounds"]
end

check("a category opens with a control per setting") do
  settings = TitanSettings.new(bus)
  $events = [[nil, :none]]
  categories = settings.send(:read)
  general = categories.first
  # build the form the way `edit` does, without running its loop
  items = general["items"]
  kinds = items.map { |i| i["kind"] }
  raise "wrong kinds: #{kinds.inspect}" if kinds != ["bool", "choice", "text"]
end

# --- Titan-Net ----------------------------------------------------------
check("Titan-Net says whose account it is showing") do
  client = TitanNetClient.new(bus)
  raise "wrong title: #{client.title}" if !client.title.include?("tito")
end

check("the rooms are a list, with type and password") do
  client = TitanNetClient.new(bus)
  rows = client.rows("rooms", "rooms") { |r| client.room_row(r) }
  raise "wrong rooms: #{rows.inspect}" if rows.size != 2
  raise "no password marker" if !rows[1][0].include?("password")
end

check("a room's messages are rows, newest readable in full") do
  client = TitanNetClient.new(bus)
  rows = client.rows("room_messages", "messages", {"room" => "General"}) { |m| client.message_row(m) }
  raise "no messages" if rows.size != 2
  raise "not attributed" if !rows[0][0].start_with?("ala: ")
  raise "no full text to open" if !rows[0][1]["text"].include?("Hello everybody")
end

check("the forum lists topics and opens one with its replies") do
  client = TitanNetClient.new(bus)
  rows = client.rows("topics", "topics") { |t| client.topic_row(t) }
  raise "no topics" if rows.empty?
  $events = []
  $script = []
  client.topic("3", "Welcome")
  # The topic is shown in a read-only field, not a dialog, so the reader's
  # own cursor and copy work on it - that is what to assert on.
  body = $last_form.fields.find { |f| f.is_a?(EditBox) }
  raise "topic not shown" if body.nil? || !body.text.include?("Hello and welcome.")
  raise "reply missing" if !body.text.include?("Thanks!")
  raise "not read-only" if (body.instance_variable_get(:@type).to_i & EditBox::Flags::ReadOnly) == 0
end

check("the mailbox lists mail and opens a message") do
  client = TitanNetClient.new(bus)
  rows = client.rows("mailbox", "mail", {"folder" => "inbox"}) { |m| client.mail_row(m) }
  raise "no mail" if rows.empty?
  raise "unread not marked" if !rows[0][0].include?("unread")
  $script = [nil]                       # the menu after reading: cancel
  client.one_mail("5", "A letter")
  raise "message not shown" if !$pages.last[1].include?("The whole message.")
end

# --- the shell ----------------------------------------------------------
check("the shell view is offered only when Titan is the shell") do
  shell = TitanShell.new(bus)
  raise "should be running" if !shell.running?
end

check("the taskbar lists real windows with their state") do
  shell = TitanShell.new(bus)
  rows = shell.window_rows
  raise "no windows" if rows.size != 2
  raise "active not marked" if !rows[0][0].include?("active")
  raise "minimised not marked" if !rows[1][0].include?("minimised")
end

check("the desktop and the notification area are lists") do
  shell = TitanShell.new(bus)
  raise "no desktop icons" if shell.desktop_rows.size != 3
  raise "numbering left in" if shell.desktop_rows[0][0] != "This PC"
  raise "no tray icons" if shell.tray_rows.size != 2
end

check("pressing a desktop icon opens it") do
  shell = TitanShell.new(bus)
  shell.open_row({"where" => "desktop", "name" => "Titan"}, "Titan")
  raise "did not open" if !$said.any? { |l| l.include?("open_desktop_item") }
end

# --- the areas ----------------------------------------------------------
check("the areas menu offers the shell as a view, not as actions") do
  areas = TitanAreas.new(bus)
  areas.instance_variable_set(:@shell_running, true)
  ids = areas.areas.map { |a| a[0] }
  raise "no shell view: #{ids.inspect}" if !ids.include?("shell_view")
  raise "voices missing" if !ids.include?("voices")
end

check("the computer is panels: a value is moved, a choice is a list") do
  bus.call_sync("probe", "forget", {})
  system = TitanSystem.new(bus)
  # It reads what IS before it offers to change anything.
  raise "the volume was not read" if system.number_in(system.read("get_volume"), 0) != 45
  raise "the brightness was not read" if system.number_in(system.read("get_brightness"), 0) != 70

  # A choice is offered from what the computer answered, and the name sent
  # is the name without the "[in use]" marker.
  $script = [1]                                   # pick the second device
  system.choose_device
  chosen = JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue []
  entry = chosen.find { |e| e[0] == "set_audio_device" }
  raise "no device was chosen: #{chosen.inspect}" if entry.nil?
  raise "the marker was sent as part of the name: #{entry[1]}" if entry[1].include?("[")

  # And the parameter names are the ones Titan really takes.
  bus.call_sync("probe", "forget", {})
  system.run("set_volume", {"percent" => "30"})
  sent = JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue []
  raise "set_volume did not reach Titan" if !sent.any? { |e| e[0] == "set_volume" && e[1] == "30" }
end

check("an add-on's actions are shown with what they do") do
  actions = TitanActions.new(bus)
  described = actions.send(:describe, "tedit")
  raise "no actions" if described.size != 2
  raise "no summary" if !described[0]["summary"].include?("Open a file")
end

# --- the voice ----------------------------------------------------------
check("Titan's voice is offered to Elten and speaks") do
  TitanSpeechOutput.start(bus)
  raise "not registered" if !SpeechOutput.outputs.include?(TitanSpeechOutput)
  raise "not available" if !TitanSpeechOutput.available?
  TitanSpeechOutput.set_rate(75)
  TitanSpeechOutput.speak_text("A line of speech.", :interrupt => true)
  raise "not speaking" if !TitanSpeechOutput.speaking?
  TitanSpeechOutput.stop
  raise "still speaking after stop" if TitanSpeechOutput.speaking?
end


# --- the bug this pair of checks exists for -----------------------------
# Reading through `titan.speak` with a rate makes Titan speak SYNCHRONOUSLY:
# the answer does not come back until the sentence is finished, so the next
# keystroke's "stop" arrives after the line it was meant to interrupt. These
# two checks are what keep the reader off that path.
check("a line is handed over at once, not when it has been spoken") do
  TitanSpeechOutput.start(bus)
  TitanSpeechOutput.set_rate(10)          # a rate far from Elten's middle
  started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
  TitanSpeechOutput.speak_text("A long line that would take a while to say.",
                               :interrupt => true)
  took = (Process.clock_gettime(Process::CLOCK_MONOTONIC) - started) * 1000
  raise "speaking blocked the caller for #{took.round} ms" if took > 100
end

check("an interrupt reaches Titan while it is still speaking") do
  bus.call_sync("probe", "forget", {})
  TitanSpeechOutput.start(bus)
  TitanSpeechOutput.set_rate(50)
  TitanSpeechOutput.speak_text("The first line, which is being spoken now.")
  sleep 0.2                                # it is on its way, as in a reader
  TitanSpeechOutput.stop
  sleep 0.3
  spoken = JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue []
  kinds = spoken.map { |entry| entry[0] }
  raise "the reader used titan.speak: #{kinds.inspect}" if kinds.include?("speak")
  raise "nothing was spoken: #{kinds.inspect}" if !kinds.include?("reader_speak")
  raise "the stop never arrived: #{kinds.inspect}" if !kinds.include?("stop")
  raise "the stop came before the line" if kinds.index("stop") < kinds.index("reader_speak")
end

check("a line the user has already moved past is never said") do
  bus.call_sync("probe", "forget", {})
  TitanSpeechOutput.start(bus)
  4.times { |i| TitanSpeechOutput.speak_text("Queued line #{i}.") }
  TitanSpeechOutput.stop                   # the user pressed a key
  sleep 0.4
  spoken = JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue []
  said = spoken.select { |entry| entry[0] == "reader_speak" }
  raise "every queued line was said anyway (#{said.size})" if said.size >= 4
  raise "the stop never arrived" if !spoken.map { |e| e[0] }.include?("stop")
end


# --- Titan IM, as a client ----------------------------------------------
check("Titan IM lists conversations of a service") do
  im = TitanIM.new(bus)
  rows = im.chats("whatsapp")
  raise "no chats: #{rows.inspect}" if rows.size != 2
  raise "chat not addressable" if rows[0][1]["chat"].to_s == ""
end

check("a conversation shows its messages and sends one") do
  bus.call_sync("probe", "forget", {})
  im = TitanIM.new(bus)
  $events = []
  im.conversation("whatsapp", "Ala", "Ala")
  body = $last_form.fields.find { |f| f.is_a?(ListBox) }
  raise "no messages shown" if body.nil? || body.options.size < 2
  # write a line and press Send, as a user would
  entry = $last_form.fields.find { |f| f.is_a?(EditBox) }
  send_button = $last_form.fields.find { |f| f.is_a?(Button) && f.label == _("Send") }
  entry.set_text("a reply")
  send_button.press
  sent = JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue []
  raise "nothing was sent: #{sent.inspect}" if !sent.any? { |e| e[0] == "im_send" && e[2] == "a reply" }
end

check("Titan IM offers Titan-Net people and the installed modules") do
  im = TitanIM.new(bus)
  raise "no Titan-Net people" if im.titan_net_people.empty?
  raise "no modules" if im.modules.empty?
end

check("Titan IM lists the services Titan's own view lists") do
  im = TitanIM.new(bus)
  names = im.services.map { |row| row[0] }
  %w[Telegram Messenger WhatsApp Titan-Net EltenLink].each do |wanted|
    raise "#{wanted} is missing: #{names.inspect}" if !names.include?(wanted)
  end
  telegram = im.services.find { |row| row[0] == "Telegram" }
  raise "Telegram is not openable" if telegram[1]["kind"] != "contacts"
end

check("the main window's Titan IM tab IS that service list") do
  console = TitanConsole.new(bus)
  console.instance_variable_set(:@views, [{"id" => "network", "short_name" => "Titan IM"}])
  console.instance_variable_set(:@list, ListBox.new)
  console.fill
  rows = console.instance_variable_get(:@rows)
  names = rows.map { |row| row[0] }
  raise "the services are not on the tab: #{names.inspect}" if !names.include?("WhatsApp")
  raise "the modules are missing" if !names.include?("ExampleIM")
  raise "a service row does not open a service" if rows[0][1]["do"] != "im_service"
end

# --- the categories Titan's non-visual face has -------------------------
check("the main window has Widgets and Components on its tab bar") do
  console = TitanConsole.new(bus)
  views = console.read_views
  console.instance_variable_set(:@views, views + [{"id" => "widgets", "short_name" => "Widgets"},
                                                  {"id" => "components", "short_name" => "Components"}])
  console.instance_variable_set(:@list, ListBox.new)
  console.instance_variable_set(:@tab, views.size)         # Widgets
  console.fill
  widgets = console.instance_variable_get(:@rows)
  raise "no widgets: #{widgets.inspect}" if widgets.size != 2
  console.instance_variable_set(:@tab, views.size + 1)     # Components
  console.fill
  components = console.instance_variable_get(:@rows)
  raise "no component menu entries" if components.size != 2
  console.instance_variable_get(:@list).index = 0
  console.open_row
  raise "the component action did not run" if !$said.any? { |l| l.include?("Ran Macro Manager") }
end

check("the shell is detected as data, not by reading a translated sentence") do
  shell = TitanShell.new(bus)
  raise "the shell should be running" if !shell.running?
end


# --- macros, Cling and the AI, each as its own screen -------------------
check("the Macro Manager lists macros and runs THE ONE THAT WAS CHOSEN") do
  bus.call_sync("probe", "forget", {})
  macros = TitanMacros.new(bus)
  rows = macros.rows
  raise "no macros: #{rows.inspect}" if rows.size < 3          # two plus "write a new one"
  raise "the shortcut is not shown" if !rows[0][0].include?("ctrl+alt+v")
  # **The name handed back is the NAME.** This row used to be built by
  # splitting the prose `list_macros` answers with, so what went back to
  # Titan was "- Voice demo (ctrl+alt+v) [tcs]" and every macro opened as
  # "There is no macro called ...". That is the whole of this assertion.
  raise "the name carries the label with it: #{rows[0][1].inspect}" if
    rows[0][1]["name"] != "Voice demo"
  $script = [true]                                             # confirm "Run?"
  macros.open_row(rows[0][1], rows[0][0])
  ran = JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue []
  raise "the macro did not run: #{ran.inspect}" if
    !ran.any? { |e| e[0] == "run_macro" && e[1] == "Voice demo" }
end

# --- the menu, as every other face of Titan builds it -------------------
check("the menu is Titan's GROUPS, not one flat list of Group: Entry") do
  console = TitanConsole.new(bus)
  console.instance_variable_set(:@api, TitanAPI.new(bus))
  groups = console.menu_groups(JSON.parse(
    bus.call_sync("titan", "menu", {}).text)["groups"])
  ids = groups.map { |group| group[0] }
  raise "the groups are not Titan's: #{ids.inspect}" if
    !ids.include?("program") || !ids.include?("ai")
  # Every entry is inside its group, and no label carries the group name
  # with it - "Program: Settings" in one long list was the bug.
  groups.each do |group|
    group[2].each do |entry|
      raise "an entry still carries its group: #{entry[1].inspect}" if
        entry[1].include?(": ")
    end
  end
  program = groups.find { |group| group[0] == "program" }
  labels = program[2].map { |entry| entry[0] }
  raise "the face's own entries are missing: #{labels.inspect}" if
    !labels.include?("__settings__") || !labels.include?("__help__")
end

check("Minimize and Bring Titan back are one entry, whichever applies") do
  console = TitanConsole.new(bus)
  console.instance_variable_set(:@api, TitanAPI.new(bus))
  groups = console.menu_groups(JSON.parse(
    bus.call_sync("titan", "menu", {}).text)["groups"])
  program = groups.find { |group| group[0] == "program" }
  ids = program[2].map { |entry| entry[0] }
  # The stand-in Titan says its window is up, so the entry is Minimize and
  # "Bring Titan back" - which would do nothing - is not offered at all.
  raise "both were offered: #{ids.inspect}" if
    ids.include?("__minimize__") && ids.include?("__restore__")
  raise "neither was offered: #{ids.inspect}" if
    !ids.include?("__minimize__") && !ids.include?("__restore__")
  raise "the wrong one for a window that is up: #{ids.inspect}" if
    !ids.include?("__minimize__")
end

# --- Elten's own notifications, the other way through the wall ----------
# A store the consent can really be written to and read back from, which
# is what `TitanPrefs.source` is in the running add-on.
class FakePrefsSource
  attr_reader :state
  def initialize(state = {}) @state = state; end
  def bridge_setting(key, fallback) @state.fetch(key, fallback) end
  def update_json(_name, _options = {})
    yield(@state)
    @state
  end
end

check("nothing about Elten leaves Elten before the question is answered") do
  bus.call_sync("probe", "forget", {})
  TitanPrefs.source = FakePrefsSource.new
  raise "it should not be answered yet" if TitanConsent.answered?
  EltenNews.start(bus)
  EltenNews.enabled = true
  def EltenNews.read_notifications
    [{:id => "1", :text => "Nowa wiadomosc", :cat => "message"}]
  end
  EltenNews.tick
  EltenNews.instance_variable_set(:@last_looked, 0.0)
  def EltenNews.read_notifications
    [{:id => "2", :text => "Odpowiedz", :cat => "forum"},
     {:id => "1", :text => "Nowa wiadomosc", :cat => "message"}]
  end
  EltenNews.tick
  sent = JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue []
  raise "something was shared unasked: #{sent.inspect}" if
    sent.any? { |e| e[0] == "notification" || e[0] == "report" }
end

check("the question is the one that was asked for, and No really means no") do
  source = FakePrefsSource.new
  TitanPrefs.source = source
  $said = []
  $script = [false]
  raise "No was read as yes" if TitanConsent.ensure_answered != false
  raise "the wording is not the one agreed: #{$said.inspect}" if
    !$said.first.to_s.include?("data stored on the Elten portal") ||
    !$said.first.to_s.include?("share the necessary data with TCE")
  raise "the answer was not remembered" if source.state["share_data"] != false
  raise "a refusal must not read as unanswered" if !TitanConsent.answered?
  raise "refused must not be granted" if TitanConsent.granted?
  # And it is asked ONCE: a second call must not put the question up again.
  $said = []
  TitanConsent.ensure_answered
  raise "it asked twice" if !$said.empty?
end

check("Elten's notifications reach Titan's notification centre") do
  bus.call_sync("probe", "forget", {})
  TitanPrefs.source = FakePrefsSource.new("share_data" => true)
  EltenNews.start(bus)
  EltenNews.enabled = true
  # The first look is what there IS - announcing it would be announcing the
  # past - so nothing is sent for it.
  def EltenNews.read_notifications
    [{:id => "1", :text => "Nowa wiadomosc od Dawida", :cat => "message"}]
  end
  EltenNews.tick
  sent = JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue []
  raise "the backlog was announced" if sent.any? { |e| e[0] == "notification" }
  # And then one really arrives.
  def EltenNews.read_notifications
    [{:id => "2", :text => "Odpowiedz na forum", :cat => "forum"},
     {:id => "1", :text => "Nowa wiadomosc od Dawida", :cat => "message"}]
  end
  EltenNews.instance_variable_set(:@last_looked, 0.0)
  EltenNews.tick
  sent = JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue []
  new_ones = sent.select { |e| e[0] == "notification" }
  raise "nothing reached Titan: #{sent.inspect}" if new_ones.size != 1
  raise "the wrong one: #{new_ones.inspect}" if
    new_ones[0][2] != "Odpowiedz na forum"
  raise "it did not say it is Elten's" if new_ones[0][1] != "Elten"
  raise "Titan was never told what Elten is" if !sent.any? { |e| e[0] == "report" }
end

# --- the shell: an identifier is not the first word of a sentence -------
check("Power sends the identifier, not the first word with its colon") do
  bus.call_sync("probe", "forget", {})
  shell = TitanShell.new(bus)
  $script = [0, true]              # choose the first entry, then confirm
  shell.power
  did = JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue []
  raise "nothing happened: #{$said.inspect}" if !did.any? { |e| e[0] == "power" }
  raise "the wrong thing: #{did.inspect}" if
    !did.any? { |e| e[0] == "power" && e[1] == "logoff" }
end

check("a drive opens by its letter, not by its label") do
  shell = TitanShell.new(bus)
  rows = shell.drive_rows
  raise "no drives: #{rows.inspect}" if rows.size != 2
  raise "the label became the path: #{shell.drive_letter(rows[0][1]["name"]).inspect}" if
    shell.drive_letter(rows[0][1]["name"]) != "C:"
  raise "a drive with no label was not read" if
    shell.drive_letter(rows[1][1]["name"]) != "D:"
end

check("a folder row is a NAME, not the whole line Titan wrote") do
  shell = TitanShell.new(bus)
  raise "the type came with it" if
    shell.entry_name("1. Documents - File folder") != "Documents"
  raise "the size came with it" if
    shell.entry_name("2. readme.txt - Text Document, 2 KB") != "readme.txt"
  # A name with a dash in it is kept whole: the type is after the LAST one.
  raise "a name with a dash was cut" if
    shell.entry_name("3. a - b.txt - Text Document, 1 KB") != "a - b.txt"
end

check("the file list drops the folder's own heading and the folder marks") do
  tools = TitanTools.new(bus)
  rows = tools.lines("C:\\Windows:\ndata/\nProgram Files/\nreadme.txt")
  raise "the heading is a row: #{rows.inspect}" if rows.include?("C:\\Windows:")
  raise "wrong rows: #{rows.inspect}" if rows != ["data/", "Program Files/", "readme.txt"]
end

check("a conversation opens as the PERSON, not as the line about them") do
  im = TitanIM.new(bus)
  rows = im.chats("telegram")
  raise "the heading is a row: #{rows.inspect}" if
    rows.any? { |row| row[0].to_s.end_with?(":") }
  raise "the count came with the name: #{rows[0][1].inspect}" if
    rows[0][1]["chat"] != "Ala"
  raise "the last message came with the name: #{rows[1][1].inspect}" if
    rows[1][1]["chat"] != "Family group"
  # The row still SHOWS everything Titan wrote - the unread count and the
  # last message are what makes a list of conversations readable.
  raise "the row lost what it says" if !rows[0][0].include?("3 unread")
end

check("contacts on one line are people, not one row saying all of them") do
  im = TitanIM.new(bus)
  names = im.contact_names("Online Titan-Net users: Ala, Borys")
  raise "wrong: #{names.inspect}" if names != ["Ala", "Borys"]
  raise "nobody online should be nobody" if
    !im.contact_names("Online Titan-Net users: (none online)").empty?
end

# --- the other direction: Titan asking Elten -----------------------------
check("Titan may ASK Elten, and the names travel in the hello") do
  declared = JSON.parse(bus.call_sync("probe", "served", {}).text) rescue []
  names = declared.map { |entry| entry["name"] }
  raise "the hello declared nothing: #{declared.inspect}" if names.empty?
  %w[status notifications news].each do |wanted|
    raise "#{wanted} is not offered to Titan: #{names.inspect}" if
      !names.include?(wanted)
  end
  raise "an action with no summary is one nothing can be told about" if
    declared.any? { |entry| entry["summary"].to_s.strip == "" }
end

check("an unasked-for Elten refuses to answer, in a sentence") do
  TitanPrefs.source = FakePrefsSource.new
  bus.serve(EltenNews.handlers)
  answered = JSON.parse(bus.call_sync(
    "probe", "invoke", {"action" => "notifications"}).text) rescue nil
  raise "no answer came back" if answered == nil
  raise "it answered anyway: #{answered.inspect}" if answered["ok"] != true
  raise "it shared: #{answered.inspect}" if !answered["result"].is_a?(String)
  raise "the refusal does not say why: #{answered["result"].inspect}" if
    !answered["result"].to_s.include?("permission")
end

check("with permission, Titan gets what Elten has RIGHT NOW") do
  TitanPrefs.source = FakePrefsSource.new("share_data" => true)
  def EltenNews.read_notifications
    [{:id => "7", :text => "Wiadomosc na teraz", :cat => "message"}]
  end
  bus.serve(EltenNews.handlers)
  answered = JSON.parse(bus.call_sync(
    "probe", "invoke", {"action" => "notifications"}).text) rescue nil
  raise "no answer came back" if answered == nil
  rows = answered["result"].is_a?(Hash) ? answered["result"]["notifications"] : nil
  raise "not a shape: #{answered.inspect}" if !rows.is_a?(Array)
  raise "wrong rows: #{rows.inspect}" if rows.size != 1 ||
    rows[0]["text"] != "Wiadomosc na teraz"
  news = JSON.parse(bus.call_sync(
    "probe", "invoke", {"action" => "news"}).text) rescue nil
  raise "news came back wrong: #{news.inspect}" if
    news["result"]["news"]["message"] != 1
end

check("an action nobody wrote is refused, not a dropped connection") do
  answered = JSON.parse(bus.call_sync(
    "probe", "invoke", {"action" => "no_such_thing"}).text) rescue nil
  raise "no answer came back" if answered == nil
  raise "it did not refuse: #{answered.inspect}" if answered["ok"] != false
  raise "it did not say which: #{answered.inspect}" if
    !answered["error"].to_s.include?("no_such_thing")
  # And the connection is still there afterwards, which is the whole point.
  raise "the connection went with it" if !bus.connected?
end

# --- Elten's own thread, and what only it can answer ---------------------
check("a job posted from another thread runs on Elten's and comes back") do
  EltenMain.drop_all
  answered = nil
  worker = Thread.new { answered = EltenMain.call(3.0) { 6 * 7 } }
  # Nothing runs until Elten's own pump does, which is the whole point.
  sleep 0.2
  raise "it ran without the pump" if answered != nil
  EltenMain.pump
  worker.join(3.0)
  raise "no answer: #{answered.inspect}" if answered == nil
  raise "wrong answer: #{answered.inspect}" if answered != [true, 42]
end

check("a job that raises is an error, not a lost caller") do
  EltenMain.drop_all
  answered = nil
  worker = Thread.new { answered = EltenMain.call(3.0) { raise "no" } }
  sleep 0.1
  EltenMain.pump
  worker.join(3.0)
  raise "the caller was left waiting" if answered == nil
  raise "it was reported as success: #{answered.inspect}" if answered[0] != false
  raise "it does not say what: #{answered.inspect}" if !answered[1].include?("no")
end

check("nobody waits for ever for a tick that is not coming") do
  EltenMain.drop_all
  started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
  answered = EltenMain.call(0.4) { 1 }
  waited = Process.clock_gettime(Process::CLOCK_MONOTONIC) - started
  raise "it did not give up: #{answered.inspect}" if answered[0] != false
  raise "it waited #{waited}s" if waited > 2.0
  raise "it does not say why: #{answered.inspect}" if
    !answered[1].to_s.include?("did not answer")
end

check("Elten's screen is read as its controls, with the focused one marked") do
  list = ListBox.new(%w[Ala Borys], :header => "Wiadomosci")
  field = EditBox.new("Tresc", :text => "czesc")
  button = Button.new("Wyslij")
  form = Form.new([list, field, button])
  described = EltenScreen.describe(form)
  raise "a form must be opened out: #{described.inspect}" if
    described["kind"] != "form"
  kinds = described["controls"].map { |entry| entry["kind"] }
  raise "wrong controls: #{kinds.inspect}" if kinds != %w[list field button]
  first = described["controls"][0]
  raise "the list did not say what it is on: #{first.inspect}" if
    first["current"] != "Ala" || first["count"] != 2
  raise "the keyboard was not placed" if first["focused"] != true
  raise "the field lost its text" if described["controls"][1]["text"] != "czesc"
  raise "the button lost its label" if described["controls"][2]["label"] != "Wyslij"
end

check("the screen is Elten's data, and is refused unasked") do
  TitanPrefs.source = FakePrefsSource.new
  raise "it read the screen unasked" if !EltenScreen.read_screen.is_a?(String)
  raise "it does not say why" if !EltenScreen.read_screen.include?("permission")
  raise "the programs were listed unasked" if
    !EltenScreen.list_programs.is_a?(String)
  raise "a program was opened unasked" if
    !EltenScreen.run_program("anything").is_a?(String)
end

check("with permission, Titan gets Elten's screen through the bus") do
  TitanPrefs.source = FakePrefsSource.new("share_data" => true)
  bus.serve(EltenNews.handlers.merge(EltenScreen.handlers))
  # Elten's pump, for as long as this takes: in the real add-on it is the
  # extension tick, and here it is a thread standing in for one.
  pumping = true
  pump = Thread.new { while pumping; EltenMain.pump; sleep 0.02; end }
  begin
    $speech_lasttext = "Wiadomosci, lista, 2 elementy"
    answered = JSON.parse(bus.call_sync(
      "probe", "invoke", {"action" => "screen"}).text) rescue nil
    raise "no answer: #{answered.inspect}" if answered == nil
    raise "it refused: #{answered.inspect}" if answered["ok"] != true
    screen = answered["result"]
    raise "not a shape: #{screen.inspect}" if !screen.is_a?(Hash)
    raise "what Elten said was not read: #{screen.inspect}" if
      screen["said"] != "Wiadomosci, lista, 2 elementy"
  ensure
    pumping = false
    pump.join(1.0)
  end
end

check("the Titan Script reference is readable from the bridge") do
  macros = TitanMacros.new(bus)
  macros.open_row({"do" => "language"}, "")
  raise "no reference shown" if $pages.empty? || !$pages.last[1].include?("Titan Script")
end

check("Cling lists Klango applications and starts THE ONE THAT WAS CHOSEN") do
  bus.call_sync("probe", "forget", {})
  cling = TitanCling.new(bus)
  rows = cling.rows
  raise "no applications: #{rows.inspect}" if rows.size != 2
  raise "the name is not shown" if !rows[0][0].include?("Mole No More")
  # The identifier goes back, not the line. Cling matches `id` first, and
  # handing it the whole line was "There is no Cling application called
  # '- Mole No More (mole, grid_hunt): ...'".
  raise "the id is not what goes back: #{rows[0][1].inspect}" if
    rows[0][1]["name"] != "mole"
  $script = [true]
  cling.open_row(rows[0][1], rows[0][0])
  started = JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue []
  raise "Cling did not start it" if
    !started.any? { |e| e[0] == "cling_run" && e[1] == "mole" }
end

check("the AI screen is offered only when Titan has AI, and answers here") do
  bus.call_sync("probe", "forget", {})
  ai = TitanAI.new(bus)
  raise "AI should be available" if !ai.available?
  $script = ["Co potrafisz?"]
  ai.open_row({"do" => "ask"}, "")
  asked = JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue []
  raise "the question never reached Titan" if !asked.any? { |e| e[0] == "ask_ai" }
  raise "the answer was not shown" if $pages.empty? || !$pages.last[1].include?("hello")
  # Asking WITHOUT tools is the default: nothing may act unless asked to.
  entry = asked.find { |e| e[0] == "ask_ai" }
  raise "asking defaulted to acting" if entry[2].to_s == "true"
end

check("the shell's Start menu has Titan's own branches") do
  shell = TitanShell.new(bus)
  labels = shell.start_rows.map { |row| row[0] }
  [_("Applications"), _("Games"), _("Macros"), _("Settings")].each do |wanted|
    raise "#{wanted} missing from the Start menu: #{labels.inspect}" if !labels.include?(wanted)
  end
end


# --- the things nothing else exposes ------------------------------------
check("the Buffer System is browsable, category by buffer") do
  areas = TitanAreas.new(bus)
  rows = areas.buffer_rows
  raise "no buffers: #{rows.inspect}" if rows.empty?
  row = rows.find { |entry| entry[1].is_a?(Hash) }
  raise "no openable buffer" if row.nil?
  raise "the count is not shown" if !row[0].include?("(")
  areas.buffers_open(row[1], row[0])
  raise "the buffer was not shown" if $pages.empty? || !$pages.last[1].include?("hello there")
end

check("the notification centre is listed and can be emptied") do
  areas = TitanAreas.new(bus)
  rows = areas.notification_rows
  raise "no notifications: #{rows.inspect}" if rows.size < 2
  clear = rows.find { |entry| entry[1].is_a?(Hash) && entry[1]["do"] == "clear" }
  raise "no way to empty it" if clear.nil?
  $script = [true]
  areas.buffers_open(clear[1], clear[0])
  raise "it was not emptied" if !$said.any? { |line| line.include?("Cleared") }
end


check("the Component Manager lists components with their state and toggles one") do
  bus.call_sync("probe", "forget", {})
  manager = TitanComponents.new(bus)
  rows = manager.rows
  raise "no components: #{rows.inspect}" if rows.empty?
  raise "the state is not shown: #{rows[0][0]}" if !rows[0][0].include?(_("Enabled"))
  $script = [true]                                   # confirm "switch off?"
  manager.toggle(rows[0][1], rows[0][0])
  raise "it was not switched" if !$said.any? { |line| line.include?("disable") || line.include?("Ran") }
end


# --- the add-on's own contract with Elten -------------------------------
check("activate registers the voice and the setting, and leaves Elten's menu alone") do
  load File.join(BASE, "__app.rb")
  ProgramTCEBridge.instance_variable_set(:@bus, bus)   # the test's own bus
  ProgramTCEBridge.activate
  raise "no extension registered" if $extension.nil?
  # Elten's main menu belongs to Elten: the manifest already puts this
  # add-on in the programs menu, and everything TCE has is inside its own
  # window. Adding four more top-level entries was clutter.
  raise "it put entries in Elten's menu: #{$extension.commands.map { |c| c.label }.inspect}" if !$extension.commands.empty?
  raise "no settings" if $extension.settings_builder.nil?
  builder = $extension.settings_builder
  labels = builder.booleans.map { |entry| entry[1] } + builder.integers.map { |entry| entry[1] }
  [_("Say when something arrives on Titan-Net"),
   _("How often to look, in minutes"),
   _("Read the AI's answer out loud"),
   _("Ask before starting a TCE application")].each do |wanted|
    raise "#{wanted} is not in Elten's settings: #{labels.inspect}" if !labels.include?(wanted)
  end
  # The interval is offered in minutes and bounded, because every look is a
  # call into Titan's own interface thread.
  minutes = builder.integers.find { |entry| entry[0] == "news_minutes" }
  raise "the interval has no range" if minutes.nil? || minutes[2].nil?
  raise "the range is wrong: #{minutes[2]}" if minutes[2].first < 1 || minutes[2].last > 60
  # **TCE's settings are reachable from the add-on's own settings**, which
  # is where somebody looks for "the settings of the thing I am
  # configuring". It is a real action button, so it really opens something.
  shortcut = builder.actions.find { |entry| entry[0] == "tce_settings" }
  raise "no shortcut to TCE's settings: #{builder.actions.inspect}" if shortcut.nil?
  raise "the shortcut does nothing" if !shortcut[2].respond_to?(:call)
  # And the sharing is a switch of its own, so a Yes can be taken back.
  raise "the consent cannot be changed: #{labels.inspect}" if
    !labels.include?(_("Share Elten's data with TCE"))

  # And what the settings say is what the watcher does.
  TitanWatch.interval = 7 * 60
  raise "the interval is not honoured: #{TitanWatch.interval}" if TitanWatch.interval != 420.0
  raise "the voice is not registered" if !SpeechOutput.outputs.include?(TitanSpeechOutput)
  # TCE's lists belong in Elten's own quick actions - a list the user puts
  # together - rather than in its main menu.
  labels = ($quickactions || []).map { |entry| entry[1] }
  [_("TCE applications"), _("TCE games")].each do |wanted|
    raise "#{wanted} is not a quick action: #{labels.inspect}" if !labels.include?(wanted)
  end
  # The bridge's own window is in Elten's programs list already; a quick
  # action for it would be a second way to the same place.
  raise "the window is duplicated as a quick action" if labels.include?(_("TCE"))
end

check("Titan-Net opens its own main screen, not a list of its parts") do
  entries = TitanNetClient.entries
  first = entries.first
  raise "the first entry is not Titan-Net itself: #{first.inspect}" if first[1]["screen"] != "main"
  client = TitanNetClient.new(bus)
  $events = []
  client.open("main")
  raise "no screen was put up" if $last_form.nil?
  list = $last_form.fields.find { |f| f.is_a?(ListBox) }
  raise "the main screen has no list" if list.nil?
end

check("the news watcher announces only what is NEW, and never on the first look") do
  TitanWatch.start(bus)
  TitanWatch.absorb('{"unread_messages": 2, "unread_forum_topics": 1}')
  $said = []
  TitanWatch.announce_pending
  raise "it announced what was already there" if $said.any? { |l| l.start_with?("speak:") }
  TitanWatch.absorb('{"unread_messages": 4, "unread_forum_topics": 1}')
  TitanWatch.announce_pending
  spoken = $said.find { |l| l.start_with?("speak:") }
  raise "nothing was announced" if spoken.nil?
  raise "wrong announcement: #{spoken}" if !spoken.include?("Titan-Net")
  # Going DOWN is somebody reading their messages, which is not news.
  $said = []
  TitanWatch.absorb('{"unread_messages": 0, "unread_forum_topics": 1}')
  TitanWatch.announce_pending
  raise "it announced messages being read" if $said.any? { |l| l.start_with?("speak:") }
end


# --- the rest of Titan-Net's own window ---------------------------------
check("the Feedback Hub is a list of what people asked for") do
  client = TitanNetClient.new(bus)
  rows = client.rows("feedback", "items") { |i| client.feedback_row(i) }
  raise "no items: #{rows.inspect}" if rows.size != 2
  raise "the kind is not shown" if !rows[0][0].include?("idea")
  raise "the votes are not shown" if !rows[0][0].include?("3")
  $script = [nil]                                  # the menu after reading
  client.feedback_item("4", "Wiecej glosow")
  raise "the item was not shown" if $pages.empty? || !$pages.last[1].include?("Prosze o wiecej")
  raise "the comments are missing" if !$pages.last[1].include?("Popieram")
end

check("the app repository lists packages and downloads one") do
  bus.call_sync("probe", "forget", {})
  client = TitanNetClient.new(bus)
  rows = client.rows("repository", "apps") { |a| client.app_row(a) }
  raise "no packages: #{rows.inspect}" if rows.size != 1
  $script = ["download", true]                     # menu choice, then confirm
  client.repository_menu(rows[0][1], rows[0][0])
  got = JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue []
  raise "it was not downloaded" if !got.any? { |e| e[0] == "download" }
end

check("the announcements can be read") do
  client = TitanNetClient.new(bus)
  rows = client.rows("announcements", "files") { |f| client.announcement_row(f) }
  raise "no announcements" if rows.empty?
  client.open_entry(rows[0][1], rows[0][0])
  raise "not shown" if $pages.empty? || !$pages.last[1].include?("wylaczony")
end

check("a component's view lists what it HAS, not what it can be told to do") do
  console = TitanConsole.new(bus)
  console.instance_variable_set(:@views, [{"id" => "macros", "short_name" => "Macros"}])
  console.instance_variable_set(:@list, ListBox.new)
  console.fill
  rows = console.instance_variable_get(:@rows)
  labels = rows.map { |r| r[0] }
  raise "it listed actions: #{labels.inspect}" if labels.any? { |l| l.include?("list macros") }
  raise "it should open the Macro Manager: #{labels.inspect}" if rows[0][1]["do"] != "screen"
end


check("a widget is used, not merely listed: it reads, moves and presses") do
  widgets = TitanWidgets.new(bus)
  rows = widgets.rows
  raise "no widgets: #{rows.inspect}" if rows.size != 2
  raise "the real one is missing" if rows[0][0] != "Szybkie ustawienia"
  # Open it: the surface says where the cursor is.
  $events = []
  $said = []
  widgets.use(rows[0][1], rows[0][0])
  surface = $last_form.fields.find { |f| f.is_a?(Static) }
  raise "no surface" if surface.nil?
  raise "the cursor is not read: #{surface.label}" if !surface.label.include?("Szybki start")
  raise "it was not spoken" if !$said.any? { |l| l.include?("Szybki start") }
end


check("every way into Titan-Net lands on Titan-Net's own main screen") do
  # The client's main screen is the one whose first tab is the rooms; the
  # list of who is online is one corner of it and must not stand in for it.
  opened = proc do |what|
    $events = []
    $last_form = nil
    what.call
    list = $last_form && $last_form.fields.find { |f| f.is_a?(ListBox) }
    raise "nothing was opened" if list.nil?
    list.header.to_s
  end

  from_service = opened.call(proc { TitanIM.new(bus).open_service("titan_net", "titannet", "Titan-Net") })
  raise "Titan IM opened a corner of it: #{from_service}" if !from_service.include?(_("Main menu"))

  from_entry = opened.call(proc { TitanNetClient.new(bus).open("main") })
  raise "the entry opened a corner of it: #{from_entry}" if !from_entry.include?(_("Main menu"))

  # And the account it is speaking as is in the title, so it is never vague
  # about whose Titan-Net this is.
  raise "the account is not named: #{from_entry}" if !from_entry.include?("tito")
end


# --- the last of the action lists, turned into screens ------------------
check("the gamepad screen lists MODES, not functions") do
  bus.call_sync("probe", "forget", {})
  tools = TitanTools.new(bus)
  rows = tools.gamepad_rows
  raise "no modes: #{rows.inspect}" if rows.size != 3
  raise "it listed functions" if rows.any? { |r| r[0].include?("set_mode") }
  raise "the active one is not marked" if !rows[0][0].include?("active")
  raise "the mode is not addressable" if rows[1][1]["mode"] != "Screen reader mode"
end

check("the areas menu offers screens, not add-ons to be told what to do") do
  areas = TitanAreas.new(bus)
  areas.instance_variable_set(:@shell_running, false)
  areas.instance_variable_set(:@ai_available, true)
  ids = areas.areas.map { |entry| entry[0] }
  %w[gamepad_view clock_view terminal_view files_view browser_view
     macros_view cling_view widgets components_view].each do |wanted|
    raise "#{wanted} is missing: #{ids.inspect}" if !ids.include?(wanted)
  end
  # The bare add-on ids are gone from the menu; the generic screen is
  # reached from a row or from "Everything installed".
  raise "a bare add-on is still offered" if ids.include?("gamepad") || ids.include?("web")
end


check("the assistant is a conversation, and it opens with what was said before") do
  bus.call_sync("probe", "forget", {})
  ai = TitanAI.new(bus)
  rows = ai.history
  raise "the history is empty" if rows.size < 2
  raise "the speaker is not named: #{rows[0][0]}" if !rows[0][0].start_with?(_("You"))
  raise "the whole message is not kept" if !rows[1][1].include?("Duzo rzeczy")

  # Sending adds to the same conversation.
  $events = []
  ai.chat
  list = $last_form.fields.find { |f| f.is_a?(ListBox) }
  entry = $last_form.fields.find { |f| f.is_a?(EditBox) }
  send_button = $last_form.fields.find { |f| f.is_a?(Button) && f.label == _("Send") }
  raise "the chat has no list" if list.nil?
  raise "the chat has no field" if entry.nil?
  before = list.options.size
  entry.set_text("Jak sie masz?")
  send_button.press
  raise "the question never reached Titan" if !$said.any? { |l| l.include?("hello") }
  raise "the conversation did not grow" if list.options.size <= before
  raise "the field was not cleared" if entry.text.to_s != ""
end

check("the main window has a button for the assistant") do
  console = TitanConsole.new(bus)
  console.instance_variable_set(:@views, console.read_views)
  # open() builds the form and then pumps; with no scripted events the stub
  # presses Close at once, so this is the window as it was built.
  $events = []
  console.open
  labels = $last_form.fields.select { |f| f.is_a?(Button) }.map { |f| f.label }
  raise "no assistant button: #{labels.inspect}" if !labels.include?(_("AI Assistant"))
end


check("Titan-Net's menu is Titan's own menu, in Titan's own order") do
  # src/network/titan_net_gui.py, TitanNetMainWindow: What's New, Chat
  # Rooms, Online Users, Private Messages, Blocked Users, Mail, Forum, App
  # Repository, Feedback Hub, Interactive Games.
  wanted = ["What's New", "Chat Rooms", "Online Users", "Private Messages",
            "Blocked Users", "Mail", "Forum", "App Repository",
            "Feedback Hub", "Interactive Games"]
  got = TitanNetClient::MENU.map { |entry| entry[1] }
  raise "the menu does not match Titan's: #{got.inspect}" if got != wanted

  $events = []
  TitanNetClient.new(bus).main
  list = $last_form.fields.find { |f| f.is_a?(ListBox) }
  raise "no menu on the screen" if list.nil?
  raise "the first entry is not What's New: #{list.options.first}" if list.options.first != _("What's New")
  raise "the account is not offered" if !list.options.include?(_("My account"))
end


# --- the point of the rewrite -------------------------------------------
check("the lists come from Titan's own managers, through one typed call") do
  bus.call_sync("probe", "bridge_on", {})
  bus.call_sync("probe", "forget", {})
  api = TitanAPI.new(bus)
  raise "the typed surface is not there" if !api.available?
  raise "wrong version: #{api.api}" if api.api != TitanAPI::WANTED

  console = TitanConsole.new(bus)
  apps = console.inventory("app")
  raise "the applications are not Titan's own: #{apps.inspect}" if apps.first != "Edytor Tekstowy"
  games = console.inventory("game")
  raise "the games are not Titan's own: #{games.inspect}" if games.first != "Cult of the Lamb"

  # Opened through the manager that owns it, by the name the list gave.
  console.launch("Cult of the Lamb", "game")
  opened = JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue []
  raise "it did not go through games.open: #{opened.inspect}" if !opened.any? { |e| e[0] == "games.open" }
end

check("a Titan that is a version behind is told about, and still works") do
  bus.call_sync("probe", "bridge_off", {})
  api = TitanAPI.new(bus)
  raise "it should not be available" if api.available?
  message = api.unavailable_message
  raise "the reason is not named: #{message}" if !message.include?(_("Restart Titan") .split(" ").first)

  # And the screens fall back to the action path rather than breaking.
  console = TitanConsole.new(bus)
  apps = console.inventory("app")
  raise "the fallback list is empty" if apps.empty?
  bus.call_sync("probe", "bridge_on", {})
end


check("a screen works without the application class, on the defaults") do
  # A screen that reached into the Program class could not be opened
  # without it. TitanPrefs answers with defaults when nobody has been
  # handed over, which is what makes the screens usable on their own.
  TitanPrefs.source = nil
  raise "the defaults are wrong" if !TitanPrefs.announce_news?
  raise "starting should not ask by default" if TitanPrefs.confirm_launch?
  raise "the interval default is wrong" if TitanPrefs.news_minutes != 3

  # And what the application keeps is what they answer.
  keeper = Object.new
  def keeper.bridge_setting(key, fallback)
    {"confirm_launch" => true, "news_minutes" => 9}.fetch(key, fallback)
  end
  TitanPrefs.source = keeper
  raise "the setting was not read" if !TitanPrefs.confirm_launch?
  raise "the interval was not read" if TitanPrefs.news_minutes != 9
  TitanPrefs.source = nil
end


check("the bridge can sound like TCE, and is silent when told to be") do
  bus.call_sync("probe", "bridge_on", {})
  bus.call_sync("probe", "forget", {})
  TitanSounds.bus = bus
  TitanPrefs.source = nil                       # defaults: TCE sounds on

  # Titan plays its own sound per kind of news; so does this, and it is the
  # same name out of the same theme.
  raise "the mapping is wrong" if TitanSounds::FOR_NEWS["unread_messages"] != "titannet/new_message.ogg"
  TitanSounds.for_news("unread_forum_topics")
  sleep 0.3
  played = JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue []
  entry = played.find { |e| e[0] == "sound" }
  raise "nothing was played: #{played.inspect}" if entry.nil?
  raise "the wrong sound: #{entry[1]}" if entry[1] != "titannet/new_feedpost.ogg"

  # Off means off: no call is made at all.
  quiet = Object.new
  def quiet.bridge_setting(key, fallback)
    key == "tce_sounds" ? false : fallback
  end
  TitanPrefs.source = quiet
  bus.call_sync("probe", "forget", {})
  TitanSounds.play(TitanSounds::NEW_MESSAGE)
  sleep 0.2
  after = JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue []
  raise "it played with the setting off" if after.any? { |e| e[0] == "sound" }
  TitanPrefs.source = nil
end


check("the bridge's own screens sound like TCE, from TCE's own theme") do
  bus.call_sync("probe", "bridge_on", {})
  bus.call_sync("probe", "forget", {})
  TitanSounds.bus = bus
  TitanPrefs.source = nil

  # Opening a screen, moving along the tab bar and leaving it are TCE's own
  # cues - the same files TCE plays for the same things, out of whichever
  # theme the user chose there.
  screen = TitanUI::Screen.new(bus, "T", [["one", proc { [["a", {}]] }],
                                          ["two", proc { [["b", {}]] }]])
  $events = []
  screen.open
  sleep 0.4
  played = (JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue [])
             .select { |e| e[0] == "sound" }.map { |e| e[1] }
  raise "the screen did not open with TCE's sound: #{played.inspect}" if !played.include?("ui/tui_open.ogg")
  raise "it did not close with TCE's sound: #{played.inspect}" if !played.include?("ui/tui_close.ogg")

  bus.call_sync("probe", "forget", {})
  screen.instance_variable_set(:@tab, 0)
  screen.send(:cycle, 1)
  sleep 0.3
  switched = (JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue [])
               .select { |e| e[0] == "sound" }.map { |e| e[1] }
  raise "the tab bar is silent: #{switched.inspect}" if !switched.include?("ui/switch_category.ogg")
end

check("with TCE's sounds on, Elten's own cues step aside") do
  bus.call_sync("probe", "bridge_on", {})
  TitanSounds.bus = bus
  TitanPrefs.source = nil                       # TCE sounds on by default

  # Elten's ListBox guards only its `play_sound` calls with `silent`, never
  # its speech - so quieting it removes the doubled focus sound and leaves
  # the item announced exactly as before.
  quiet = TitanSounds.quiet(ListBox.new([], :header => "x"))
  raise "Elten's list would still make its own noises" if quiet.silent != true

  off = Object.new
  def off.bridge_setting(key, fallback) key == "tce_sounds" ? false : fallback end
  TitanPrefs.source = off
  loud = TitanSounds.quiet(ListBox.new([], :header => "x"))
  raise "it was quieted with the setting off" if loud.silent == true
  TitanPrefs.source = nil
end

check("the status bar and the list are entered with TCE's own two cues") do
  bus.call_sync("probe", "bridge_on", {})
  bus.call_sync("probe", "forget", {})
  TitanSounds.bus = bus
  TitanPrefs.source = nil

  # TCE plays `statusbar` when the keyboard moves TO the status bar and
  # `applist` when it moves back to the list (gui.py's Tab handling), and
  # Elten's Form triggers :focus on the field Tab lands on - the same moment.
  console = TitanConsole.new(bus)
  status = ListBox.new([], :header => "s")
  list = ListBox.new([], :header => "l")
  console.instance_variable_set(:@status, status)
  console.instance_variable_set(:@list, list)
  status.on(:focus) { TitanSounds.play(TitanSounds::STATUS) }
  list.on(:focus) { TitanSounds.play(TitanSounds::LIST) }
  status.trigger(:focus)
  list.trigger(:focus)
  sleep 0.3
  heard = (JSON.parse(bus.call_sync("probe", "spoken", {}).text) rescue [])
            .select { |e| e[0] == "sound" }.map { |e| e[1] }
  raise "moving to the status bar was silent: #{heard.inspect}" if !heard.include?("ui/statusbar.ogg")
  raise "moving back to the list was silent: #{heard.inspect}" if !heard.include?("ui/applist.ogg")
end

bus.stop
say "done"
REPORT.close
exit!(0)
