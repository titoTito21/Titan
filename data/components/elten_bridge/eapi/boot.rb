# frozen_string_literal: true

# What Titan starts: load the platform, load the application, run it, report.
#
#   ruby boot.rb <unpacked application directory> <manifest json>
#
# Nothing here writes to stdout - that belongs to the protocol (see
# `bridge.rb`) - so the only way anything is said is across the wire.

$LOAD_PATH.unshift(__dir__) unless $LOAD_PATH.include?(__dir__)

require 'json'
require_relative 'bridge'
require_relative 'loop'
require_relative 'eapi'
require_relative 'program'
require_relative 'controls'
require_relative 'server'
require_relative 'audio'
require_relative 'media'
require_relative 'paths'
require_relative 'childproc'
require_relative 'eltenlink'
require_relative 'eltenapi'
require_relative 'vendor/resources'
require_relative 'vendor/runner'

EltenBridge.start

directory = ARGV[0].to_s
manifest = begin
  JSON.parse(ARGV[1].to_s)
rescue StandardError
  {}
end

status = 'finished'
detail = ''

begin
  raise "the application directory #{directory} is not there" unless Dir.exist?(directory)

  # The application's own folder goes on the load path so `require` finds a
  # file beside the entry point, and the working directory goes with it -
  # applications use `require_relative` mostly, but not only.
  $LOAD_PATH.unshift(directory) unless $LOAD_PATH.include?(directory)
  Dir.chdir(directory)

  entry = File.expand_path(manifest['main'].to_s.empty? ? '__app.rb' : manifest['main'],
                           directory)
  raise "#{File.basename(entry)} is not in this package" unless File.file?(entry)

  load(entry)

  name = manifest['main_class'].to_s
  raise 'the manifest does not name a class to run' if name.empty?

  begin
    klass = Object.const_get(name)
  rescue NameError
    raise "#{name} is not defined by this application"
  end
  unless klass.is_a?(Class) && klass <= Program
    raise "#{name} is not a Program"
  end

  # Elten's own order: `activate` synchronously, `init` on a worker whose
  # failure is logged and does not stop the application, then the instance.
  klass.activate if klass.respond_to?(:activate)
  if klass.respond_to?(:init)
    Thread.new do
      begin
        klass.init
      rescue StandardError => error
        Log.error("#{name}.init raised: #{error.class}: #{error.message}")
      end
    end
  end

  EltenBridge.notify('started', { 'class' => name })

  # **With no arguments.** An application's `initialize` is its OWN - the
  # file manager's is `initialize(startpath = false, mode: :files)`, and it
  # is constructed by Elten with nothing, so `startpath` is empty and it
  # opens on the user's home folder. Handing it the manifest as its first
  # positional argument made `startpath` a JSON document: the file manager
  # opened on a folder called `{"id" => "8c8d86ce-...` which does not
  # exist, and showed one row saying "Up one level". Every application that
  # defines its own `initialize` was being given the same thing.
  #
  # The manifest reaches the instance through the class instead, which is
  # where a `Program` looks for everything else about itself.
  Program.manifest = manifest
  program = klass.new
  Program.current = program
  program.run
rescue EltenBridge::Closed
  status = 'closed'
rescue SystemExit
  status = 'finished'
rescue Exception => error                            # rubocop:disable Lint/RescueException
  # Anything at all: an application that fails must say so in a sentence a
  # user can read, not disappear. The backtrace goes to the log, where a
  # developer can find it.
  status = 'failed'
  detail = "#{error.class}: #{error.message}"
  Log.error(detail)
  Log.debug(Array(error.backtrace).first(12).join("\n"))
end

begin
  EltenBridge.notify('ended', { 'status' => status, 'detail' => detail })
rescue StandardError
  nil
end
