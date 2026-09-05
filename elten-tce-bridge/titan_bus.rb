# The TCE action bus, from inside Elten.
#
# Titan listens on one named pipe, \\.\pipe\TitanActions, and speaks JSON
# lines: a hello carrying a shared token, then {"type":"call"} answered by
# {"type":"call_result"} with the same id, and {"type":"list"} answered by
# {"type":"list_result"} carrying every add-on Titan can reach. Titan's own
# client library (src/titan_core/titan_actions.py) is the authority for the
# wire; this is that protocol written in Ruby.
#
# ONE THREAD OWNS THE PIPE, and that is not tidiness. Measured against a
# stand-in Titan: with a reader thread parked in `gets` on the File and
# another thread writing to it, every write waited for the parked read - a
# fire-and-forget "say this" took 993 ms to hand over, and afterwards
# exactly as long as the previous answer took. Ruby serialises operations on
# one IO object, which is the same trap Titan documents on its own side. So
# nothing but the worker touches the pipe: callers post and are never
# blocked, which is what lets the speech output ask this to speak on every
# keystroke without Elten's own thread ever waiting on a pipe.

require "json"
require "thread"

class TitanBus
  PIPE = "\\\\.\\pipe\\TitanActions".freeze
  # What each served action is FOR, in Titan's own words - this is what
  # Titan lists and what its AI is told about them. Deliberately in
  # English and not translated: it is read by Titan and by a model, not by
  # somebody sitting in Elten.
  SUMMARIES = {
    "status" => "Whether the Elten client is running, who is signed in to "\
                "it and which version it is. Asked of Elten itself.",
    "notifications" => "The notifications Elten is holding right now - a "\
                       "private message, a forum reply, somebody coming "\
                       "online. Read live from Elten's own service.",
    "news" => "How much of each kind is waiting in Elten right now.",
    "screen" => "What is on Elten's screen at this moment: what it last "\
                "said, which screen it is on, and the controls that screen "\
                "is holding.",
    "programs" => "The programs installed in Elten, as its own menu lists "\
                  "them.",
    "run_program" => "Open one of Elten's own programs, by name. It appears "\
                     "in Elten, in front of whoever is sitting there.",
  }.freeze
  RECONNECT_SECONDS = 3.0
  # An idle probe, so "is Titan still running?" is answered by having asked.
  # Nothing else would notice a Titan that has exited: the worker is parked
  # on its own queue, not on the pipe.
  IDLE_PROBE_SECONDS = 5.0
  DEFAULT_TIMEOUT = 30.0

  # What an action answered. `question` is Titan asking for something it
  # needs before it can run - a pending result, not a failure.
  Answer = Struct.new(:ok, :text, :question, :addons) do
    def ok?
      ok == true
    end

    def pending?
      question != nil
    end

    def to_s
      text.to_s
    end
  end

  # `pipe` is here so the bridge can be run against a stand-in Titan in a
  # test; nothing but a test ever passes it.
  def initialize(id: "elten_tce_bridge", label: "TCE bridge (Elten)", pipe: PIPE)
    @id = id
    @label = label
    @pipe = pipe
    @queue = Queue.new
    @lock = Mutex.new
    @connected = false
    @io = nil
    @next_id = 0
    @thread = nil
    @stopping = false
    @last_error = ""
    @handlers = {}
  end

  # **What TITAN may ask of US.** Everything else here is this side calling
  # Titan; this is the other direction, which is what lets Titan's AI ask
  # Elten a question in flight rather than reading the last thing that was
  # pushed at it.
  #
  # `handlers` is {name => proc(args)}, and every one of them must be a
  # cheap READ that returns promptly: it runs on the bus worker, which is
  # also the thread that carries this side's own calls, so a handler that
  # waits is a bridge that has stopped answering. Nothing that touches
  # Elten's screen belongs here either - that is Elten's own thread's.
  #
  # Call it before `start`: the names travel in the hello, which is where
  # Titan learns what this add-on can be asked.
  def serve(handlers)
    @lock.synchronize { @handlers = (handlers || {}).dup }
    true
  end

  def served
    @lock.synchronize { @handlers.keys.map(&:to_s) }
  end

  def start
    @lock.synchronize do
      return true if @thread != nil && @thread.alive?
      @stopping = false
      @thread = Thread.new { worker }
      begin
        @thread.name = "TitanBus"
      rescue Exception
      end
    end
    true
  end

  def stop
    @lock.synchronize { @stopping = true }
    @queue.push(nil)
    io = @lock.synchronize { @io }
    io.close rescue nil
    true
  end

  def connected?
    @lock.synchronize { @connected }
  end

  def last_error
    @lock.synchronize { @last_error }
  end

  # Fire and forget. Returns at once; `block`, when given, runs on the
  # worker thread with the answer text (nil when the call failed).
  def call(addon, action, args = {}, &block)
    return false if @lock.synchronize { @stopping }
    @queue.push({"payload" => {"type" => "call", "addon" => addon.to_s,
                               "action" => action.to_s, "args" => args || {}},
                 "block" => proc { |answer| block.call(answer && answer.text) if block }})
    true
  end

  # Ask and wait. NEVER call this from Elten's own thread: wrap it in
  # Tasks.run, which runs the block on a worker while the owner thread goes
  # on pumping the interface. Everything in the bridge's screens does.
  def call_sync(addon, action, args = {}, timeout: DEFAULT_TIMEOUT)
    request({"type" => "call", "addon" => addon.to_s, "action" => action.to_s,
             "args" => args || {}}, timeout)
  end

  # Every add-on Titan can reach, with its kind and the names of its
  # actions: {"id","label","kind","kind_label","description","actions",...}.
  def list_sync(timeout: DEFAULT_TIMEOUT)
    answer = request({"type" => "list"}, timeout)
    answer.ok? ? (answer.addons || []) : []
  end

  # Everything still waiting that has not been sent. Speech is "latest
  # wins": a line the user has already interrupted must not be spoken when
  # its turn comes round.
  def drop_pending
    dropped = 0
    begin
      loop do
        item = @queue.pop(true)
        break if item == nil
        dropped += 1
      end
    rescue ThreadError
    end
    dropped
  end

  private

  def request(payload, timeout)
    return Answer.new(false, missing_titan_message, nil, nil) if !connected? && !wait_for_connection(2.0)
    inbox = Queue.new
    @queue.push({"payload" => payload, "block" => proc { |answer| inbox.push(answer) }})
    answer = begin
      inbox.pop(timeout: timeout)
    rescue Exception
      nil
    end
    return Answer.new(false, "Titan did not answer within #{timeout.round} seconds.", nil, nil) if answer == nil
    answer
  end

  def wait_for_connection(seconds)
    deadline = monotonic + seconds
    while monotonic < deadline
      return true if connected?
      sleep 0.05
    end
    connected?
  end

  def monotonic
    Process.clock_gettime(Process::CLOCK_MONOTONIC)
  end

  def missing_titan_message
    error = last_error
    error == "" ? "TCE is not running." : "TCE is not running (#{error})."
  end

  def token
    base = ENV["APPDATA"].to_s
    return "" if base == ""
    File.read(File.join(base, "titosoft", "Titan", "actions", "bus.token")).strip
  rescue Exception
    ""
  end

  def worker
    until @lock.synchronize { @stopping }
      begin
        connect if @lock.synchronize { @io } == nil
        if @lock.synchronize { @io } == nil
          sleep RECONNECT_SECONDS
          next
        end
        command = @queue.pop(timeout: IDLE_PROBE_SECONDS)
        if command == nil
          next if @lock.synchronize { @stopping }
          probe
          next
        end
        deliver(command)
      rescue Exception => e
        note("worker: #{e.class}: #{e.message}")
        disconnect
        sleep RECONNECT_SECONDS
      end
    end
    disconnect
  end

  def connect
    io = File.open(@pipe, "r+b")
    io.sync = true
    io.write(JSON.generate({"type" => "hello", "token" => token, "id" => @id,
                            "label" => @label, "kind" => "app",
                            # **This side DRIVES Titan; it serves nothing.**
                            # Titan says so out loud when a client joins and
                            # when it leaves - an add-on opening is something
                            # the user just did, and a program somewhere else
                            # on the machine taking hold of Titan is not.
                            "client" => true,
                            "pid" => Process.pid, "path" => __dir__.to_s,
                            # What Titan may ask of us. A client that serves
                            # nothing declares nothing, which is what this
                            # did until Titan's AI needed to ask Elten a
                            # question rather than read the last answer it
                            # was handed.
                            "actions" => action_manifest}) + "\n")
    line = io.gets
    welcome = line == nil ? nil : (JSON.parse(line) rescue nil)
    if welcome == nil || welcome["type"] != "welcome" || welcome["ok"] != true
      # A refused token is not an outage and must not be retried silently
      # for ever as though it were: say which it was.
      reason = welcome == nil ? "no answer" : welcome["error"].to_s
      @lock.synchronize { @last_error = "TCE refused the connection: #{reason}" }
      note(@lock.synchronize { @last_error })
      io.close rescue nil
      return
    end
    @lock.synchronize { @io = io; @connected = true; @last_error = "" }
    note("connected to TCE")
  rescue Errno::ENOENT, Errno::EAGAIN, Errno::EACCES => e
    # Not running, or busy with another client for a moment. Both are
    # ordinary and neither is worth a line in the log every three seconds.
    @lock.synchronize { @connected = false; @last_error = e.class.to_s }
  rescue Exception => e
    @lock.synchronize { @connected = false; @last_error = "#{e.class}: #{e.message}" }
    note("could not connect: #{e.class}: #{e.message}")
  end

  def disconnect
    io = nil
    @lock.synchronize do
      io = @io
      @io = nil
      @connected = false
    end
    io.close rescue nil
  end

  def deliver(command)
    io = @lock.synchronize { @io }
    block = command["block"]
    if io == nil
      block.call(Answer.new(false, missing_titan_message, nil, nil)) if block
      return
    end
    id = @lock.synchronize { @next_id += 1 }
    payload = command["payload"].merge("id" => id)
    io.write(JSON.generate(payload) + "\n")
    message = read_answer(io, id)
    block.call(to_answer(message)) if block
  end

  def to_answer(message)
    return Answer.new(false, missing_titan_message, nil, nil) if message == nil
    if message["type"] == "list_result"
      return Answer.new(message["ok"] == true, "", nil, message["addons"] || [])
    end
    text = message["ok"] == true ? message["result"].to_s : message["error"].to_s
    Answer.new(message["ok"] == true, text, message["question"], nil)
  end

  # Reads until the answer to `id` arrives. Titan only speaks when spoken to
  # - it answers a ping, and invokes actions the client declared, and this
  # client declares none - so anything else is noise to step over.
  def read_answer(io, id)
    loop do
      line = io.gets
      if line == nil
        disconnect
        return nil
      end
      message = JSON.parse(line) rescue nil
      next if message == nil
      case message["type"]
      when "ping"
        io.write(JSON.generate({"type" => "pong"}) + "\n")
      when "invoke"
        # **Answered HERE, while we are waiting for our own answer**, and
        # that is not an optimisation: Titan may well be asking us
        # something because of the very call we are waiting on, and a
        # reader that stepped over an invoke until its own answer arrived
        # would be two sides each waiting for the other.
        answer_invoke(io, message)
      when "call_result", "list_result"
        next if message["id"] != id
        return message
      end
    end
  rescue Exception => e
    note("read: #{e.class}: #{e.message}")
    disconnect
    nil
  end

  # One thing Titan asked of us. Never raises: a handler that fails is an
  # error sent back, because an exception here would take the connection
  # with it and Titan would see the add-on leave.
  def answer_invoke(io, message)
    name = message["action"].to_s
    handler = @lock.synchronize { @handlers[name] || @handlers[name.to_sym] }
    if handler == nil
      write_result(io, message["id"], false,
                   "the TCE bridge has no action '#{name}'")
      return
    end
    result = handler.call(message["args"] || {})
    write_result(io, message["id"], true, result)
  rescue Exception => e
    write_result(io, message["id"], false, "#{e.class}: #{e.message}")
  end

  def write_result(io, id, ok, value)
    payload = {"type" => "result", "id" => id, "ok" => ok == true}
    if ok == true
      payload["result"] = value
    else
      payload["error"] = value.to_s
    end
    io.write(JSON.generate(payload) + "\n")
  rescue Exception
    nil
  end

  # [{name:, summary:}] for the hello. Titan reads the names; the summaries
  # are what its own `list_addons` shows and what its AI is told.
  def action_manifest
    served.map do |name|
      {"name" => name, "summary" => SUMMARIES[name].to_s}
    end
  end

  def probe
    io = @lock.synchronize { @io }
    return if io == nil
    id = @lock.synchronize { @next_id += 1 }
    io.write(JSON.generate({"type" => "call", "id" => id, "addon" => "titan",
                            "action" => "speaking", "args" => {}}) + "\n")
    read_answer(io, id)
  rescue Exception
    disconnect
  end

  def note(message)
    Log.info("TCE bridge: #{message}") if defined?(Log)
  rescue Exception
  end
end
