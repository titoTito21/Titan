# frozen_string_literal: true

# `loop_update` - the one place a frame happens.
#
# Elten is a single-threaded polling loop: `loop_update` takes a frame of
# input, and everything else - a `Runner`, a `Form`, a control waiting for a
# row - is a `while` around it asking what happened. That model is why
# `key_pressed?` ("it went down THIS frame") and `key_held?` ("it is down
# now") are different questions, and why Elten's own `Runner` can be
# vendored here unchanged: it needs a frame and five questions, and this is
# the frame.
#
# So there is exactly ONE consumer of the event queue. Two loops each
# draining it - which is what a `Runner` and a `Form#wait` reading
# `next_event` separately would be - lose each other's events: a key press
# swallowed by whichever loop happened to ask first.

module EltenLoop
  @pressed = {}
  @released = {}
  @held = {}
  @time = 0.0
  @closed = false
  @asked_with = nil

  class << self
    attr_reader :time

    def closed?
      @closed
    end

    # One frame: forget last frame's edges, then take everything waiting.
    #
    # `wait` is how long to block if nothing has happened yet - a game with
    # a frame interval wants to come round at that rate rather than spin,
    # and a form waiting on a person wants to sit still.
    def pump(wait = 0.02)
      ensure_somewhere_for_keys
      @pressed = {}
      @released = {}
      @time = EltenBridge.now
      first = true
      loop do
        event = EltenBridge.next_event(first ? wait : 0.0)
        first = false
        if event.nil?
          @closed = true
          break
        end
        break if event == :timeout

        deliver(event)
      end
      @time
    end

    # **A loop with no window gets no keys.** Purrposterous is a `Runner`
    # and nothing else - hold Left and Right to move, Space to feed - with
    # no form, no list and no control anywhere in it, so there was no
    # window of Titan's to have the keyboard and not one key ever reached
    # it. The game ran, ticked its whole length and could not be played:
    # from the outside, a game that made noises and had no game in it.
    #
    # So the FRAME is what makes sure there is somewhere for keys to
    # arrive, because every loop goes through here. A form is already a
    # window with the keyboard, so one is asked for only when there is no
    # form open - and only when that has actually changed, since asking on
    # every frame would be a round trip sixty times a second.
    def ensure_somewhere_for_keys
      return if @closed

      open_forms = defined?(EltenForms) ? EltenForms.count : 0
      return if open_forms.positive?
      return if @asked_with == 0

      @asked_with = 0
      EltenBridge.call('open_keyboard', {})
    rescue EltenBridge::Closed
      @closed = true
    end

    # A form opening or closing means the answer above may have changed.
    def surface_changed
      @asked_with = nil
    end

    def key_pressed?(name)
      any?(@pressed, name)
    end

    def key_released?(name)
      any?(@released, name)
    end

    def key_held?(name)
      any?(@held, name)
    end

    # Elten's own words for the modifiers an application asks about.
    def modifier_held?(which)
      case which.to_s
      when 'main_modifier', 'control', 'ctrl' then key_held?('key_control')
      when 'option', 'alt' then key_held?('key_alt')
      when 'shift' then key_held?('key_shift')
      else key_held?(which)
      end
    end

    def held
      @held.keys
    end

    # Nothing may stay held when the window loses the keyboard, or a game
    # walks into a wall for ever because Left never came up.
    def release_all
      @held.each_key { |name| @released[name] = true }
      @held = {}
    end

    private

    # A key answers to both its spellings: Elten writes `hold: [:key_left,
    # :a]`, so `a` and `key_a` are the same key and a game that binds one
    # must not lose the other.
    def any?(table, name)
      wanted = name.to_s.downcase
      return true if table[wanted]

      other = wanted.start_with?('key_') ? wanted[4..] : "key_#{wanted}"
      !!table[other]
    end

    def deliver(event)
      return unless event.is_a?(Hash)

      case event['event']
      when 'key'
        name = event['name'].to_s.downcase
        # An auto-repeat is "still down", not a second press - which is the
        # difference between walking and teleporting.
        @pressed[name] = true unless event['repeat']
        @held[name] = true
      when 'key_up'
        name = event['name'].to_s.downcase
        @released[name] = true
        @held.delete(name)
      when 'blur'
        release_all
      when 'control'
        # A control somebody is showing was used. Whichever loop is running
        # dispatches it, because either may be the one that is.
        EltenForms.dispatch(event) if defined?(EltenForms)
      when 'close'
        @closed = true
      end
    end
  end
end

module Kernel
  # The frame. Everything that loops calls this and then asks what happened.
  def loop_update(wait = 0.02)
    EltenLoop.pump(wait)
  end

  def loop_update_time
    EltenLoop.time
  end

  def key_pressed?(name)
    EltenLoop.key_pressed?(name)
  end

  def key_released?(name)
    EltenLoop.key_released?(name)
  end

  def key_first_pressed?(name)
    EltenLoop.key_pressed?(name)
  end

  def raw_key_held?(name)
    EltenLoop.key_held?(name)
  end

  def modifier_held?(which)
    EltenLoop.modifier_held?(which)
  end

  def keyboard_input_idle?
    false
  end
end
