# -*- coding: utf-8 -*-
# The parts of Elten's PLATFORM an application reaches without ever
# thinking of them as the API: the clipboard, the window Elten runs in,
# the screen reader it talks to, the scene it goes back to, the TLS store
# its HTTP goes through, the notification groups on the main screen, the
# keyboard state a nested window clears. None of them are in
# `src/eapi/program.rb`, which is why the method lists read out of it did
# not find them - each was found by an installed application calling it:
#
#   Clipboard.set_data          freesound, tyflopodcast, youtube, spotify
#   EltenWindow.minimized?      the Game Room's widget, the MCP server
#   NVDA.check / braille        the Game Room's board
#   Scene_Main.new              Weather, the media catalogue (finalize)
#   EltenAPI::TLS               freesound, tyflopodcast (their own Net::HTTP)
#   NotificationGroups          tyflopodcast's news
#   KeyboardState               Spotify's nested windows
#   AudioInfo::Chapter          tyflopodcast's markers on a player
#   executeprocess              the FFMPEG encoders
#
# A name that is not there is a `NameError` inside somebody else's program,
# usually inside their own `rescue Exception`, where it becomes a feature
# quietly not working. Each of these is written against Elten's own
# definition (the file is named beside it) and answers what a Titan can
# honestly answer; what it cannot, it says rather than pretends.

require 'openssl'

# ------------------------------------------------------------- clipboard
# `platforms/windows/eapi/clipboard.rb`. Elten talks to user32 through
# Fiddle; here the clipboard is Titan's, through the bridge, so it is the
# same clipboard whichever platform the host is on and the Ruby process
# never has to own a window to use it.
class ClipboardError < StandardError; end unless defined?(ClipboardError)

class Clipboard
  TEXT = 1
  OEMTEXT = 7
  UNICODETEXT = 13
  HDROP = 15

  class << self
    def open; self; end
    def close; self; end

    def set_data(clip_data, _format = TEXT)
      text = clip_data.is_a?(Array) ? clip_data.join("\n") : clip_data.to_s
      EltenBridge.call('clipboard', { 'do' => 'set', 'text' => text })
      self
    rescue EltenBridge::Closed
      self
    end

    def text=(value)
      set_data(value)
    end

    def data(_format = TEXT)
      answer = EltenBridge.call('clipboard', { 'do' => 'get' })
      answer.is_a?(String) ? answer : ''
    rescue EltenBridge::Closed, EltenBridge::RemoteError
      ''
    end
    alias get_data data

    def text
      data(UNICODETEXT)
    end

    def files
      []
    end

    def empty
      set_data('')
    end
  end
end

# ----------------------------------------------------------- the window
# `platforms/windows/ri/desktopruntime.rb`'s `EltenWindow`. Elten is one
# window; an application here has a window of Titan's per screen, so the
# questions are answered about THAT: it is active while it has the
# keyboard, and Titan never puts it in a tray.
module EltenWindow
  class << self
    def active_or_child?(_hwnd = nil)
      answer = EltenBridge.call('window_state', {})
      answer.is_a?(Hash) ? answer['active'] != false : true
    rescue EltenBridge::Closed, EltenBridge::RemoteError
      true
    end

    def minimized?
      answer = EltenBridge.call('window_state', {})
      answer.is_a?(Hash) ? answer['minimized'] == true : false
    rescue EltenBridge::Closed, EltenBridge::RemoteError
      false
    end

    def window_thread?; true; end
    def tray_supported?; false; end
    def in_tray?; false; end
    def hwnd; 0; end
    def show(_command = nil); 0; end
    def hide; false; end
    def focus(_hwnd = nil); true; end
    def restore_from_tray; false; end
    def minimize_to_tray; false; end
    def post_window_action(_wait = false, &block); block&.call; end
    def foreground_window; 0; end
  end
end

# ----------------------------------------------------- the screen reader
# `platforms/windows/eapi/nvda.rb`. Elten drives NVDA over its own pipe;
# an application asks two things of it - is it there (`check`) and show
# this on the braille display. Titan has its own reader and its own
# braille, and speech here already goes to whichever reader is listening,
# so `check` is honest about there being no NVDA pipe and `braille` hands
# the text to Titan, which brailles it where it has a display.
class NVDA
  class << self
    def check
      false
    end

    def init; true; end
    def destroy; true; end
    def initialized?; false; end

    def speak(text, *_rest)
      Speech.speak(text.to_s) if defined?(Speech)
      true
    end

    def stop
      Speech.stop if defined?(Speech)
      true
    end

    def braille(text, *_rest)
      EltenBridge.notify('braille', { 'text' => text.to_s })
      nil
    rescue EltenBridge::Closed
      nil
    end

    def sleepmode; nil; end
    def get_speech(*_rest); nil; end
  end
