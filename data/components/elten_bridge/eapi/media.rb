# frozen_string_literal: true

# Elten's media layer: the registries an application adds itself to.
#
# Two of the installed applications are nothing but this. `ffmpeg` registers
# five encoder classes and exits - it is a plug-in that gives every OTHER
# application the ability to write ogg, opus, mp3 and so on. `youtube`
# registers a finder and an extractor, so that a link pasted anywhere in
# Elten becomes something playable. Neither has a screen of its own.
#
# So the registries have to be real - an application that registers into
# nothing and returns has done nothing - and they are: what is registered is
# kept, listed, and reachable by whatever asks. What Titan does not do is
# pretend to encode: `MediaEncoder`'s own default is `false` from
# `encode_file`, which is Elten's own answer for an encoder that cannot run,
# and a subclass that really shells out to `ffmpeg.exe` works here exactly as
# it does there because it is the application's own code doing it.

# ------------------------------------------------------------------ finders
module MediaFinders
  @finders = []

  class << self
    def register(cls)
      return false if !cls.is_a?(Class)
      return false if @finders.include?(cls)

      @finders << cls
      Log.debug("Registering media finder #{cls}")
      true
    end

    def unregister(cls)
      @finders.delete(cls) != nil
    end

    def delete_all
      count = @finders.size
      @finders = []
      count
    end

    def list
      @finders.dup
    end

    def possible_media?(text)
      @finders.any? do |finder|
        begin
          finder.possible_media?(text)
        rescue StandardError
          false
        end
      end
    end

    def get_media(text)
      found = []
      @finders.each do |finder|
        begin
          found += Array(finder.get_media(text))
        rescue StandardError => error
          Log.error("Failed to get media: #{error.class}: #{error.message}")
        end
      end
      found
    end
  end
end

class MediaFinder
  def initialize
    raise 'Abstract class cannot be initialized'
  end

  def self.possible_media?(_text)
    false
  end

  def self.get_media(_text)
    []
  end
end

class MediaExtractor
  def initialize
    raise 'Abstract class cannot be initialized'
  end

  def title
    ''
  end

  def proceed
    nil
  end
end

# ----------------------------------------------------------------- encoders
module MediaEncoders
  @encoders = []

  class << self
    # Elten's own contract, kept deliberately: ANY class is accepted, because
    # an older application must not fail while it is being loaded. Whether an
    # encoder can actually do anything is asked later, by `for_audio`.
    def register(encoder_class)
      return false if !encoder_class.is_a?(Class)
      return false if @encoders.include?(encoder_class)

      @encoders << encoder_class
      Log.debug("Registering media encoder #{encoder_class}")
      true
    rescue StandardError => error
      Log.error("Cannot register media encoder: #{error.class}: #{error.message}")
      false
    end

    def unregister(encoder_class)
      @encoders.delete(encoder_class) != nil
    end

    def list
      @encoders.dup
    end
    alias encoders list

    def for_audio
      @encoders.select do |encoder|
        begin
          encoder.audio_supported?
        rescue StandardError
          false
        end
      end
    end

    def find(identifier)
      @encoders.find do |encoder|
        begin
          encoder.identifier.to_s == identifier.to_s
        rescue StandardError
          false
        end
      end
    end

    def delete_all
      count = @encoders.size
      @encoders = []
      count
    end
  end
end

class MediaEncoder
  Type = :audio
  Extension = '.'
  IsBitrateSupported = true
  Name = ''
  SupportsPcmStream = false

  class UnsupportedOperation < StandardError; end

  class << self
    def identifier
      nil
    end

    def output_descriptor
      nil
    end

    def input_constraints
      nil
    end

    def available?
      true
    end

    def audio_supported?
      return false if const_get(:Type) != :audio
      return false if output_descriptor.nil? || input_constraints.nil?
      return false if !available?

      instance_method(:start).owner != MediaEncoder
    end

    def encode_file(_file, _output, _bitrate = nil)
      false
    end

    def audio_encoder(_bitrate = nil)
      nil
    end
  end

  def start(_output, frequency: 48_000, channels: 2, source_channel: nil)
    raise UnsupportedOperation, "#{self.class} cannot encode a stream"
  end

  def feed(_data)
    nil
  end

  def process_pcm(data)
    feed(data)
  end

  def finish
    nil
  end
end

# What an encoder writes into. Elten's own three.
class RecorderOutput
  def write(_data); nil; end
  def rewrite(_offset, _data); nil; end
  def close; nil; end
  def data; nil; end
end

class FileRecorderOutput < RecorderOutput
  def initialize(file)
    @file = File.open(file, 'wb')
  end

  def write(data)
    @file.write(data)
  end

  def rewrite(offset, data)
    here = @file.pos
    @file.seek(offset)
    @file.write(data)
    @file.seek(here)
  end

  def close
    @file.close unless @file.closed?
  end
end

class MemoryRecorderOutput < RecorderOutput
  def initialize
    @data = +''.b
  end

  def write(data)
    @data << data.to_s.b
  end

  def rewrite(offset, data)
    @data[offset, data.bytesize] = data.to_s.b
  end

  def data
    @data
  end
end

class AudioEncoder < MediaEncoder; end
