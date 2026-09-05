# frozen_string_literal: false

# The rest of `Program`, so an application written against Elten finds
# everything it reaches for.
#
# This exists because of what an Elten application DOES when a method is
# merely absent: `NoMethodError`, inside somebody else's program, usually
# inside their own `rescue Exception` where it becomes a feature quietly
# not working rather than an error anybody sees. Every name below is one
# Elten's own `src/eapi/program.rb` defines - the list was taken from it -
# and each answers what its name promises rather than raising.
#
# The two halves matter equally. Elten defines almost all of these at CLASS
# level as well as on an instance, and applications use both: the file
# manager's `activate` reads its playlists off the class before an
# instance exists, and `Scene_Programs` asks a class for its menu label.

class Program
  # -------------------------------------------------------- the manifest
  def app_uuid
    (manifest['id'] || manifest['uuid']).to_s
  end

  def elten_api_version
    (manifest['EltenAPIVersion'] || manifest['elten_api_version']).to_s
  end

  # A name or a description may be written once, or once per language.
  # Elten answers which languages it really has, so an application can
  # say so - and an application that asks and gets nothing shows its
  # untranslated name rather than an empty one.
  def name_languages
    localisation_languages('name')
  end

  def description_languages
    localisation_languages('description')
  end

  def localisation_languages(field)
    value = manifest[field]
    return Array(value.keys).map(&:to_s) if value.is_a?(Hash)

    localised = manifest["#{field}_localizations"] || manifest["#{field}s"]
    return Array(localised.keys).map(&:to_s) if localised.is_a?(Hash)

    [main_language].reject { |language| language == 'unknown' }
  end

  # What this application is called in a menu, and whether it belongs in
  # one at all. `ffmpeg` and `mcp` say `menu: {hidden: true}` because they
  # are plug-ins that give every other application something; listing them
  # offers the user a row that opens, works for a fraction of a second and
  # closes.
  def menu_entry
    entry = manifest['menu']
    entry.is_a?(Hash) ? entry : {}
  end

  def menu_label
    label = menu_entry['label']
    label.to_s.empty? ? name.to_s : label.to_s
  end

  def hidden?
    menu_entry['hidden'] == true
  end

  def user_menu_options
    Array(manifest['user_menu'])
  end

  def app_file(file = '')
    asset_path(file.to_s)
  end

  def app_cache(file = '')
    cache_path(file.to_s)
  end

  # The certificate the package was signed with, as Titan read it. An
  # application asks so it can say who built it; there is nothing secret
  # in it - it is the public half, shipped in front of the payload.
  def appsignature
    EltenBridge.call('app_signature') || {}
  rescue StandardError
    {}
  end

  # ------------------------------------------------------- required assets
  # A manifest may declare what the application cannot run without -
  # AudioMemory names thirty-five sounds. Elten checks them, and an
  # application that asks is entitled to a real answer rather than an
  # optimistic one.
  def required_assets
    declared = manifest['required_assets']
    return {} unless declared.is_a?(Hash)

    declared.each_with_object({}) do |(kind, names), found|
      found[kind.to_s] = Array(names).map(&:to_s)
    end
  end

  def missing_required_assets
    required_assets.each_with_object({}) do |(kind, names), missing|
      absent = names.reject { |name| asset_present?(kind, name) }
      missing[kind] = absent unless absent.empty?
    end
  end

  def required_assets_available?
    missing_required_assets.empty?
  end

  def validate_required_assets!
    missing = missing_required_assets
    return true if missing.empty?

    listed = missing.map { |kind, names| "#{kind}: #{names.join(', ')}" }.join('; ')
    raise Programs::ProgramError, "This application is missing assets - #{listed}"
  end

  def asset_present?(kind, name)
    return !sound_asset_path(name).to_s.empty? if kind.to_s == 'sounds'

    path = asset_path(name.to_s)
    !path.to_s.empty? && File.exist?(path)
  rescue StandardError
    false
  end

  # ------------------------------------------------------------- the sound
  # Where a named sound really is. Elten looks it up in the package's own
  # `Audio/` with any of the extensions it might have been shipped with,
  # which is why an application names "border" and not "Audio/border.mp3".
  SOUND_EXTENSIONS = %w[.ogg .mp3 .wav .opus .flac .m4a].freeze
  SOUND_FOLDERS = ['Audio', 'audio', 'sounds', 'Sounds', ''].freeze

  def sound_asset_path(name)
    text = name.to_s
    return '' if text.empty?

    candidates = []
    if File.extname(text).empty?
      SOUND_FOLDERS.each do |folder|
        SOUND_EXTENSIONS.each do |extension|
          candidates << (folder.empty? ? "#{text}#{extension}" : "#{folder}/#{text}#{extension}")
        end
      end
    else
      SOUND_FOLDERS.each do |folder|
        candidates << (folder.empty? ? text : "#{folder}/#{text}")
      end
    end
    candidates.each do |relative|
      path = asset_path(relative)
      return path if path.to_s != '' && File.file?(path)
    end
    ''
  rescue StandardError
    ''
  end

  def sound_asset_data(name)
    path = sound_asset_path(name)
    return ''.b if path.to_s.empty?

    File.binread(path)
  rescue StandardError
    ''.b
  end

  # ------------------------------------------------------------- lifetime
  def managed_resources
    registry.respond_to?(:objects) ? registry.objects : []
  end

  def close_managed_resources
    registry.close_all
    true
  rescue StandardError
    false
  end

  # `on(:event) { }` - an application listening to itself. Recorded and
  # answered; nothing here fires one that Elten would not.
  def on(event, &block)
    (@program_events ||= {})[event.to_sym] ||= []
    @program_events[event.to_sym] << block if block
    self
  end

  def program_events
    @program_events ||= {}
  end

  def emit(event, *arguments)
    Array(program_events[event.to_sym]).each { |block| block.call(*arguments) }
    self
  end

  # An application asking to be over. Elten's own is an exception the
  # runner catches, which is what makes `ensure` blocks run on the way
  # out - a game closing its sounds, a file manager stopping a playlist.
  def exit(status = 0)
    raise SystemExit.new(status)
  end

  # ---------------------------------------------------------- the network
  def server_resources(_uuid = nil)
    []
  end

  def update_server_app(uuid = nil, **options)
    self.class.update_server_app(uuid, **options)
  end

  def send_notification(user, type:, metadata: {}, expires_in: 0)
    self.class.send_notification(user, type: type, metadata: metadata,
                                 expires_in: expires_in)
  end

  # `signal` is how two copies of one application talk to each other
  # through EltenLink. There is no relay here, so it answers honestly -
  # false, and `signaled` is never called - rather than pretending to
  # have delivered something.
  def signal(_user, _packet)
    false
  end

  def signaled(_user = nil, _packet = nil)
    nil
  end

  def live_sessions
    nil
  end

  def communication
    nil
  end

  def get_configuration
    self.class.get_configuration
  end

  def set_configuration(values)
    self.class.set_configuration(values)
  end

  def notification_action(_action, _notification)
    nil
  end

  def write_binary(path, data)
    full = data_path(path.to_s)
    require 'fileutils'
    FileUtils.mkdir_p(File.dirname(full))
    File.binwrite(full, data.to_s)
    true
  rescue StandardError => error
    Log.warning("#{path} could not be written: #{error.message}")
    false
  end

  # ------------------------------------------------- and all of it at class
  # level, because Elten defines it there too and applications use both.
  #
  # Delegated to the running instance where there is one, so a class
  # method and an instance method are the same answer rather than two that
  # can drift; a class asked before anything is constructed makes a
  # throwaway instance, which is what its methods read the manifest off.
  class << self
    def current_or_sample
      Program.current.is_a?(self) ? Program.current : (@sample ||= allocate)
    end

    DELEGATED = %i[
      app_file app_cache app_uuid appsignature author build_id
      description_languages elten_api_version execution_backend box?
      native_box? hidden? main_language managed_resources menu_label
      missing_required_assets name_languages play_app_sound
      play_sound_from_asset raw_description raw_name read_binary
      required_assets required_assets_available? send_notification
      server_resources sound_asset sound_asset_data sound_asset_path
      sound_pool close_sound_pool close_managed_resources
      create_sound_from_asset create_spatial_sound_from_asset
      supported_languages user_menu_options validate_required_assets!
      write_binary
    ].freeze

    DELEGATED.each do |name|
      define_method(name) do |*arguments, **options, &block|
        target = current_or_sample
        if options.empty?
          target.public_send(name, *arguments, &block)
        else
          target.public_send(name, *arguments, **options, &block)
        end
      end
    end

    # `on` at class level is Elten's own place for an application to
    # listen to itself before it is constructed.
    def on(event, &block)
      (@program_events ||= {})[event.to_sym] ||= []
      @program_events[event.to_sym] << block if block
      self
    end

    def program_events
      @program_events ||= {}
    end

    # The manifest's `configuration` block, and whatever the user has
    # since changed - which is where Elten keeps an application's own
    # options when it does not put up a settings form of its own.
    def get_configuration
      read_json('configuration.json', default: {})
    end

    def set_configuration(values)
      write_json('configuration.json', values.is_a?(Hash) ? values : {})
    end

    def update_server_app(uuid = nil, **options)
      EltenLink::Apps.update(nil, (uuid || server_app_uuid).to_s, **options)
    rescue StandardError => error
      Log.warning("updating the app failed: #{error.message}")
      false
    end

    def send_notification(user, type:, metadata: {}, expires_in: 0)
      EltenBridge.call('elten_app',
                       { 'do' => 'notify', 'uuid' => server_app_uuid,
                         'user' => user.to_s, 'type' => type.to_s,
                         'metadata' => metadata, 'expires_in' => expires_in.to_i })
    rescue StandardError => error
      Log.warning("the notification was not sent: #{error.message}")
      false
    end
  end
end
