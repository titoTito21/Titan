# frozen_string_literal: true

# The Elten application API, served by Titan.
#
# This is Titan's own implementation of the surface documented in Elten's
# `docs/eltenapps.md` - not Elten's code. That distinction is not pedantry:
# Elten 3 is GPL-3.0, and a component that lifted its Ruby would put Titan
# under the GPL as a whole. What is copied here is the *shape* of the API,
# which is what an application is written against and what a bridge is for.
#
# Everything below ends at `EltenBridge.call`, and therefore in Titan: a
# dialog is a wx window, `speak` is whichever TTS the user chose at the rate
# they set, a sound is Titan's mixer with the user's theme volume and their
# stereo or HRTF preference. An Elten application running here should sound
# like the rest of this desktop, because for the person using it, it is.

require 'json'
require 'fileutils'

# ---------------------------------------------------------------- logging
# `Log` is what applications reach for constantly (72 call sites across the
# eleven installed here), usually inside a `rescue`. It must therefore never
# raise: a logger that throws inside an error handler turns a warning into a
# crash.
module Log
  class << self
    %w[debug info warning error fatal].each do |level|
      define_method(level) do |*parts|
        write(level, parts.map(&:to_s).join(' '))
      end
    end

    def write(level, text)
      EltenBridge.notify('log', { 'level' => level, 'text' => text })
      nil
    rescue StandardError
      nil
    end
  end
end

# ------------------------------------------------------------ translation
# Elten packages a GNU gettext `.mo` per language; Titan reads it and answers
# here, so `_()` is one round trip and the catalogue is never parsed in Ruby.
# The result is cached because a list redraws its labels on every keystroke.
module EltenGettext
  @cache = {}

  class << self
    def translate(text)
      return text if text.nil? || text.empty?

      @cache[text] ||= begin
        answer = EltenBridge.call('translate', { 'text' => text })
        answer.is_a?(String) ? answer : text
      rescue EltenBridge::Closed
        text
      end
    end

    def clear
      @cache = {}
    end

    # `p_(context, text)`: a `.mo` keys a context translation as
    # `context U+0004 text`, and U+0004 is a control character the wire
    # strips out of a TEXT - so a context sent inside the text arrived
    # as "WeatherMain menu", matched nothing, and every one of the 236
    # strings Weather translates that way was English on a Polish
    # desktop. The context is its own field now, and Titan asks its
    # catalogue with `pgettext`.
    def translate_context(context, text)
      return text if text.nil? || text.empty?

      (@context_cache ||= {})[[context, text]] ||= begin
        answer = EltenBridge.call('translate', { 'text' => text, 'context' => context })
        answer.is_a?(String) && !answer.empty? ? answer : text
      rescue EltenBridge::Closed
        text
      end
    end

    # The language the application is being shown in - Titan's, which the
    # bridge chose the catalogue by. `Configuration.language` is built on
    # it and the Neighbourhood Radar and the Game Room read that to pick
    # their own words; a `NoMethodError` here was those two answering in
    # the wrong language, or not at all.
    def language
      @language ||= begin
        answer = EltenBridge.call('language', {})
        answer.is_a?(String) && !answer.empty? ? answer : 'en'
      rescue EltenBridge::Closed, EltenBridge::RemoteError
        'en'
      end
    end
  end
end

module Kernel
  # The translation mark. Elten's applications use it for every string a
  # person will hear.
  def _(text)
    EltenGettext.translate(text)
  end

  # `n_` is gettext's plural form. Titan picks the form from the catalogue.
  def n_(singular, plural, count)
    answer = EltenBridge.call('translate_plural',
                              { 'one' => singular, 'other' => plural,
                                'count' => count })
    answer.is_a?(String) ? answer : (count == 1 ? singular : plural)
  rescue EltenBridge::Closed
    count == 1 ? singular : plural
  end
end

# ------------------------------------------------------------------ speech
# Titan's TTS, at the user's rate, in the user's voice, positioned where the
# application asks. `interrupt` is Elten's own default: a self-voicing
# interface says the thing you have just moved to and stops saying the last
# one.
module Speech
  class << self
    # **Elten's signature, or it is nothing.** Elten's own is
    #
    #     speak(text, stop: true, use_dictionary: true, id: nil,
    #           break_sequence: true, pan: 50, limit: nil)
    #
    # and not one of those keywords was accepted here: this took `interrupt`,
    # `position`, `pitch` and `wait`, which are the port's own invention. So
    # every application writing what Elten documents got
    # `ArgumentError: unknown keywords: :stop, :break_sequence` - the ELTEN
    # Game Room says its narration that way at ten call sites and its board
    # at an eleventh (`speak(value, pan: position)`), so the whole of what it
    # reads aloud raised instead of being said. The same fault `input_text`
    # had, and found the same way: by reading Elten instead of guessing.
    #
    # `stop` IS this port's `interrupt` (Elten stops the current line by
    # default), and Elten's `pan` is 0..100 about a centre of 50 where this
    # takes -1.0..1.0 - handing one straight to the other is the bug that has
    # already put Titan's shell sounds in the left speaker, so it is
    # converted. `use_dictionary`, `id`, `break_sequence` and `limit` are
    # accepted and not acted on: a keyword this build cannot honour must
    # still be accepted, or refusing one is refusing the application for
    # asking precisely. The port's own four keep working, for `alert` and for
    # anything already written against them.
    def speak(text, stop: nil, use_dictionary: nil, id: nil,
              break_sequence: nil, pan: nil, limit: nil,
              interrupt: nil, position: nil, pitch: nil, wait: nil,
              **_ignored)
      return if text.nil?

      really_interrupt = if !interrupt.nil?
                           !!interrupt
                         elsif !stop.nil?
                           !!stop
                         else
                           true
                         end
      really_position = if !position.nil?
                          position.to_f
                        elsif !pan.nil?
                          # 0..100 about 50 -> -1.0..1.0
                          ((pan.to_f - 50.0) / 50.0).clamp(-1.0, 1.0)
                        else
                          0.0
                        end

      EltenBridge.call('speak', { 'text' => text.to_s,
                                  'interrupt' => really_interrupt,
                                  'position' => really_position,
                                  'pitch' => (pitch || 0.0).to_f,
                                  'wait' => !!wait })
      nil
    rescue EltenBridge::Closed
      nil
    rescue StandardError => error
      # **Speech that fails must not end the application.** `alert` is
      # called from the middle of a game - AudioMemory says the round
      # number as the board is dealt - and a `RemoteError` there travels
      # all the way out of `program_main`: a voice that hiccuped closed
      # the game. The line is lost, which is bad; the game is not, which
      # is what matters.
      Log.warning("speech failed: #{error.class}: #{error.message}")
      nil
    end

    def stop
      EltenBridge.call('stop_speech')
      nil
    rescue EltenBridge::Closed
      nil
    end

    def speaking?
      !!EltenBridge.call('speaking')
    rescue EltenBridge::Closed
      false
    end
  end
end

module Kernel
  def speak(text, **options)
    Speech.speak(text, **options)
  end

  def speech_stop
    Speech.stop
  end
end