end

# --------------------------------------------------------------- scenes
# `scenes/main.rb`. Elten's main screen: an application that is finished
# with itself puts one up (`$scene = Scene_Main.new`,
# `insert_scene(Scene_Main.new)`). There is no main screen of Elten's
# here - the application is closing back into Titan - so the scene is a
# thing that runs and does nothing, which is what "go back to the main
# screen" means when the main screen is the desktop the user is already on.
class Scene_Main
  def initialize(*_args, **_options); end
  def main; end
  def update; end
end

class Scene_Loading < Scene_Main; end

# ------------------------------------------------------------------ TLS
# `eapi/tls.rb`. Elten embeds its own CA bundle; an application that
# builds a `Net::HTTP` of its own asks for the store so its connection
# verifies the same way Elten's do. Ruby's own default store is what a
# Titan can honestly hand over, and it verifies.
module EltenAPI
  module TLS
    class Error < StandardError; end

    class << self
      def certificate_store
        @certificate_store ||= OpenSSL::SSL::SSLContext::DEFAULT_CERT_STORE
      end

      def client_context
        context = OpenSSL::SSL::SSLContext.new
        context.set_params(verify_mode: OpenSSL::SSL::VERIFY_PEER,
                           verify_hostname: true,
                           cert_store: certificate_store)
        context
      end

      def install!
        certificate_store
      end
    end
  end
end

# ---------------------------------------------------------- audio info
# `eapi/audio/sound.rb`'s `AudioInfo`. A player's chapter is one of these,
# and Tyflopodcast makes its own to mark a podcast's bookmarks on the
# player: `item = AudioInfo::Chapter.new; item.name = ...; item.time = ...`.
class AudioInfo
  class ID3Frame
    attr_accessor :id, :size, :encrypted, :compressed, :grouped, :group, :numvalue, :strvalue
    attr_reader :subframes

    def initialize
      @id = ''
      @size = 0
      @encrypted = false
      @compressed = false
      @grouped = false
      @group = 0
      @numvalue = 0
      @strvalue = ''
      @subframes = []
    end
  end

  class Chapter
    attr_accessor :id, :name, :time

    def initialize(id = nil, name = '', time = 0.0)
      @id = id
      @name = name
      @time = time
    end

    def to_s; @name.to_s; end
  end

  def initialize(channel = nil)
    @channel = channel
  end

  def tags_ogg; {}; end
  def tags_id3v2; {}; end
  def tags_id3v1; {}; end
  def tags; {}; end
  def chapters; []; end
  def title; ''; end
  def artist; ''; end
  def album; ''; end
end

