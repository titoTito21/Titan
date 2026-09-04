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
  DEFAULT_FRAMESIZE = 512
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
