# TitanSpeechOutput against a stand-in Elten and a stand-in Titan.
# What is being tested is the part Elten's own speech loop depends on:
# that registering the class IS the registration, that speaking? answers
# instantly and locally, and that an interrupt drops what was queued.

class SpeechOutput
  Voice = Struct.new(:id, :name, :output, :native, :keyword_init => true) do
    def voiceid; id.to_s; end
    def to_s; name.to_s; end
  end
  class << self
    def inherited(cls)
      SpeechOutput.outputs.push(cls) if cls != SpeechOutput && !SpeechOutput.outputs.include?(cls)
    end
    def outputs; @outputs ||= []; end
    def voices; outputs.flat_map(&:voices); end
  end
end

require_relative "../titan_bus"
require_relative "../titan_speech_output"

REPORT = File.open(File.join(__dir__, "speech_test.txt"), "w")
def say(line) REPORT.puts(line); REPORT.flush; end

say "registered by being defined: #{SpeechOutput.outputs.include?(TitanSpeechOutput)}"
say "Elten would list the voice: #{SpeechOutput.voices.map(&:voiceid).inspect}"

bus = TitanBus.new(:pipe => "\\\\.\\pipe\\TitanBusProbe")
bus.start
30.times { break if bus.connected?; sleep 0.1 }
TitanSpeechOutput.start(bus)
say "available? #{TitanSpeechOutput.available?}"
say "default? #{TitanSpeechOutput.default?} (must be false: picking it is the user's choice)"

# Elten's own rate is 0..100; Titan's per-line argument is -10..10.
TitanSpeechOutput.set_rate(100)
TitanSpeechOutput.set_pitch(50)

started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
TitanSpeechOutput.speak_text("This is a line of speech from Elten.", :interrupt => true)
handed = ((Process.clock_gettime(Process::CLOCK_MONOTONIC) - started) * 1000).round(2)
say "speak_text handed over in #{handed} ms"

# speaking? is asked by Elten every frame - it must be free and must not
# touch the pipe.
polls = []
20.times do
  t = Process.clock_gettime(Process::CLOCK_MONOTONIC)
  TitanSpeechOutput.speaking?
  polls << ((Process.clock_gettime(Process::CLOCK_MONOTONIC) - t) * 1_000_000).round
end
say "speaking? answered #{polls.size} times, worst #{polls.max} microseconds"
say "speaking? now: #{TitanSpeechOutput.speaking?}"

TitanSpeechOutput.speak_text("spelled", :spelling => true)
TitanSpeechOutput.stop
say "after stop, speaking?: #{TitanSpeechOutput.speaking?}"

TitanSpeechOutput.shutdown
say "after shutdown Elten offers: #{SpeechOutput.voices.map(&:voiceid).inspect}"
bus.stop
REPORT.close
exit!(0)
