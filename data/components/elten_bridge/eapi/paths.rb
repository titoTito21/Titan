# frozen_string_literal: true

# `EltenPath` and `Dirs` - where things are, in Elten's own words.
#
# `EltenPath` is pure string work and is Elten's exactly: forward slashes
# everywhere, because an application builds a path once and uses it on three
# operating systems. `Dirs` is the machine's own folders, which on Titan are
# Titan's - `Dirs.eltendata` is Elten's data directory when Elten is
# installed and the bridge's own when it is not, so an application that keeps
# something beside Elten's own files finds it either way.

module EltenPath
  module_function

  def normalize(path)
    path.to_s.tr('\\', '/')
  end

  def join(*parts)
    parts = parts.flatten.compact.map { |part| normalize(part) }
                 .reject { |part| part == '' }
    return '' if parts.empty?

    first = parts.shift
    rest = parts.map { |part| part.sub(%r{\A/+}, '') }
    File.join(first, *rest)
  end

  def with_separator(path)
    value = normalize(path)
    return value if value == '' || value.end_with?('/')

    value + '/'
  end

  def basename(path)
    File.basename(normalize(path))
  end

  def dirname(path)
    File.dirname(normalize(path))
  end

  def extname(path)
    value = normalize(path)
    extension = File.extname(value)
    return extension unless extension.empty?

    name = File.basename(value)
    name.match?(/\A\.[^.]+\z/) ? name : ''
  end

  def relative_from(path, root)
    value = normalize(path)
    prefix = with_separator(root)
    value.start_with?(prefix) ? value[prefix.length..-1].to_s : value
  end
end

module Dirs
  class << self
    # Asked of Titan, which is the side that knows where this machine keeps
    # things - and answered once, because an application that builds paths
    # in a loop should not make a round trip for each one.
    def known
      @known ||= begin
        answer = EltenBridge.call('dirs')
        answer.is_a?(Hash) ? answer : {}
      rescue EltenBridge::Closed
        {}
      end
    end

    def user; EltenPath.normalize(known['user'].to_s); end
    def appdata; EltenPath.normalize(known['appdata'].to_s); end
    def documents; EltenPath.normalize(known['documents'].to_s); end
    def desktop; EltenPath.normalize(known['desktop'].to_s); end
    def music; EltenPath.normalize(known['music'].to_s); end
    def tmp; EltenPath.normalize(known['tmp'].to_s); end
    def eltendata; EltenPath.normalize(known['eltendata'].to_s); end
    def apps; EltenPath.normalize(known['apps'].to_s); end
    def appsdata; EltenPath.normalize(known['appsdata'].to_s); end
    def soundthemes; EltenPath.normalize(known['soundthemes'].to_s); end
    def extras; EltenPath.normalize(known['extras'].to_s); end
    def temp; tmp; end
  end
end

module EltenSystemHelpers
  module_function

  # Every drive on this machine, as Elten's own answers it: "C:", "D:".
  # The file tree's root is built out of this, so a file manager with no
  # drives is one that can only ever see the folder it opened on.
  #
  # Asked of Windows through the same call Elten uses
  # (`GetLogicalDriveStrings`), and on anything else the root is the root.
  def logical_drives
    return @drives if defined?(@drives) && @drives

    @drives = if Programs.platform_os == 'windows'
      windows_drives
    else
      ['/'] + ['/media', '/mnt'].flat_map do |place|
        File.directory?(place) ? Dir.children(place).sort.map { |name| File.join(place, name) } : []
      end.select { |place| File.directory?(place) }
    end
  rescue StandardError
    @drives = []
  end

  def windows_drives
    require 'fiddle'
    require 'fiddle/import'
    unless defined?(@get_drives)
      kernel = Fiddle.dlopen('kernel32.dll')
      @get_drives = Fiddle::Function.new(
        kernel['GetLogicalDriveStringsW'],
        [Fiddle::TYPE_LONG, Fiddle::TYPE_VOIDP], Fiddle::TYPE_LONG
      )
    end
    buffer = "\0" * 2048
    length = @get_drives.call(buffer.bytesize / 2, buffer).to_i
    return [] if length <= 0

    text = buffer.byteslice(0, length * 2).to_s
                 .force_encoding(Encoding::UTF_16LE)
                 .encode(Encoding::UTF_8, invalid: :replace, undef: :replace)
    text.split("\0").map { |drive| drive.end_with?('\\') ? drive[0...-1] : drive }
        .reject(&:empty?)
  rescue StandardError
    ('A'..'Z').map { |letter| "#{letter}:" }.select { |drive| File.directory?("#{drive}/") }
  end

  def appdata_dir; Dirs.appdata; end
  def user_dir; Dirs.user; end
  def documents_dir; Dirs.documents; end
  def desktop_dir; Dirs.desktop; end
  def music_dir; Dirs.music; end
end


# `Programs.platform_*` - what machine this is, in Elten's own words. Youtube
# picks which yt-dlp and which Deno to fetch off `platform_target`, so it has
# to be the real answer for THIS machine and not a guess.
module Programs
  module_function

  def platform_os
    case RbConfig::CONFIG['host_os'].to_s.downcase
    when /mswin|mingw|cygwin/ then 'windows'
    when /darwin/ then 'osx'
    when /linux/ then 'linux'
    else 'unknown'
    end
  end

  def platform_target
    cpu = RbConfig::CONFIG['host_cpu'].to_s.downcase
    arch = if cpu =~ /arm|aarch64/
             'arm64'
           elsif cpu.include?('64')
             'x64'
           else
             'x86'
           end
    "#{platform_os}-#{arch}"
  rescue StandardError
    platform_os
  end

  # The family is the OS without the architecture - `windows`, `linux`,
  # `osx` - which is what an application checks when it only cares which
  # kind of machine it is on.
  def platform_family
    platform_os
  end

  def platform_arch
    platform_target.split('-').last.to_s
  end

  def platform_computer_name
    require 'socket'
    Socket.gethostname.to_s
  rescue StandardError
    ''
  end

  def box?; false; end
  def native_box?; false; end
  def native_box_available?; false; end
  def beta_version_creation_supported?; false; end
end

module ProgramSigning
  module_function

  # Nothing here is signed BY Titan, and an application must not be told it
  # is running in a developer build when it is not: Skeet skips offering a
  # score in developer mode, and answering true would silently disable it.
  def developer_mode?
    false
  end
end

module Programs
  ProgramSigning = ::ProgramSigning
end