# --------------------------------------------------- notification groups
# `eapi/notificationgroups.rb`. The main screen's notifications are
# GROUPS - one per thread, per blog, per program - and an application
# that announces something of its own makes a "virtual" group and keeps
# it there (Tyflopodcast: one per new podcast, restored on every tick so
# it survives the main screen being rebuilt). The module is what
# `Object.new.extend(NotificationGroups)` reads its labels from, and the
# struct is Elten's own field list, keyword for keyword.
module NotificationGroups
  NotificationGroup = Struct.new(:key, :cat, :label, :category, :date, :revoked, :ids, :payload,
                                 :payloads, :fallback_text, :event_count, :virtual, :action,
                                 :program_class, :app_notification, :presentation,
                                 keyword_init: true) do
    def virtual?; virtual == true; end
    def revoked?; revoked == true; end
  end

  NOTIFICATION_TYPE_ORDER = %w[message followedthread followedforum followedforumpost mention
                               forumthreadoffer forumpostreport forumpostreportresolved friend
                               birthday followedblog blogcomment followedblogpost blogfollower
                               blogmention groupinvitation mtr app program_updates update
                               other].freeze

  @groups = []
  @seen_at = {}
  @revoked = {}
  @mutex = Mutex.new

  class << self
    def default_notification_type_order
      NOTIFICATION_TYPE_ORDER.dup
    end

    def notification_type_key(cat)
      key = cat.to_s
      NOTIFICATION_TYPE_ORDER.include?(key) ? key : nil
    end

    def normalize_notification_type_order(order)
      values = order.is_a?(String) ? order.split(',') : Array(order)
      normalized = []
      values.each do |value|
        key = value.to_s
        normalized << key if NOTIFICATION_TYPE_ORDER.include?(key) && !normalized.include?(key)
      end
      normalized.concat(NOTIFICATION_TYPE_ORDER - normalized)
    end

    def virtual_notification_groups
      @mutex.synchronize { @groups.map(&:dup) }
    end

    # What arrives here is the whole list as the application wants it to
    # stand, and the difference from last time is what is NEWS: a group
    # with a key nobody has seen before is put into Titan's notification
    # centre once, the way its own alert would be.
    def store_virtual_notification_groups(groups)
      groups = Array(groups).select { |group| group.respond_to?(:key) }
      now = Time.now.to_i
      fresh = []
      changed = false
      helper = Object.new.extend(NotificationGroups)
      @mutex.synchronize do
        old_keys = @groups.map { |group| group.key.to_s }.sort
        new_keys = groups.map { |group| group.key.to_s }.sort
        changed = old_keys != new_keys
        groups.each do |group|
          key = group.key.to_s
          fresh << group unless @seen_at.key?(key)
          @seen_at[key] ||= now
          group.date = @seen_at[key] if group.respond_to?(:date=)
          group.revoked = @revoked[key] == true if group.respond_to?(:revoked=)
          group.label = helper.group_label(group) if group.respond_to?(:label=)
        end
        @groups = groups
      end
      fresh.each { |group| announce(group) }
      changed
    end

    def refresh_virtual_notifications(_updates)
      false
    end

    def clear_virtual_notifications
      store_virtual_notification_groups([])
    end

    def revoke_virtual_notification(key)
      @mutex.synchronize { @revoked[key.to_s] = true }
      true
    end

    def installed_program_update_payload
      []
    end

    private

    def announce(group)
      text = group.respond_to?(:fallback_text) ? group.fallback_text.to_s : ''
      text = group.label.to_s if text.empty? && group.respond_to?(:label)
      return if text.empty?

      EltenBuffers.push('notifications', text) if defined?(EltenBuffers)
    rescue StandardError
      nil
    end
  end

  def group_label(group)
    "#{group.category}: #{group_description(group)}"
  end

  def group_description(group)
    return group.fallback_text.to_s if group.respond_to?(:fallback_text) && !group.fallback_text.to_s.empty?

    payload = group.respond_to?(:payload) ? group.payload : nil
    return payload['title'].to_s if payload.is_a?(Hash) && payload['title']

    group.respond_to?(:key) ? group.key.to_s : ''
  end

  def category_label(cat)
    case cat.to_s
    when 'message' then p_('Notifications', 'Messages')
    when 'followedthread' then p_('Notifications', 'Followed threads')
    when 'followedforum', 'followedforumpost' then p_('Notifications', 'Followed forums')
    when 'mention' then p_('Notifications', 'Forum mentions')
    when 'forumthreadoffer' then p_('Notifications', 'Thread transfer offers')
    when 'forumpostreport' then p_('Notifications', 'Forum post reports')
    when 'forumpostreportresolved' then p_('Notifications', 'Forum post report results')
    when 'friend' then p_('Notifications', 'Contacts')
    when 'birthday' then p_('Notifications', 'Birthdays')
    when 'followedblog' then p_('Notifications', 'Followed blogs')
    when 'blogcomment' then p_('Notifications', 'Blog comments')
    when 'followedblogpost' then p_('Notifications', 'Followed blog posts')
    when 'blogfollower' then p_('Notifications', 'Blog followers')
    when 'blogmention' then p_('Notifications', 'Blog mentions')
    when 'groupinvitation' then p_('Notifications', 'Group invitations')
    when 'mtr' then p_('Notifications', 'Online monitors')
    when 'app' then p_('Notifications', 'Programs')
    when 'program_updates' then p_('Notifications', 'Program updates')
    when 'update' then p_('Notifications', 'Updates')
    else p_('Notifications', 'Other')
    end
  end

  def title_for(_cat, payload, count: 1, payloads: nil)
    payload = Array(payloads).first if payload.nil? && payloads
    return payload['title'].to_s if payload.is_a?(Hash) && payload['title']

    count.to_s
  end

  def update_notification(_updates); nil; end
  def program_updates_notification(_updates); nil; end
end

