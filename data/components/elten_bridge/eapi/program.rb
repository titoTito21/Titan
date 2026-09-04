# frozen_string_literal: true

# `Program` - what every Elten application inherits from, and `Runner` - the
# loop the ones that are games are built on.
#
# Written against Elten's `docs/eltenapps.md`. The lifecycle is Elten's:
# `self.activate` at class registration, `self.init` on a worker, then
# `program_main` on the instance (or `main` for the older applications that
# call `finish` themselves), and `finalize` afterwards whatever happened.

# The registry that makes `manage` mean something: anything put in it is
# closed when the application ends, in the reverse of the order it arrived,
# and a failure to close one thing does not stop the next.
class EltenRegistry
  def initialize
    @held = []
  end

  def manage(object)
    @held << object unless @held.include?(object)
    object
  end

  def release(object, close: false)
    @held.delete(object)
    _close(object) if close
    object
  end

  def close_all
    while (object = @held.pop)
      _close(object)
    end
  end

  private

  def _close(object)
    object.close if object.respond_to?(:close)
  rescue StandardError => error
    Log.warning("closing #{object.class} failed: #{error.class}: #{error.message}")
  end
end

class Program
  class << self
    # Elten calls this synchronously at class registration, for short
    # class-level work. Applications override it or do not.
    def activate; end

    # ...and this on a worker, for state that must exist before the user is
    # let in. An exception here is logged and the application still starts,
    # which is Elten's own behaviour.
    def init; end

    def box?
      false
    end

    def native_box?
      false
    end
  end

  class << self
    # The application's own manifest, set once by the bridge before anything
    # is constructed. On the CLASS because an application's `initialize` is
    # its own and takes its own arguments - see `boot.rb`.
    attr_writer :manifest

    def manifest
      @manifest ||= {}
    end
  end

  # Deliberately NO `initialize`. An application is free to define its own,
  # with whatever parameters it likes, and most do; one here would either be
  # overridden (so its work would not happen - which is why everything this
  # class needs makes itself lazily) or would take arguments the application
  # did not mean to give.
  def manifest
    self.class.manifest
  end

  # ------------------------------------------------------------ lifecycle
  # What the bridge calls. `program_main` is the modern entry point and
  # `main` the older one; an application has one or the other, and one that
  # has neither is a manifest pointing at a class that does nothing.
  def run
    if respond_to?(:program_main)
      program_main
    elsif respond_to?(:main)
      main
    else
      # Not an error. `ffmpeg` registers five audio encoders and `mcp` is a
      # server; both do their whole job in `activate` and have no screen at
      # all, which is why their manifests say `menu: {hidden: true}`.
      # Refusing them would be refusing the plug-ins every other
      # application depends on.
      Log.info("#{self.class} has no screen of its own; it has registered "\
               'what it provides and finished')
    end
  ensure
    finalize
  end

  # Normal finalisation, and safe to call as often as an application likes -
  # the older API has `main` call it explicitly and then return, which would
  # otherwise close everything twice.
  def finish
    finalize
  end

  def finalize
    return if @finished == true

    @finished = true
    begin
      close
    rescue StandardError => error
      Log.error("#{self.class}#close raised: #{error.class}: #{error.message}")
    end
    close_sound_pool
    registry.close_all
  end

  # For an application to override.
  def close; end

  def finished?
    @finished
  end

  # -------------------------------------------------------------- registry
  # Lazily, and that is not tidiness: an application is free to define its
  # own `initialize` and plenty do, and one that does not call `super` never
  # runs the constructor here. Reading `@registry` then answered nil and
  # `finalize` died on `undefined method 'close_all' for nil` - at the very
  # end, after the application had run correctly, so what the user saw was a
  # program that worked and then reported a crash on its way out. Anything
  # the platform needs to have must be able to make itself.
  def registry
    @registry ||= EltenRegistry.new
  end

  def manage(object)
    registry.manage(object)
  end

  def release(object, close: false)
    registry.release(object, close: close)
  end

  # ----------------------------------------------------------- what it is
  def id
    manifest['id'].to_s
  end

  def name(language = nil)
    EltenBridge.call('app_name', { 'language' => language&.to_s })
  rescue EltenBridge::Closed
    raw_name
  end

  def raw_name
    manifest['name'].to_s
  end

  def description(language = nil)
    EltenBridge.call('app_description', { 'language' => language&.to_s })
  rescue EltenBridge::Closed
    raw_description
  end

  def raw_description
    manifest['description'].to_s
  end

  def version
    manifest['version'].to_s
  end

  def build_id
    manifest['build_id']
  end

  # The one that is running. Set by `boot.rb` the moment it is built, so
  # anything reaching for the application's own storage can find it -
  # `EltenLink::Apps.table` does, because some applications ask for their
  # server table through EltenLink rather than through the Program.
  class << self
    attr_accessor :current
  end

  def author
    manifest['author'].to_s
  end

  def main_language
    (manifest['main_language'] || 'unknown').to_s
  end

  def supported_languages
    Array(manifest['supported_languages']).map(&:to_s)
  end

  # ---------------------------------------------------------------- paths
  # Three roots, and they mean different things - Elten's own split, kept
  # because applications rely on it: assets are read-only and shipped, data
  # survives everything, cache may be gone at any moment.
  #
  # `data_path` is Elten's OWN `apps/data/<app>/`, not a directory of Titan's.
  # Somebody who plays a game in Elten and then opens it here finds their
  # saved game, because it is the same file. A bridge that kept a second copy
  # would be one that silently loses whichever half was written last.
  def asset_path(relative = '')
    resolve('asset', relative)
  end

  def data_path(relative = '')
    resolve('data', relative)
  end

  def cache_path(relative = '')
    resolve('cache', relative)
  end

  def resolve(kind, relative = '')
    EltenBridge.call('path', { 'kind' => kind, 'relative' => relative.to_s })
  end

  # ----------------------------------------------------------------- data
  def read_json(path, default: {})
    raw = read_text(path, default: nil)
    return default if raw.nil? || raw.empty?

    JSON.parse(raw)
  rescue JSON::ParserError => error
    Log.warning("#{path} is not valid JSON: #{error.message}")
    default
  end

  def write_json(path, data)
    write_text(path, JSON.pretty_generate(data))
  end

  # Read, change, write, with nobody else writing in between. Elten
  # guarantees it per resolved file and so does this: the lock lives on
  # Titan's side, which is the only place that can see every writer.
  def update_json(path, default: {})
    token = EltenBridge.call('lock', { 'path' => path.to_s })
    begin
      data = read_json(path, default: default)
      result = yield(data)
      write_json(path, data)
      result
    ensure
      EltenBridge.call('unlock', { 'token' => token })
    end
  end

  def read_text(path, default: '')
    return default unless File.exist?(path)

    File.read(path, encoding: 'UTF-8')
  rescue SystemCallError, IOError => error
    Log.warning("#{path} could not be read: #{error.message}")
    default
  end

  # Written to a temporary file and moved into place, so a crash halfway
  # through leaves the previous version rather than half of this one.
  def write_text(path, text)
    FileUtils.mkdir_p(File.dirname(path))
    temporary = "#{path}.#{Process.pid}.tmp"
    File.write(temporary, text.to_s, encoding: 'UTF-8')
    File.rename(temporary, path)
    true
  rescue SystemCallError, IOError => error
    Log.warning("#{path} could not be written: #{error.message}")
    begin
      File.delete(temporary) if temporary && File.exist?(temporary)
    rescue StandardError
      nil
    end
    false
  end

  def read_binary(path, default: ''.b)
    return default unless File.exist?(path)

    File.binread(path)
  rescue SystemCallError, IOError
    default
  end

  # ---------------------------------------------------------------- sound
  # `sound_asset` answers the resolved path or nil, and applications test it
  # before playing - Solitaire's whole audio layer is optional and asks first,
  # so this has to answer nil rather than raise for a sound that is not there.
  def sound_asset(name)
    EltenBridge.call('sound_asset', { 'name' => name.to_s })
  rescue EltenBridge::Closed
    nil
  end

  # Elten's own keywords, all of them. Purrposterous asks for its background
  # music with `create_sound_from_asset("nyancat", loop: true)` and wraps the
  # call in `rescue Exception` - so a signature that did not take `loop:`
  # did not raise where anybody could see it: the game logged one line and
  # played in complete silence. A keyword this bridge cannot act on
  # (`effect_buffer` is Elten's own DSP) is ACCEPTED and ignored, which is
  # the difference between a game with no reverb and a game with no sound.
  def create_sound_from_asset(name, sample: false, loop: false,
                              effect_buffer: nil, effect_buffer_seconds: nil,
                              **_ignored)
    handle = EltenBridge.call('sound_create',
                              { 'name' => name.to_s, 'loop' => !!loop })
    return nil if handle.nil?

    manage(EltenSound.new(handle, name.to_s, loop: !!loop))
  rescue EltenBridge::Closed
    nil
  end

  def play_sound_from_asset(name, volume: 1.0, sample: false, loop: false,
                            spatial: nil, interpolation: :bilinear,
                            effect_buffer: nil, effect_buffer_seconds: nil,
                            max_voices: 8, position: nil, **_ignored)
    handle = EltenBridge.call('sound_pool_play',
                              { 'name' => name.to_s, 'volume' => volume,
                                'max_voices' => max_voices,
                                'loop' => !!loop,
                                'position' => position || spatial })
    handle.nil? ? nil : handle
  rescue EltenBridge::Closed
    nil
  end

  def create_spatial_sound_from_asset(name, position: nil, sample: false,
                                      loop: false, interpolation: :bilinear,
                                      effect_buffer: nil,
                                      effect_buffer_seconds: nil, **_ignored)
    handle = EltenBridge.call('sound_create',
                              { 'name' => name.to_s, 'spatial' => true,
                                'loop' => !!loop,
                                'position' => position })
    return nil if handle.nil?

    sound = manage(EltenSound.new(handle, name.to_s, loop: !!loop))
    sound.spatialize(position: position, interpolation: interpolation) if sound
    sound
  rescue EltenBridge::Closed
    nil
  end

  # A place crosses the wire as Elten writes it - `[x, y, z]` in metres,
  # `{x:, y:, z:}`, or a bare number that is already a pan - and TITAN's
  # side turns it into a pan, an elevation and a distance gain
  # (`host._place`). Converting here was wrong twice over: it threw the
  # height and the distance away before anything could use them, and it
  # divided x by a fixed two, so Skeet - which hands over a pan it has
  # already worked out - could only ever reach half of the stereo image.

  def play_app_sound(name, **options)
    play_sound_from_asset(name, **options)
  end

  def close_sound_pool
    EltenBridge.call('sound_pool_close')
    nil
  rescue EltenBridge::Closed
    nil
  end

  def sound_pool
    self
  end

  # -------------------------------------------------------------- runtime
  def app
    self
  end

  def execution_backend
    'runtime'
  end

  def box?
    false
  end

  def native_box?
    false
  end
