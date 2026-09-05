# Titan's voices, offered to Elten as one of its own speech outputs.
#
# Elten registers a speech output by INHERITANCE: SpeechOutput.inherited
# pushes every subclass into SpeechOutput.outputs, and SpeechOutput.voices
# is computed from that list every time it is asked. So defining this class
# is the whole registration, and the voice appears in Elten's ordinary
# voice list in Settings - nothing in Elten is patched or replaced.
#
# ONE voice, called Titan, exactly as Elten's own NVDA output offers one
# called NVDA. Titan's per-utterance API has no "say this in that engine",
# so a voice per Titan engine could only be honoured by switching Titan's
# own engine - changing the user's whole desktop because they picked a
# voice in Elten. Which engine speaks is Titan's own setting, where the
# user already chose it.

class TitanSpeechOutput < SpeechOutput
  VOICE_ID = "TitanTTS".freeze
  VOICE_NAME = "Titan".freeze

  # Titan's own estimate of how long a line takes: the figure Titan uses
  # wherever it has to pace speech it cannot measure.
  ESTIMATE_BASE = 0.28
  ESTIMATE_PER_CHARACTER = 1.0 / 16.0
  # How stale an answer from Titan may be before "am I still speaking?"
  # is worth asking again. Elten asks this every frame; Titan is asked at
  # most five times a second, and never on Elten's own thread.
  TRUTH_SECONDS = 0.2

  class << self
    def bus
      @bus
    end

    def start(bus)
      @bus = bus
      @rate = 50
      @pitch = 50
      @rate_sent = nil
      @titan_rate_before = nil
      @speaking_until = 0.0
      @truth = nil
      @truth_at = 0.0
      @asking = false
      true
    end

    def shutdown
      give_titan_its_rate_back
      @bus = nil
      @speaking_until = 0.0
      SpeechOutput.outputs.delete(self)
      true
    end

    # ------------------------------------------------------------------ what
    def available?
      @bus != nil && @bus.connected?
    end

    def usable?
      available?
    end

    # Never the default. A user who has not asked for Titan should keep the
    # output they had; ours is chosen by picking its voice.
    def default?
      false
    end

    def voices
      [SpeechOutput::Voice.new(:id => VOICE_ID, :name => VOICE_NAME,
                               :output => self, :native => nil)]
    end

    def rate_supported?
      true
    end

    def pitch_supported?
      true
    end

    # Titan speaks at its own volume, set in Titan. Claiming otherwise
    # would give the user a slider in Elten that moves nothing.
    def volume_supported?
      false
    end

    def indexed_supported?
      false
    end

    def braille_supported?
      false
    end

    def pause_supported?
      false
    end

    def stream_output_supported?
      false
    end

    # ----------------------------------------------------------------- doing
    def speak_text(text, method: 1, spelling: false, interrupt: true, pitch: 50)
      line = text.to_s
      line = line.chars.join(", ") if spelling
      return 1 if line.strip == ""
      return 0 if !available?
      @pitch = pitch.to_i if pitch != nil
      # An interrupting line replaces whatever has not been sent yet: the
      # user has moved on, and saying the old line when its turn comes is
      # a reader that lags further behind with every keystroke.
      @bus.drop_pending if interrupt
      # `titan.reader_speak` and NOT `titan.speak`, and that is the whole
      # difference between a voice that can be interrupted and one that
      # cannot. `titan.speak` borrows a rate for one line and can only give
      # it back after the line has been spoken, so it speaks synchronously
      # and its answer does not come back until the sentence is finished -
      # by which time the next keystroke's "stop" is already too late, and
      # Titan's own interface has been held for the length of the sentence.
      # Here the rate is SET when it changes (below) and speech starts and
      # returns, so an interrupt arrives while there is still something to
      # interrupt.
      @bus.call("titan", "reader_speak",
                {"text" => line, "interrupt" => interrupt,
                 "pitch" => titan_pitch, "spelling" => false})
      @speaking_until = now + estimate(line)
      @truth = nil
      1
    end

    def speak_sequence(seq)
      speak_text(seq.text, method: 1)
    end

    def speak_indexed(texts, indexes, id = nil)
      speak_text(texts.join, method: 1)
    end

    def stop
      return 1 if !available?
      @bus.drop_pending
      @bus.call("titan", "stop_speech")
      @speaking_until = 0.0
      @truth = false
      @truth_at = now
      1
    end

    # Answered locally, because Elten asks it every frame and a pipe round
    # trip per frame is the one thing this design must not do. The estimate
    # is corrected by Titan's own answer, which is fetched in the
    # background: the caller is never blocked, and the answer it gets is
    # never older than a fifth of a second.
    def speaking?
      return false if !available?
      believed = now < @speaking_until
      # Titan is believed when it says YES and not when it says no. Its
      # answer comes from the reserved speech channel, and an engine that
      # speaks through its own device - the SAPI bridge does - leaves that
      # channel empty the whole time it is talking. Ending an utterance on
      # that "no" would make Elten move on in the middle of every line;
      # ending it on the estimate is at worst slightly late.
      fresh = @truth != nil && (now - @truth_at) < TRUTH_SECONDS
      return true if fresh && @truth == true
      refresh_truth if believed
      believed
    end

    # Elten's rate is 0..100 and Titan's is -10..10, and it is applied by
    # SETTING Titan's rate rather than by passing one per line: a rate
    # passed per line is what makes Titan speak synchronously. Titan's own
    # rate is remembered the first time and put back when this output stops
    # being used - a reader borrowing the voice must not leave Titan talking
    # to its own user at Elten's speed for ever.
    def set_rate(rate)
      @rate = rate.to_i
      wanted = titan_rate
      return rate.to_i if !available? || @rate_sent == wanted
      @rate_sent = wanted
      @bus.call("titan", "set_speech_rate", {"rate" => wanted}) do |answer|
        @titan_rate_before = answer if @titan_rate_before == nil && answer != nil
      end
      rate.to_i
    end

    def give_titan_its_rate_back
      return if @bus == nil || @titan_rate_before == nil
      @bus.call("titan", "set_speech_rate", {"rate" => @titan_rate_before})
      @titan_rate_before = nil
      @rate_sent = nil
    end

    def set_pitch(pitch)
      @pitch = pitch.to_i
      pitch.to_i
    end

    def apply_voice(_voice)
      true
    end

    # Elten calls this on every output that is NOT the chosen one, so it is
    # also where Titan's own rate goes back.
    def deactivate
      stop if available?
      give_titan_its_rate_back
    end

    private

    def now
      Process.clock_gettime(Process::CLOCK_MONOTONIC)
    end

    # Elten's rate, volume and pitch are 0..100; Titan's per-utterance
    # arguments are -10..10.
    def titan_rate
      ((@rate.to_i - 50) / 5.0).round(2)
    end

    def titan_pitch
      ((@pitch.to_i - 50) / 5.0).round(2)
    end

    def estimate(text)
      seconds = ESTIMATE_BASE + text.to_s.length * ESTIMATE_PER_CHARACTER
      seconds / (1.0 + titan_rate / 15.0)
    rescue Exception
      1.0
    end

    def refresh_truth
      return if @asking
      @asking = true
      @bus.call("titan", "speaking") do |answer|
        # "unknown" means the host cannot tell - keep the estimate rather
        # than inventing an answer from it.
        @truth = (answer == "yes") if answer == "yes" || answer == "no"
        @truth_at = now
        @asking = false
      end
    rescue Exception
      @asking = false
    end
  end
end
