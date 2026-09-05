# Asking the REAL Elten what its API is.
#
# The other half of this repository (`data/components/elten_bridge/`) is a
# port: Elten's API, re-implemented in Ruby on top of Titan, so that an
# `.eltenapp` runs inside Titan. Everything that has ever gone wrong with it
# has gone wrong the same way - a signature guessed from call sites rather
# than read from Elten. `text=` where Elten has `set_text`. `alert` modelled
# as a dialog when Elten's is speech. `Tasks.run` yielding one value where
# Elten yields two. And, the one that started this file, a `player` helper
# that simply was not there, so playing a YouTube video raised
# `NoMethodError` inside an application that only rescues `Youtube::Error`.
#
# The bridge is INSIDE the real Elten. It can be asked. That turns "guess,
# ship, and find out from a user" into "ask the client that is running", and
# it is the same question a checkout answers except that this one is the
# Elten the user actually has - the right authority when the two differ.
#
# Everything here is introspection: `method_defined?`, `parameters`,
# `const_defined?`. No screen, no thread of Elten's, nothing that runs any
# of the application's code.

class EltenApi
  #: How many methods are described in one answer. A class with two hundred
  #: methods is a wall; a caller that wants one asks for it by name.
  MAX_METHODS = 200

  #: How many names one batch may ask about. A whole port is a few hundred;
  #: more than this is somebody sweeping Elten rather than checking a port,
  #: and it runs on the bus worker.
  MAX_NAMES = 400

  class << self
    def handlers
      { "api" => proc { |args| answer(args) } }
    end

    # One name, or MANY. A checker comparing a whole port against the real
    # Elten asks about hundreds of names, and one round trip each - through
    # a pipe, through a worker, through Elten's own tick - is a checker
    # nobody runs. `names` takes a list or a comma-separated string.
    def answer(args)
      names = args["names"]
      return describe(args["name"], args["kind"]) if names.nil?
      wanted = (names.is_a?(String) ? names.split(",") : Array(names))
               .map { |entry| entry.to_s.strip }.reject(&:empty?)
      return EltenNews.refusal if !TitanConsent.granted?
      return {"error" => "that is more than #{MAX_NAMES} names"} if
        wanted.size > MAX_NAMES
      {"api" => wanted.each_with_object({}) do |name, out|
        out[name] = describe(name, nil)
      end}
    end

    # `name` is a bare function ("player"), a constant ("ListBox"), or a
    # method on one ("ListBox#set_text"). `kind` narrows it when a name is
    # both, and is otherwise worked out.
    def describe(name, kind = nil)
      return EltenNews.refusal if !TitanConsent.granted?
      wanted = name.to_s.strip
      return {"error" => "say which name"} if wanted == ""
      if wanted.include?("#") || wanted.include?(".")
        holder, _sep, method = wanted.rpartition(/[#.]/)
        return method_on(holder, method, wanted.include?("."))
      end
      return constant(wanted) if kind.to_s == "constant" ||
                                 (kind.to_s == "" && looks_like_constant?(wanted))
      function(wanted)
    end

    def looks_like_constant?(name)
      name[0..0] == name[0..0].upcase && name[0..0] =~ /[A-Z]/
    end

    # A bare function: the ones an application calls with no receiver.
    def function(name)
      symbol = name.to_sym
      defined = Kernel.method_defined?(symbol) ||
                Kernel.private_method_defined?(symbol) ||
                Object.respond_to?(symbol, true)
      return {"name" => name, "kind" => "function", "defined" => false} if !defined
      method = begin
        Kernel.instance_method(symbol)
      rescue Exception
        begin
          Object.method(symbol).unbind
        rescue Exception
          nil
        end
      end
      {"name" => name, "kind" => "function", "defined" => true,
       "parameters" => parameters_of(method),
       "source" => source_of(method)}
    rescue Exception => e
      {"name" => name, "error" => "#{e.class}: #{e.message}"}
    end

    # A class or a module: what it is, and what it answers to.
    def constant(name)
      return {"name" => name, "kind" => "constant", "defined" => false} if
        !Object.const_defined?(name)
      value = Object.const_get(name)
      out = {"name" => name, "kind" => value.is_a?(Class) ? "class" : "module",
             "defined" => true}
      out["parent"] = value.superclass.to_s if value.is_a?(Class) && value.superclass
      if value.is_a?(Module)
        out["methods"] = (value.instance_methods(true) - Object.instance_methods)
                         .map(&:to_s).sort.first(MAX_METHODS)
        out["class_methods"] = (value.methods(true) - Object.methods)
                               .map(&:to_s).sort.first(MAX_METHODS)
      end
      out
    rescue Exception => e
      {"name" => name, "error" => "#{e.class}: #{e.message}"}
    end

    # One method on one class - the question that is actually asked when a
    # port is being written: "what does Elten's ListBox#focus take?"
    def method_on(holder, name, class_method)
      return {"name" => "#{holder}##{name}", "defined" => false,
              "error" => "there is no #{holder}"} if !Object.const_defined?(holder)
      value = Object.const_get(holder)
      symbol = name.to_sym
      method = if class_method
                 value.respond_to?(symbol, true) ? value.method(symbol).unbind : nil
               else
                 value.instance_method(symbol) rescue nil
               end
      return {"name" => "#{holder}##{name}", "kind" => "method",
              "defined" => false} if method == nil
      {"name" => "#{holder}#{class_method ? '.' : '#'}#{name}",
       "kind" => "method", "defined" => true,
       "owner" => method.owner.to_s,
       "parameters" => parameters_of(method),
       "source" => source_of(method)}
    rescue Exception => e
      {"name" => "#{holder}##{name}", "error" => "#{e.class}: #{e.message}"}
    end

    # [["req", "text"], ["key", "label"], ...] - Ruby's own shape, which is
    # what says whether an argument is positional, optional or a keyword.
    # That distinction is the whole of "the signature", and getting it wrong
    # is an ArgumentError inside somebody else's program.
    def parameters_of(method)
      return [] if method == nil
      method.parameters.map { |kind, argument| [kind.to_s, argument.to_s] }
    rescue Exception
      []
    end

    # Where it is written, which is what to READ next. A method defined in
    # C, or by something that hides it, answers nothing rather than lying.
    def source_of(method)
      return "" if method == nil || !method.respond_to?(:source_location)
      place = method.source_location
      place == nil ? "" : "#{place[0]}:#{place[1]}"
    rescue Exception
      ""
    end
  end
end
