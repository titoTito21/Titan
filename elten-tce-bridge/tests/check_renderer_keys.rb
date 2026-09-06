# encoding: utf-8
#
# **The keys, on every real screen.** The loop is where every renderer bug
# the user reported actually lived - Enter opening nothing in the file
# manager, Backspace doing nothing, Ctrl+S in the editor saving nothing -
# and none of it can be seen by reading the source or by building a form.
#
# So the real `pump` is run, with Elten replaced by the stub and its
# keyboard scripted, and what is asserted is what reached TCE: choosing a
# row must ask TCE to press that row, Backspace must be forwarded from a
# list and kept by a field being typed into, and a menu shortcut must
# press the menu item that declares it.
#
# The screens come from `screens.json` (written by `capture_screens.py`),
# so this needs neither Titan nor Elten.

$LOAD_PATH.unshift(File.expand_path("..", __dir__))
require "json"
require_relative "elten_stub"

$warnings = []
module Log
  def self.info(_m); end
  def self.warning(m) $warnings.push(m.to_s); end
end

require_relative "../titan_apps"

class Answering
  Answer = Struct.new(:ok, :data, :error) do
    def ok?() ok == true end
    def [](key) data.is_a?(Hash) ? data[key] : nil end
  end

  attr_reader :asked

  def initialize(screen) @screen = screen; @asked = [] end
  def language() "pl" end
  def available?() true end
  def call(name, args = {}, title: nil)
    @asked.push([name.to_s, args])
    Answer.new(true, {"screen" => @screen}, nil)
  end
end

# The loop, really run - for a bounded number of frames, because `pump`
# ends only when the screen has moved and here it deliberately never does.
class Driven < TitanApps
  FRAMES = 3

  def initialize(screen)
    @tce = Answering.new(screen)
    super(nil, @tce)
    @screen = screen
    @running = true
  end

  attr_reader :tce

  def pump(form, screen, bound)
    @form = form
    frames = 0
    super
  rescue StopIteration
    nil
  end

  def loop_update
    @frames = (@frames || 0) + 1
    raise StopIteration if @frames > FRAMES
    super rescue nil
  end
end

def drive(screen, keys, focus = 0)
  renderer = Driven.new(screen)
  # A form update that presses Cancel would end the loop before a key is
  # ever read, so the screen is given something harmless to do instead.
  $events = Array.new(Driven::FRAMES + 2) { [Static.new(""), :nothing] }
  $keys = keys
  begin
    renderer.send(:show, screen)
  rescue Exception => e
    return [renderer.tce.asked, "#{e.class}: #{e.message}"]
  ensure
    $keys = []
  end
  [renderer.tce.asked, nil]
end

def pressed?(asked, id)
  asked.any? { |name, args| name == "app.press" && args["control"] == id }
end

def key_sent?(asked, key)
  asked.any? { |name, args| name == "app.key" && args["key"] == key }
end

path = File.join(__dir__, "screens.json")
if !File.exist?(path)
  puts "no screens.json - run capture_screens.py against a live TCE first"
  exit 1
end

problems = []
checked = 0
JSON.parse(File.read(path)).each do |entry|
  app = entry["app"].to_s
  screen = entry["screen"]
  where = "%s / %s" % [app, screen["title"].to_s]
  controls = screen["controls"] || []

  # ------------------------------------------------ Enter opens a row
  table = controls.find { |c| c["kind"] == "table" }
  if table != nil
    asked, raised = drive(screen, [:key_enter])
    checked += 1
    problems.push("#{where}: enter raised #{raised}") if raised
    if !raised && !pressed?(asked, table["id"])
      problems.push("#{where}: enter on the table reaches nothing")
    end
  end

  # ------------------- Backspace is forwarded, unless a field wants it
  first = controls.first
  if first != nil
    asked, raised = drive(screen, [0x08])
    checked += 1
    problems.push("#{where}: backspace raised #{raised}") if raised
    editing = TitanApps::EDITING_KINDS.include?(first["kind"].to_s)
    if !raised && editing && key_sent?(asked, "backspace")
      problems.push("#{where}: backspace was taken from the #{first['kind']} being typed into")
    end
    if !raised && !editing && !key_sent?(asked, "backspace")
      problems.push("#{where}: backspace never reached the application")
    end
  end

  # ------------------------------- a menu shortcut presses its own item
  shortcut = Driven.new(screen).send(:shortcuts, screen).find { |_c, _i, _l, sh| !sh }
  if shortcut != nil
    asked, raised = drive(screen, [:main_modifier, shortcut[0]])
    checked += 1
    problems.push("#{where}: the shortcut raised #{raised}") if raised
    if !raised && !pressed?(asked, shortcut[1])
      problems.push("#{where}: ctrl+#{shortcut[2]} presses nothing")
    end
  end
end

$warnings.uniq.each { |line| problems.push("a control would not bind: #{line}") }
puts "%d key(s) driven on real screens" % checked
problems.each { |line| puts "  ! #{line}" }
puts(problems.empty? ? "every key does what it says" : "#{problems.size} PROBLEM(S)")
exit(problems.empty? ? 0 : 1)
