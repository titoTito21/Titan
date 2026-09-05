# What is on Elten's screen, and opening one of its programs.
#
# Elten is self-voicing: there is one screen, it is not drawn, and what is
# "on" it is what it last SAID plus the controls the current scene is
# holding. Both are Elten's own thread's, so everything here goes through
# `EltenMain` - and everything here is a read except the last one, which is
# `insert_scene`, Elten's own way of opening a screen.
#
# This is the third direction through the wall. The first was Titan inside
# Elten, the second was Elten's notifications inside Titan, and this is
# Titan's AI being able to answer "what am I looking at in Elten?" and
# "open the file manager there" - which until now it could not, because
# nothing outside Elten's own thread could see or touch that screen.

class EltenScreen
  class << self
    # What Titan may ask. Every one of them checks the consent for itself:
    # it can be taken back at any moment, and a screen is as much Elten's
    # data as a notification is.
    def handlers
      {
        "screen" => proc { |_args| read_screen },
        "programs" => proc { |_args| list_programs },
        "run_program" => proc { |args| run_program(args["name"]) },
      }
    end

    def refusal
      EltenNews.refusal
    end

    # ----------------------------------------------------------- reading
    def read_screen
      return refusal if !TitanConsent.granted?
      ok, value = EltenMain.call { screen_now }
      ok ? value : {"error" => value.to_s}
    end

    # Runs ON Elten's thread.
    def screen_now
      {"said" => last_spoken, "scene" => scene_name,
       "controls" => scene_controls}
    end

    # **What Elten last said IS its screen.** For a program that is not
    # drawn, the sentence the user just heard is the closest thing there
    # is to "what is showing" - which is why Elten keeps it for its own
    # "say that again" shortcut, and why that is the global read here.
    def last_spoken
      value = ($speech_lasttext rescue nil)
      value.to_s
    end

    def scene_name
      scene = ($scene rescue nil)
      return "" if scene == nil
      scene.class.name.to_s.sub(/\AScene_/, "")
    rescue Exception
      ""
    end

    # The controls the current scene is holding, read off the scene itself.
    # Elten's scenes keep them in instance variables with no interface in
    # common, so what is looked for is the SHAPE - anything that answers
    # like one of Elten's controls - rather than a list of variable names
    # that would go stale at the next Elten.
    def scene_controls
      scene = ($scene rescue nil)
      return [] if scene == nil
      found = []
      scene.instance_variables.each do |variable|
        value = begin
          scene.instance_variable_get(variable)
        rescue Exception
          nil
        end
        described = describe(value)
        next if described == nil
        described["field"] = variable.to_s.sub(/\A@/, "")
        found.push(described)
        break if found.size >= 12
      end
      found
    rescue Exception
      []
    end

    # One control, as words. A Form is opened out into its own fields with
    # the focused one marked, because a form IS its fields - reporting it
    # as one thing called "form" says nothing about what the user is on.
    def describe(value, depth = 0)
      return nil if value == nil || depth > 1
      if value.respond_to?(:fields) && value.respond_to?(:index)
        fields = (value.fields rescue nil)
        return nil if !fields.is_a?(Array)
        at = value.index.to_i rescue 0
        return {"kind" => "form",
                "controls" => fields.each_with_index.map do |field, position|
                  entry = describe(field, depth + 1) || {"kind" => "control"}
                  entry["focused"] = (position == at)
                  entry
                end}
      end
      if value.respond_to?(:options) && value.respond_to?(:index)
        options = (value.options rescue nil)
        return nil if !options.is_a?(Array)
        at = value.index.to_i rescue 0
        return {"kind" => "list", "header" => header_of(value),
                "count" => options.size,
                "index" => at,
                "current" => options[at].to_s,
                "options" => options.first(30).map(&:to_s)}
      end
      if value.respond_to?(:text) && value.respond_to?(:set_text)
        return {"kind" => "field", "header" => header_of(value),
                "text" => value.text.to_s}
      end
      if value.respond_to?(:label) && value.respond_to?(:press)
        return {"kind" => "button", "label" => value.label.to_s}
      end
      if value.respond_to?(:checked)
        return {"kind" => "checkbox", "header" => header_of(value),
                "checked" => value.checked == true}
      end
      nil
    rescue Exception
      nil
    end

    def header_of(control)
      return "" if !control.respond_to?(:header)
      control.header.to_s
    rescue Exception
      ""
    end

    # ---------------------------------------------------------- programs
    # Elten's own programs, as its main menu lists them - the classes
    # `Programs.list` holds, minus the ones that ask not to be shown.
    def list_programs
      return refusal if !TitanConsent.granted?
      ok, value = EltenMain.call { programs_now }
      ok ? value : {"error" => value.to_s}
    end

    def programs_now
      return {"programs" => []} if !defined?(Programs)
      rows = []
      (Programs.list || []).each do |program|
        next if program.respond_to?(:hidden?) && program.hidden? == true
        rows.push({"name" => program_label(program),
                   "class" => program.to_s})
      end
      {"programs" => rows}
    rescue Exception => e
      {"programs" => [], "error" => "#{e.class}: #{e.message}"}
    end

    def program_label(program)
      label = (program.menu_label rescue nil)
      label = (program.name rescue nil) if label.to_s == ""
      label.to_s == "" ? program.to_s : label.to_s
    end

    # **Opening one is `insert_scene`, which is what Elten's own menu
    # does** - a program IS a scene there - and it runs Elten's pump, so
    # it can only happen on Elten's thread.
    def run_program(name)
      return refusal if !TitanConsent.granted?
      wanted = name.to_s.strip
      return {"error" => "say which program"} if wanted == ""
      ok, value = EltenMain.call { open_now(wanted) }
      ok ? value : {"error" => value.to_s}
    end

    def open_now(wanted)
      return {"error" => "this Elten has no programs"} if !defined?(Programs)
      lowered = wanted.downcase
      program = (Programs.list || []).find do |candidate|
        program_label(candidate).downcase == lowered ||
          candidate.to_s.downcase == lowered
      end
      program ||= (Programs.list || []).find do |candidate|
        program_label(candidate).downcase.include?(lowered)
      end
      return {"error" => "Elten has no program called '#{wanted}'"} if program == nil
      insert_scene(program.new)
      {"opened" => program_label(program)}
    rescue Exception => e
      {"error" => "#{e.class}: #{e.message}"}
    end
  end
end
