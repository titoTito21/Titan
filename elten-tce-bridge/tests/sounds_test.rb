# What the user HEARS, which is the whole of this file's subject.
#
# Three of TCE's sounds mean one thing each and are the only ones every
# theme carries - `core/FOCUS.ogg` for the cursor moving a row,
# `ui/applist.ogg` for the keyboard arriving on a list, `ui/statusbar.ogg`
# for it arriving on the status bar - so the thing worth testing is not that
# a sound is played but that the RIGHT one is, for the right movement, and
# that Elten's own is quieted so there is one per key rather than one from
# each.
#
#     ruby tests/sounds_test.rb

require "json"
require_relative "elten_stub"
BASE = File.expand_path("..", __dir__)
%w[titan_prefs titan_sounds].each { |name| require_relative "#{BASE}/#{name}" }

# A bus that plays nothing and remembers everything.
class RecordingBus
  attr_reader :played
  def initialize; @played = []; end
  def connected?; true; end
  def call(_addon, _action, args)
    request = JSON.parse(args["request"]) rescue {}
    return if request["call"] != "sounds.play"
    @played.push([request["args"]["name"], request["args"]["pan"]])
  end
end

# Elten's ListBox answers `lpos` as 0 to 100 - the stub has no need of one,
# but a cue that is panned by where the cursor is does.
class ListBox
  def lpos
    return 50.0 if @options.to_a.size <= 1
    @index.to_f / (@options.size - 1).to_f * 100.0
  end
end

$failures = 0
def check(name)
  ok = yield
  puts((ok ? "PASS " : "FAIL ") + name)
  $failures += 1 if !ok
rescue Exception => e
  puts "FAIL #{name}: #{e.class}: #{e.message}"
  $failures += 1
end

bus = RecordingBus.new
TitanSounds.bus = bus

# ---------------------------------------------------------------- the list
list = TitanSounds.cued(ListBox.new(%w[one two three], :header => "Titan"))

check("Elten's own sound is quieted, so there is one sound per movement") do
  list.silent == true
end

bus.played.clear
list.trigger(:focus)
check("arriving on the list is applist, which is what TCE plays for it") do
  bus.played.map { |entry| entry[0] } == ["ui/applist.ogg"]
end

bus.played.clear
list.index = 1
list.trigger(:move)
check("moving a row is FOCUS, panned by how far down the list it is") do
  bus.played.size == 1 && bus.played[0][0] == "core/FOCUS.ogg" &&
    (bus.played[0][1] - 0.5).abs < 0.01
end

bus.played.clear
list.index = 2
list.trigger(:move)
check("the last row is heard on the right") do
  (bus.played[0][1] - 1.0).abs < 0.01
end

bus.played.clear
list.trigger(:border)
check("the end of the list is endoflist") do
  bus.played.map { |entry| entry[0] } == ["ui/endoflist.ogg"]
end

bus.played.clear
list.trigger(:select)
check("choosing a row is SELECT") do
  bus.played.map { |entry| entry[0] } == ["core/SELECT.ogg"]
end

# --------------------------------------------------------- the status bar
status = TitanSounds.cued(ListBox.new(["12:40"], :header => "Status bar"),
                          TitanSounds::STATUS)
bus.played.clear
status.trigger(:focus)
check("arriving on the status bar is statusbar, not applist") do
  bus.played.map { |entry| entry[0] } == ["ui/statusbar.ogg"]
end

bus.played.clear
status.trigger(:move)
check("moving along the status bar is still FOCUS") do
  bus.played.map { |entry| entry[0] } == ["core/FOCUS.ogg"]
end

# ------------------------------------------------- Titan's own events
check("every named event is a sound, and every sound is a real name") do
  TitanSounds::EVENTS.all? do |key, name|
    key.is_a?(Symbol) && name.is_a?(String) && name.include?("/")
  end
end

bus.played.clear
TitanSounds.event(:error)
TitanSounds.event(:ai_question)
TitanSounds.event(:macro_start)
check("an action of Titan's makes Titan's own noise for it") do
  bus.played.map { |entry| entry[0] } ==
    ["core/error.ogg", "ai/agent_question.ogg", "macro/macro_start.ogg"]
end

bus.played.clear
TitanSounds.event(:no_such_event_at_all)
check("an event nothing is mapped to is silent, not a crash") do
  bus.played.empty?
end

# ------------------------------------------ and none of it with it off
module TitanPrefs
  class << self
    def tce_sounds?; false; end
  end
end
bus.played.clear
quiet_list = TitanSounds.cued(ListBox.new(%w[a b], :header => "Off"))
quiet_list.trigger(:focus)
quiet_list.trigger(:move)
check("with TCE sounds off nothing is quieted and nothing is played here") do
  quiet_list.silent != true && bus.played.empty?
end

# ------------------------------- and every one of them is a real file
# A mapping to a sound that is not there is silence, which is the one
# failure a user cannot tell from "this add-on makes no sound".
THEME = File.join(File.expand_path("../..", __dir__), "sfx", "default")
if File.directory?(THEME)
  missing = TitanSounds::EVENTS.values.uniq.reject do |name|
    File.file?(File.join(THEME, name)) ||
      File.file?(File.join(THEME, name.sub(%r{\Aai/}, "AI/")))
  end
  check("every sound named here is one the default theme really ships") do
    puts("     missing: #{missing.inspect}") if missing.size > 0
    missing.empty?
  end
end

puts($failures == 0 ? "all good" : "#{$failures} failed")
exit($failures == 0 ? 0 : 1)
