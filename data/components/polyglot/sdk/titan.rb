# Titan for Ruby - the Polyglot line protocol. `require 'titan'`.
#
#   Titan.speak("Hello")
#   name = Titan.ask("Your name?")
#   i = Titan.choose("Pick one", ["Tea", "Coffee"])   # index from 0, or nil
#   Titan.open_window("My game")
#   while (e = Titan.next_event(nil)) ... end
#
# Every call in the protocol is a method here (Titan.call(:name, ...) for the
# rest). A refusal raises Titan::Error with Titan's own sentence.
require 'json'

module Titan
  class Error < StandardError; end

  @out = $stdout
  @in = $stdin
  @out.sync = true
  @out.binmode
  @in.binmode
  # Anything the program itself prints goes to the log, never to the wire.
  $stdout = $stderr
  @next_id = 0

  def self.call(name, *args, **named)
    @next_id += 1
    payload = { 'id' => @next_id, 'call' => name.to_s,
                'args' => named.empty? ? args : named.transform_keys(&:to_s) }
    @out.write(JSON.generate(payload) + "\n")
    loop do
      line = @in.gets
      raise Error, 'Titan has gone' if line.nil?
      line = line.force_encoding('UTF-8')
      next unless line.start_with?('{')
      reply = JSON.parse(line)
      next unless reply['id'] == @next_id
      raise Error, reply['error'].to_s unless reply['ok']
      return reply['value']
    end
  end

  %w[info speak stop_speech play stop_sounds message ask confirm choose text
     open_window close_window next_event wait action data_dir log exit
     add_menu title provide reply].each do |name|
    define_singleton_method(name) { |*a, **k| call(name, *a, **k) }
  end

  # A method of an object Titan handed the program (a launcher's api, a
  # Titan IM module's "sounds"...): Titan.host(api, 'open_telegram').
  def self.host(target, method, *args)
    call(:host, target, method.to_s, args)
  end

  # A function of this program Titan may keep and call later - a menu
  # entry's action: { 'label' => 'Hello', 'action' => Titan.fn('hello') }.
  def self.fn(name)
    { '__function' => name.to_s }
  end

  # Every add-on Titan CALLS (a widget, a statusbar applet, a TTS engine, a
  # gamepad mode...) ends with this: the functions Titan may call, by the
  # same names a Python add-on of that kind defines.
  #   Titan.serve('get_statusbar_item_text' => -> { Time.now.strftime('%H:%M') })
  def self.serve(handlers = {}, **named)
    # Titan.serve('a' => ...) without braces arrives as keywords in Ruby 3.
    on_event = named.delete(:on_event)
    handlers = handlers.merge(named).transform_keys(&:to_s)
    provide(handlers.keys)
    loop do
      event = next_event(nil)
      next if event.nil?
      return if event['type'] == 'close'
      if event['type'] == 'call'
        handler = handlers[event['name'].to_s]
        begin
          value = handler ? handler.call(*(event['args'] || [])) : nil
          reply(event['id'], value)
        rescue StandardError => e
          reply(event['id'], nil, e.message)
        end
      elsif on_event
        on_event.call(event)
      end
    end
  end
end