# ------------------------------------------------------------------- sound
# A sound the application is holding, as opposed to one it fired and forgot.
# Elten's own split, and worth keeping: a game's background bed is held and
# stopped deliberately, a click is played into a pool and forgotten.
class EltenSound
  attr_reader :handle, :name

  def initialize(handle, name = '', loop: false)
    @handle = handle
    @name = name
    @loop = loop
    @closed = false
    @volume = 1.0
    @spatial = false
    @position = nil
    @interpolation = :bilinear
    @slide = nil
    @started = nil
  end

  # A sound created as looping keeps looping when it is played: the loop
  # belongs to the SOUND, and an application sets it up once
  # (`create_sound_from_asset(name, loop: true)`) and then just calls
  # `play`.
  def play(volume: nil, position: nil, loop: nil)
    return false if @closed

    @volume = volume.to_f unless volume.nil?
    @position = position unless position.nil?
    @started = EltenBridge.now
    !!EltenBridge.call('sound_play', compact({ 'handle' => @handle,
                                               'volume' => volume,
                                               'position' => position,
                                               'loop' => loop.nil? ? @loop : loop }))
  rescue EltenBridge::Closed
    false
  end

  def stop
    return false if @closed

    !!EltenBridge.call('sound_stop', { 'handle' => @handle })
  rescue EltenBridge::Closed
    false
  end

  def playing?
    return false if @closed

    !!EltenBridge.call('sound_playing', { 'handle' => @handle })
  rescue EltenBridge::Closed
    false
  end

  # ------------------------------------------------------ told, not asked
  # **These four are notifications, and that is what makes a game
  # playable.** Nothing reads their answer - each returns the value it was
  # given - but each used to block the application's own thread until
  # Titan had replied, and a game changes them on the FRAME: Purrposterous
  # runs at 100 Hz and re-places every cat on every frame, so three cats
  # were three hundred blocking round trips a second on the thread that
  # also has to run the game. The stalling that reads as "the sound stops"
  # is that. Order on the wire is unchanged, so a `playing?` asked after a
  # move still sees the moved sound.
  def volume=(value)
    @volume = value.to_f
    EltenBridge.notify('sound_volume', { 'handle' => @handle, 'volume' => value })
    value
  rescue EltenBridge::Closed
    nil
  end

  def position=(value)
    EltenBridge.notify('sound_position', { 'handle' => @handle,
                                           'position' => value })
    value
  rescue EltenBridge::Closed
    nil
  end

  # ------------------------------------------------------------- 3D
  # Elten's own spatial surface, from `src/eapi/audio/sound.rb`. It is here
  # in full because an application ASKS before it uses it -
  # `respond_to?(:spatial_position_slide)`, `@flight_sound.closed?` - and a
  # method that is merely missing does not degrade, it raises: Skeet wraps
  # `move_flight` in `rescue Exception`, so a missing `closed?` was a
  # `NoMethodError` on the first frame of every throw, caught, logged and
  # answered with `stop_flight`. The clay target was released and went
  # silent a frame later, for the whole game.
  #
  # A position is `[x, y, z]` in metres with the listener at the origin and
  # it crosses the wire UNCONVERTED - Titan's side turns it into a pan, an
  # elevation and a gain, because that is the side that knows what Titan's
  # mixer is.
  def spatialize(position: nil, interpolation: :bilinear)
    @spatial = true
    @interpolation = interpolation
    self.spatial_position = position if position
    self
  end

  def spatial?
    @spatial == true
  end

  def spatial_position
    @position
  end

  def spatial_position=(position)
    cancel_spatial_position_slide
    @spatial = true
    @position = position
    EltenBridge.notify('sound_position', { 'handle' => @handle,
                                           'position' => position })
    position
  rescue EltenBridge::Closed
    position
  end

  def spatial_interpolation
    @interpolation
  end

  def spatial_interpolation=(value)
    @interpolation = value
  end

  # A journey, stepped on a thread of its own so the application's frame is
  # never the thing that has to keep it moving. A game that drives the
  # travel from its own clock instead (Skeet does, when this is absent)
  # gets exactly the same result through `spatial_position=`.
  def spatial_position_slide(position, duration:, from: nil, start_at: 0.0)
    duration = Float(duration)
    raise ArgumentError, 'duration must be a positive finite number' if !duration.finite? || duration <= 0.0

    origin = _coordinates(from || @position || [0.0, 0.0, 0.0])
    target = _coordinates(position)
    cancel_spatial_position_slide
    @spatial = true
    self.spatial_position = origin
    started = EltenBridge.now + Float(start_at)
    @slide = Thread.new do
      begin
        sleep(Float(start_at)) if start_at.to_f > 0.0
        loop do
          gone = EltenBridge.now - started
          break if gone >= duration || @closed

          part = gone <= 0.0 ? 0.0 : gone / duration
          step = [origin[0] + (target[0] - origin[0]) * part,
                  origin[1] + (target[1] - origin[1]) * part,
                  origin[2] + (target[2] - origin[2]) * part]
          @position = step
          EltenBridge.notify('sound_position', { 'handle' => @handle,
                                                'position' => step })
          sleep(0.02)
        end
        unless @closed
          @position = target
          EltenBridge.notify('sound_position', { 'handle' => @handle,
                                                'position' => target })
        end
      rescue StandardError, EltenBridge::Closed
        nil
      ensure
        @slide = nil
      end
    end
    self
  end

  def spatial_position_sliding?
    thread = @slide
    !thread.nil? && thread.alive?
  end

  def cancel_spatial_position_slide
    thread = @slide
    @slide = nil
    return false if thread.nil?

    thread.kill
    true
  end

  def despatialize
    cancel_spatial_position_slide
    @spatial = false
    self
  end

  # Titan's mixer places a sound as it plays it, so there is no effect
  # pipeline in front of it and nothing to be late by. Answering honestly
  # matters: Skeet subtracts this from the time it scores a shot at, so a
  # made-up number would move the target away from where it sounds.
  def effects_latency_ms
    0.0
  end

  def effect_playback_seconds
    return 0.0 if @started.nil?

    EltenBridge.now - @started
  end

  def effect_playback_seconds_at(time)
    return 0.0 if @started.nil?

    Float(time) - @started
  rescue StandardError
    effect_playback_seconds
  end

  # An effect an application attaches is remembered rather than applied:
  # Titan has already placed and mixed the sound one layer down, and doing
  # the same filtering again in Ruby on top of that is two HRTFs on one
  # sound, which is worse than either. See `audio.rb`.
  def effects
    @effects ||= []
  end

  def effect_add(effect)
    effects.push(effect) unless effects.include?(effect)
    @spatial = true if defined?(::Audio3DEffect) && effect.is_a?(::Audio3DEffect)
    self
  end

  def effect_remove(effect)
    effects.delete(effect)
    self
  end

  # ---------------------------------------------------------- state
  def closed?
    @closed
  end

  def finished?
    !@closed && !playing?
  end

  def pan
    _coordinates(@position)[0]
  end

  # **And it is remembered.** `position=` sends it and answered nothing, so
  # `pan` read back whatever the sound was made with - a game that placed a
  # sound and then asked where it was got the old answer. Purrposterous
  # places every cat on every step.
  def pan=(value)
    @position = value
    self.position = value
    value
  end

  def volume
    @volume
  end

  # ------------------------------------------------------------- the pitch
  # **`basefrequency` is what a sound was sampled at**, and it is the
  # number a game changes the pitch RELATIVE to: Purrposterous reads it
  # when a cat is born and then sets `frequency = basefrequency * pitch /
  # 100` as the cat gets hungrier. Missing, it ended the game on the first
  # cat - inside the game's own `rescue`, so what the user saw was a game
  # that started and stopped.
  DEFAULT_FREQUENCY = 44_100

  def basefrequency
    @basefrequency ||= (EltenBridge.call('sound_frequency',
                                         { 'handle' => @handle }) ||
                        DEFAULT_FREQUENCY).to_i
  rescue EltenBridge::Closed
    DEFAULT_FREQUENCY
  end

  def frequency
    @frequency || basefrequency
  end

  # Elten resamples; Titan's mixer changes the playback rate, which is the
  # same thing heard - a sound played faster is a sound played higher.
  def frequency=(value)
    @frequency = value.to_f
    EltenBridge.notify('sound_pitch',
                       { 'handle' => @handle,
                         'pitch' => basefrequency.to_f.zero? ? 1.0 : @frequency / basefrequency.to_f })
    @frequency
  rescue EltenBridge::Closed
    @frequency
  end

  # Elten's `pitch` is a percentage of the sound's own rate, which is what
  # `frequency` is underneath.
  def pitch
    return 100.0 if basefrequency.to_f.zero?

    frequency.to_f / basefrequency.to_f * 100.0
  end

  def pitch=(value)
    self.frequency = basefrequency.to_f * value.to_f / 100.0
    value
  end

  # Tempo is speed without pitch, which Titan's mixer does not do. Answered
  # rather than raised, and answered HONESTLY - it reports back what it was
  # set to and changes nothing, so an application reading it is not lied
  # to about the sound it can hear.
  def tempo
    @tempo || 0.0
  end

  def tempo=(value)
    @tempo = value.to_f
  end

  # ------------------------------------------------------- where it is up to
  def length
    (EltenBridge.call('sound_length', { 'handle' => @handle }) || 0).to_f
  rescue EltenBridge::Closed
    0.0
  end

  def position
    (EltenBridge.call('sound_at', { 'handle' => @handle }) || 0).to_f
  rescue EltenBridge::Closed
    0.0
  end

  def pause
    return false if @closed

    @paused = true
    !!EltenBridge.call('sound_pause', { 'handle' => @handle, 'paused' => true })
  rescue EltenBridge::Closed
    false
  end

  def resume
    return false if @closed

    @paused = false
    !!EltenBridge.call('sound_pause', { 'handle' => @handle, 'paused' => false })
  rescue EltenBridge::Closed
    false
  end

  def paused?
    @paused == true
  end

  def stopped?
    !playing? && !paused?
  end

  def opened?
    !@closed
  end

  def status
    name = if @closed then :closed
           elsif paused? then :paused
           elsif playing? then :playing
           else :stopped
           end
    SoundStatus.new(name)
  end

  # What a player shows about the file. Titan reads no tags, so these
  # answer the name rather than inventing anything.
  def title; @name.to_s; end
  def artist; ''; end
  def album; ''; end
  def channels; 2; end
  def output_frequency; basefrequency; end
  def id; @handle; end
  def to_s; @name.to_s; end

  # Sit here until it has finished. Elten's own, used by a game that plays
  # a sting and then goes on.
  def wait(timeout = nil)
    deadline = timeout.nil? ? nil : EltenBridge.now + timeout.to_f
    loop_update(0.02) while playing? && !@closed && (deadline.nil? || EltenBridge.now < deadline)
    self
  end

  # What a player shows about a file: Elten's `AudioInfo`, read from the
  # file's own tags by Titan.
  def info
    @info ||= PlayerInfo.new(_details['info'] || {})
  end

  def chapters
    Array(_details['chapters']).map { |c| PlayerChapter.new(c['name'] || c[:name], c['time'] || c[:time]) }
  end

  def bitrate
    (_details['bitrate'] || 0).to_i
  end

  def type
    (_details['type'] || 'unknown').to_sym
  end

  def download_status
    nil
  end

  def data(_seconds = nil)
    raise NotImplementedError, 'Titan does not hand an application the decoded audio of a sound'
  end

  def _details
    @details ||= (EltenBridge.call('sound_details', { 'handle' => @handle }) || {})
  rescue EltenBridge::Closed
    {}
  end

  def fade_in(_duration, to: 1.0, logarithmic: false, play: true)
    self.volume = to
    self.play if play
    self
  end

  def fade_out(_duration, stop: true, logarithmic: false)
    self.volume = 0.0
    self.stop if stop
    self
  end

  # `on(:slide_end)` is Elten's only sound event, fired when a volume or
  # position slide finishes. A fade here is instant, so the block is
  # called at once rather than never.
  def on(event, &block)
    raise ArgumentError, 'Sound#on requires a block' if block.nil?

    block.call if event.to_sym == :slide_end
    block
  end

  def _coordinates(position)
    return [0.0, 0.0, 0.0] if position.nil?
    return [Float(position), 0.0, 0.0] if position.is_a?(Numeric)

    values = Array(position)
    [values[0].to_f, values[1].to_f, values[2].to_f]
  rescue StandardError
    [0.0, 0.0, 0.0]
  end

  def close
    return if @closed

    @closed = true
    cancel_spatial_position_slide
    EltenBridge.call('sound_close', { 'handle' => @handle })
  rescue EltenBridge::Closed
    nil
  end

  private

  def compact(hash)
    hash.reject { |_key, value| value.nil? }
  end
