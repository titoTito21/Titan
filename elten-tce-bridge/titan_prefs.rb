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

    def elten_notifications?
      get("elten_notifications") == true
    end
  end
end
