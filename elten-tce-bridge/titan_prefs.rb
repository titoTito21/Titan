# What the user chose for the bridge, without a screen having to know where
# it is kept.
#
# The settings live in the application's own `settings.json`, which only the
# Program class can read (`read_json` belongs to the runtime). A screen that
# reached for that class was coupled to it and could not be opened without
# it - which is exactly what a test found, and what would break the moment
# a screen is used from somewhere else.
#
# So the application hands itself over once, and everything else asks here.
# With nobody handed over, the defaults answer: the bridge works, it simply
# has not been told otherwise.

module TitanPrefs
  DEFAULTS = {
    "announce_news" => true,
    "news_minutes" => 3,
    "speak_answers" => true,
    "confirm_launch" => false,
    "tce_sounds" => true,
    "elten_notifications" => true,
    "allow_keys" => false,
    "render_apps" => false,
    "widget" => true,
    "allow_writes" => false,
    "share_with_ai" => false,
  }.freeze

  class << self
    attr_writer :source

    def source
      @source
    end

    def get(key)
      if @source != nil && @source.respond_to?(:bridge_setting)
        value = @source.bridge_setting(key, DEFAULTS[key])
        return value if value != nil
      end
      DEFAULTS[key]
    end

    def announce_news?
      get("announce_news") == true
    end

    def news_minutes
      value = get("news_minutes").to_i
      value < 1 ? DEFAULTS["news_minutes"] : [value, 60].min
    end

    def speak_answers?
      get("speak_answers") == true
    end

    def confirm_launch?
      get("confirm_launch") == true
    end

    def tce_sounds?
      get("tce_sounds") == true
    end

    # **A widget you cannot take off your home screen is rude.** On by
    # default because somebody who installed this add-on wants TCE where
    # they can see it, and off is one checkbox away - which is exactly
    # what Elten's own weather widget does (`visible: -> { enabled? }`).
    def widget?
      get("widget") == true
    end

    # **Reading Elten and ACTING in Elten are different questions**, the
    # same split as `allow_keys?` and for the same reason: what Titan
    # does through this acts in the user's own name, in a program other
    # people can see the results of. Off by default, and not implied by
    # either consent.
    def allow_writes?
      get("allow_writes") == true
    end

    # **Telling the user is not the same as telling a model.**
    #
    # A notification pushed into Titan's notification centre stays on the
    # user's own machine: it makes a sound, a screen reader says it, it
    # goes in the Titan buffer. A notification READ BACK - by Perun or
    # Melitele answering "have I anything waiting in Elten" - is the text
    # of somebody's private message put into a prompt and sent to a model
    # provider. That is Elten's data leaving the machine entirely, which
    # the first question did not cover and the desktop notification does
    # not need.
    #
    # **Off by default.** It was written the other way round, on the
    # grounds that answering that question is what the assistant's Elten
    # tools are FOR - which is true and is not a reason: a default is who
    # bears the cost of not having thought about it, and here that cost
    # is somebody's private messages at a third party. Being useful is
    # worth one switch; it is not worth spending a privacy answer nobody
    # gave. Off leaves the notifications themselves working exactly as
    # they were - the sound, the reader, the notification centre - and
    # leaves Titan able to say that Elten is running and who is signed in.
    def share_with_ai?
      get("share_with_ai") == true
    end

    def elten_notifications?
      get("elten_notifications") == true
    end

    # **Off by default, and deliberately not part of the consent.** Letting
    # TCE READ Elten and letting it PRESS KEYS in Elten are different
    # questions - Enter in a messenger sends the message - so they are asked
    # separately and this one starts as no.
    # **Where a TCE application appears when it is started from here.**
    #
    # Off, it opens in TCE - a window on the other machine's screen, which
    # is what starting an application has always meant here and what
    # somebody who is at both computers wants.
    #
    # On, it opens IN ELTEN: the application runs with no window at all,
    # describes its interface as data, and this add-on builds that out of
    # Elten's own controls. Which is the more useful of the two depends
    # entirely on where the person is sitting, so it is a choice rather
    # than a decision made for them.
    #
    # Experimental, and off by default, because it really is: an
    # application whose interface cannot be described (a web view, a media
    # surface) is read off its own window instead, which is a weaker thing
    # and says so - and no amount of care makes "somebody else's program,
    # rendered by us" as sure as the program's own window.
    def render_apps?
      get("render_apps") == true
    end

    def allow_keys?
      get("allow_keys") == true
    end
  end
end
