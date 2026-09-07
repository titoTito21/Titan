# encoding: utf-8
#
# Titan, as part of the Elten API an application is written against.
#
# Everything else in this add-on is a SCREEN: somebody opens the TCE
# bridge and works Titan through it. This is the other half - Titan as
# something an `.eltenapp` can CALL, the way it calls anything else in
# `EltenAPI`. An application that wants to say a line in the user's own
# Titan voice, read what is on their desktop, open one of their programs
# or run three Titan actions in order does not want a window of this
# add-on: it wants a method.
#
#   EltenAPI::Titan.available?
#   EltenAPI::Titan.action("tnotes", "create_note", "title" => "Ideas")
#   EltenAPI::Titan.script('say "hello"' + "\n" + 'return now("%H:%M")')
#
# **Titan Script is the interesting half**, and it is why this exists at
# all rather than being one more list of methods. Elten applications are
# Ruby and Titan actions are a flat list of calls; the thing that is
# neither - and that Titan already has, checked, translated and
# documented - is a small language whose statements ARE those actions,
# with variables, conditions, forms, sounds and a voice. So an Elten
# application can compose one, have Titan check it before it runs, and be
# handed back what it answered. `macros.run_script` is the Titan action
# that makes that possible; nothing here parses or interprets anything.
#
# Three rules, and each of them is one this repository has already paid
# for once:
#
# - **Nothing here raises.** Every call answers a `Result`, because an
#   application reaching for Titan on a machine where Titan is not
#   running is the ordinary case, not the exceptional one - and a
#   `NoMethodError` inside somebody else's `rescue Exception` becomes a
#   feature quietly not working rather than an error anybody sees.
# - **Nothing here waits on Elten's own thread.** Every call goes through
#   `TitanUI.ask`, which runs it on a worker while Elten carries on
#   pumping - a self-voicing interface that stops answering the keyboard
#   because a pipe is slow is an interface that has hung.
# - **Reading and driving are different permissions**, and Titan is the
#   one that decides. An application does not get its own answer to that
#   question: a call Titan refuses because its user has not allowed this
#   bridge to control them comes back as `needs_consent?`, which is a
#   different thing from a call that failed and must not be retried as
#   though it were.

