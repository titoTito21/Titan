# Every function the bridge depends on, against the REAL Titan.
#
# Read-only by design: it lists, reads and describes, and the only thing it
# changes is that Titan says one short line and is then told to stop - which
# is the one behaviour that cannot be proved any other way.
#
#     ruby tests/live_probe.rb          (with Titan running)

require "json"
require_relative "../titan_bus"

REPORT = File.open(File.join(__dir__, "live_probe.txt"), "w")
def say(line)
  REPORT.puts(line); REPORT.flush
end

bus = TitanBus.new
bus.start
40.times { break if bus.connected?; sleep 0.25 }
if !bus.connected?
  say "NOT CONNECTED: #{bus.last_error}"
  REPORT.close
  exit!(1)
end
say "connected to the real Titan"

addons = bus.list_sync
say "add-ons Titan offers: #{addons.size}"
titan = addons.find { |a| a["id"] == "titan" }
say "titan actions: #{(titan ? titan['actions'] : []).size}"
%w[reader_speak set_speech_rate stop_speech speaking views status_bar menu
   inventory addon_actions components widgets buffers notifications].each do |name|
  have = titan != nil && titan["actions"].include?(name)
  say "  #{have ? 'present' : 'MISSING'}: titan.#{name}"
end

def probe(bus, addon, action, args = {}, note = "")
  answer = bus.call_sync(addon, action, args, :timeout => 25)
  text = answer.text.to_s
  head = text.gsub(/\s+/, " ")[0, 150]
  say(format("%-34s %-4s %s", "#{addon}.#{action}", answer.ok? ? "ok" : "FAIL", head))
  answer
end

say ""
say "--- the main window ---"
probe(bus, "titan", "views")
probe(bus, "titan", "status_bar")
probe(bus, "titan", "menu")
probe(bus, "titan", "inventory", {"kind" => "app"})
probe(bus, "titan", "inventory", {"kind" => "game"})
probe(bus, "titan", "inventory", {"kind" => "im_module"})
probe(bus, "titan", "components")
probe(bus, "titan", "widgets")
probe(bus, "titan", "addon_actions", {"addon" => "titan"})

say ""
say "--- the less obvious ones ---"
probe(bus, "titan", "buffers")
probe(bus, "titan", "notifications")
probe(bus, "titan", "list_tts_engines")
probe(bus, "titan", "list_media_catalogs")

say ""
say "--- the settings ---"
answer = probe(bus, "settings", "screen")
if answer.ok?
  data = JSON.parse(answer.text) rescue {}
  categories = data["categories"] || []
  items = categories.sum { |c| (c["items"] || []).size }
  say "  #{categories.size} categories, #{items} settings"
  say "  first: #{categories.first && categories.first['name']}"
  kinds = categories.flat_map { |c| (c["items"] || []).map { |i| i["kind"] } }.tally rescue {}
  say "  kinds: #{kinds.inspect}"
end

say ""
say "--- Titan-Net ---"
probe(bus, "titannet", "whoami")
probe(bus, "titannet", "rooms")
probe(bus, "titannet", "online")
probe(bus, "titannet", "topics", {"limit" => 5})
probe(bus, "titannet", "mailbox", {"folder" => "inbox"})

say ""
say "--- Titan IM ---"
probe(bus, "im", "status")

say ""
say "--- the shell and the computer ---"
probe(bus, "shell", "status")
probe(bus, "shell", "windows")
probe(bus, "system", "get_volume")
probe(bus, "system", "network_status")

say ""
say "--- macros, Cling, the screen reader and the AI ---"
probe(bus, "macros", "list_macros")
probe(bus, "macros", "macro_language")
probe(bus, "cling", "list_applications")
probe(bus, "cling", "status")
probe(bus, "titan_access", "status")
probe(bus, "titan", "ai_available")
probe(bus, "zegarynka", "get_settings")
probe(bus, "shell", "state")

say ""
say "--- the voice, which is the bug that was reported ---"
rate = probe(bus, "titan", "get_speech_rate")
probe(bus, "titan", "speaking")
started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
probe(bus, "titan", "reader_speak",
      {"text" => "Most TCE dziala. To jest glos Titana w Eltenie.",
       "interrupt" => true})
handed = ((Process.clock_gettime(Process::CLOCK_MONOTONIC) - started) * 1000).round
say "  reader_speak returned in #{handed} ms (it must not wait for the line)"
sleep 0.6
speaking = bus.call_sync("titan", "speaking", {})
say "  speaking while it talks: #{speaking.text}"
stopped = Process.clock_gettime(Process::CLOCK_MONOTONIC)
probe(bus, "titan", "stop_speech")
say "  stop took #{((Process.clock_gettime(Process::CLOCK_MONOTONIC) - stopped) * 1000).round} ms"
sleep 0.3
say "  speaking after the stop: #{bus.call_sync('titan', 'speaking', {}).text}"

bus.stop
say ""
say "done"
REPORT.close
exit!(0)
