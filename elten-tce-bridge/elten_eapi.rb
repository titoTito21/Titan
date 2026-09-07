# encoding: utf-8
#
# Elten's own API, callable from Titan.
#
# `eapi_titan.rb` is one direction: an Elten application reaching Titan.
# This is the other, and it is the one Titan's AI and Titan's actions have
# been missing. Titan already has `elten_tools.py`, but that talks to the
# **EltenLink server** with saved credentials - it can answer "what is in
# my inbox" and cannot answer anything about the Elten the user is sitting
# in front of. The bridge is inside that client, so it can.
#
#   actions.run('elten_client', 'eapi', call='account')
#   actions.run('elten_client', 'eapi', call='messages', args='{"limit": 5}')
#
# **The table IS the security boundary**, and that is the rule this
# repository already applies to the same problem in the mirror direction:
# `data/components/elten_bridge/eltenkit/eltenlink.py` reaches EltenLink
# through an explicit list of calls and never `getattr` on a name the
# caller supplied. An `.eltenapp` cannot post to somebody's forum because
# it was opened; Titan's AI cannot either. There is no way here to name a
# Ruby method, a constant, a file or an object - a call exists in `CALLS`
# or it does not exist at all.
#
# **Three gates, and they are three different questions.**
#
# - The **consent** (`TitanConsent`) is Elten's data leaving Elten. Every
#   call checks it, because it can be taken back at any moment.
# - **Writing** is not reading. A call that posts, sends, marks or deletes
#   acts in the user's name on a network other people are on, and somebody
#   who agreed to let Titan READ their Elten has not agreed to that. It is
#   its own switch (`TitanPrefs.allow_writes?`), off by default - the same
#   split, for the same reason, as `press_key`.
# - **Elten's own thread** is where all of it runs (`EltenMain.call`),
#   because that is where Elten's state lives. Nothing here touches it
#   from the bus worker.