module EltenAPI
  module Titan
    # What a call answered. `ok?` is whether there is anything in `value`;
    # `needs_consent?` is Titan's own user not having said yes yet, which
    # is neither success nor a fault of the application's.
    Result = Struct.new(:ok, :value, :error, :consent) do
      def ok?
        ok == true
      end

      def needs_consent?
        consent.to_s != ""
      end

      def to_s
        ok? ? value.to_s : error.to_s
      end
    end

    class << self
      # The bus belongs to the add-on, not to this module: an application
      # must never make a second connection on the same pipe.
      def bus
        ProgramTCEBridge.bus
      end

      def api
        @api ||= TitanAPI.new(bus)
      end

      # ------------------------------------------------------------ state
      # Is Titan there at all? Cheap and answered from the connection, so
      # an application may ask it on a frame.
      def available?
        bus.connected?
      rescue Exception
        false
      end

      # May this bridge CHANGE Titan, or only read it? Asked of Titan
      # rather than remembered here: the user can take the answer back at
      # any time, in Titan's own settings, and an application holding a
      # stale yes would offer a button that no longer works.
      def may_control?
        answer = call("capabilities")
        return false if !answer.ok?
        clients = ((answer.value["consent"] || {})["clients"] || [])
        mine = clients.find { |one| one["client"].to_s.include?("elten") }
        mine != nil && mine["allowed"] == true
      rescue Exception
        false
      end

      # ---------------------------------------------------------- actions
      # Any Titan action, by the add-on and the name Titan itself lists.
      # This is the whole of what Titan can do - its own subsystems and
      # every add-on installed in it - so it is deliberately one method
      # rather than a method per thing.
      def action(addon, name, args = {})
        answer = TitanUI.perform(bus, addon.to_s, name.to_s, args || {},
                                 :title => nil)
        return Result.new(true, answer.text.to_s, nil, nil) if answer.ok?
        Result.new(false, nil, answer.text.to_s, answer.consent)
      rescue Exception => e
        Result.new(false, nil, "#{e.class}: #{e.message}", nil)
      end

      # What can be called: every add-on, or one add-on's actions with
      # their parameters. An application that asks rather than assuming
      # goes on working against a Titan that has more in it than this one.
      def addons
        answer = call("addons.list")
        answer.ok? ? (answer.value["addons"] || []) : []
      end

      def actions(addon)
        answer = call("addons.actions", {"addon" => addon.to_s})
        answer.ok? ? (answer.value["actions"] || []) : []
      end

      # The typed doorway - JSON in, JSON out, one shape for every answer.
      # What a program rebuilding an interface should use; `action` is the
      # prose layer, which is written for a model and for macros.
      def call(name, args = {})
        answer = api.call(name.to_s, args || {})
        return Result.new(true, answer.data, nil, nil) if answer.ok?
        Result.new(false, nil, answer.error.to_s, answer.consent)
      rescue Exception => e
        Result.new(false, nil, "#{e.class}: #{e.message}", nil)
      end

      # ----------------------------------------------------- Titan Script
      # Run a script this application composed. Checked by Titan first, so
      # a script naming something that is not there is refused whole
      # rather than stopping halfway with its first half already done -
      # and what comes back is what the script's own `return` handed over.
      def script(source, title: nil, check: true)
        action("macros", "run_script",
               {"script" => source.to_s,
                "title" => (title || app_title).to_s,
                "check" => check == true})
      end

      # Read it without running it: what would stop it, and what would run
      # and looks wrong. For an application that lets somebody WRITE one.
      def check(source)
        action("macros", "check_macro", {"script" => source.to_s})
      end

      # The language itself, in the user's own language, and what a script
      # may call - both read from Titan's macro manager, so a statement
      # added to the language appears here without this file changing.
      def language
        action("macros", "macro_language")
      end

      def vocabulary
        action("macros", "macro_actions")
      end

      # The user's own macros, and running one of them by name.
      def macros
        answer = call("macros.list")
        answer.ok? ? (answer.value["macros"] || []) : []
      end

      def run_macro(name)
        action("macros", "run_macro", {"name" => name.to_s})
      end

      # Save one INTO the user's macro manager - listed, editable, with a
      # shortcut - rather than leaving a script file somewhere on the
      # disk, which is the rule Titan's own creation kit follows.
      def save_macro(name, source, hotkey: nil)
        args = {"name" => name.to_s, "kind" => "tcs", "script" => source.to_s}
        args["hotkey"] = hotkey.to_s if hotkey.to_s != ""
        action("macros", "create_macro", args)
      end

      # ----------------------------------------------- TCE's applications
      # **A TCE application, opened as an Elten screen, from one line.**
      # This add-on already renders them - a TCE application runs with a
      # `wx` that describes its interface instead of painting it, and
      # `TitanApps` builds real Elten controls out of that description -
      # but only as a screen somebody navigates to. An application that
      # wants to hand its user Titan's text editor, file manager or notes
      # should not have to send them through this add-on's own menus to
      # get there.
      #
      # It BLOCKS while the user works it, exactly as `Form#wait` does,
      # and comes back when they leave: an application calling this is
      # opening a screen, not starting something in the background.
      def application(name)
        return Result.new(false, nil, unavailable, nil) if !TitanUI.require_tce(bus)
        TitanApps.new(bus, TitanAPI.new(bus)).run(name.to_s)
        Result.new(true, name.to_s, nil, nil)
      rescue Exception => e
        Result.new(false, nil, "#{e.class}: #{e.message}", nil)
      end

      # Which of them there are, so an application can offer a list rather
      # than a name it hopes exists. Each row carries the `name` to hand
      # back - **in the user's own language**, because that is the name
      # TCE matches on and the name they know it by.
      def applications
        answer = call("app.list", {"language" => api.language})
        answer.ok? && answer.value.is_a?(Array) ? answer.value : []
      end

      # ------------------------------------------------------- the desktop
      # Titan's own voice, on Titan's machine. Not Elten's speech: an
      # application using this is deliberately saying something over
      # there - a notification on the desktop, a line where the user is
      # working - and Elten's own `speak` is what says something here.
      def speak(text, position: 0.0, rate: nil, pitch: nil)
        args = {"text" => text.to_s, "position" => position}
        args["rate"] = rate if rate != nil
        args["pitch"] = pitch if pitch != nil
        action("titan", "speak", args)
      end

      # Into Titan's notification centre, its Titan buffer and its
      # notification sound - where Titan's own news goes.
      def notify(text, title: nil)
        call("notifications.add",
             {"content" => text.to_s, "app" => (title || app_title).to_s})
      end

      private

      def unavailable
        _("This needs TCE. Start Titan, then try again.")
      end

      # What Titan is told this came from. The application's own name
      # where it has one, so a notification or a script's window says
      # which Elten application put it there rather than saying "Elten".
      def app_title
        name = Program.manifest["name"].to_s rescue ""
        name == "" ? "Elten" : name
      end
    end
  end
end

# **There is deliberately no bare `Titan` alias, and that is not a matter
# of taste.** Elten loads every application into a namespace of its own -
# a `Ruby::Box`, or a `Module.new` under `EltenPrograms` - so a top-level
# constant assigned here is set on THIS add-on's namespace and on nothing
# else: another application would never see it, and the one place it did
# work is the one place nobody needed it. `EltenAPI::Titan` is reachable
# because `EltenAPI` is the same module OBJECT in every namespace
# (`BoxBackend#expose_host_constants` copies the reference, and reopening
# `module EltenAPI` finds that object rather than making a second one), so
# what is added to it here is what every application sees. That is also
# how `EltenAPI::LiveSessions` and `EltenAPI::Tasks` are reached, and an
# application naming this one the same way is naming it the way it names
# everything else.
