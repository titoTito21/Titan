# Pressing a key in Elten, from Titan.
#
# This is the one thing in the bridge that DRIVES Elten rather than reading
# it, and it is the most dangerous: Enter in somebody's messenger sends the
# message. So it is behind a switch of its own, off by default, on top of
# the consent everything else here is behind - agreeing to SHARE data is not
# agreeing to be driven, and the two are asked separately because they are
# different questions.
#
# **Elten has its own way in, and this uses it rather than inventing one.**
# `key_update` builds each frame's keyboard from the hardware, from NVDA's
# gestures, and from `$setkeys` - a list of virtual key codes that count as
# pressed for exactly one frame (`KeyboardState.update(synthetic_keys:)`).
# That is how Elten's own NVDA bridge presses a key, so a key put there is
# indistinguishable from one the user pressed: `key_pressed?` answers true
# for that frame and `key_held?` with it, which is what a shortcut asks.
#
# It follows that this must run on ELTEN's thread. `key_update` drains the
# global and clears it in the same breath, so a worker writing to it while a
# frame is being built is a keystroke that is half there.

class EltenKeys
  #: Windows virtual key codes by the name somebody would say. Written out
  #: rather than read from `KeyboardScheme.KEY_CODES`, which holds only the
  #: handful that scheme needs - and these numbers are Windows', not
  #: Elten's, so there is nothing to keep in step.
  NAMES = {
    "enter" => 0x0D, "return" => 0x0D, "escape" => 0x1B, "esc" => 0x1B,
    "space" => 0x20, "tab" => 0x09, "backspace" => 0x08, "delete" => 0x2E,
    "insert" => 0x2D, "left" => 0x25, "up" => 0x26, "right" => 0x27,
    "down" => 0x28, "home" => 0x24, "end" => 0x23, "pageup" => 0x21,
    "page_up" => 0x21, "pagedown" => 0x22, "page_down" => 0x22,
    "shift" => 0x10, "ctrl" => 0x11, "control" => 0x11, "alt" => 0x12,
    "menu" => 0x5D, "context" => 0x5D, "apps" => 0x5D,
    "f1" => 0x70, "f2" => 0x71, "f3" => 0x72, "f4" => 0x73, "f5" => 0x74,
    "f6" => 0x75, "f7" => 0x76, "f8" => 0x77, "f9" => 0x78, "f10" => 0x79,
    "f11" => 0x7A, "f12" => 0x7B,
  }.freeze

  #: The modifiers, so a combination can be told from a key.
  MODIFIERS = %w[shift ctrl control alt].freeze

  #: At most this many keys in one request. A caller with a hundred keys is
  #: typing, and typing is `type_text`, which goes one frame at a time; a
  #: hundred keys in one frame is a hundred keys held down at once.
  MAX_KEYS = 8

  class << self
    def handlers
      {
        "press_key" => proc { |args| press(args["keys"]) },
        "keys_allowed" => proc { |_args| {"allowed" => allowed?} },
      }
    end

    # Both switches, and they are different questions: the consent is about
    # Elten's data leaving Elten, this is about Elten being driven.
    def allowed?
      TitanConsent.granted? && TitanPrefs.allow_keys?
    end

    def refusal
      return EltenNews.refusal if !TitanConsent.granted?
      "Elten is not letting TCE press keys in it. It is off by default - " \
      "pressing a key in Elten is not the same as reading it - and the " \
      "switch is in the TCE bridge's own settings, 'Let TCE press keys in " \
      "Elten'."
    end

    # `keys` is "down", "ctrl+s", or a list of either. Answers what was
    # pressed so a caller can say it, or an error.
    def press(keys)
      return refusal if !allowed?
      wanted = Array(keys.is_a?(String) ? keys.split(",") : keys)
                 .map { |entry| entry.to_s.strip }.reject(&:empty?)
      return {"error" => "say which key"} if wanted.empty?
      return {"error" => "that is more than #{MAX_KEYS} keys"} if
        wanted.size > MAX_KEYS
      pressed = []
      wanted.each do |combination|
        codes = codes_for(combination)
        return {"error" => "there is no key called '#{combination}'"} if codes == nil
        ok, value = EltenMain.call { send_codes(codes) }
        return {"error" => value.to_s} if !ok
        return {"error" => value["error"].to_s} if value.is_a?(Hash) && value["error"]
        pressed.push(combination)
      end
      {"pressed" => pressed}
    end

    # One combination, as the codes that make it up: "ctrl+shift+s" is the
    # two modifiers and the letter, all pressed in the same frame, which is
    # what a shortcut asks about.
    def codes_for(combination)
      parts = combination.to_s.downcase.split("+").map(&:strip).reject(&:empty?)
      return nil if parts.empty?
      codes = []
      parts.each do |part|
        code = NAMES[part]
        # A letter or a digit is itself: Windows' code for "a" is the
        # capital letter's, which is why this is not a lookup table of
        # twenty-six entries.
        code = part.upcase.ord if code == nil && part.size == 1 &&
                                  part =~ /\A[a-z0-9]\z/
        return nil if code == nil
        codes.push(code)
      end
      codes
    end

    # Runs ON Elten's thread. `$setkeys` is drained by the next
    # `key_update` and cleared in the same breath, so this appends rather
    # than assigns - two keys asked for in the same moment must not lose
    # each other - and it is only ever touched from here.
    def send_codes(codes)
      $setkeys = [] if !$setkeys.is_a?(Array)
      $setkeys += codes
      {"sent" => codes}
    rescue Exception => e
      {"error" => "#{e.class}: #{e.message}"}
    end
  end
end
