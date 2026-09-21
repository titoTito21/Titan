# frozen_string_literal: true

# Elten's audio effects, as far as an application needs them to exist.
#
# Elten does its 3D itself, in Ruby, over a BASS/Steam Audio stack it ships:
# `Audio3DEffect` is an HRTF filter an application loads and then attaches to
# a sound. **Titan already does the same job one layer down** - the mixer
# places a sound with OpenAL HRTF when the user has 3D on and with a
# constant-power pan when they have not - so an application's sound is
# positioned here whether or not it ever touches this class.
#
# That is why these are declarations rather than a second implementation.
# `Audio3DEffect.load` answers whether positioning is available (it is, from
# Titan), and an effect attached to a sound records what it was asked for.
# Doing the filtering again in Ruby, on top of a mixer that has already done
# it, would be two HRTFs on one sound - which sounds worse than either.

class SoundEffect
  def initialize(*_arguments, **_options)
    @enabled = true
  end

  def enabled?
    @enabled
  end

  def enable
    @enabled = true
    self
  end

  def disable
    @enabled = false
    self
  end

  def apply(*_arguments)
    self
  end

  def close
    nil
  end
end

class Audio3DEffect < SoundEffect
  DEFAULT_FREQUENCY = 48_000
  # Elten's own is 20 - MILLISECONDS per frame of its 3D engine, not a
  # sample count - and an application that reads it back and hands it to
  # `load` expects that number.
  DEFAULT_FRAMESIZE = 20
  # Where the listener is. Elten's own, and applications read it -
  # `Audio3DEffect::ORIGIN` is what a sound with no place given gets.
  ORIGIN = [0.0, 0.0, 0.0].freeze

  class << self
    # Is positioned audio available? Titan's mixer answers, because Titan's
    # mixer is what will actually do it.
    def load(*_arguments)
      @loaded = true
    end

    def loaded?
      @loaded == true
    end

    def available?
      true
    end

    def unload
      @loaded = false
    end
  end

  attr_accessor :position, :interpolation

  def initialize(frequency = DEFAULT_FREQUENCY, framesize = DEFAULT_FRAMESIZE,
                 position: nil, interpolation: :nearest)
    super()
    @frequency = frequency
    @framesize = framesize
    @position = position
    @interpolation = interpolation
  end
end

# The other effects Elten ships, declared for the same reason: an
# application that asks for one gets an object that answers, and its sound
# is positioned and mixed by Titan either way.
class ReverbEffect < SoundEffect; end
class EqualizerEffect < SoundEffect; end
class CompressorEffect < SoundEffect; end
class VolumeEffect < SoundEffect; end

module SoundEffects
  module_function

  def available
    [Audio3DEffect]
  end

  def load_all
    Audio3DEffect.load
    true
  end
end

# ------------------------------------------------------------- recording
# Elten's `Recorder` (`src/eapi/audio/recorder.rb`): the microphone into a
# file, WAV, Vorbis or Opus, with pause and resume. The file manager records
# with all three (`Recorder.opus_recording(file, 192, 20)`,
# `vorbis_recording(file, 192)`, `wave_recording(file)`) and the
# Tyflopodcast client's voice message goes through `OpusRecordButton`, which
# is built on it. Titan does the recording - its own input device and
# PyAV's encoders - and answers `error` when it cannot (no microphone, the
# Windows privacy switch), because an application asks `paused` and `stop`
# of whatever it was handed and must never be handed nil.
class RecordingEncoder
  attr_reader :format, :bitrate

  def initialize(format, bitrate = 64)
    @format = format.to_s
    @bitrate = bitrate.to_i
  end

  def recording_buffer_bytes; 384_000; end
end

class WaveAudioEncoder < RecordingEncoder
  def initialize(*_arguments, **_options)
    super('wav', 0)
  end
end

class VorbisAudioEncoder < RecordingEncoder
  def initialize(bitrate = 64, *_arguments, **_options)
    super('ogg', bitrate)
  end
end

class OpusAudioEncoder < RecordingEncoder
  def initialize(bitrate = 64, *_arguments, **_options)
    super('opus', bitrate)
  end
end

class Recorder
  attr_reader :file, :encoder, :error, :time_limit

  def initialize(file, encoder = nil, time_limit: 0)
    @file = file.to_s
    @encoder = encoder || WaveAudioEncoder.new
    @time_limit = time_limit.to_f
    @error = nil
    @handle = nil
    @seconds = 0.0
    answer = EltenBridge.call('record_start',
                              { 'path' => @file, 'format' => @encoder.format,
                                'bitrate' => @encoder.bitrate.to_i * 1000,
                                'time_limit' => @time_limit })
    if answer.is_a?(Hash) && answer['handle']
      @handle = answer['handle']
    else
      @error = (answer.is_a?(Hash) && answer['error']) || 'the recording could not be started'
      Log.warning("Recorder: #{@error}")
    end
  rescue EltenBridge::Closed
    @error = 'Titan has closed this application'
  end

  def recording?
    !@handle.nil?
  end

  def stop
    return @seconds if @handle.nil?

    answer = EltenBridge.call('record_stop', { 'handle' => @handle })
    @handle = nil
    @seconds = (answer.is_a?(Hash) ? answer['seconds'] : 0).to_f
    @error ||= answer['error'] if answer.is_a?(Hash) && answer['error']
    @seconds
  rescue EltenBridge::Closed
    @handle = nil
    @seconds
  end

  def pause
    return false if @handle.nil?

    @paused = true
    !!EltenBridge.call('record_pause', { 'handle' => @handle, 'paused' => true })
  rescue EltenBridge::Closed
    false
  end

  def resume
    return false if @handle.nil?

    @paused = false
    !!EltenBridge.call('record_pause', { 'handle' => @handle, 'paused' => false })
  rescue EltenBridge::Closed
    false
  end

  def paused
    @paused == true
  end
  alias paused? paused

  def seconds
    return @seconds if @handle.nil?

    answer = EltenBridge.call('record_status', { 'handle' => @handle })
    (answer.is_a?(Hash) ? answer['seconds'] : @seconds).to_f
  rescue EltenBridge::Closed
    @seconds
  end

  class << self
    def start(file, encoder = nil)
      new(file, encoder)
    end

    def opus_recording(file, bitrate = 64, _framesize = 60, _application = 2048, _usevbr = 1,
                       timelimit = 0, tags: nil, denoise: nil)
      new(file, OpusAudioEncoder.new(bitrate), time_limit: timelimit)
    end

    def vorbis_recording(file, bitrate = 64)
      new(file, VorbisAudioEncoder.new(bitrate))
    end

    def wave_recording(file)
      new(file, WaveAudioEncoder.new)
    end

    def opus_encoder(bitrate = 64, *_rest, **_options); OpusAudioEncoder.new(bitrate); end
    def vorbis_encoder(bitrate = 64, *_rest, **_options); VorbisAudioEncoder.new(bitrate); end
    def wave_encoder; WaveAudioEncoder.new; end
  end
end