# ------------------------------------------------------- keyboard state
# `eapi/keyboard.rb`'s `KeyboardState`. Two of its calls are how a nested
# window (Spotify's) makes sure the key that closed it - Escape, still
# physically down - is not read again by the screen underneath:
# everything held is treated as released until it really comes up, and
# this frame's presses are forgotten. Both are questions about the frame,
# which is `EltenLoop`'s.
module EltenAPI
  module KeyboardState
    class << self
      def suppress_held_until_release
        EltenLoop.release_all
        true
      end

      def clear_current_frame
        EltenLoop.clear_frame
        true
      end

      def state_when_pressed(_key)
        nil
      end

      def held?(key)
        EltenLoop.key_held?(key)
      end

      def pressed?(key)
        EltenLoop.key_pressed?(key)
      end

      def active?
        true
      end

      def reset
        EltenLoop.release_all
        EltenLoop.clear_frame
        true
      end
    end
  end
end

module Kernel
  # `platforms/windows/eapi/childprocess.rb`. Run a command line and wait
  # for it, pumping the frame while it runs (`update`), giving up after
  # `tmax` seconds (0 waits for ever), answering -1 for a timeout and the
  # exit code otherwise. The FFMPEG encoders are the caller.
  def executeprocess(cmdline, _hide = false, tmax = 0, update = true, path = nil)
    process = ChildProc.new(cmdline.to_s, path: path.to_s.empty? ? nil : path.to_s, show_window: false)
    started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    until process.finished?
      update ? loop_update(0.05) : sleep(0.05)
      elapsed = Process.clock_gettime(Process::CLOCK_MONOTONIC) - started
      if tmax.to_f > 0 && elapsed > tmax.to_f
        process.terminate
        return -1
      end
    end
    process.exitstatus.to_i
  rescue StandardError => error
    Log.warning("executeprocess: #{error.class}: #{error.message}") if defined?(Log)
    -1
  end

  # `eapi/common/diagnostics.rb`. What Elten writes into a bug report; the
  # MCP server hands it to a tool. Titan's own facts stand in.
  def createdebuginfo
    require 'rbconfig'
    lines = ['[_Elten]', 'Runtime: Titan Elten API bridge',
             "Elten API: #{defined?(Programs::ELTEN_API_VERSION) ? Programs::ELTEN_API_VERSION : ''}",
             '', '[_System]',
             "Ruby: #{RUBY_VERSION} (#{RUBY_PLATFORM})",
             "OS: #{RbConfig::CONFIG['host_os']}",
             '']
    lines.join("\n")
  end

  # `eapi/documents.rb`. The licence, which this component also carries.
  def licensetext
    file = File.join(__dir__, '..', 'LICENSE')
    File.exist?(file) ? File.read(file, encoding: 'utf-8') : 'GNU General Public License, version 3.'
  rescue StandardError
    'GNU General Public License, version 3.'
  end

  # `eapi/core/runtime.rb`. There is no developer mode of Elten's to
  # restart into, and an application must not restart Titan.
  def restart_to_developer_mode
    false
  end

  # `ui/input.rb`. An application asks about an ACTION - `:player_start`,
  # `:player_end`, `:select_all` - and Elten's keyboard scheme says which
  # key that is on this machine. Answers the first action whose binding
  # is pressed this frame, or nil.
  def keyboard_action_pressed?(*actions)
    actions.flatten.each do |action|
      binding = EltenAPI::KeyboardScheme.binding(action)
      next if binding.nil?

      return action if keyboard_binding_pressed?(binding)
    end
    nil
  end

  def keyboard_binding_pressed?(binding, first: false)
    key, *requirements = Array(binding)
    shift_optional = requirements.delete(:shift_optional) != nil
    shift_required = requirements.delete(:shift) != nil
    pressed = first ? key_first_pressed?(EltenAPI::KeyboardScheme.key_name(key)) : EltenLoop.key_pressed?(EltenAPI::KeyboardScheme.key_name(key))
    return false unless pressed

    required = requirements.map(&:to_sym).sort
    active = %i[control option command].select { |modifier| modifier_held?(modifier) }.sort
    return false unless active == required
    return true if shift_optional

    raw_key_held?(:key_shift) == shift_required
  end
end