end

# What an application announced, into Titan's Buffer System - the `Elten
# API` category, `notifications` and `messages` - so it can be reviewed
# after it was said. Told, never asked: an announcement must not wait.
module EltenBuffers
  def self.push(buffer, text)
    text = text.to_s.strip
    return if text.empty?

    EltenBridge.notify('buffer', { 'buffer' => buffer.to_s, 'text' => text })
  rescue EltenBridge::Closed
    nil
  end
end

# Elten's `SoundStatus` - what `Sound#status` answers. It is compared as a
# symbol too (`status == :playing`), because the port used to answer one.
class SoundStatus
  attr_reader :name

  def initialize(name)
    @name = name.to_sym
  end

  def stopped?; @name == :stopped || @name == :closed; end
  def playing?; @name == :playing; end
  def stalled?; false; end
  def paused?; @name == :paused; end
  def to_sym; @name; end
  def to_s; @name.to_s; end
  def ==(other); other.is_a?(SoundStatus) ? other.name == @name : other.to_s == @name.to_s; end

  # Elten's own named statuses (`eapi/audio/sound.rb`), which an
  # application compares against: `sound.status == SoundStatus::Playing`.
  Stopped = new(:stopped)
  Playing = new(:playing)
  Paused = new(:paused)
  Stalled = new(:stalled)
  Closed = new(:closed)

  def self.from_bass(code)
    case code.to_i
    when 1 then Playing
    when 2 then Stalled
    when 3 then Paused
    else Stopped
    end
  end
end

