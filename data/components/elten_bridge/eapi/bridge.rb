# frozen_string_literal: true

# The wire between an Elten application and Titan.
#
# Titan owns the window, the voice and the mixer; this process owns the
# application. So everything the platform does is a call across, and
# everything the user does arrives back as an event.
#
# The line protocol is JSON, one object per line:
#
#   out  {"id":7,"op":"alert","args":{"text":"..."}}     a call, awaiting a reply
#   in   {"id":7,"ok":true,"result":null}                the reply
#   in   {"event":"key","name":"down"}                   something happened
#   out  {"log":"...","level":"warning"}                 no reply wanted
#
# **stdout belongs to the protocol and nothing else.** An application is
# somebody else's code and it will `puts`; Elten's own applications do it
# constantly, and one stray line of it corrupts the stream and takes the
# application down with a parse error that reads like a Titan bug. So the real
# stdout is taken away at boot, kept privately here, and `$stdout` is pointed
# at stderr - where Titan collects it as the application's log.
module EltenBridge
  CHANNEL = $stdout.dup
  CHANNEL.sync = true

  $stdout = $stderr

  @lock = Mutex.new
  @pending = {}
  @events = Queue.new
  @next_id = 0
  @reader = nil
  @closed = false

  class Closed < StandardError; end

  class RemoteError < StandardError
    attr_reader :kind

    def initialize(message, kind = 'error')
      super(message)
      @kind = kind
    end
  end

  class << self
    attr_reader :events

    # Start the thread that reads Titan's side of the wire.
    #
    # One reader, forever: a reply is handed to whoever is waiting for its id
    # and an event goes on the queue. Doing this per-call instead would mean
    # two threads reading one pipe, which loses lines.
    def start
      return if @reader

      @reader = Thread.new do
        begin
          while (line = $stdin.gets)
            line = line.strip
            next if line.empty?

            begin
              message = JSON.parse(line)
            rescue StandardError
              next
            end
            deliver(message)
          end
        rescue IOError, Errno::EPIPE
          # Titan has gone. Everything waiting is released below.
        ensure
          shutdown
        end
      end
      @reader.abort_on_exception = false
    end

    # Ask Titan to do something, and wait for the answer.
    #
    # The wait is the point: an application's `main` is a linear script that
    # stops on a dialog until the user answers it, and that is exactly what
    # Elten's own API is. A call that did not block would turn every form in
    # every application into a race.
    def call(op, args = {})
      raise Closed, 'Titan has closed this application' if @closed

      id = nil
      slot = Queue.new
      @lock.synchronize do
        @next_id += 1
        id = @next_id
        @pending[id] = slot
      end
      write({ 'id' => id, 'op' => op.to_s, 'args' => args })
      answer = slot.pop
      raise Closed, 'Titan has closed this application' if answer.nil?

      if answer['ok']
        answer['result']
      else
        raise RemoteError.new(answer['error'].to_s,
                              answer['kind'].to_s.empty? ? 'error' : answer['kind'])
      end
    end

    # Say something with no reply wanted - a log line, a state change.
    def notify(op, args = {})
      return if @closed

      write({ 'op' => op.to_s, 'args' => args })
    end

    # The next thing the user did, or nil when Titan has gone.
    #
    # `timeout` in seconds; nil waits for ever. A Runner's loop is built on
    # this, and so is every control that waits for a key.
    def next_event(timeout = nil)
      return nil if @closed && @events.empty?

      if timeout.nil?
        @events.pop
      else
        deadline = now + timeout
        loop do
          return @events.pop(true) if !@events.empty?
          return nil if @closed

          left = deadline - now
          return :timeout if left <= 0

          sleep([left, 0.01].min)
        end
      end
    rescue ThreadError
      :timeout
    end

    def closed?
      @closed
    end

    def now
      Process.clock_gettime(Process::CLOCK_MONOTONIC)
    end

    private

    def write(message)
      line = JSON.generate(message)
      @lock.synchronize do
        begin
          CHANNEL.puts(line)
        rescue IOError, Errno::EPIPE
          @closed = true
        end
      end
    end

    def deliver(message)
      if message.key?('id')
        slot = @lock.synchronize { @pending.delete(message['id']) }
        slot&.push(message)
      elsif message['event']
        @events.push(message)
      end
    end

    # Titan has gone, or is going. Nothing may wait for ever afterwards: an
    # application parked on a dialog whose window has been closed would hold
    # this process open until it was killed.
    def shutdown
      waiting = nil
      @lock.synchronize do
        @closed = true
        waiting = @pending.values
        @pending = {}
      end
      waiting.each { |slot| slot.push(nil) }
      @events.push(nil)
    end
  end
end
