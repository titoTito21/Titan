# frozen_string_literal: true

# The half of the Elten API that talks to EltenLink's servers - declared by
# an application at class level, and reached at run time for leaderboards,
# shared tables, notifications and quick actions.
#
# **Titan is not EltenLink**, and this is the honest consequence: an
# application here has no EltenLink session, so a table it asks the SERVER
# for cannot be the server's. What it gets instead is a real table, kept in
# the application's own `data_path` - which means a game's high scores work,
# are per-user, survive restarts and are shared with Elten's copy of the same
# application, but they are THIS MACHINE's scores and not the network's.
#
# The alternative was to raise, and it is worse: three of the installed games
# (`skeet`, `audiomemory`, `MileByMile`) declare `server_app` at class level
# and never start at all without it, so refusing would mean refusing the
# applications rather than refusing the network. `available?` answers false
# and `last_error` says why, which is exactly the contract Elten's own
# `Leaderboard` documents for a server it cannot reach - so an application
# that checks, as they are written to, behaves correctly.

module Programs
  class ProgramError < StandardError; end

  # What `server_app(...)` records at class level.
  class ServerAppDefinition
    attr_reader :uuid, :tables, :notifications

    def initialize(uuid: nil, tables: {}, protected: false, notifications: false)
      @uuid = uuid
      @tables = tables || {}
      @protected = protected
      @notifications = notifications
    end

    def protected?
      @protected == true
    end
  end

  # One named table, kept as a JSON file beside the application's own data.
  #
  # Deliberately a small subset of what EltenLink's tables do: insert, read
  # back in an order, and count. It is what a leaderboard needs and what the
  # installed games actually call.
  class LocalTable
    def initialize(program, name)
      @program = program
      @name = name.to_s
      @path = program.data_path(File.join('server_tables', "#{safe(@name)}.json"))
    end

    def available?
      true
    end

    def insert(data)
      rows = read
      row = data.is_a?(Hash) ? data.dup : { 'value' => data }
      row['id'] = (rows.map { |held| held['id'].to_i }.max || 0) + 1
      row['time'] ||= Time.now.to_i
      rows << row
      write(rows)
      row
    end
    alias add insert

    def all(where: nil, order: nil, limit: nil, offset: 0)
      rows = read
      rows = rows.select { |row| matches?(row, where) } if where
      rows = sort(rows, order) if order
      rows = rows.drop(offset.to_i) if offset.to_i > 0
      rows = rows.first(limit.to_i) if limit
      rows
    end
    alias select all

    def count(where: nil)
      all(where: where).size
    end

    def delete(where: nil)
      return write([]) if where.nil?

      write(read.reject { |row| matches?(row, where) })
    end

    private

    def safe(name)
      name.gsub(/[^A-Za-z0-9_\-]/, '_')[0, 60]
    end

    def read
      rows = @program.read_json(@path, default: [])
      rows.is_a?(Array) ? rows : []
    end

    def write(rows)
      @program.write_json(@path, rows)
      rows
    end

    def matches?(row, where)
      return true if where.nil?

      where.all? { |key, value| row[key.to_s] == value }
    end

    def sort(rows, order)
      key, direction = Array(order).flatten
      key = key.to_s
      sorted = rows.sort_by { |row| comparable(row[key]) }
      direction.to_s.downcase == 'asc' ? sorted : sorted.reverse
    end

    def comparable(value)
      value.is_a?(Numeric) ? value : value.to_s
    end
  end

  # `leaderboard(name, order:)` - Elten's own wrapper, over whichever table
  # it was given.
  class Leaderboard
    DEFAULT_RETRY_DELAYS = [5, 30, 120].freeze

    attr_reader :last_error

    def initialize(table, order: nil, retry_delays: DEFAULT_RETRY_DELAYS,
                   log_label: 'Leaderboard')
      @table = table
      @order = order || ['score', 'desc']
      @log_label = log_label
      @last_error = nil
    end

    def available?
      @table != nil && @table.available?
    end

    def top(limit: 10, where: nil, order: nil, offset: 0)
      return [] if @table.nil?

      @table.all(where: where, order: order || @order, limit: limit,
                 offset: offset)
    rescue StandardError => error
      @last_error = error.message
      Log.warning("#{@log_label}: #{error.message}")
      []
    end

    def submit(data)
      return false if @table.nil?

      @table.insert(data)
      true
    rescue StandardError => error
      @last_error = error.message
      Log.warning("#{@log_label}: #{error.message}")
      false
    end
  end
