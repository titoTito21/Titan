# Asking before Elten's own data leaves Elten.
#
# The rest of this add-on carries TITAN into Elten, and needs nobody's
# permission for that: it is the user's own desktop, reached from the
# program they are sitting in. One thing goes the other way - what Elten
# knows about them: who they are signed in as, the notifications their
# account has, what has arrived. That is data held in the Elten portal, and
# Titan's AI assistant is one of the things that would then read it.
#
# So it is asked for, once, in plain words, before any of it is sent, and
# the answer is remembered. Three things make the question honest rather
# than a formality:
#
# * **Nothing is shared until it is answered.** Not the notifications, not
#   the account name, not the fact that Elten is running. A user who never
#   opens this add-on is never asked and nothing ever leaves.
# * **No is a real answer.** The bridge goes on working - Titan's window,
#   its settings, Titan-Net, the shell, the AI itself are all still there,
#   because none of that is Elten's data. Only the Elten -> Titan direction
#   stops.
# * **It can be changed afterwards**, in this add-on's own settings, and
#   revoking it stops the sharing at the next tick.

module TitanConsent
  # Kept with the add-on's other settings, and deliberately THREE-valued:
  # unset means "not asked yet", which is not the same as "no".
  KEY = "share_data".freeze

  class << self
    def answered?
      !TitanPrefs.get(KEY).nil?
    end

    def granted?
      TitanPrefs.get(KEY) == true
    end

    def refused?
      TitanPrefs.get(KEY) == false
    end

    # Ask, once. **Must be called from Elten's own thread** - it puts a
    # dialog up - so it belongs at the top of a screen the user has just
    # opened, never on the extension tick: a consent question that appears
    # while somebody is reading their messages is a question they will
    # answer to get rid of.
    #
    # Answers true when sharing is allowed.
    def ensure_answered
      return granted? if answered?
      answer = ask
      remember(answer)
      answer
    end

    def ask
      # One msgid on one line: a message split across two Ruby literals is
      # looked up as the joined text, which is never what is in the
      # catalogue - it would have stayed English for ever.
      confirm(_("The AI assistant will use data stored on the Elten portal. Do you agree to share the necessary data with TCE?")) == true
    rescue Exception
      false
    end

    def remember(value)
      source = TitanPrefs.source
      return value if source == nil || !source.respond_to?(:update_json)
      source.update_json("settings.json", :default => {}) do |state|
        state[KEY] = (value == true)
      end
      value
    rescue Exception
      value
    end
  end
end
