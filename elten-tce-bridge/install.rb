# Puts the TCE bridge where Elten looks for its applications.
#
#     ruby install.rb            install (or update) it
#     ruby install.rb --remove   take it out again
#
# Elten loads an UNPACKED application: a folder holding `__app.rb` with the
# Elten3AppInfo manifest in it is a complete application, which is why this
# ships as source rather than as a signed `.eltenapp` - it needs no
# packaging step, no zstd and no signing key, and the folder can be edited
# in place while Elten is closed.
#
# An installed application is two things: the folder under `apps/src`, and
# a line in `apps/apps.json` saying it is loaded - `Programs.load_all` walks
# that registry, not the directory.

require "json"
require "fileutils"

APP_ID = "e6a514cc-bffc-4bf4-9a8d-adc8b8471558".freeze
FOLDER = "tce_bridge".freeze
SOURCES = %w[__app.rb titan_bus.rb titan_ui.rb titan_speech_output.rb
             titan_actions.rb titan_settings.rb titan_net.rb titan_im.rb
             titan_tools_ui.rb titan_widgets.rb titan_watch.rb titan_components.rb titan_macros.rb titan_cling.rb titan_ai.rb
             titan_shell.rb
             titan_areas.rb titan_console.rb].freeze
# Elten reads an unpacked application's catalogue straight off its folder
# (Programs::Runtime#language_data), so the translations ship as files.
CATALOGUES = %w[pl.mo].freeze

def elten_apps
  base = ENV["APPDATA"].to_s
  abort("APPDATA is not set - this installer is for Windows.") if base == ""
  path = File.join(base, "elten", "apps")
  abort("Elten is not installed here (#{path} is missing).") if !File.directory?(path)
  path
end

def registry_path(apps)
  File.join(apps, "apps.json")
end

def read_registry(apps)
  path = registry_path(apps)
  return {"apps" => {}} if !File.file?(path)
  data = JSON.parse(File.read(path)) rescue nil
  data.is_a?(Hash) && data["apps"].is_a?(Hash) ? data : {"apps" => {}}
end

def write_registry(apps, data)
  # Elten is reading this file at every start; a half-written one would
  # cost the user every application they have installed.
  path = registry_path(apps)
  temporary = path + ".tce_bridge.tmp"
  File.write(temporary, JSON.pretty_generate(data))
  FileUtils.mv(temporary, path)
end

# Copied with LINE ENDINGS NORMALISED, and that is not tidiness. Elten's
# manifest parser closes the block with /^\=end[ \t]+Elten3AppInfo[ \t]*$/:
# the opening marker allows \r?\n and the closing one does not, so one file
# checked out with CRLF is an application that reports "Unclosed
# Elten3AppInfo" and never loads. A Windows editor, a git checkout or a copy
# through a tool that rewrites text is all it takes.
def install_source(source, target)
  File.binwrite(target, File.binread(source).gsub(/\r\n/, "\n"))
end

def install
  apps = elten_apps
  target = File.join(apps, "src", FOLDER)
  FileUtils.mkdir_p(target)
  here = __dir__
  SOURCES.each do |name|
    source = File.join(here, name)
    abort("#{name} is missing next to the installer.") if !File.file?(source)
    install_source(source, File.join(target, name))
  end
  locale = File.join(target, "locale")
  FileUtils.mkdir_p(locale)
  CATALOGUES.each do |name|
    source = File.join(here, "locale", name)
    FileUtils.cp(source, File.join(locale, name)) if File.file?(source)
  end
  data = read_registry(apps)
  entry = data["apps"][FOLDER] || {}
  entry["uuid"] = APP_ID
  entry["loaded"] = true
  entry["installation_time"] ||= Time.now.to_i
  entry["installation_source"] = "local"
  entry["update_time"] = Time.now.to_i
  data["apps"][FOLDER] = entry
  write_registry(apps, data)
  puts "Installed into #{target}"
  puts "Start Elten. The bridge is in the main menu as 'TCE bridge', and"
  puts "Titan's voice is in Settings under the ordinary list of voices."
end

def remove
  apps = elten_apps
  data = read_registry(apps)
  data["apps"].delete(FOLDER)
  write_registry(apps, data)
  target = File.join(apps, "src", FOLDER)
  FileUtils.rm_rf(target) if File.directory?(target)
  puts "Removed #{target}"
  puts "If Titan's voice was the one Elten was speaking with, choose another"
  puts "in Elten's settings."
end

ARGV.include?("--remove") ? remove : install
