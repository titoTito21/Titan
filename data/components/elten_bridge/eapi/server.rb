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
  # **A server table that really is on the server.**
  #
  # `server_table("scores")` and `leaderboard("scores")` are rows in a
  # table belonging to the application's own uuid on EltenLink, written as
  # whoever is signed in - which is the whole point of them: a game's best
  # scores are everybody's. Here they were a JSON file beside the
  # application, so "Best scores" was a scoreboard with one player on it.
  #
  # Titan is already signed in to EltenLink through Titan IM, so that is
  # the session these use. What is kept from the old behaviour is the
  # local copy: a score is written HERE first and unconditionally, and
  # shared afterwards - a server that is not there, or a user who has not
  # signed in, costs a sentence and never a score. It is also what makes
  # `available?` an honest answer rather than an optimistic one.
  class ServerTable
    def initialize(program, name, uuid = nil)
      @program = program
      @name = name.to_s
      @uuid = (uuid || program.server_app_uuid).to_s
      @local = LocalTable.new(program, name)
    end

    attr_reader :name, :uuid

    # Whether the network half is there. Asked by every game before it
    # offers to share a score, and answered without raising.
    # Whether there is anywhere real to share a score. Asked by every game
    # before it offers to.
    #
    # Two places can be real: Elten itself for an UNPROTECTED table (that
    # is the genuine Elten leaderboard), and Titan-Net for a table Elten
    # will not take from Titan. So this stays true once Elten has refused
    # a protected table, because there is still the Titan-Net board to
    # share to - the game should still offer.
    def available?
      return false if @uuid.empty?
      return true if shared?

      !!EltenBridge.call('elten_app', { 'do' => 'signed_in' })
    rescue StandardError
      shared?
    end

    # Whether this table is being kept on Titan-Net rather than Elten -
    # because Elten refused it as protected, which Titan is not the signed
    # launcher to write.
    def shared?
      return true if @shared

      false
    end

    def shared_available?
      !!EltenBridge.call('elten_app', { 'do' => 'shared_available' })
    rescue StandardError
      false
    end

    def local
      @local
    end

    def insert(data)
      values = data.is_a?(Hash) ? data : { 'value' => data }
      row = @local.insert(values)

      # If Elten's own protected table has already turned Titan away, the
      # score goes to the Titan-Net board and not back to a door that is
      # shut.
      if @shared
        return share_insert(values) || row
      end

      begin
        remote = remote_call('insert', 'values' => stringify(values))
        row = remote if remote.is_a?(Hash)
      rescue StandardError => error
        if error.message.to_s.include?('PROTECTED')
          # Elten will not take a Titan-played score onto its own global
          # leaderboard, which is its right - so the score goes to
          # Titan's own shared board, where other Titan players of this
          # game will see it.
          @shared = true
          shared = share_insert(values)
          row = shared if shared
        else
          Log.warning("#{@name}: the row was kept locally only: #{error.message}")
        end
      end
      row
    end
    alias add insert

    # The scoreboard, best-effort, from wherever this game's is kept:
    # Elten for an unprotected table, Titan-Net for one Elten will not
    # share, and this machine's own copy when neither can be reached.
    def all(where: nil, order: nil, limit: nil, offset: nil)
      if @shared
        return share_select(where, order, limit, offset) ||
               @local.all(where: where, order: order, limit: limit, offset: offset.to_i)
      end

      begin
        rows = remote_call('select', 'where' => where, 'order' => order,
                                     'limit' => limit, 'offset' => offset)
        return rows if rows.is_a?(Array)
      rescue StandardError => error
        if error.message.to_s.include?('PROTECTED')
          @shared = true
          shared = share_select(where, order, limit, offset)
          return shared if shared
        else
          Log.warning("#{@name}: read locally: #{error.message}")
        end
      end
      @local.all(where: where, order: order, limit: limit, offset: offset.to_i)
    end
    alias select all

    def upsert(values)
      remote_call('upsert', 'values' => stringify(values))
    end

    def update(id, values)
      remote_call('update', 'id' => id.to_i, 'values' => stringify(values))
    end

    def delete(id = nil, where: nil)
      return @local.delete(where: where) if id.nil?

      remote_call('delete', 'id' => id.to_i)
    end

    def count(where: nil)
      all(where: where).size
    end

    private

    def remote_call(what, extra = {})
      raise 'this application has no server app uuid' if @uuid.empty?

      EltenBridge.call('elten_app', { 'do' => what, 'uuid' => @uuid,
                                      'table' => @name }.merge(extra))
    end

    # The Titan-Net board for this game - a real, shared scoreboard that
    # is Titan's, for the games Elten keeps to its own signed client.
    def share_insert(values)
      remote_call('shared_insert', 'values' => stringify(values))
    rescue StandardError => error
      Log.warning("#{@name}: the shared score was kept locally only: #{error.message}")
      nil
    end

    def share_select(where, order, limit, offset)
      rows = remote_call('shared_select', 'where' => where, 'order' => order,
                                          'limit' => limit, 'offset' => offset)
      rows.is_a?(Array) ? rows : nil
    rescue StandardError => error
      Log.warning("#{@name}: the shared board could not be read: #{error.message}")
      nil
    end

    # JSON on the wire, so a symbol key is a string key.
    def stringify(values)
      return values unless values.is_a?(Hash)

      values.each_with_object({}) { |(key, value), out| out[key.to_s] = value }
    end
  end

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
    # Tell EltenLink about this application and the tables it declared.
    #
    # An application that ships a `SERVER_TABLES` schema and calls
    # `server_app(uuid:, tables:)` expects the server to know about them
    # before a row is written; a game whose table was never declared gets
    # a refusal on its first score and reports "the score could not be
    # shared". It is done once per run, and a machine with nobody signed
    # in keeps the uuid the manifest named and says nothing.
    def register_server_app!(name: nil, data: nil, tables: nil,
                             tables_protected: false, notifications: false,
                             **_options)
      definition = server_app_definition
      uuid = server_app_uuid
      return uuid if @server_app_registered || uuid.to_s.empty?

      @server_app_registered = true
      EltenLink::Apps.update(
        nil, uuid,
        name: name || display_name,
        data: data,
        tables: tables || definition&.tables,
        tables_protected: tables_protected || definition&.protected?,
        notifications: notifications || definition&.notifications
      )
      uuid
    rescue StandardError => error
      Log.warning("the server app could not be declared: #{error.message}")
      server_app_uuid
    end
    alias register_server_app register_server_app!

    def update_server_schema!(**options)
      register_server_app!(**options)
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
      recorder.blocks_for('start').each { |_args, started| started&.call }
      start_extension_frames
      recorder
    end

    # One frame hook for every extension this application declared, so
    # the number of them does not depend on how many were declared.
    def start_extension_frames
      return if @extension_frames || !defined?(EltenLoop)

      owner = self
      @extension_frames = EltenLoop.every_frame do |now|
        owner.extensions.each_value { |recorder| recorder.run_ticks(now) }
      end
    end

    # Told to stop, on the way out - which is where the file manager
    # closes its playlist down.
    def stop_extensions(reason = :unload)
      extensions.each_value do |recorder|
        recorder.blocks_for('stop').each do |_args, block|
          begin
            block&.call(reason)
          rescue Exception => error
            Log.warning("extension stop failed: #{error.class}: #{error.message}")
          end
        end
      end
      EltenLoop.forget_frame_hook(@extension_frames) if @extension_frames && defined?(EltenLoop)
      @extension_frames = nil
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
    def server_table(name, uuid = nil)
      @server_tables ||= {}
      @server_tables[name.to_s] ||= Programs::ServerTable.new(self, name, uuid)
    end

    def leaderboard(name, order: nil,
                    retry_delays: Programs::Leaderboard::DEFAULT_RETRY_DELAYS,
                    log_label: 'Leaderboard')
      Programs::Leaderboard.new(server_table(name), order: order,
                                retry_delays: retry_delays,
                                log_label: log_label)
    end

    # **A name is a name in the application's own data folder, not a path
    # in whatever directory this process happens to be running in.** The
    # instance methods have always resolved it that way (`read_text` ->
    # `data_path`); these did not, so the file manager's `activate` -
    # which reads its playlists at CLASS level, before any instance
    # exists - wrote "playlists.json" beside Titan and read it back from
    # wherever Titan had been started, and a saved playlist was gone the
    # next time.
    def read_json(path, default: {})
      raw = read_text(path, default: nil)
      return default if raw.nil? || raw.empty?

      JSON.parse(raw)
    rescue StandardError
      default
    end

    def write_json(path, data)
      write_text(path, JSON.pretty_generate(data))
    end

    def update_json(path, default: {})
      data = read_json(path, default: default)
      result = yield(data)
      write_json(path, data)
      result
    end

    def read_text(path, default: '')
      full = File.absolute_path?(path.to_s) ? path.to_s : data_path(path.to_s)
      return default if full.nil? || !File.exist?(full)

      File.read(full, encoding: 'UTF-8')
    rescue StandardError
      default
    end

    def write_text(path, text)
      require 'fileutils'
      full = File.absolute_path?(path.to_s) ? path.to_s : data_path(path.to_s)
      return false if full.nil? || full.to_s.empty?

      FileUtils.mkdir_p(File.dirname(full))
      File.write(full, text.to_s, encoding: 'UTF-8')
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

    def blocks_for(hook)
      @blocks[hook.to_s] || []
    end

    # An extension's `tick` really ticks, while the application is open.
    #
    # The file manager's background playlist is one - `service.tick(interval:
    # 0.1) { @playlist_playback.tick }` - and with nothing calling it the
    # playlist advanced to its next track and stopped there for good.
    # Elten runs these whether the application is open or not; here they
    # run while it is, because a bridge doing an application's background
    # work after the user has closed it is a bridge doing something
    # nobody asked for.
    def run_ticks(now)
      blocks_for('tick').each do |args, block|
        next if block.nil?

        options = args.find { |value| value.is_a?(Hash) } || {}
        interval = (options[:interval] || options['interval']).to_f
        @last ||= {}
        key = block.object_id
        next if interval.positive? && @last[key] && now - @last[key] < interval

        @last[key] = now
        begin
          block.call
        rescue Exception => error
          Log.warning("extension #{@name}: #{error.class}: #{error.message}")
        end
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

  # One named table, on EltenLink and mirrored here - see `ServerTable`.
  def server_table(name, uuid = nil)
    self.class.server_table(name, uuid)
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