# ------------------------------------------------------------------ BASS
# Elten plays through BASS, and two applications reach past `Sound` into
# it: Spotify ends its push stream with
# `Bass::BASS_StreamPutData.call(channel, nil, Bass::BASS_STREAMPROC_END)`,
# and the media catalogue records a station to MP3 through BASSenc. There
# is no BASS here - the mixer is Titan's - so the module answers what can
# be answered (the end of a PCM stream goes to Titan's own sink) and says
# honestly that the encoder libraries are not loaded, which is the
# sentence the media catalogue already shows for that case
# ("The MP3 encoder is unavailable") rather than a `NameError` in the
# middle of its player.
module Bass
  require 'fiddle'
  BASS_ABI = defined?(Fiddle::Function::STDCALL) ? Fiddle::Function::STDCALL : Fiddle::Function::DEFAULT
  F_INT = Fiddle::TYPE_INT
  F_UINT = Fiddle::TYPE_INT
  F_PTR = Fiddle::TYPE_VOIDP
  F_FLOAT = Fiddle::TYPE_FLOAT
  F_DOUBLE = Fiddle::TYPE_DOUBLE
  BASS_STREAMPROC_END = 0x80000000
  BASS_UNICODE = 0x80000000
  BASS_ACTIVE_STOPPED = 0
  BASS_ACTIVE_PLAYING = 1
  BASS_ACTIVE_STALLED = 2
  BASS_ACTIVE_PAUSED = 3
  BASS = nil
  BASSENC = nil
  BASSENCMP3 = nil
  BASSENCOGG = nil
  BASSENCOPUS = nil
  BASSMIX = nil
  BASS_FX = nil

  # A callable standing in for a library function: it is `.call`ed with
  # BASS's own arguments and answers a BASS-shaped number.
  class Function
    def initialize(&block); @block = block; end
    def call(*arguments); @block.call(*arguments); end
  end

  BASS_StreamPutData = Function.new do |channel, _buffer, length|
    if (length.to_i & BASS_STREAMPROC_END) != 0
      EltenBridge.notify('pcm_end', { 'handle' => channel.to_i })
    end
    0
  end
  BASS_ErrorGetCode = Function.new { 0 }
  BASS_Encode_Stop = Function.new { |_encoder| 1 }
  BASS_ChannelIsActive = Function.new { |_channel| BASS_ACTIVE_STOPPED }
  BASS_ChannelGetTags = Function.new { |_channel, _tags| 0 }
  BASS_ChannelStop = Function.new { |_channel| 1 }

  def self.error_name
    'BASS_OK'
  end

  def self.loaded?
    false
  end
end

# --------------------------------------------------- notification service
# `eapi/notifications.rb`. Elten's own polls EltenLink for the account's
# notifications and keeps the server's clock; the Game Room reads the
# clock for its table timers (`server_time`), and its receipts read and
# revoke the active notifications - each guarded with `respond_to?`, so
# what is answered here is what can be: the server's time is asked of
# EltenLink when there is a session and is this machine's clock otherwise,
# and the notifications are those the account has, when Titan can reach it.
module EltenAPI
  module NotificationService
    class << self
      def start; @running = true; end
      def stop; @running = false; end
      def running?; @running != false; end
      def reset_feeds; nil; end
      def drain_events(_limit = 50); []; end

      def server_time
        answer = EltenLink.request('System', 'server_time')
        answer.is_a?(Numeric) ? answer.to_i : Time.now.to_i
      rescue StandardError
        Time.now.to_i
      end

      def active_notifications
        answer = EltenLink.request('Notifications', 'active')
        Array(answer).select { |row| row.is_a?(Hash) }.map { |row| EltenLink::Record.new(row) }
      rescue StandardError
        []
      end

      def synchronize_active_notifications(_notifications); false; end

      def revoke_active_notifications(ids = nil)
        EltenLink.request('Notifications', 'revoke', Array(ids).flatten.map(&:to_i))
        true
      rescue StandardError
        false
      end

      def refresh_active_notifications; nil; end
      def synchronize_runtime_state(_timeout = nil); nil; end
    end
  end

  # `eapi/quickactions.rb`. Elten's quick actions are the shortcuts on its
  # main screen; the Game Room prepends its own dispatcher onto
  # `QuickActions.singleton_class` and calls `super(key)`, so the module
  # and `hotkey_actions` must be there for that `super` to land.
  module QuickActions
    class QuickAction
      attr_accessor :action, :label, :params, :key, :show

      def initialize(action, label = '', params = [], key = 0, show = true)
        @action = action
        @label = label
        @params = params
        @key = key
        @show = show
      end

      def call
        @action.respond_to?(:call) ? @action.call(*Array(@params)) : nil
      end

      def detail; @label.to_s; end
    end

    EMPTY_HOTKEY_ACTIONS = [].freeze
    HOTKEY_KEYS = [1, 2, 3, -2, -3].freeze

    class << self
      def actions; @actions ||= []; end
      def load_actions; actions; end
      def hotkey_actions(_key); EMPTY_HOTKEY_ACTIONS; end
      def hotkey_keys; HOTKEY_KEYS; end
      def hotkey_label(key); key.to_s; end
      def register(action); actions << action; action; end
      def add(&block); (@addprocs ||= []) << block; nil; end
      def refresh; nil; end
    end
  end
end
