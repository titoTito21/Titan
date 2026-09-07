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

# **There are two questions, and they are not the same question.**
#
# The first is the NECESSARY data: who is signed in, the notifications
# that arrived, what is on the screen - what the bridge needs to be a
# bridge at all, and what it has always asked for.
#
# The second is EVERYTHING: Titan's AI and Titan's actions reaching
# Elten's own API for whatever they are asked about. Somebody who agreed
# to let Titan tell them a message arrived has not thereby agreed to let
# it read their client on any subject, and rolling the two into one
# question would be taking the second answer by asking the first. So it
# is a second question, asked separately, off until it is answered, and
# refusing it leaves everything above it working.

module TitanConsent
  # Kept with the add-on's other settings, and deliberately THREE-valued:
  # unset means "not asked yet", which is not the same as "no".
  KEY = "share_data".freeze

  #: The wider one. Never implied by the first, and never asked before it:
  #: a question about ALL of somebody's data put to somebody who has not
  #: yet agreed to any of it is a question with no context.
  FULL_KEY = "share_everything".freeze

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

    # ------------------------------------------------------ all of it
    def full_answered?
      !TitanPrefs.get(FULL_KEY).nil?
    end

    def full_granted?
      granted? && TitanPrefs.get(FULL_KEY) == true
    end

    # **Asked only once the first has been**, and only where the user
    # went looking for it - never on the tick. It is the wider question,
    # so it is put in the words that say what it really allows rather
    # than in words that make it sound like a formality.
    def ensure_full_answered
      return false if !ensure_answered
      return full_granted? if full_answered?
      answer = ask_full
      remember(answer, FULL_KEY)
      answer
    end

    def ask_full
      confirm(_("Do you agree that Titan may use all of Elten's data - your account, your settings, what is installed and what is on the screen - whenever its AI or one of its actions asks for it?")) == true
    rescue Exception
      false
    end

    def remember(value, key = KEY)
      source = TitanPrefs.source
      return value if source == nil || !source.respond_to?(:update_json)
      source.update_json("settings.json", :default => {}) do |state|
        state[key] = (value == true)
      end
      value
    rescue Exception
      value
    end
  end
end
