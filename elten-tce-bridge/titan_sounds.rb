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
#
# **Three of these sounds already mean one thing each, and they are spent on
# that and on nothing else.** They are the only ones every TCE theme carries,
# which is what makes them the vocabulary rather than decoration:
#
#     core/FOCUS.ogg     the cursor moved from one row to the next
#     ui/applist.ogg     the keyboard ARRIVED on the list
#     ui/statusbar.ogg   the keyboard ARRIVED on the status bar
#
# So `applist` is what this add-on plays when the keyboard enters a list and
# `statusbar` when it enters the status bar - which is exactly what TCE's own
# main window plays for the same two movements (`play_applist_sound` from
# `_focus_current_view_control`, `play_statusbar_sound` from the status bar).
# Using either of them for anything else would be the desktop's own word for
# a place, said about something that is not a place.

module TitanSounds
  # ----------------------------------------------------- moving about
  # The names TCE itself plays, from `src/titan_core/sound.py` (the
  # `play_*_sound` helpers), `src/ui/gui.py` and `src/ui/invisibleui.py`.
  FOCUS = "core/FOCUS.ogg".freeze          # one row to the next
  LIST = "ui/applist.ogg".freeze           # arriving on the list
  STATUS = "ui/statusbar.ogg".freeze       # arriving on the status bar
  EDGE = "ui/endoflist.ogg".freeze         # there is nothing past this row
  SELECT = "core/SELECT.ogg".freeze        # that row was chosen
  CLICK = "core/click.ogg".freeze
  ERROR = "core/error.ogg".freeze

  # ------------------------------------------------- screens and windows
  # The bridge's own screens are TCE's screens, so they open and close with
  # the sounds TCE opens and closes its own with, and the tab bar uses the
  # one TCE uses for exactly that - switching a category.
  OPEN = "ui/tui_open.ogg".freeze
  CLOSE = "ui/tui_close.ogg".freeze
  SWITCH = "ui/switch_category.ogg".freeze
  TAB = "ui/switch_list.ogg".freeze
  MENU = "ui/contextmenu.ogg".freeze
  MENU_CLOSE = "ui/contextmenuclose.ogg".freeze
  DIALOG = "ui/dialog.ogg".freeze
  DIALOG_CLOSE = "ui/dialogclose.ogg".freeze
  WIDGET = "ui/widget.ogg".freeze
  TICKED = "ui/cb_listitem_checked.ogg".freeze
  SECTION = "ui/sectionchange.ogg".freeze
  TIP = "ui/tip.ogg".freeze

  # -------------------------------------------------------------- the AI
  # TCE keeps the AI's own set in `sfx/<theme>/AI/`, and plays it through
  # `play_ai_sound` so the feature is heard whichever theme is chosen.
  # `ai_speech.SOUND_QUESTION` is what TCE plays when the AI needs an
  # answer before it can go on, and this bridge asks that same question
  # with Elten's own controls - so it makes the same noise first.
  AI_READY = "ai/initialized.ogg".freeze
  AI_QUESTION = "ai/agent_question.ogg".freeze
  AI_ERROR = "ai/action_error.ogg".freeze
  AI_SENT = "ai/ui1.ogg".freeze
  AI_ANSWER = "ai/ui2.ogg".freeze

  # ---------------------------------------------------------- the machine
  MACRO_START = "macro/macro_start.ogg".freeze
  MACRO_END = "macro/macro_end.ogg".freeze
  VOLUME = "system/volume.ogg".freeze
  ONLINE = "system/online.ogg".freeze
  OFFLINE = "system/offline.ogg".freeze
  NETWORK_ON = "system/network_connect.ogg".freeze
  NETWORK_OFF = "system/network_disconnect.ogg".freeze
  UPDATE = "system/newupdate.ogg".freeze
  INSTALLING = "system/installingapps.ogg".freeze
  COMPONENT_ERROR = "system/component_error.ogg".freeze
  ADDON_ERROR = "system/addon_error.ogg".freeze
  APP_UPDATED = "apprepo/appupdate.ogg".freeze
  PROCESS_OPEN = "system/sysprocess_open.ogg".freeze
  PROCESS_CLOSE = "system/sysprocess_close.ogg".freeze

  # ----------------------------------------------------- people and files
  NEW_MESSAGE = "titannet/new_message.ogg".freeze
  NEW_POST = "titannet/new_feedpost.ogg".freeze
  NOTIFICATION = "titannet/titannet-notification.ogg".freeze
  SENT = "titannet/message_send.ogg".freeze
  SUCCESS = "titannet/titannet_success.ogg".freeze
  FILE_SAVED = "titannet/file_success.ogg".freeze
  FILE_FAILED = "titannet/file_error.ogg".freeze
  USER_ONLINE = "system/user_online.ogg".freeze
  USER_OFFLINE = "system/user_offline.ogg".freeze

  # Which sound Titan plays for which piece of news.
  FOR_NEWS = {
    "unread_messages" => NEW_MESSAGE,
    "unread_mail" => NEW_MESSAGE,
    "unread_forum_topics" => NEW_POST,
    "new_apps" => NOTIFICATION,
    "app_updates" => NOTIFICATION,
  }.freeze

  # **Every event this add-on can make a noise about, by name.** An action
  # of Titan's that happens in here - a macro running, a setting saved, the
  # AI answering, something failing - should sound the way it sounds in
  # Titan, and naming them is what lets a screen ask for one without
  # knowing which file it is. `TitanSounds.event(:saved)`.
  EVENTS = {
    :focus => FOCUS, :list => LIST, :status => STATUS, :edge => EDGE,
    :select => SELECT, :click => CLICK, :error => ERROR,
    :open => OPEN, :close => CLOSE, :switch => SWITCH, :tab => TAB,
    :menu => MENU, :menu_close => MENU_CLOSE, :dialog => DIALOG,
    :dialog_close => DIALOG_CLOSE, :widget => WIDGET, :ticked => TICKED,
    :section => SECTION, :tip => TIP,
    :ai_ready => AI_READY, :ai_question => AI_QUESTION,
    :ai_error => AI_ERROR, :ai_sent => AI_SENT, :ai_answer => AI_ANSWER,
    :macro_start => MACRO_START, :macro_end => MACRO_END,
    :volume => VOLUME, :online => ONLINE, :offline => OFFLINE,
    :network_on => NETWORK_ON, :network_off => NETWORK_OFF,
    :update => UPDATE, :installing => INSTALLING,
    :component_error => COMPONENT_ERROR, :addon_error => ADDON_ERROR,
    :app_updated => APP_UPDATED,
    :process_open => PROCESS_OPEN, :process_close => PROCESS_CLOSE,
    :message => NEW_MESSAGE, :post => NEW_POST,
    :notification => NOTIFICATION, :sent => SENT, :saved => SUCCESS,
    :file_saved => FILE_SAVED, :file_failed => FILE_FAILED,
    :user_online => USER_ONLINE, :user_offline => USER_OFFLINE,
  }.freeze

  #: How close together two arrivals on one control have to be to be the
  #: same arrival. Elten builds a form by focusing its first field and the
  #: screen then asks for the keyboard itself; both are the same moment.
  ARRIVAL_DEBOUNCE = 0.3

  class << self
    attr_writer :bus

    # `pan` is Elten's own 0 to 100 - which is what every control here
    # answers with (`lpos`) - and Titan's `sounds.play` takes 0 to 1. The
    # two disagree, and handing one straight to the other is what puts
    # everything from the centre leftwards into the left speaker.
    def play(name, pan = nil)
      return false if !TitanPrefs.tce_sounds?
      return false if @bus == nil || !@bus.connected?
      args = {"name" => name}
      args["pan"] = clamp(pan.to_f / 100.0) if pan != nil
      # Fire and forget: a sound is not something to wait for, and the
      # thread that wants it is usually Elten's own.
      @bus.call("titan", "bridge",
                {"request" => JSON.generate({"call" => "sounds.play",
                                             "args" => args})})
      true
    rescue Exception
      false
    end

    # One of Titan's events, by the name the event is called by. A name
    # nothing is mapped to is not an error - it is an event this build of
    # Titan has no sound for, and the screen carries on.
    def event(key, pan = nil)
      name = EVENTS[key.to_sym]
      name == nil ? false : play(name, pan)
    end

    def for_news(key)
      play(FOR_NEWS[key.to_s] || NOTIFICATION)
    end

    def clamp(value)
      return 0.0 if value < 0.0
      return 1.0 if value > 1.0
      value
    end

    # Elten's controls make their own noises, and with TCE's sounds on you
    # would hear both - two focus sounds for one movement. Elten's ListBox
    # guards only its `play_sound` calls with `silent`, never its speech, so
    # this quiets the sound and leaves the announcement exactly as it was.
    def quiet(control)
      return control if !TitanPrefs.tce_sounds?
      control.silent = true if control.respond_to?(:silent=)
      control
    end

    # **A list that sounds like a TCE list.** Quieting a control on its own
    # makes it silent; this is the other half, and the two belong together
    # or a screen is one or the other by accident. `entering` is what is
    # heard when the keyboard ARRIVES on it - `applist` for a list, and
    # `statusbar` for the status bar, which is what TCE plays for those two
    # movements and what this add-on must not spend on anything else.
    #
    # Elten fires `:focus` when a form gives a field the keyboard, `:move`
    # as the cursor goes down it, `:border` at either end and `:select` on
    # Enter - and every one of Elten's own sounds for those four is behind
    # `@silent == false`, so quieting really does leave exactly one sound
    # per movement. Handlers are ADDED, never replaced (`FormBase#on`
    # pushes), so a screen still binds its own work to `:select`.
    def cued(control, entering = LIST)
      quiet(control)
      return control if !TitanPrefs.tce_sounds?
      return control if !control.respond_to?(:on)
      where = proc { control.respond_to?(:lpos) ? control.lpos : nil }
      # **A form focuses field 0 when it is BUILT and again when the screen
      # asks for the keyboard**, which is one arrival announced twice - so
      # `:focus` is debounced with the interval `FormBase#on` already takes.
      # `:move` is not: holding an arrow key really is one movement per row.
      control.on(:focus, ARRIVAL_DEBOUNCE) { play(entering, where.call) }
      control.on(:move) { play(FOCUS, where.call) }
      control.on(:border) { play(EDGE, where.call) }
      control.on(:select) { play(SELECT, where.call) }
      control
    end
  end
end
