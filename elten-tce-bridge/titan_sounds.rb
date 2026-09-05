# Titan's own sounds, played from Elten.
#
# The user chose a sound theme in Titan, and Titan plays a particular sound
# for a particular thing: `titannet/new_message.ogg` when a private message
# arrives, `titannet/new_feedpost.ogg` for a forum reply,
# `titannet/titannet-notification.ogg` for a new application. A bridge that
# announces those events should announce them the way Titan does - the name
# is theme-relative, so whichever theme is chosen is the one that is heard.
#
# It is a setting, because somebody using Elten may want Elten's own sounds
# and nothing else; and it costs nothing when it is off, because the call is
# never made.

module TitanSounds
  # The names Titan itself plays, from src/network/titan_net_gui.py and
  # src/ui/invisibleui.py.
  NEW_MESSAGE = "titannet/new_message.ogg".freeze
  NEW_POST = "titannet/new_feedpost.ogg".freeze
  NOTIFICATION = "titannet/titannet-notification.ogg".freeze
  LIST = "ui/applist.ogg".freeze
  FOCUS = "core/focus.ogg".freeze
  STATUS = "statusbar.ogg".freeze

  # Which sound Titan plays for which piece of news.
  FOR_NEWS = {
    "unread_messages" => NEW_MESSAGE,
    "unread_mail" => NEW_MESSAGE,
    "unread_forum_topics" => NEW_POST,
    "new_apps" => NOTIFICATION,
    "app_updates" => NOTIFICATION,
  }.freeze

  class << self
    attr_writer :bus

    def play(name)
      return false if !TitanPrefs.tce_sounds?
      return false if @bus == nil || !@bus.connected?
      # Fire and forget: a sound is not something to wait for, and the
      # thread that wants it is usually Elten's own.
      @bus.call("titan", "bridge",
                {"request" => JSON.generate({"call" => "sounds.play",
                                             "args" => {"name" => name}})})
      true
    rescue Exception
      false
    end

    def for_news(key)
      play(FOR_NEWS[key.to_s] || NOTIFICATION)
    end
  end
end
