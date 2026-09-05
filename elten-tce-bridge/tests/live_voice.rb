# The bridge's OWN speech output against the REAL Titan: does a line get
# interrupted? This is the exact code Elten runs, with Elten's own calls.
#
#     ruby tests/live_voice.rb        (with Titan running; it will speak)

require "json"

# Just enough of Elten for the output class.
class SpeechOutput
  Voice = Struct.new(:id, :name, :output, :native, :keyword_init => true) do
    def voiceid; id.to_s; end
  end
  class << self
    def inherited(cls) outputs.push(cls) if cls != SpeechOutput && !outputs.include?(cls) end
    def outputs; @outputs ||= []; end
    def voices; outputs.flat_map(&:voices); end
  end
end

require_relative "../titan_bus"
require_relative "../titan_speech_output"

REPORT = File.open(File.join(__dir__, "live_voice.txt"), "w")
def say(line) REPORT.puts(line); REPORT.flush; end

bus = TitanBus.new
bus.start
40.times { break if bus.connected?; sleep 0.25 }
say "connected: #{bus.connected?}"
abort_now = !bus.connected?
if abort_now
  say "Titan is not running - nothing to test."
  REPORT.close
  exit!(1)
end

TitanSpeechOutput.start(bus)
say "available: #{TitanSpeechOutput.available?}"
TitanSpeechOutput.set_rate(50)

def titan_speaking(bus)
  bus.call_sync("titan", "speaking", {}, :timeout => 10).text.to_s
end

# 1. A long line, exactly as Elten hands it over.
line = "To jest bardzo dluga linia tekstu, ktora Titan powinien czytac przez kilka sekund, " \
       "zeby dalo sie ja przerwac w polowie i uslyszec, ze naprawde ucichla."
started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
TitanSpeechOutput.speak_text(line, :interrupt => true)
handed = ((Process.clock_gettime(Process::CLOCK_MONOTONIC) - started) * 1000).round
say "speak_text handed over in #{handed} ms"
sleep 1.0
say "Titan says it is speaking: #{titan_speaking(bus)}"
say "the output says it is speaking: #{TitanSpeechOutput.speaking?}"

# 2. Elten's own interrupt: speech_stop -> speech_output.stop
stopped = Process.clock_gettime(Process::CLOCK_MONOTONIC)
TitanSpeechOutput.stop
say "stop returned in #{((Process.clock_gettime(Process::CLOCK_MONOTONIC) - stopped) * 1000).round} ms"
sleep 0.5
after = titan_speaking(bus)
say "Titan says it is speaking AFTER the stop: #{after}"
say(after == "no" ? "VERDICT: the interrupt works" : "VERDICT: IT DID NOT STOP (#{after})")

# 3. The other interrupt: a new line while the old one is still going.
TitanSpeechOutput.speak_text("Pierwsza linia, dosc dluga, zeby ja bylo slychac przez chwile.",
                             :interrupt => true)
sleep 0.8
TitanSpeechOutput.speak_text("Druga linia.", :interrupt => true)
sleep 0.3
say "still speaking after the replacement: #{titan_speaking(bus)} (should be yes - the second line)"
TitanSpeechOutput.stop
sleep 0.4
say "silent at the end: #{titan_speaking(bus) == 'no'}"

bus.stop
REPORT.close
exit!(0)
