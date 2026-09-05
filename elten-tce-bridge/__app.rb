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
require_relative "titan_speech_output"
require_relative "titan_actions"
require_relative "titan_settings"
require_relative "titan_net"
require_relative "titan_im"
require_relative "titan_tools_ui"
require_relative "titan_widgets"
require_relative "titan_watch"
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
      bus.start
      TitanSpeechOutput.start(bus)
      # Elten applies the configured voice while it is loading, which is
      # BEFORE applications are loaded - so a user whose chosen voice is
      # this one would have been left on whatever Elten fell back to.
      # Asking for it again once the output exists is what makes the choice
      # survive a restart.
      apply_voice_settings
      TitanWatch.start(bus)
      register_quick_actions
      extension("tce_bridge") do |extension|
        # An extension stays loaded while Elten runs, with or without a
        # window of ours open, so this is what notices that something has
        # arrived on Titan-Net. The tick is Elten's own main pump: it posts
        # a question to the bus and says whatever the last answer brought,
        # and it never waits for either.
        extension.tick(:interval => 5) do
          TitanWatch.enabled = announce_news?
          TitanWatch.tick
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
        end

        extension.stop do |_reason|
          TitanWatch.stop
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
      read_json("settings.json", :default => {}).fetch("announce_news", true) == true
    rescue Exception
      true
    end

    def apply_voice_settings
      SpeechOutput.apply_current_settings if defined?(SpeechOutput)
    rescue Exception => error
      Log.warning("TCE bridge: could not apply the voice: #{error.message}") if defined?(Log)
    end
  end

  def program_main
    TitanConsole.new(self.class.bus).open
  end
end