class EltenEapi
  #: How many rows one answer may carry. A caller that wants more asks
  #: again; a whole forum in one reply is a wall nobody reads and a
  #: message big enough to matter on the pipe.
  MAX_ROWS = 50

  #: What may be called, and nothing else. `:write` marks the ones that
  #: act in the user's name.
  #
  #: Deliberately small and deliberately about the CLIENT: anything the
  #: EltenLink server can answer, Titan already asks the server for
  #: through `src/ai/tools/elten_tools.py`, and a second implementation
  #: is a second thing to be wrong. What is here is what only the running
  #: client knows.
  CALLS = {
    "account" => {:write => false},
    "session" => {:write => false},
    "settings" => {:write => false},
    "programs" => {:write => false},
    "extensions" => {:write => false},
    "sounds" => {:write => false},
    "speak" => {:write => true},
  }.freeze

  class << self
    def handlers
      {
        "eapi" => proc { |args| call(args) },
        "eapi_calls" => proc { |_args| catalogue },
      }
    end

    # **What can be called, answered rather than guessed at.** A caller
    # that has to find out by failing is a caller that guesses, and every
    # guess this bridge has cost was of that shape.
    def catalogue
      return refusal if !TitanConsent.full_granted?
      {"calls" => CALLS.map { |name, shape|
        {"name" => name, "writes" => shape[:write] == true,
         "allowed" => shape[:write] != true || writes_allowed?}
      }, "writes_allowed" => writes_allowed?}
    end

    def call(args)
      # **The wider consent, and it says WHICH one is missing.** Answering
      # "Elten has not given permission" to somebody who granted the first
      # question sends them to check a setting that is already on - the
      # exact fault this add-on already fixed once for a timeout.
      return refusal if !TitanConsent.granted?
      return {"error" => refusal_for_everything} if !TitanConsent.full_granted?
      name = args["call"].to_s.strip
      shape = CALLS[name]
      # Named, never resolved. A name that is not in the table is not a
      # method somebody might reach by spelling it differently.
      return {"error" => "Elten's API has no call '#{name}' here",
              "calls" => CALLS.keys} if shape == nil
      return {"error" => refusal_for_writes} if shape[:write] && !writes_allowed?
      ok, value = EltenMain.call { perform(name, arguments(args)) }
      return {"error" => value.to_s} if !ok
      value
    rescue Exception => e
      {"error" => "#{e.class}: #{e.message}"}
    end

    # Arguments arrive as JSON over the bus, or already as a hash when a
    # caller had one. Anything else is no arguments rather than an error:
    # a call that takes none must not fail because somebody sent "".
    def arguments(args)
      raw = args["args"]
      return raw if raw.is_a?(Hash)
      return {} if !raw.is_a?(String) || raw.strip == ""
      parsed = JSON.parse(raw) rescue nil
      parsed.is_a?(Hash) ? parsed : {}
    end

    # ------------------------------------------------------- on Elten's thread
    def perform(name, args)
      case name
      when "account"    then account
      when "session"    then session
      when "settings"   then settings(args)
      when "programs"   then programs
      when "extensions" then extensions
      when "sounds"     then sounds
      when "speak"      then say_in_elten(args)
      else {"error" => "not implemented"}
      end
    end

    # Who is signed in, from the client rather than from the server - so
    # it costs nothing and is true even with the network gone.
    def account
      {"name" => value_of { Session.name },
       "id" => value_of { Session.userid },
       "logged_in" => value_of { Session.logged_in? }}
    end

    # What the client itself is: its version, its language, whether it is
    # in the foreground. The questions Titan's AI cannot answer any other
    # way.
    def session
      {"version" => value_of { $version },
       "language" => value_of { Configuration.language },
       "scene" => value_of { $scene.class.to_s },
       "active" => value_of { EltenWindow.active_or_child? },
       "minimized" => value_of { EltenWindow.minimized? }}
    end

    # Elten's own configuration, by NAME and read-only. Not the whole of
    # it: a configuration dump is somebody's whole client, and what a
    # caller actually wants is one answer.
    def settings(args)
      wanted = args["name"].to_s.strip
      return {"error" => "say which setting"} if wanted == ""
      return {"error" => "that is not a readable setting name"} if
        wanted !~ /\A[a-z][a-z0-9_]*\z/
      {"name" => wanted,
       "value" => value_of { Configuration.send(wanted) }}
    end

    # What is installed in Elten, which is the list a caller needs before
    # it can name one to `run_program`.
    def programs
      rows = value_of { Programs.installed.map { |one| program_row(one) } }
      {"programs" => Array(rows).first(MAX_ROWS)}
    rescue Exception => e
      {"programs" => [], "error" => "#{e.class}: #{e.message}"}
    end

    def program_row(one)
      {"id" => (one.manifest.id.to_s rescue ""),
       "name" => (one.manifest.name.to_s rescue ""),
       "version" => (one.manifest.version.to_s rescue "")}
    end

    # Which extensions are live - this add-on's own among them, so
    # "is the bridge actually running in there" has an answer.
    def extensions
      rows = value_of {
        Programs::Extensions.all.map { |one| one.name.to_s rescue "" }
      }
      {"extensions" => Array(rows).reject(&:empty?).first(MAX_ROWS)}
    rescue Exception => e
      {"extensions" => [], "error" => "#{e.class}: #{e.message}"}
    end

    def sounds
      {"theme" => value_of { Configuration.soundtheme }}
    end

    # **The one write, and it is the mildest there is.** Speaking is the
    # whole of Elten's interface, so saying something in it is how Titan
    # tells the person sitting there anything at all - and it publishes
    # nothing, reaches no network and cannot be read by anybody else.
    # Everything that WOULD publish is deliberately absent from `CALLS`
    # rather than present and refused: an action Titan offers and cannot
    # perform is worse than one it does not offer.
    # **Not called `speak`.** A method of that name here would shadow
    # Elten's own top-level helper for everything inside this class, and
    # the call would recurse into itself with a String where a Hash was
    # expected. Elten's signature is
    # `speak(text, stop: true, use_dictionary: true, ...)`, read from
    # `src/eapi/speech.rb` rather than guessed - `stop:` is the interrupt,
    # so there is nothing to stop separately.
    def say_in_elten(args)
      text = args["text"].to_s.strip
      return {"error" => "say what to speak"} if text == ""
      return {"error" => "that is more than 500 characters"} if text.size > 500
      speak(text, :stop => args["interrupt"] == true)
      {"said" => text}
    rescue Exception => e
      {"error" => "#{e.class}: #{e.message}"}
    end

    # **A name Elten has not got answers nothing.** Every one of these
    # reads a global or a class method that a future Elten may rename,
    # and a `NoMethodError` here would come back as an error about the
    # whole call rather than about the one field that was missing.
    def value_of
      yield
    rescue Exception
      nil
    end

    def writes_allowed?
      TitanConsent.full_granted? && TitanPrefs.allow_writes?
    end

    def refusal
      EltenNews.refusal
    end

    def refusal_for_everything
      "Titan may read what this bridge needs, but has not been allowed to " \
      "use all of Elten's data. The TCE bridge asks that separately - the " \
      "answer is in its own settings."
    end

    def refusal_for_writes
      "That call would act in your name in Elten. Switch on 'Let TCE act " \
      "in Elten' in the TCE bridge's settings first."
    end
  end
end