end

# --------------------------------------------------------------------------
# `Runner` is Elten's OWN, vendored unchanged - see `eapi/vendor/runner.rb`.
#
# It was written here first, and the rewrite kept finding the same thing: a
# game's timing is not a shape you can approximate. `phase:` decides whether
# an action fires as the key goes down, while it is held, or as it comes up;
# a dynamic timer reschedules itself off what its own block returned; a hold
# gesture is a small state machine. Guessing at any of those gives a game
# that runs and plays wrong, which is worse than one that does not start.
#
# Elten is GPL-3.0 and so is this component, so the honest thing is to use
# it. What Titan supplies underneath is the frame and five questions
# (`eapi/loop.rb`); everything above them is Elten's.

# `Tasks.run` - finite, cancellable background work with a progress window.
# The block is given something it can report progress to; Titan draws it.
module Tasks
  class Progress
    def initialize(token)
      @token = token
      @cancellation = CancellationToken.new
    end

    # Applications reach for the token through the progress object and then
    # hand it down into their own helpers - the media catalogue does it on
    # every fetch - so it has to be a real one rather than nil.
    attr_reader :cancellation

    alias cancellation_token cancellation

    def ui(text = nil, fraction = nil)
      EltenBridge.call('task_progress',
                       { 'token' => @token, 'text' => text&.to_s,
                         'fraction' => fraction })
    rescue EltenBridge::Closed
      nil
    end

    def cancelled?
      !!EltenBridge.call('task_cancelled', { 'token' => @token })
    rescue EltenBridge::Closed
      true
    end
  end

  # What a slow piece of work is handed so it can be stopped. Applications
  # rescue on it and pass it down into their own helpers, so it has to be a
  # real object with real state rather than a marker.
  class CancellationToken
    def initialize
      @mutex = Mutex.new
      @cancelled = false
      @reason = nil
    end

    def cancelled?
      @mutex.synchronize { @cancelled }
    end

    def reason
      @mutex.synchronize { @reason }
    end

    def cancel(reason = nil)
      @mutex.synchronize do
        @cancelled = true
        @reason = reason
      end
      self
    end

    def raise_if_cancelled!
      error = reason
      raise error if error

      self
    end

    def wait(timeout = nil)
      deadline = timeout.nil? ? nil : EltenBridge.now + timeout.to_f
      until cancelled?
        return false if deadline && EltenBridge.now >= deadline

        Kernel.sleep(0.05)
      end
      true
    end

    # `token.sleep(seconds)` - Elten's own, and PUBLIC on purpose: it is how
    # an application waits between retries and gives up the moment the user
    # cancels. Applications call it with an explicit receiver
    # (`cancellation_token.sleep(0.02)`), so inheriting `Kernel#sleep` -
    # which is private - answers
    # `private method 'sleep' called for an instance of CancellationToken`.
    def sleep(duration)
      raise_if_cancelled! if wait(duration)
      self
    end
  end

  # Raised out of a task the user cancelled, or one that ran out of time.
  # Applications rescue these by name (`rescue ::EltenAPI::Tasks::Cancelled`),
  # so they must exist even when nothing ever raises them.
  class Cancelled < StandardError; end
  class TimedOut < StandardError; end

  # The title arrives either way: `Tasks.run(_("Groups"))` and
  # `Tasks.run(title: _("Groups"))` are both written, and KlangoArchive uses
  # the keyword - which a positional-only signature refuses with
  # `ArgumentError: unknown keyword: :title` before the block ever runs.
  # Taking `**options` rather than naming both is what keeps them from
  # colliding on the same local name.
  def self.run(positional = nil, **options)
    title = options[:title] || positional
    cancellable = options.fetch(:cancellable, true)
    token = EltenBridge.call('task_begin',
                             { 'title' => title&.to_s,
                               'cancellable' => cancellable })
    begin
      # TWO values, which is Elten's own shape: applications write
      # `Tasks.run(label) { |progress, token| ... }` and hand the token
      # straight down into their own fetching code. Yielding only the
      # progress made every one of those calls pass nil as a cancellation
      # token and stop on `raise_if_cancelled!` for nil.
      progress = Progress.new(token)
      block_given? ? yield(progress, progress.cancellation) : nil
    ensure
      begin
        EltenBridge.call('task_end', { 'token' => token })
      rescue EltenBridge::Closed
        nil
      end
    end
  end
end
