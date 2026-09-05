# Getting onto Elten's own thread from the bus worker.
#
# The bus has one thread and it owns the pipe; Elten has one thread and it
# owns the screen. Everything the bridge answered until now was a read of
# state that belongs to neither - a notification list its background service
# keeps, a name on the session - so the worker could answer it where it
# stood. Reading what is ON the screen, and putting something on it, cannot
# be: `insert_scene` runs Elten's own pump, and a scene's controls are being
# changed by the thread that draws them.
#
# So this is the marshaller, and it is the same shape as Titan's own
# `run_on_gui`: a job is posted, Elten's tick runs it, and the caller waits
# for the answer with a deadline. Three rules keep it from becoming the
# thing that makes Elten stutter:
#
# * **A job is short.** It runs inside Elten's pump, so whatever it takes is
#   time Elten is not answering the keyboard in. Reads of what is already in
#   memory, and `insert_scene`, which is Elten's own way of opening a screen.
# * **A tick spends a budget, not the queue.** However many jobs are waiting,
#   the tick runs what fits in `BUDGET` and leaves the rest for the next one.
# * **Nobody waits for ever.** A caller gets a deadline, and a job whose
#   answer nobody is waiting for any more is still run and its answer
#   dropped - which is what stops a slow answer from arriving inside a
#   later, unrelated question.

require "thread"

module EltenMain
  #: How long one tick may spend running jobs, in seconds. Elten's pump is
  #: the keyboard, and a tick that spends much longer than this is a
  #: keystroke the user waited for.
  BUDGET = 0.15

  #: How long a caller on the bus worker waits. The tick runs every 5
  #: seconds at worst (the extension's own interval), so this has to cover
  #: one of those with room.
  WAIT = 6.0

  class << self
    def queue
      @queue ||= Queue.new
    end

    # Post a job and wait for what it answers. Returns [true, value] or
    # [false, why]. Never raises: this is called from the bus worker, where
    # an exception is a dropped connection.
    def call(timeout = WAIT, &block)
      return [false, "the bridge is not running inside Elten"] if block == nil
      inbox = Queue.new
      queue.push({:block => block, :inbox => inbox})
      answer = begin
        inbox.pop(:timeout => timeout)
      rescue Exception
        nil
      end
      return [false, "Elten did not answer within #{timeout.round} seconds"] if answer == nil
      answer
    rescue Exception => e
      [false, "#{e.class}: #{e.message}"]
    end

    # Run what is waiting, on ELTEN's thread. Called from the extension
    # tick and from nowhere else.
    def pump
      deadline = Process.clock_gettime(Process::CLOCK_MONOTONIC) + BUDGET
      while Process.clock_gettime(Process::CLOCK_MONOTONIC) < deadline
        job = begin
          queue.pop(true)
        rescue ThreadError
          nil
        end
        break if job == nil
        run(job)
      end
      nil
    rescue Exception
      nil
    end

    def run(job)
      answer = begin
        [true, job[:block].call]
      rescue Exception => e
        [false, "#{e.class}: #{e.message}"]
      end
      job[:inbox].push(answer)
    rescue Exception
      nil
    end

    # For the tests, and for a stop: a job nobody will ever run must not
    # leave its caller waiting out the whole deadline.
    def drop_all(why = "the bridge is stopping")
      loop do
        job = begin
          queue.pop(true)
        rescue ThreadError
          nil
        end
        break if job == nil
        job[:inbox].push([false, why]) rescue nil
      end
      nil
    end
  end
end
