# encoding: utf-8
#
# **The renderer, RUN.** Every screen of every TCE application, built into
# real Elten controls by the real `TitanApps#show`, with Elten replaced by
# the stub and the loop cut off at `pump`.
#
# A syntax check never reaches a format string and a simulation that reads
# the source never reaches one either: `%r` is Python's "inspect this" and
# Ruby answers it with `ArgumentError: malformed format string` at the
# moment the line runs. It sat in the line `show` writes for EVERY screen,
# so the first screen raised, the exception left the renderer, and the
# console fell back to starting the application in TCE - a renderer that
# had stopped rendering anything at all, reported as the word Ruby used.
#
# The screens are captured from a live Titan by `capture_screens.py` and
# kept in `screens.json`, so this needs neither Titan nor Elten to run.

$LOAD_PATH.unshift(File.expand_path("..", __dir__))
require "json"
require_relative "elten_stub"

# **A control that would not bind says so and carries on**, which is right
# in front of a user and silent in a check: `wire` rescues per control and
# writes one warning. Collected here, a swallowed `NoMethodError` is a
# failure rather than a control that quietly answers nothing.
$warnings = []
module Log
  def self.info(_m); end
  def self.warning(m) $warnings.push(m.to_s); end
end

# `titan_apps.rb` requires the real `titan_ui`, so the loop, the keys and
# the screen class under test are the ones that ship - not a second copy
# here that could quietly drift from them.
require_relative "../titan_apps"

# TCE, answering every call with the screen that is already up: what is
# under test is the renderer, and a press that really moved the screen
# would end the form before the rest of it had been fired.
class StillThere
  Answer = Struct.new(:ok, :data, :error) do
    def ok?() ok == true end
    def [](key) data.is_a?(Hash) ? data[key] : nil end
  end

  attr_reader :asked

  def initialize(screen) @screen = screen; @asked = [] end
  def language() "pl" end
  def available?() true end
  # **A set is ECHOED**, because that is what an application does: it
  # answers with the control holding what was just put in it. A fake that
  # hands the old screen back would make the one thing worth testing here
  # - that typing a letter does not rebuild the form - true for free.
  def call(name, args = {}, title: nil)
    @asked.push([name.to_s, args])
    if name.to_s == "app.set"
      @screen = Marshal.load(Marshal.dump(@screen))
      (@screen["controls"] || []).each do |c|
        next if c["id"] != args["control"]
        c["value"] = args["value"]
        c["checked"] = args["value"] if c["kind"] == "check"
      end
    end
    Answer.new(true, {"screen" => @screen}, nil)
  end
end

# The loop is Elten's; what is under test is everything that builds one.
class BuiltOnce < TitanApps
  def pump(form, _screen, bound)
    @built = [form, bound]
    @moved = true
    @running = false
  end

  def built
    @built
  end

end

path = File.join(__dir__, "screens.json")
if !File.exist?(path)
  puts "no screens.json - run capture_screens.py against a live TCE first"
  exit 1
end

screens = JSON.parse(File.read(path))
problems = []
kinds = {}
total = 0

screens.each do |entry|
  app = entry["app"].to_s
  screen = entry["screen"]
  tce = StillThere.new(screen)
  renderer = BuiltOnce.new(nil, tce)
  renderer.instance_variable_set(:@screen, screen)
  renderer.instance_variable_set(:@running, true)
  total += 1
  begin
    renderer.send(:show, screen)
  rescue Exception => e
    problems.push("%s / %s: %s: %s" %
                  [app, screen["title"].to_s, e.class, e.message])
    next
  end
  form, bound = renderer.built
  if form.nil?
    problems.push("%s / %s: nothing was built" % [app, screen["title"].to_s])
    next
  end
  # **Every binding, run.** Building a control proves it exists; firing
  # what it fires is what proves the block behind it does not raise -
  # the inner list a TableBox forwards nothing from, a file tree asked
  # where its cursor is, a menu option pressed.
  bound.each do |described, widget|
    [:press, :change, :move, :select].each do |event|
      begin
        widget.trigger(event)
        widget.sel.trigger(event) if widget.respond_to?(:sel) && widget.sel
      rescue Exception => e
        problems.push("%s / %s: %s %s raised %s: %s" %
                      [app, screen["title"].to_s, described["kind"],
                       event, e.class, e.message])
      end
    end
    # **Enter has to reach TCE.** A row chosen, a button pressed: if
    # nothing asked TCE to press that control, the key is one the user
    # would report as doing nothing - which is exactly how a TableBox
    # forwarding only `:move` was found.
    next if !%w[button list tree table].include?(described["kind"].to_s)
    pressed = tce.asked.any? do |name, args|
      name == "app.press" && args["control"] == described["id"]
    end
    if !pressed
      problems.push("%s / %s: choosing the %s %p reaches nothing" %
                    [app, screen["title"].to_s, described["kind"],
                     described["label"].to_s])
    end
  end
  # **Typing a letter is not the screen changing.** The application
  # answers a set with the control holding what was set, so counted as a
  # change the form was rebuilt on every keystroke - and a rebuilt
  # EditBox starts with its caret at the beginning, which is how a typed
  # word came out backwards.
  bound.each do |described, widget|
    next if !%w[text multiline check].include?(described["kind"].to_s)
    renderer.instance_variable_set(:@moved, false)
    if widget.respond_to?(:set_text)
      widget.set_text("#{widget.text}x")
    elsif widget.respond_to?(:checked=)
      widget.checked = !widget.checked
    end
    widget.trigger(:change)
    if renderer.instance_variable_get(:@moved)
      problems.push("%s / %s: typing into the %s %p rebuilds the screen" %
                    [app, screen["title"].to_s, described["kind"],
                     described["label"].to_s])
    end
  end

  (form.menus || []).each do |_label, entries|
    walk = lambda do |list|
      list.each do |text, thing|
        next walk.call(thing) if thing.is_a?(Array)
        next if !thing.respond_to?(:call)
        begin
          thing.call
        rescue Exception => e
          problems.push("%s / %s: menu %s raised %s: %s" %
                        [app, screen["title"].to_s, text, e.class, e.message])
        end
      end
    end
    walk.call(entries)
  end
  described = (screen["controls"] || [])
  described.each { |c| kinds[c["kind"].to_s] = true }
  # Every control the application described became a widget, and the
  # menu bar became a menu: a control silently missing is the worst
  # answer there is for somebody who cannot see the screen.
  if bound.size != described.size
    problems.push("%s / %s: %d controls described, %d built" %
                  [app, screen["title"].to_s, described.size, bound.size])
  end
  menus = screen["menus"] || []
  if !menus.empty? && (form.menus || []).empty?
    problems.push("%s / %s: %d menu(s) described, none bound" %
                  [app, screen["title"].to_s, menus.size])
  end
end

# A note the renderer wrote that raised would be a note lost, so the log
# is proof the diagnostics themselves survive being written.
if TitanApps.log.empty?
  problems.push("the renderer wrote nothing down at all")
end
$warnings.uniq.each { |line| problems.push("a control would not bind: #{line}") }


puts "%d screen(s) built, kinds: %s" % [total, kinds.keys.sort.join(", ")]
problems.each { |line| puts "  ! #{line}" }
puts(problems.empty? ? "every screen builds" : "#{problems.size} PROBLEM(S)")
exit(problems.empty? ? 0 : 1)