end

# The paths, the files and the metadata are available at CLASS level as well
# as on an instance - Elten defines them in both places, and applications use
# both: `KlangoArchive` reads `data_path` from a class method, the media
# catalogue asks the class for its `version`. Defining them once in a module
# and both including and extending it is what keeps the two from drifting.
module ProgramPaths
  def asset_path(path = '')
    EltenBridge.call('path', { 'kind' => 'asset', 'relative' => path.to_s })
  end

  def data_path(path = '')
    EltenBridge.call('path', { 'kind' => 'data', 'relative' => path.to_s })
  end

  def cache_path(path = '')
    EltenBridge.call('path', { 'kind' => 'cache', 'relative' => path.to_s })
  end
end

class Program
  include ProgramPaths
  extend ProgramPaths

  class << self
    # The manifest is not on the class, so these answer through the bridge -
    # which is Titan's copy of exactly the same manifest.
    def version
      EltenBridge.call('app_version')
    rescue EltenBridge::Closed
      ''
    end

    # NOT `name`: that is `Class#name`, which Ruby uses for constant lookup
    # and for the class in every error message it prints. Overriding it made
    # a `NoMethodError` read "undefined method for class Katalog mediów",
    # which is a class that does not exist. The application's own name is
    # asked for on an INSTANCE, where it does not collide with anything.
    def app_name(language = nil)
      EltenBridge.call('app_name', { 'language' => language&.to_s })
    rescue EltenBridge::Closed
      ''
    end

    def description(language = nil)
      EltenBridge.call('app_description', { 'language' => language&.to_s })
    rescue EltenBridge::Closed
      ''
    end

    def app_uuid
      EltenBridge.call('app_id')
    rescue EltenBridge::Closed
      ''
    end

    # Declared at class level, before anything runs - which is why an
    # application that calls it will not even load without it.
    def server_app(uuid: nil, tables: {}, protected: false, notifications: false)
      @server_app_definition = Programs::ServerAppDefinition.new(
        uuid: uuid, tables: tables, protected: protected,
        notifications: notifications
      )
    end

    def server_app_definition
      @server_app_definition
    end

    def server_app_uuid
      definition = server_app_definition
      definition&.uuid.to_s
    end

    # There is no EltenLink account here to register against, so this
    # answers the uuid the application already declared rather than
    # inventing one that no server has heard of.
    def register_server_app!(**_options)
      server_app_uuid
    end
    alias register_server_app register_server_app!

    def update_server_schema!(**_options)
      true
    end

    def delete_server_app(_uuid = nil)
      false
    end

    # A background extension - Elten runs these outside the application's
    # own window. Recorded so `.start`/`.tick`/`.stop` can be declared
    # without raising; nothing is scheduled, because a bridge that ran an
    # application's background work while the application is not open is a
    # bridge doing something the user did not ask for.
    def extension(name, &block)
      @extensions ||= {}
      recorder = ExtensionRecorder.new(name)
      block&.call(recorder)
      @extensions[name.to_s] = recorder
    end

    def extensions
      @extensions ||= {}
    end

    # The lifetime registry, at class level as well: an application that
    # holds something from `self.init` has nowhere else to put it.
    def registry
      @registry ||= EltenRegistry.new
    end

    def manage(object)
      registry.manage(object)
    end

    def release(object, close: false)
      registry.release(object, close: close)
    end

    def register_quickaction(ident, label = nil, &block)
      @quickactions ||= {}
      @quickactions[ident.to_s] = { label: label, block: block }
      true
    end

    # Asked for at class level as well as on an instance.
    def server_table(name, _uuid = nil)
      @server_tables ||= {}
      @server_tables[name.to_s] ||= Programs::LocalTable.new(self, name)
    end

    def leaderboard(name, order: nil,
                    retry_delays: Programs::Leaderboard::DEFAULT_RETRY_DELAYS,
                    log_label: 'Leaderboard')
      Programs::Leaderboard.new(server_table(name), order: order,
                                retry_delays: retry_delays,
                                log_label: log_label)
    end

    def read_json(path, default: {})
      raw = File.exist?(path) ? File.read(path, encoding: 'UTF-8') : nil
      return default if raw.nil? || raw.empty?

      JSON.parse(raw)
    rescue StandardError
      default
    end

    def write_json(path, data)
      require 'fileutils'
      FileUtils.mkdir_p(File.dirname(path))
      File.write(path, JSON.pretty_generate(data), encoding: 'UTF-8')
      true
    rescue StandardError
      false
    end

    def quickactions
      @quickactions ||= {}
    end

    def map_notification(_notification)
      nil
    end

    def notification_received(_notification, _presentation)
      nil
    end
  end

  # What `extension(...) { |ext| ... }` is handed.
  class ExtensionRecorder
    attr_reader :name

    def initialize(name)
      @name = name.to_s
      @blocks = {}
    end

    %w[start stop tick settings every trigger].each do |hook|
      define_method(hook) do |*args, &block|
        (@blocks[hook] ||= []) << [args, block]
        self
      end
    end
  end

  # ----------------------------------------------------------- instance side
  def server_app_definition
    self.class.server_app_definition
  end

  def server_app_uuid
    self.class.server_app_uuid
  end

  def register_server_app!(**options)
    self.class.register_server_app!(**options)
  end

  def update_server_schema!(**options)
    self.class.update_server_schema!(**options)
  end

  def delete_server_app(uuid = nil)
    self.class.delete_server_app(uuid)
  end

  def register_quickaction(ident, label = nil, &block)
    self.class.register_quickaction(ident, label, &block)
  end

  # One named table. Local, and honest about it - see the note at the top.
  def server_table(name, _uuid = nil)
    @server_tables ||= {}
    @server_tables[name.to_s] ||= Programs::LocalTable.new(self, name)
  end

  def server_resources(_uuid = nil)
    []
  end

  def leaderboard(name, order: nil,
                  retry_delays: Programs::Leaderboard::DEFAULT_RETRY_DELAYS,
                  log_label: 'Leaderboard')
    Programs::Leaderboard.new(server_table(name), order: order,
                              retry_delays: retry_delays, log_label: log_label)
  end

  # Nowhere to send it: there is no EltenLink session here. Said out loud in
  # the log rather than silently dropped, so an application whose whole point
  # is notifying somebody does not look like it worked.
  def send_notification(_user, type: nil, metadata: {}, expires_in: 0)
    Log.info("notification #{type} not sent: this is Titan, not EltenLink")
    false
  end

  def notification_action(_action, _notification)
    nil
  end

  def live_sessions
    @live_sessions ||= LiveSessionsUnavailable.new
  end

  def communication
    nil
  end

  # Every method answers, and every answer says the same thing: there is no
  # session. An application that checks - and they are written to - degrades
  # instead of raising `NoMethodError` on its third line.
  class LiveSessionsUnavailable
    def available?
      false
    end

    def connect(*_args, **_options)
      nil
    end

    def create(*_args, **_options)
      nil
    end

    def on_invitation(*_args)
      nil
    end

    def method_missing(_name, *_args, **_options, &_block)
      nil
    end

    def respond_to_missing?(_name, _include_private = false)
      true
    end
  end
end