# `Sound` - Elten's own, from `src/eapi/audio/sound.rb`: a sound made from a
# FILE, a URL or bytes in memory, rather than from one of the package's
# assets. The file manager previews with it (`Sound.new(path).length`), its
# playlist plays through it, Freesound plays a preview URL with it, and
# the ELTEN Game Room's own tests build one. It was simply absent - a
# `NameError` at the first of those, inside the application's own rescue,
# so what the user saw was "the file could not be played".
#
# A local file is a held sound of Titan's mixer (`sound_open` - any file the
# application can name, since a Ruby process reads the disk anyway); a URL
# is Titan's stream (the same PyAV decoder the Player uses); bytes are
# spooled to a temporary file first; raw PCM an application pushes
# (`open_pcm`) is a `PcmSound`, Titan's stream fed from the application.
class Sound < EltenSound
  class UnsupportedOperation < StandardError; end

  attr_reader :file

  def self.new(file = nil, **options)
    if self == Sound && file.to_s =~ %r{\Ahttps?://}i
      return RemoteSound.new(file, **options)
    end

    super
  end

  def self.output_devices
    []
  end

  # Elten's `Sound.open_pcm` (`eapi/audio/sound.rb`): a BASS push stream
  # the application writes sample frames into. Spotify is made of one -
  # librespot decodes, the application reads forty milliseconds at a time
  # and writes them here - so a port that refused raw PCM was a Spotify
  # that could browse and search and never make a sound.
  def self.open_pcm(frequency:, channels:, type:, buffer:, output_device: nil)
    PcmSound.new(frequency: frequency, channels: channels, type: type,
                 buffer: buffer, output_device: output_device)
  end

  def initialize(file = nil, sample: false, loop: false, stream: nil,
                 effect_buffer: nil, effect_buffer_seconds: nil,
                 output_device: nil, **_ignored)
    @file = file.to_s
    @file = _spool(stream) if @file.empty? && !stream.nil?
    raise ArgumentError, 'a sound needs a file, a URL or a stream' if @file.empty?

    handle = EltenBridge.call('sound_open', { 'path' => @file, 'loop' => !!loop })
    raise IOError, "#{@file} could not be opened as a sound" if handle.nil?

    super(handle, File.basename(@file), loop: !!loop)
  end

  private

  # Bytes in memory become a file, because that is what the mixer plays.
  def _spool(bytes)
    require 'tempfile'
    spool = Tempfile.new(['elten-sound', '.bin'], binmode: true)
    spool.write(bytes.to_s.b)
    spool.flush
    (@spools ||= []) << spool              # kept alive for the sound's life
    spool.path
  end
end

# A `Sound` on a URL: Titan's stream (PyAV, decoded a second at a time into
# the mixer) wearing the sound's own surface, so an application cannot tell
# a station from a file. Opened PAUSED - Elten's `Sound.new` does not play.
class RemoteSound < Sound
  def initialize(file = nil, loop: false, **_ignored)
    @file = file.to_s
    @loop = !!loop
    @closed = false
    @volume = 1.0
    @spatial = false
    @position = nil
    @interpolation = :bilinear
    @slide = nil
    @started = nil
    @paused = true
    answer = EltenBridge.call('stream_open', { 'url' => @file, 'label' => File.basename(@file),
                                               'autoplay' => false })
    raise IOError, "#{@file} could not be opened as a sound" if answer.nil?

    @handle = answer['handle']
    @name = File.basename(@file)
    @state = answer
  end

  def play(volume: nil, position: nil, loop: nil)
    return false if @closed

    self.volume = volume unless volume.nil?
    self.position = position unless position.nil?
    @paused = false
    @started = EltenBridge.now
    _do('play')
    true
  end

  def stop
    return false if @closed

    _do('pause')
    _do('seek', 'position' => 0.0)
    @paused = true
    true
  end

  def pause
    return false if @closed

    @paused = true
    _do('pause')
    true
  end

  def resume
    play
  end

  def playing?
    return false if @closed

    state = _do('status')
    state.is_a?(Hash) && state['playing'] == true
  end

  def length
    state = _do('status')
    (state.is_a?(Hash) ? state['duration'] : nil).to_f
  end

  def position
    state = _do('status')
    (state.is_a?(Hash) ? state['position'] : nil).to_f
  end

  def position=(value)
    _do('seek', 'position' => value.to_f)
    value
  end

  def volume=(value)
    @volume = value.to_f
    _do('volume', 'volume' => @volume)
    value
  end

  def pan=(value)
    @position = value
    _do('pan', 'pan' => value.to_f)
    value
  end

  def frequency=(value)
    @frequency = value.to_f
    _do('pitch', 'pitch' => basefrequency.to_f.zero? ? 1.0 : @frequency / basefrequency.to_f)
    @frequency
  end

  def basefrequency
    44_100
  end

  def tempo=(value)
    @tempo = value.to_f
    _do('tempo', 'tempo' => 1.0 + @tempo / 100.0)
    @tempo
  end

  def info
    state = _do('status')
    PlayerInfo.new(state.is_a?(Hash) ? (state['info'] || {}) : {})
  end

  def chapters
    state = _do('status')
    Array(state.is_a?(Hash) ? state['chapters'] : []).map { |c| PlayerChapter.new(c['name'], c['time']) }
  end

  def close
    return if @closed

    @closed = true
    cancel_spatial_position_slide
    _do('close')
  end

  private

  def _do(what, extra = {})
    EltenBridge.call('stream_do', { 'handle' => @handle, 'do' => what }.merge(extra))
  rescue EltenBridge::Closed
    nil
  end
end

# A sound the application FEEDS: `Sound.open_pcm`'s answer. It is a
# `RemoteSound` underneath - Titan's stream on a channel of the mixer - fed
# from what `write_pcm` hands over instead of from a decoder, so volume,
# pan, pitch, tempo and position all answer as for any other sound.
#
# Three things Elten's own has that the application reaches for, and none
# of them is decoration: `channel` / `source_channel` are the handle (a
# zero is "the playback channel is unavailable"), `buffer_attribute` and
# `tempo_attribute` are the BASS_FX knobs Spotify turns down and up, and
# `status` is a `SoundStatus` that says `stopped?` only once everything
# written has been played - which is how the player knows a track ended.
class PcmSound < RemoteSound
  class Attribute
    attr_reader :value

    def initialize(sound, name, available: true)
      @sound = sound
      @name = name
      @available = available
      @value = 0.0
    end

    def available?; @available; end

    def value=(number)
      @value = number.to_f
      @sound.tempo = @value if @name == :tempo
      true
    end
  end

  attr_reader :frequency_hz, :channels_count

  # `Sound.new` routes a URL to `RemoteSound` and hands everything else its
  # positional file; a PCM sound has no file, so it is built directly.
  def self.new(**options)
    sound = allocate
    sound.send(:initialize, **options)
    sound
  end

  def initialize(frequency:, channels:, type:, buffer: nil, output_device: nil, **_ignored)
    @file = ''
    @loop = false
    @closed = false
    @volume = 1.0
    @spatial = false
    @position = nil
    @interpolation = :bilinear
    @slide = nil
    @started = nil
    @paused = true
    @frequency_hz = frequency.to_i
    @channels_count = channels.to_i
    @sample_type = type.to_s
    @frame_bytes = _sample_bytes(@sample_type) * [@channels_count, 1].max
    answer = EltenBridge.call('pcm_open', { 'frequency' => @frequency_hz, 'channels' => @channels_count,
                                            'type' => @sample_type, 'label' => 'pcm' })
    raise IOError, 'the PCM output could not be opened' unless answer.is_a?(Hash)

    @handle = answer['handle']
    @name = 'pcm'
    @state = answer
    @written = 0
    @ended = false
    write_pcm(buffer) if buffer.is_a?(String) && !buffer.empty?
  end

  def channel; @closed ? 0 : @handle.to_i; end
  def source_channel; channel; end
  def playback_channel; channel; end
  def opened?; !@closed; end
  def kind; :pcm; end
  def pcm?; true; end

  def buffer_attribute
    @buffer_attribute ||= Attribute.new(self, :buffer, available: false)
  end

  def tempo_attribute
    @tempo_attribute ||= Attribute.new(self, :tempo)
  end

  def write_pcm(buffer)
    raise RuntimeError, 'Cannot write PCM data to a closed sound' if @closed

    data = buffer.to_s.b
    return 0 if data.empty?
    if data.bytesize % @frame_bytes != 0
      raise ArgumentError, "PCM data must contain complete sample frames (#{@frame_bytes} bytes per frame)"
    end

    require 'base64'
    EltenBridge.notify('pcm_write', { 'handle' => @handle, 'data' => Base64.strict_encode64(data) })
    @written += data.bytesize / @frame_bytes
    data.bytesize
  rescue EltenBridge::Closed
    0
  end

  def end_of_data
    return true if @ended

    @ended = true
    EltenBridge.notify('pcm_end', { 'handle' => @handle })
    true
  rescue EltenBridge::Closed
    true
  end

  def written_frames; @written; end

  def basefrequency
    @frequency_hz.to_f
  end

  def length
    @written.to_f / [@frequency_hz, 1].max
  end

  def status
    return SoundStatus::Stopped if @closed

    state = _do('status')
    return SoundStatus::Stopped unless state.is_a?(Hash)
    return SoundStatus::Playing if state['playing'] == true
    return SoundStatus::Stopped if state['finished'] == true
    return SoundStatus::Paused if state['paused'] == true

    @ended ? SoundStatus::Stopped : SoundStatus::Playing
  end

  def stopped?; status.stopped?; end
  def paused?; status.paused?; end

  private

  def _sample_bytes(type)
    case type.to_s.downcase.delete(':')
    when 'float', 'float32', 'f32' then 4
    when 'byte', 'int8', 's8', '8' then 1
    else 2
    end
  end
end

# ------------------------------------------------------------------ dialogs
# Elten's own signatures, from `src/ui/dialogs.rb` and `src/ui/speech.rb` -
# not guessed from call sites, because a guess that is subtly wrong is an
# `ArgumentError` in somebody else's application, and worse when it is wrong
# in a way that still runs.
module Kernel
  # `alert(text, wait=true)` - Elten's own is pure SPEECH, not a window:
  # Elten has no visual interface at all, so an "alert" is a sentence said
  # aloud, and `wait` is only ever about whether the caller blocks until it
  # has been said. Solitaire calls this after every arrow key
  # (`focus_position`, `alert(text, false)`) to say where the cursor is now -
  # which is also why this must NEVER be a dialog: a modal window on every
  # cursor move would make the board unplayable. It goes through `Speech`,
  # which is Titan's own voice, positioned and interruptible exactly like
  # everything else this desktop says.
  def alert(text, wait = true)
    Speech.speak(text.to_s, wait: wait)
    EltenBuffers.push('messages', text)
    nil
  end

  # `confirm(text="")` - yes/no, answering a boolean. Unlike `alert`, Elten's
  # own IS a real interaction (a two-item list, "No"/"Yes") and is asked
  # rarely enough that a real wx dialog is the right shape for it here too.
  # `get_file(header, path:, save:, extensions:)` - Elten's file chooser
  # (`src/ui/dialogs.rb`), answered with the platform's own picker. A
  # `nil` is the user cancelling; the record button and the file manager
  # both test for it.
  def get_file(header = '', path: '', save: false, extensions: nil, **_ignored)
    answer = EltenBridge.call('choose_path',
                              { 'header' => header.to_s, 'path' => path.to_s,
                                'directory' => false, 'save' => save == true,
                                'extensions' => Array(extensions).map(&:to_s) })
    answer.nil? || answer.to_s.empty? ? nil : answer.to_s
  rescue EltenBridge::Closed
    nil
  end

  def get_directory(header = '', path: '', **_ignored)
    answer = EltenBridge.call('choose_path',
                              { 'header' => header.to_s, 'path' => path.to_s,
                                'directory' => true })
    answer.nil? || answer.to_s.empty? ? nil : answer.to_s
  rescue EltenBridge::Closed
    nil
  end

  def confirm(text = '')
    !!EltenBridge.call('confirm', { 'text' => text.to_s })
  rescue EltenBridge::Closed
    false
  end

  # `select_action(actions, header:, start:, cancel:)` - what every
  # application's main menu is built out of. `actions` is a Hash or an Array
  # of `[key, label]` pairs; the answer is the KEY, not the label, so a
  # translated menu still branches correctly.
  def select_action(actions, header: '', start: nil, cancel: nil, **_ignored)
    entries = if actions.respond_to?(:each_pair)
      actions.to_a
    else
      Array(actions).map { |entry| entry.is_a?(Array) ? entry : [entry, entry.to_s] }
    end
    return cancel if entries.empty?

    rows = entries.map { |key, label| { 'key' => key.to_s, 'label' => label.to_s } }
    start_key = if start.is_a?(Integer)
      entries[start] ? entries[start][0].to_s : nil
    else
      start&.to_s
    end
    chosen = EltenBridge.call('select_action',
                              { 'entries' => rows, 'header' => header.to_s,
                                'start' => start_key })
    return cancel if chosen.nil?

    match = entries.find { |key, _label| key.to_s == chosen }
    match.nil? ? cancel : match[0]
  rescue EltenBridge::Closed
    cancel
  end

  # `selector(options, header:, start_index:, cancel_index:, ...)` - Elten's
  # own name for a list of strings to choose from, and what several
  # applications call directly rather than through `select_action`. It
  # answers the INDEX, or `cancel_index` when it was cancelled.
  def selector(options, header: '', start_index: 0, cancel_index: nil,
               flags: 0, border: true, cancel_key: nil, focus_on_tab: true,
               **_ignored)
    select_item(options, header: header, start_index: start_index,
                cancel_index: cancel_index)
  end

  # A plain list of strings to pick from - `selector`'s shape, answering the
  # index chosen or `cancel_index` (nil by default).
  def select_item(items, header: '', start_index: 0, cancel_index: nil, **_ignored)
    rows = Array(items)
    return cancel_index if rows.empty?

    chosen = EltenBridge.call('select_item',
                              { 'items' => rows.map(&:to_s), 'header' => header.to_s,
                                'start' => start_index.to_i })
    chosen.nil? ? cancel_index : chosen
  rescue EltenBridge::Closed
    cancel_index
  end

  # `display_text(text, header:, markdown:, escapable:)` - a screen of text
  # to READ, not to answer: an application's help, its rules, a changelog.
  # Solitaire's "Rules and controls" is this, and so is every other
  # application's. Shown as a read-only Titan window with the text in a real
  # text control, so the reader's own cursor, say-all and Ctrl+C all work on
  # it - which is what somebody reading a page of rules actually wants.
  def display_text(text, header: '', markdown: false, escapable: true,
                   **_ignored)
    EltenBridge.call('display_text',
                     { 'text' => text.to_s, 'header' => header.to_s })
    nil
  rescue EltenBridge::Closed
    nil
  end

  # `display_list(options, header:)` - a list to look through and leave.
  # Like `selector`, but nothing is chosen: it answers nil.
  def display_list(options, header: '', start_index: 0, quiet: false,
                   flags: 0, empty_label: nil, **_ignored)
    select_item(options, header: header, start_index: start_index)
    nil
  end

  # `display_table(columns, rows, header:)` - the same, with columns.
  def display_table(columns, rows, header: '', start_index: 0, quiet: false,
                    flags: 0, empty_label: nil, **_ignored)
    table = TableBox.new(columns, rows, header: header, index: start_index)
    back = Button.new(_('Close'))
    form = Form.new([table, back], header: header)
    form.cancel_button = back
    back.on(:press) { form.resume }
    table.on(:select) { form.resume }
    form.wait
    nil
  end

  # `menuselector(options)` - a bare list, answering the index or -1. Older
  # than `selector` and still called.
  def menuselector(options)
    chosen = select_item(Array(options).map { |option| option.to_s },
                         header: '')
    chosen.nil? ? -1 : chosen
  end

  # `waiting { ... }` - do something slow and say so. Titan shows the same
  # progress the Tasks API does.
  def waiting(&block)
    return nil if block.nil?

    Tasks.run { block.call }
  end

  def waiting_end
    nil
  end

  # The bookkeeping Elten does around a modal screen. Titan's own dialogs are
  # modal by being modal, so these answer and change nothing - but they must
  # ANSWER, because the library calls them around every dialog it opens.
  def dialog_open; nil; end
  def dialog_close; nil; end
  def dialog_opened; false; end
  def dialog_mute; nil; end
  def modal_interaction_open; nil; end
  def modal_interaction_close; nil; end
  def modal_interaction_active?; false; end
  def modal_interaction_time; 0.0; end
  def modal_interaction_elapsed; 0.0; end
  def speech_wait; nil; end

  # `loop_update` is deliberately NOT here. It is the frame - defined once,
  # on Kernel, in `loop.rb` - and a stub of it in this module shadows the
  # real one for every class that includes EltenAPI, which is the Runner,
  # every Program and every control. What that looked like: a vendored
  # Runner whose frame did nothing (so no key ever arrived) and
  # `ArgumentError: wrong number of arguments (given 1, expected 0)` the
  # moment anything asked for a frame of a stated length.

  # `prompt(header, confirmation, cancellation)` - a multi-line text answer,
  # or nil when cancelled.
  def prompt(header = '', confirmation = 'Ok', cancellation = _('Cancel'))
    EltenBridge.call('input_text',
                     { 'prompt' => header.to_s, 'default' => '',
                       'multiline' => true, 'password' => false,
                       'confirm' => confirmation.to_s,
                       'cancel' => cancellation.to_s })
  rescue EltenBridge::Closed
    nil
  end

  # `input_text(header, flags:, text:, escapable:, ...)` - Elten's own
  # signature, and it is worth being exact about: the header is
  # positional, everything else is a keyword, and `flags` is the same
  # bitmask an `EditBox` takes.
  #
  # `display_text` is BUILT on it in Elten - read-only plus multiline - so
  # an application asking to SHOW a page arrives here, and a signature
  # that took `default:` / `multiline:` instead answered
  # `unknown keywords: :escapable, :text` and ended the application on the
  # screen it was trying to put up.
  def input_text(header = '', flags: 0, text: '', default: nil,
                 escapable: false, max_length: 0, move_to_end: false,
                 select_all: false, permitted_characters: [],
                 denied_characters: [], character_counter: false,
                 multiline: nil, password: nil, **_ignored)
    flags = flags.to_i
    readonly = (EditBox::Flags::ReadOnly & flags).positive?
    lines = multiline.nil? ? (EditBox::Flags::MultiLine & flags).positive? : multiline
    secret = password.nil? ? (EditBox::Flags::Password & flags).positive? : password
    start = default.nil? ? text.to_s : default.to_s

    # Read-only IS a page to read rather than a field to type in, which is
    # what `display_text` asks for.
    if readonly
      EltenBridge.call('display_text',
                       { 'text' => start, 'header' => header.to_s })
      return nil
    end

    EltenBridge.call('input_text',
                     { 'prompt' => header.to_s, 'default' => start,
                       'multiline' => lines, 'password' => secret,
                       'max_length' => max_length.to_i })
  rescue EltenBridge::Closed
    nil
  end

  # What is held down right now. A game asks this inside its own loop -
  # Solitaire carries a card while Shift is down - so it must be the live
  # state of the keyboard and never a remembered event.
  def key_held?(name)
    !!EltenBridge.call('key_held', { 'name' => name.to_s })
  rescue EltenBridge::Closed
    false
  end

  def control_held?
    key_held?(:key_control)
  end

  def shift_held?
    key_held?(:key_shift)
  end

  def alt_held?
    key_held?(:key_alt)
  end

  # The keyboard scheme, as much of it as an application reads.
  # `main_modifier_name` is what a tip line is built out of - the media
  # catalogue writes "press CTRL+F to add to favourites" with this - and a
  # method that is merely missing ends the application on a `NameError`
  # where a list of radio stations should have appeared. On Windows the
  # main modifier is Control; the names are Elten's own spelling, upper
  # case, from `EltenAPI::KeyboardScheme.modifier_name`.
  MODIFIER_NAMES = { control: 'CTRL', command: 'COMMAND',
                     option: 'OPTION', shift: 'SHIFT' }.freeze

  def main_modifier
    :control
  end

  def word_modifier
    :control
  end

  def modifier_name(modifier = :main_modifier)
    modifier = main_modifier if modifier.to_sym == :main_modifier
    modifier = word_modifier if modifier.to_sym == :word_modifier
    MODIFIER_NAMES.fetch(modifier.to_sym, modifier.to_s.upcase)
  end

  def main_modifier_name
    modifier_name(:main_modifier)
  end

  def word_modifier_name
    modifier_name(:word_modifier)
  end

  def main_modifier_held?
    control_held?
  end

  def physical_control_held?
    control_held?
  end

  def navigation_modifier_held?
    control_held? || alt_held?
  end

  def main_shortcut_pressed?(key, shift: false, first: false)
    return false unless control_held?
    return false if shift && !shift_held?

    first ? key_first_pressed?("key_#{key}") : key_pressed?("key_#{key}")
  end

  def keyboard_action_label(_action)
    ''
  end

  # `play_sound(name)` - Elten's own name for making one of the interface's
  # noises: moving onto a row, choosing it, a branch opening, the end of a
  # list, a dialog. It comes out of TITAN's sound theme, because the user
  # picked that theme and this is their desktop - an application that
  # brought its own set would be the one thing on it that sounds like
  # somewhere else.
  #
  # Only the PLATFORM's cues are Titan's. A sound that belongs to the
  # application - a card being dealt, a clay pigeon, a bird - is the
  # application and not the interface, and falls through to the package's
  # own `Audio/` folder untouched. So mapping a cue can replace a sound and
  # can never lose one.
  #
  # `volume` is Elten's 0..100.
  # A sound that will not play is not a reason to stop either.
  def play_sound(name, volume: nil, position: nil, pan: nil, **_ignored)
    level = volume.nil? ? 1.0 : (volume.to_f / 100.0)
    level = 1.0 if level > 1.0
    # **Elten says where a sound is as 0 to 100; Titan says -1 to 1.**
    # Every line of Elten's own control code writes `pan: @sel.lpos`, and
    # handing one straight to the other puts everything from the centre
    # leftwards into the left speaker - the same mistake the shell's own
    # sounds once made. `position:` is Titan's spelling and wins when both
    # are given.
    position = (pan.to_f / 50.0) - 1.0 if position.nil? && !pan.nil?
    position = 0.0 if position.nil?
    !!EltenBridge.call('play_cue', { 'name' => name.to_s,
                                     'position' => position,
                                     'volume' => level })
  rescue EltenBridge::Closed
    false
  rescue StandardError => error
    Log.warning("#{name} could not be played: #{error.message}")
    false
  end

  # Elten's other spellings for the same thing.
  def play_sound_theme(name, **options)
    play_sound(name, **options)
  end

  def play_fallback(name, position: 0.0)
    play_sound(name, position: position)
  end
end

# `SoundPool` - Elten's own, from `src/eapi/audio/soundpool.rb`.
#
# A pool holds the one-shot sounds a game is playing and closes them when
# they have finished, with a ceiling on how many may be going at once. The
# ceiling is the point: a game that plays a click per keypress asks for
# thirty a second on a held arrow, and a mixer handed all of them runs out
# of channels and goes silent - which reads as the game having stopped.
class SoundPool
  DEFAULT_MAX_VOICES = 16

  attr_reader :max_voices

  def initialize(max_voices: DEFAULT_MAX_VOICES)
    @max_voices = normalise(max_voices)
    @sounds = []
    @lock = Mutex.new
    @closed = false
  end

  def max_voices=(value)
    value = normalise(value)
    removed = []
    @lock.synchronize do
      @max_voices = value
      removed = trim
    end
    close_all(removed)
    value
  end

  # `pool.play(sound)` - Elten's own signature. The sound is played, held
  # while it lasts, and closed when the pool has to make room.
  def play(sound)
    raise ArgumentError, 'sound must respond to play, finished? and close' unless managed?(sound)
    raise RuntimeError, 'sound pool is closed' if closed?

    sound.play
    removed = []
    @lock.synchronize do
      raise RuntimeError, 'sound pool is closed' if @closed

      @sounds << sound
      removed = trim
    end
    close_all(removed)
    sound
  rescue Exception
    begin
      sound.close
    rescue StandardError
      nil
    end
    raise
  end

  # Let go of everything that has finished. Called by the frame, so a game
  # that never asks still does not accumulate.
  def update
    finished = @lock.synchronize do
      done = @sounds.select do |sound|
        begin
          sound.finished?
        rescue StandardError
          true
        end
      end
      done.each { |sound| @sounds.delete(sound) }
      done
    end
    close_all(finished)
    finished.size
  end

  def remove(sound, close: false)
    @lock.synchronize { @sounds.delete(sound) }
    close_all([sound]) if close
    sound
  end

  def sounds
    @lock.synchronize { @sounds.dup }
  end

  def size
    @lock.synchronize { @sounds.size }
  end

  def close
    held = @lock.synchronize do
      @closed = true
      taken = @sounds
      @sounds = []
      taken
    end
    close_all(held)
    true
  end

  def closed?
    @closed == true
  end

  private

  def trim
    return [] if @sounds.size <= @max_voices

    @sounds.shift(@sounds.size - @max_voices)
  end

  def close_all(sounds)
    Array(sounds).each do |sound|
      begin
        sound.close
      rescue StandardError
        nil
      end
    end
  end

  def managed?(sound)
    sound.respond_to?(:play) && sound.respond_to?(:finished?) &&
      sound.respond_to?(:close)
  end

  def normalise(value)
    [value.to_i, 1].max
  end
end


# --------------------------------------------------------------------------
# The rest of Elten's top-level helpers
#
# Elten defines a handful of bare functions every application may call -
# `src/eapi/core/base.rb` and `src/eapi/common/*.rb` - and a name that is
# there and not here is a `NoMethodError` inside somebody else's program,
# usually inside their own `rescue`, where it becomes a feature quietly not
# working. `tests/check_elten_helpers.py` reads Elten's own sources and the
# installed applications and fails when one of these goes missing again.
# --------------------------------------------------------------------------
module Kernel
  # `delay(seconds)` - wait, WITHOUT stopping the interface. Elten pumps its
  # own loop while the time passes, which is why an application uses this
  # rather than `sleep`: a sleeping Elten answers no keys. `break_on_escape`
  # and the block are Elten's own two ways of cutting it short.
  def delay(time = 0, break_on_escape = false, &break_proc)
    deadline = Time.now.to_f + time.to_f
    while Time.now.to_f < deadline
      loop_update
      if (break_on_escape && key_pressed?(:key_escape)) ||
         (break_proc != nil && break_proc.call == true)
        loop_update
        return true
      end
    end
    false
  end

  # `delay_precise(seconds)` - the same, but the last stretch is really
  # slept rather than pumped, so a caller timing something gets the length
  # it asked for instead of the length of a whole frame.
  def delay_precise(time)
    finish = Time.now.to_f + time.to_f
    tick = 0.01
    loop_update while finish - Time.now.to_f > tick * 2
    sleep((finish - Time.now.to_f) * 0.8) while finish - Time.now.to_f > 0
    time
  end

  # `format_date(time, justdate=false, secs=true)` - Elten's own spelling of
  # a date, character for character: 2026-09-05 17:40:12.
  def format_date(date, justdate = false, secs = true)
    return '' if !date.is_a?(Time)

    text = format('%04d-%02d-%02d', date.year, date.month, date.day)
    if !justdate
      text += format(' %02d:%02d', date.hour, date.min)
      text += format(':%02d', date.sec) if secs
    end
    text
  end

  # `developer_mode?` - whether Elten is running with its developer tools
  # on. Elten's own reads a global; here it is off unless somebody sets
  # that global, because the tools it gates (the console, the debugger,
  # loading a translation by hand) are Elten's own and not this port's.
  # An application asking is `mcp`, which calls it through `super`.
  def developer_mode?
    $developer_mode == true
  end

  # `getsize(path)` - how big a file is, in bytes. A folder answers what
  # Elten's own answers for one, which is not a walk of it.
  def getsize(location, _update = true)
    return 0 if location.to_s == ''
    return [File.size(location), 0].max if File.file?(location)
    return Dir.children(location).size if File.directory?(location)

    0
  rescue Exception
    0
  end

  # `p_(context, text)` and `np_` - gettext with a CONTEXT, which is how
  # Elten tells apart a word translated differently in two places. A `.mo`
  # keys one as the context, U+0004 and the text; a catalogue with no
  # contexts in it therefore answers nothing, and the text itself is the
  # right fallback - which is exactly what Elten's own does.
  # A catalogue with no entry for the key answers the KEY - and the wire
  # strips the U+0004 out of it on the way back, so the answer was
  # "WeatherMainly clear." - context and text run together - and it was
  # taken for a translation. The Weather widget read that way on every
  # row. An answer that is the key with or without its separator is no
  # translation, and the text alone is what Elten answers then.
  def p_(context, src)
    EltenGettext.translate_context(context.to_s, src.to_s)
  end

  def np_(context, src, *params)
    plural, count = params[0].to_s, (params[1] || 1)
    answer = EltenBridge.call('translate_plural',
                              { 'one' => src.to_s, 'other' => plural, 'count' => count,
                                'context' => context.to_s })
    return answer if answer.is_a?(String) && !answer.empty?

    n_(src, *params)
  rescue EltenBridge::Closed
    n_(src, *params)
  end

  def _untranslated?(answer, key)
    answer.nil? || answer.to_s.empty? || answer == key ||
      answer == key.delete("\u0004") || answer == key.tr("\u0004", ' ')
  end

  # `platform_open_url(url)` - a link, in the browser the user has open.
  def platform_open_url(url)
    !!EltenBridge.call('open_url', { 'url' => url.to_s })
  rescue EltenBridge::Closed
    false
  rescue Exception
    false
  end

  # `insert_scene(scene)` - in Elten a scene is a screen and this is how one
  # opens another. There are no scenes here: an application's screens are
  # Titan windows and its own object is what it opened them from, so the
  # nearest true thing is to RUN it - `main` is what Elten's own loop would
  # have called - and to come back when it is finished, which is what the
  # caller does anyway.
  #
  # An object with no `main` is not a screen, and saying so beats opening
  # nothing in silence.
  def insert_scene(scene, _must = false, return_to_main: false)
    return false if scene.nil?

    if scene.respond_to?(:main)
      scene.main
      return true
    end
    if scene.respond_to?(:program_main)
      scene.program_main
      return true
    end

    Log.warning("insert_scene was given #{scene.class}, which is not a screen")
    false
  rescue Exception => e
    Log.warning("insert_scene: #{e.class}: #{e.message}")
    false
  end

  # ------------------------------------------------------------------------
  # More of Elten's BARE functions - the ones applications call with no
  # receiver. A name that is there and not here is a NoMethodError inside
  # somebody else's program, usually swallowed by its own `rescue` and seen
  # as a feature that quietly does nothing. Each of these was found by
  # reading what the installed applications really call and asking Elten's
  # own source whether it has it.
  # ------------------------------------------------------------------------

  # `process_notification(notif)` - `eapi/common/activity.rb`. A hash with
  # `'sound'` and `'alert'`. Tyflopodcast announces every new episode with
  # it, so without this the whole point of that application was a
  # NoMethodError. Elten's body, line for line.
  def process_notification(notif)
    return nil unless notif.is_a?(Hash)

    play_sound(notif['sound']) unless notif['sound'].nil?
    unless notif['alert'].nil?
      speak(notif['alert'], stop: false, break_sequence: false)
      EltenBuffers.push('notifications', notif['alert'])
    end
    nil
  end

  # `process_url(url)` - `eapi/common/url.rb`. Anything that is not
  # `elten://` goes to the browser the user has open, which is what BopIt
  # asks for when it offers its beta group.
  #
  # An `elten://` address names a SCENE inside Elten - a forum group, a
  # blog, a thread - and there are no scenes here, so it cannot be followed.
  # Elten's own code answers `false` for a path it does not recognise, which
  # makes that the honest answer rather than a new kind of failure.
  def process_url(url)
    return false unless url.is_a?(String)
    return platform_open_url(url) if url[0...8].to_s.downcase != 'elten://'

    Log.warning("process_url cannot follow #{url} - an elten:// address " \
                'names a screen inside Elten, and there are none here')
    false
  end

  # `getkeychar(keybd = nil, multi = false)` - `eapi/common/input.rb`. The
  # character just typed, as a String, and '' when nothing printable was.
  # Tyflopodcast reads its search box with `getkeychar(nil, true)`.
  #
  # Elten reads a 256-byte keyboard state and translates virtual keys; here
  # the frame already carries the keys BY NAME, so the printable ones are
  # turned back into characters, with Shift honoured. `keybd` is Elten's way
  # of asking about a state the caller already has, which this port never
  # hands out, so it is accepted and ignored rather than refused.
  PRINTABLE_KEYS = {
    'space' => ' ', 'tab' => "\t",
    'comma' => ',', 'period' => '.', 'slash' => '/', 'semicolon' => ';',
    'quote' => "'", 'bracketleft' => '[', 'bracketright' => ']',
    'backslash' => '\\', 'minus' => '-', 'equal' => '=', 'grave' => '`'
  }.freeze
  SHIFTED_KEYS = {
    ',' => '<', '.' => '>', '/' => '?', ';' => ':', "'" => '"',
    '[' => '{', ']' => '}', '\\' => '|', '-' => '_', '=' => '+',
    '`' => '~', '1' => '!', '2' => '@', '3' => '#', '4' => '$', '5' => '%',
    '6' => '^', '7' => '&', '8' => '*', '9' => '(', '0' => ')'
  }.freeze

  def getkeychar(keybd = nil, multi = false)
    _ = keybd
    # `raw_key_held?`, not `key_held?`: the latter asks TITAN over the bridge
    # for the live keyboard, and this is called once a FRAME by anything with
    # a text field - a round trip per frame is the trap that made moving a
    # sound three hundred blocking calls a second. The frame's own state is
    # also the right answer: the characters typed THIS frame, with the shift
    # that was down THIS frame.
    shifted = raw_key_held?('key_shift')
    typed = ''
    EltenLoop.pressed_names.each do |name|
      bare = name.start_with?('key_') ? name[4..].to_s : name.to_s
      character =
        if bare.length == 1 && bare.match?(/[a-z0-9]/)
          shifted ? (SHIFTED_KEYS[bare] || bare.upcase) : bare
        elsif PRINTABLE_KEYS.key?(bare)
          plain = PRINTABLE_KEYS[bare]
          shifted ? (SHIFTED_KEYS[plain] || plain) : plain
        end
      next if character.nil?

      typed += character
      break unless multi == true
    end
    typed
  end

  # `readini` / `writeini` - `eapi/core/base.rb`. Elten's own INI pair, and
  # what `readconfig` / `writeconfig` are built on.
  def readini(file, group, key, default = "\0")
    default = default.to_s if default.is_a?(Integer)
    return default.to_s unless File.file?(file.to_s)

    current = nil
    _elten_ini_lines(file).each do |line|
      text = line.to_s.strip
      if text =~ /\A\[(.+?)\]\s*\z/
        current = Regexp.last_match(1).to_s
      elsif !current.nil? && current.casecmp(group.to_s).zero? &&
            text =~ /\A([^=]+?)\s*=\s*(.*)\z/
        return Regexp.last_match(2).to_s if
          Regexp.last_match(1).to_s.strip.casecmp(key.to_s).zero?
      end
    end
    default.to_s
  rescue Exception => e
    Log.warning("readini(#{file}): #{e.class}: #{e.message}")
    default.to_s
  end

  def writeini(file, group, key, value)
    text_value = value.nil? ? nil : value.to_s.delete("\r\n")
    lines = File.file?(file.to_s) ? _elten_ini_lines(file) : []
    current = nil
    section_at = nil
    key_at = nil
    lines.each_with_index do |line, index|
      text = line.to_s.strip
      if text =~ /\A\[(.+?)\]\s*\z/
        current = Regexp.last_match(1).to_s
        section_at = index if current.casecmp(group.to_s).zero?
      elsif !current.nil? && current.casecmp(group.to_s).zero? &&
            text =~ /\A([^=]+?)\s*=/ &&
            Regexp.last_match(1).to_s.strip.casecmp(key.to_s).zero?
        key_at = index
      end
    end
    if key_at
      if text_value.nil?
        lines.delete_at(key_at)
      else
        lines[key_at] = "#{key}=#{text_value}"
      end
    elsif !text_value.nil?
      if section_at
        lines.insert(section_at + 1, "#{key}=#{text_value}")
      else
        lines << '' unless lines.empty? || lines.last.to_s.strip.empty?
        lines << "[#{group}]"
        lines << "#{key}=#{text_value}"
      end
    end
    directory = File.dirname(file.to_s)
    require 'fileutils'
    FileUtils.mkdir_p(directory) unless File.directory?(directory)
    File.binwrite(file.to_s, lines.join("\n") + "\n")
    true
  rescue Exception => e
    Log.warning("writeini(#{file}): #{e.class}: #{e.message}")
    false
  end

  # `readconfig(group, key, val = "")` / `writeconfig(group, key, val)` -
  # `eapi/core/base.rb` and `eapi/core/local_config.rb`. Pointed at ELTEN's
  # own `elten.ini`, so a setting made here is the setting Elten reads - the
  # rule `data_path` already follows for an application's saves. Reading an
  # absent key WRITES the default, which is Elten's own behaviour and what
  # makes a first run leave the file it will read next time.
  def readconfig(group, key, val = '')
    file = _elten_ini_path
    return val if file.nil?

    answer = readini(file, group, key, '$DEFAULT')
    if answer == '$DEFAULT'
      writeconfig(group, key, val)
      answer = val
    end
    return answer.to_i if val.is_a?(Integer)

    answer
  end

  def writeconfig(group, key, val)
    file = _elten_ini_path
    return false if file.nil?

    val = val.to_s unless val.nil?
    writeini(file, group, key, val)
  end

  private

  # Elten's own `elten.ini`, or NOTHING. `Dirs.eltendata` is empty when Elten
  # is not installed beside Titan, and joining an empty directory gives the
  # bare name `elten.ini` - which would write a configuration file into
  # whatever folder the process happens to have started in, and read it back
  # from somewhere else next time. Answering nil makes `readconfig` hand back
  # the default and `writeconfig` say it could not, which is the truth.
  def _elten_ini_path
    directory = Dirs.eltendata.to_s
    return nil if directory.strip.empty?

    EltenPath.join(directory, 'elten.ini')
  end

  def _elten_ini_lines(file)
    File.binread(file.to_s).force_encoding('UTF-8')
        .encode('UTF-8', invalid: :replace, undef: :replace, replace: '')
        .split(/\r\n|\r|\n/)
  rescue Exception
    []
  end
end
