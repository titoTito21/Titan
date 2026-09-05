=begin Elten3AppInfo
{
  "id": "e6a514cc-bffc-4bf4-9a8d-adc8b8471558",
  "name": "TCE bridge",
  "description": "TCE (Titan) inside Elten: its applications, games, components, Titan IM modules, status bar, settings and Titan-Net - and its voices as an Elten speech output. Needs Titan running on this machine.",
  "version": "1.0.0",
  "build_id": 20260904001,
  "EltenAPIVersion": "3.0.1",
  "author": "titosoft",
  "main": "__app.rb",
  "main_class": "ProgramTCEBridge",
  "platforms": ["windows"],
  "main_language": "en",
  "supported_languages": ["en", "pl"],
  "localized_descriptions": {
    "pl": "TCE (Titan) w Eltenie: aplikacje, gry, komponenty, moduly Titan IM, pasek stanu, ustawienia i Titan-Net, a takze glosy Titana jako syntezator Eltena. Wymaga uruchomionego Titana."
  },
  "menu": {
    "main": "TCE bridge"
  }
}
=end Elten3AppInfo

# TCE bridge - Titan, reached from Elten.
#
# Two halves, and they are independent of each other:
#
# ONE, Titan's VOICES become an Elten speech output. Elten registers an
# output by inheritance - SpeechOutput.inherited collects every subclass and
# SpeechOutput.voices is computed from that list whenever it is asked - so
# `TitanSpeechOutput` appears in Elten's ordinary voice list in Settings
# with nothing in Elten patched or replaced.
#
# TWO, Titan's own interface is rebuilt here: its applications and games,
# its components, its Titan IM modules, its status bar, its settings with
# their categories, and Titan-Net. Everything crosses one named pipe -
# Titan's action bus - so this add-on does nothing at all on its own and
# says so plainly when Titan is not running.
#
# Nothing here needs Elten and Titan to know about each other: Titan's bus
# is the interface it already offers every add-on, and Elten's speech
# output and controls are the interface it already offers every
# application.

require_relative "titan_bus"
require_relative "titan_ui"
require_relative "titan_api"
require_relative "titan_prefs"
require_relative "titan_consent"
require_relative "titan_sounds"
require_relative "titan_speech_output"
require_relative "titan_actions"
require_relative "titan_settings"
require_relative "titan_net"
require_relative "titan_im"
require_relative "titan_system"
require_relative "titan_tools_ui"
require_relative "titan_widgets"
require_relative "titan_watch"
require_relative "elten_main"
require_relative "elten_news"
require_relative "elten_screen"
require_relative "titan_components"
require_relative "titan_macros"
require_relative "titan_cling"
require_relative "titan_ai"
require_relative "titan_shell"
require_relative "titan_areas"
require_relative "titan_console"

