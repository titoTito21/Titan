# Just enough of Elten to run the bridge's screens with no Elten.
# Every control records what it was given, so a test can say what the user
# would have HEARD, which is the only thing that matters here.

$said = []
$pages = []
$script = []          # scripted answers for the dialogs
$events = []          # [control, :event] applied one per form update

def _(text) text end
def alert(text, wait = true) $said.push("alert: #{text}"); nil end
def speak(text, **_o) $said.push("speak: #{text}"); nil end
def confirm(text = "") $said.push("confirm: #{text}"); $script.shift == true end
def display_text(text, header: "", **_o)
  $pages.push([header.to_s, text.to_s]); $said.push("page: #{header}"); nil
end
def selector(options, header: "", cancel_index: nil, **_o)
  $said.push("selector: #{header} #{options.inspect}")
  answer = $script.shift
  answer.is_a?(Integer) ? answer : -1
end
def select_action(actions, header: "", **_o)
  entries = Array(actions).map { |e| e.is_a?(Array) ? e : [e, e.to_s] }
  $said.push("menu: #{header} #{entries.map { |e| e[1] }.inspect}")
  answer = $script.shift
  answer.nil? ? nil : answer
end
def input_text(header = "", **_o)
  $said.push("ask: #{header}")
  $script.shift
end
def loop_update; end
def key_pressed?(_key, **_o) false end
def raw_key_held?(_key) false end
def play_sound(*_a); end

module Log
  def self.info(m) end
  def self.warning(m) end
end

module Tasks
  Outcome = Struct.new(:value)
  Progress = Struct.new(:ui)
  class Token; def raise_if_cancelled!; end; def sleep(t) Kernel.sleep(t) end; end
  def self.run(title: "", **_o, &block)
    Outcome.new(block.call(Progress.new(nil), Token.new))
  end
end

class Control
  attr_accessor :header
  def initialize; @events = {}; end
  def on(event, *_a, &block) (@events[event] ||= []).push(block); self end
  def trigger(event, *args) (@events[event] || []).each { |b| b.call(*args) }; end
  def focus(*_a); end
  def update; end
end

class ListBox < Control
  attr_accessor :index
  attr_reader :options
  def initialize(options = [], header: "", index: 0, **_o)
    super()
    @options = options; @header = header; @index = index
  end
  def options=(list) @options = list; @index = 0 if @index.to_i >= list.size; end
end

class EditBox < Control
  class Flags
    MultiLine = 1; ReadOnly = 2; Password = 4; Numbers = 8
  end
  attr_accessor :text
  def initialize(header = "", type: 0, text: "", **_o)
    super()
    @header = header; @type = type; @text = text
  end
end

# Elten's Static: focusable text that consumes no keys.
class Static < Control
  attr_accessor :label
  def initialize(label = "") super(); @label = label; end
end

class Button < Control
  attr_accessor :label
  def initialize(label = "") super(); @label = label; end
  def press; trigger(:press); end
end

class ChoiceListBox < Control
  Row = Struct.new(:label, :options, :value)
  attr_reader :rows
  def initialize(rows = [], header: "", **_o)
    super()
    @header = header
    @rows = rows.map { |r| r.is_a?(Row) ? r : Row.new(r[0], r[1], r[2].to_i) }
  end
end

class Form
  attr_accessor :cancel_button, :accept_button, :fields
  attr_reader :index
  def initialize(fields = [], **_o)
    @fields = fields; @index = 0
    $last_form = self          # so a test can read what a screen put up
  end
  def focus(*_a); end
  # Each update applies one scripted event, which is what drives a screen
  # to its end without a keyboard.
  # One scripted event per update. When the script runs out, Escape is
  # pressed - so every screen's own loop ends instead of running for ever,
  # which is what a real user leaving the screen does.
  def update
    event = $events.shift
    if event.nil?
      @cancel_button.press if @cancel_button.respond_to?(:press)
      @escaped = true
      return
    end
    control, name, *args = event
    control.trigger(name, *args)
  end
  def wait; end
  def resume; end
end

class SpeechOutput
  Voice = Struct.new(:id, :name, :output, :native, :keyword_init => true) do
    def voiceid; id.to_s; end
    def to_s; name.to_s; end
  end
  class << self
    def inherited(cls)
      SpeechOutput.outputs.push(cls) if cls != SpeechOutput && !SpeechOutput.outputs.include?(cls)
    end
    def outputs; @outputs ||= []; end
    def voices; outputs.flat_map(&:voices); end
    def apply_current_settings; end
  end
end

# Elten's extension contract, as much of it as an application can call.
# `activate` runs through this in the tests, so a hook named wrongly is a
# failing check rather than an add-on that loads and does nothing.
$extension = nil

class Program
  def self.extension(name)
    $extension = ExtensionStub.new(name)
    yield($extension)
    $extension
  end

  # Elten's own configurable quick actions.
  def self.register_quickaction(ident, label, &block)
    $quickactions ||= []
    $quickactions.push([ident, label, block])
    true
  end

  def self.read_json(_path, default: nil) ($program_state ||= (default || {})) end
  def self.update_json(_path, default: nil)
    $program_state ||= (default || {})
    yield($program_state)
    $program_state
  end

  class CommandStub
    attr_reader :key, :label, :callback, :surfaces
    def initialize(key, label, callback)
      @key = key; @label = label; @callback = callback; @surfaces = []
    end
    def place(surface, visible: nil) @surfaces.push(surface); self; end
  end

  class SettingsStub
    attr_reader :categories, :booleans
    def initialize; @categories = []; @booleans = []; end
    def category(label) @categories.push(label); end
    def boolean(key, label:, get:, set:) @booleans.push([key, label, get, set]); end
    def integer(key, label:, get:, set:, range: nil) end
    def text(key, label:, get:, set:) end
    def choice(key, label:, choices:, get:, set:) end
  end

  class ExtensionStub
    attr_reader :name, :commands, :settings_builder, :tick_interval
    def initialize(name = "") @name = name; @commands = []; end
    def start(&b) @start = b; end
    def tick(interval: 0, &b) @tick_interval = interval; @tick = b; self; end
    def stop(&b) @stop = b; end
    def settings(&b)
      @settings_builder = SettingsStub.new
      b.call(@settings_builder)
    end
    def command(key, label:, visible: nil, &b)
      stub = CommandStub.new(key, label, b)
      @commands.push(stub)
      stub
    end
    def main_tab(key, label:, visible: nil, &b) CommandStub.new(key, label, b) end
    def run_tick; @tick.call if @tick; end
    def run_stop(reason = :unload) @stop.call(reason) if @stop; end
  end
end
