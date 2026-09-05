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
    def speak(text, interrupt: true, position: 0.0, pitch: 0.0, wait: false)
      return if text.nil?

      EltenBridge.call('speak', { 'text' => text.to_s,
                                  'interrupt' => interrupt,
                                  'position' => position, 'pitch' => pitch,
                                  'wait' => wait })
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

  def volume=(value)
    @volume = value.to_f
    EltenBridge.call('sound_volume', { 'handle' => @handle, 'volume' => value })
  rescue EltenBridge::Closed
    nil
  end

  def position=(value)
    EltenBridge.call('sound_position', { 'handle' => @handle,
                                         'position' => value })
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
    EltenBridge.call('sound_position', { 'handle' => @handle,
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
          EltenBridge.call('sound_position', { 'handle' => @handle,
                                              'position' => step })
          sleep(0.02)
        end
        unless @closed
          @position = target
          EltenBridge.call('sound_position', { 'handle' => @handle,
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
  def pause
    return false if @closed

    !!EltenBridge.call('sound_pause', { 'handle' => @handle,
                                        'paused' => true })
  rescue EltenBridge::Closed
    false
  end

  def resume
    play
  end

  def closed?
    @closed
  end

  def opened?
    !@closed
  end

  def stopped?
    !playing?
  end

  def finished?
    !@closed && !playing?
  end

  def pan
    _coordinates(@position)[0]
  end

  def pan=(value)
    self.position = value
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
    EltenBridge.call('sound_pitch',
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
    return :closed if @closed
    return :paused if paused?

    playing? ? :playing : :stopped
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
    loop_update(0.02) while playing? && (deadline.nil? || EltenBridge.now < deadline)
    self
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

  def length
    0.0
  end

  def on(_event, &_block)
    self
  end

  def _coordinates(position)
    return [0.0, 0.0, 0.0] if position.nil?
    return [Float(position), 0.0, 0.0] if position.is_a?(Numeric)

    values = Array(position)
    [values[0].to_f, values[1].to_f, values[2].to_f]
  rescue StandardError
    [0.0, 0.0, 0.0]
  end

  # Wait for it to finish. Used by an application that plays a fanfare and
  # then leaves; without it the window closes over the sound.
  def wait(timeout = 30.0)
    deadline = EltenBridge.now + timeout
    sleep(0.05) while playing? && EltenBridge.now < deadline
    self
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
    nil
  end

  # `confirm(text="")` - yes/no, answering a boolean. Unlike `alert`, Elten's
  # own IS a real interaction (a two-item list, "No"/"Yes") and is asked
  # rarely enough that a real wx dialog is the right shape for it here too.
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
