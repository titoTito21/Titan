# frozen_string_literal: true

# `ChildProc` - running another program.
#
# Youtube uses it for `yt-dlp` and `deno`, ffmpeg's encoders for `ffmpeg.exe`.
# These applications ARE wrappers around external tools; without this they
# have nothing to wrap.
#
# **It is worth being plain about what this is.** An `.eltenapp` is Ruby
# running in a real interpreter with the user's privileges, and Ruby can
# already spawn a process by itself - `system`, backticks, `Process.spawn`
# are all there. So this class is not a hole being opened; it is Elten's own
# interface onto something the process can already do, and withholding it
# would only break the applications that ask politely. Elten's own
# documentation says the same thing about its signatures: they authenticate
# the bytes, they do not sandbox them.
#
# What this does add is the shape Elten's applications expect - non-blocking
# reads of stdout and stderr, `alive?`, an exit code - implemented on Ruby's
# own `Open3`, so nothing here is Titan-specific and nothing goes over the
# bridge.

require 'open3'

class ChildProc
  attr_reader :command, :exitcode

  # `ChildProc.new(command, working_directory)`. `command` is the whole
  # command line, which is how Elten's applications build it.
  def initialize(file, l_path = nil, path: nil, show_window: false,
                 cancellation_token: nil)
    @command = file.to_s
    @directory = (path || l_path).to_s
    @exitcode = nil
    @out = +''
    @err = +''
    @lock = Mutex.new
    options = {}
    options[:chdir] = @directory if !@directory.empty? && Dir.exist?(@directory)
    begin
      @stdin, @stdout, @stderr, @waiter = Open3.popen3(@command, **options)
    rescue StandardError => error
      Log.error("#{@command}: #{error.class}: #{error.message}")
      @stdin = @stdout = @stderr = nil
      @waiter = nil
      @exitcode = -1
      return
    end
    @readers = [drain(@stdout, @out), drain(@stderr, @err)]
  end

  def started?
    !@waiter.nil?
  end

  def alive?
    return false if @waiter.nil?

    @waiter.alive?
  end

  # **Elten's own spelling.** Its applications ask `process.running?`,
  # `process.avail`, `process.avail_err` and `process.terminate` - the
  # YouTube client's whole search loop is built on them - and a method
  # that is merely absent is a `NoMethodError` inside the application, so
  # the search ended before yt-dlp had said a word.
  alias running? alive?

  # How many bytes are waiting, so a loop knows whether there is anything
  # to read without a read that would block.
  def avail
    @lock.synchronize { @out.bytesize }
  end

  def avail_err
    @lock.synchronize { @err.bytesize }
  end

  # A process id, which some applications read.
  def pid
    @waiter&.pid
  end
  alias process_id pid

  # Whatever has arrived so far, and never blocks: an application polls this
  # from inside its own loop, and a read that waited would stop the loop.
  def read(size = nil)
    take(@out, size)
  end

  def read_err(size = nil)
    take(@err, size)
  end

  def write(text)
    return 0 if @stdin.nil? || @stdin.closed?

    @stdin.write(text.to_s)
    @stdin.flush
    text.to_s.bytesize
  rescue IOError, Errno::EPIPE
    0
  end

  def wait(timeout = nil)
    return @exitcode if @waiter.nil?

    if timeout.nil?
      @waiter.join
    else
      @waiter.join(timeout)
    end
    finish
    @exitcode
  end

  def kill
    return if @waiter.nil?

    begin
      Process.kill('KILL', @waiter.pid)
    rescue StandardError
      nil
    end
    finish
  end
  alias terminate kill

  def close
    kill if alive?
    [@stdin, @stdout, @stderr].each do |stream|
      begin
        stream&.close unless stream&.closed?
      rescue IOError
        nil
      end
    end
    @readers.to_a.each { |thread| thread.kill if thread.alive? }
    finish
    nil
  end

  private

  def finish
    return @exitcode if @exitcode

    @exitcode = begin
      status = @waiter&.value
      status.respond_to?(:exitstatus) ? status.exitstatus : nil
    rescue StandardError
      nil
    end
  end

  # One thread per stream, appending into a buffer the application reads.
  # Anything else means a `read` that blocks, and a blocked read inside a
  # loop is an application that has stopped.
  def drain(stream, buffer)
    return nil if stream.nil?

    Thread.new do
      begin
        while (chunk = stream.readpartial(4096))
          @lock.synchronize { buffer << chunk }
        end
      rescue EOFError, IOError
        nil
      end
    end
  end

  def take(buffer, size)
    @lock.synchronize do
      if size.nil?
        taken = buffer.dup
        buffer.clear
        taken
      else
        taken = buffer[0, size.to_i].to_s
        buffer.slice!(0, taken.length)
        taken
      end
    end
  end
end