class ProgramTCEBridge < Program
  class << self
    # The one connection, shared by the voice and by every screen. Made
    # lazily rather than in an initialize: an application's constructor is
    # its OWN, and anything the platform needs must be able to make itself.
    def bus
      @bus ||= TitanBus.new
    end

    def activate
      # **What Titan may ask of US, declared before the connection is
      # made** - the names travel in the hello, so a bus started first
      # would join saying it serves nothing.
      bus.serve(EltenNews.handlers.merge(EltenScreen.handlers))
      bus.start
      TitanSpeechOutput.start(bus)
      # Elten applies the configured voice while it is loading, which is
      # BEFORE applications are loaded - so a user whose chosen voice is
      # this one would have been left on whatever Elten fell back to.
      # Asking for it again once the output exists is what makes the choice
      # survive a restart.
      apply_voice_settings
      TitanPrefs.source = self
      TitanSounds.bus = bus
      TitanWatch.start(bus)
      EltenNews.start(bus)
      register_quick_actions
      extension("tce_bridge") do |extension|
        # An extension stays loaded while Elten runs, with or without a
        # window of ours open, so this is what notices that something has
        # arrived on Titan-Net. The tick is Elten's own main pump: it posts
        # a question to the bus and says whatever the last answer brought,
        # and it never waits for either.
        extension.tick(:interval => 5) do
          TitanWatch.enabled = TitanPrefs.announce_news?
          TitanWatch.interval = TitanPrefs.news_minutes * 60
          TitanWatch.tick
          # And the other way: Elten's own notifications into Titan's
          # notification centre. This one reads a list Elten's background
          # service already keeps in memory, so it costs nothing here and
          # reaches no network.
          EltenNews.enabled = TitanPrefs.elten_notifications?
          EltenNews.tick
          # **And this is Elten's own thread.** Anything Titan asked that
          # needs the screen - reading it, opening one of Elten's programs
          # - is waiting here, and this is the only place it can run.
          EltenMain.pump
        end

        # Deliberately NO extra entries in Elten's main menu. The manifest
        # already puts this add-on in the programs menu, and everything TCE
        # has is inside its own window - applications and games are the
        # first two tabs there. Four more top-level entries was clutter:
        # Elten's menu belongs to Elten.

        extension.settings do |settings|
          settings.category(_("TCE bridge"))
          settings.boolean(
            "announce_news",
            :label => _("Say when something arrives on Titan-Net"),
            :get => proc { announce_news? },
            :set => proc { |value|
              update_json("settings.json", :default => {}) do |state|
                state["announce_news"] = (value == true)
              end
            }
          )

          # In minutes, because that is what somebody thinks in when they
          # decide how often to be interrupted. Every check is a call into
          # Titan's own interface thread, so the floor is a minute.
          settings.integer(
            "news_minutes",
            :label => _("How often to look, in minutes"),
            :range => (1..60),
            :get => proc { news_minutes },
            :set => proc { |value|
              update_json("settings.json", :default => {}) do |state|
                state["news_minutes"] = value.to_i
              end
            }
          )

          settings.boolean(
            "speak_answers",
            :label => _("Read the AI's answer out loud"),
            :get => proc { speak_answers? },
            :set => proc { |value|
              update_json("settings.json", :default => {}) do |state|
                state["speak_answers"] = (value == true)
              end
            }
          )

          # **The shortcut to TCE's settings belongs here**, in the
          # add-on's own settings, because that is where somebody looks
          # for "the settings of the thing I am configuring" - and TCE's
          # settings ARE this add-on's other half. It opens Titan's own
          # settings window rebuilt in Elten's controls
          # (`titan_settings.rb`), so it is Titan's own save with
          # everything that hangs off it.
          settings.action(
            "tce_settings",
            :label => _("TCE settings...")
          ) { TitanSettings.new(bus).open }

          settings.boolean(
            "share_data",
            :label => _("Share Elten's data with TCE"),
            :get => proc { TitanConsent.granted? },
            :set => proc { |value|
              update_json("settings.json", :default => {}) do |state|
                state[TitanConsent::KEY] = (value == true)
              end
            }
          )

          settings.boolean(
            "elten_notifications",
            :label => _("Show Elten's notifications in Titan too"),
            :get => proc { TitanPrefs.elten_notifications? },
            :set => proc { |value|
              update_json("settings.json", :default => {}) do |state|
                state["elten_notifications"] = (value == true)
              end
            }
          )

          settings.boolean(
            "tce_sounds",
            :label => _("Use TCE's own sounds"),
            :get => proc { TitanPrefs.tce_sounds? },
            :set => proc { |value|
              update_json("settings.json", :default => {}) do |state|
                state["tce_sounds"] = (value == true)
              end
            }
          )

          settings.boolean(
            "confirm_launch",
            :label => _("Ask before starting a TCE application"),
            :get => proc { confirm_launch? },
            :set => proc { |value|
              update_json("settings.json", :default => {}) do |state|
                state["confirm_launch"] = (value == true)
              end
            }
          )
        end

        extension.stop do |_reason|
          TitanWatch.stop
          # Anything still waiting for Elten's thread is never going to get
          # it: better a refusal now than a caller waiting out its whole
          # deadline for a tick that will not come again.
          EltenMain.drop_all
          # A runtime that has been unloaded must not leave a speech output
          # behind pointing into a namespace that is gone: Elten would go
          # on offering the voice and speaking into nothing.
          TitanSpeechOutput.shutdown
          apply_voice_settings
          bus.stop
        end
      end
    end

    # Elten's quick actions are a list the USER puts together, which is
    # exactly where TCE's own lists belong: reachable in one keystroke for
    # somebody who wants them, and absent for somebody who does not. The
    # main menu is Elten's; this is theirs.
    def register_quick_actions
      register_quickaction("tce_applications", _("TCE applications")) do
        TitanConsole.new(bus).open_view("app", _("TCE applications"))
      end
      register_quickaction("tce_games", _("TCE games")) do
        TitanConsole.new(bus).open_view("game", _("TCE games"))
      end
      register_quickaction("tce_titan_net", _("Titan-Net (TCE)")) do
        TitanNetClient.new(bus).main
      end
      # No quick action for the bridge itself: the manifest already puts it
      # in Elten's programs list, and a second way to the same window is one
      # more thing to read past. What is worth a keystroke is a LIST that
      # would otherwise be two screens away.
      true
    rescue Exception => error
      Log.warning("TCE bridge: could not register the quick actions: #{error.message}") if defined?(Log)
      false
    end

    # On by default: somebody who installed a Titan-Net client wants to be
    # told when a message arrives.
    def announce_news?
      setting("announce_news", true) == true
    end

    # Minutes between looks; 3 by default, which is what the watcher used
    # before this was a setting.
    def news_minutes
      value = setting("news_minutes", 3).to_i
      value < 1 ? 3 : [value, 60].min
    end

    def speak_answers?
      setting("speak_answers", true) == true
    end

    def confirm_launch?
      setting("confirm_launch", false) == true
    end

    # The one place the application's own store is read. `TitanPrefs` asks
    # for this and answers with defaults when there is nobody to ask, so a
    # screen never has to know where the settings live.
    def bridge_setting(key, fallback)
      read_json("settings.json", :default => {}).fetch(key, fallback)
    rescue Exception
      fallback
    end

    def setting(key, fallback)
      bridge_setting(key, fallback)
    end

    def apply_voice_settings
      SpeechOutput.apply_current_settings if defined?(SpeechOutput)
    rescue Exception => error
      Log.warning("TCE bridge: could not apply the voice: #{error.message}") if defined?(Log)
    end
  end

  def program_main
    # **Asked once, before anything about Elten leaves Elten**, and asked
    # here because this is the moment the user opened the add-on - the
    # extension tick, which is where the sharing actually happens, is the
    # wrong place for a question: one that appears while somebody is
    # reading their messages is one they answer to get rid of.
    #
    # The answer is not a gate on the rest: "no" leaves Titan's window, its
    # settings, Titan-Net, the shell and the AI exactly as they were,
    # because none of that is Elten's data.
    TitanConsent.ensure_answered
    TitanConsole.new(self.class.bus).open
  end
end
