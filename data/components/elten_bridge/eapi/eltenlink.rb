# frozen_string_literal: true

# `EltenLink` - the network, answered by the client Titan is already signed
# in with.
#
# Two different things have to be true here at once, and they are why this
# file looks the way it does.
#
# **Every name must resolve.** Applications reference `EltenLink::UserInfo`,
# `EltenLink::ForumThreadPage`, `EltenLink::BlogPostSummary` and sixty more
# as constants - in a `rescue`, in a type check, as a struct they build. A
# constant that is not there is `NameError` at LOAD time, which is an
# application that does not start at all rather than one that cannot reach
# the network. So the shapes below exist whether or not anything fills them.
#
# **What actually reaches the network is a short, explicit list.** It lives
# on Titan's side (`eltenkit/eltenlink.py`'s `CALLS`), it only ever reads,
# and anything not on it raises `EltenLink::Error` - which is exactly what
# these applications already rescue, 24 times across the installed ones. So
# an application asking for something Titan does not do behaves the way it
# would against a server that said no.
#
# The account is the user's own, from Titan IM. An application never sees a
# token, never sees a password, and cannot sign in as somebody else.

module EltenLink
  # What everything here raises, and what applications rescue.
  class Error < StandardError
    attr_reader :kind

    def initialize(message = '', kind = 'error')
      super(message)
      @kind = kind
    end
  end

  class NotAvailable < Error; end
  class AuthenticationError < Error; end

  # One call across to Titan, and back.
  def self.request(namespace, method, *arguments)
    EltenBridge.call('elten', { 'namespace' => namespace.to_s,
                                'method' => method.to_s,
                                'args' => arguments })
  rescue EltenBridge::RemoteError => error
    raise Error.new(error.message, error.kind)
  rescue EltenBridge::Closed
    raise Error.new('Titan has closed this application', 'closed')
  end

  # `EltenLink.client(program)` - applications pass it around and hand it to
  # `EltenLink::Apps.table(...)`. There is one session, so this is a token
  # standing for it rather than anything an application can take apart.
  def self.client(_program = nil)
    @client ||= Client.new
  end

  def self.signed_in?
    !!request('System', 'account')
  rescue Error
    false
  end

  class Client
    def to_s
      'EltenLink client (Titan)'
    end
  end

  # A namespace is a name and the methods called on it; the check of whether
  # a given one is implemented happens once, on Titan's side, so this stays
  # one definition rather than sixty near-identical ones.
  module Namespace
    def method_missing(name, *arguments, &_block)
      EltenLink.request(namespace_name, name, *arguments)
    end

    def respond_to_missing?(_name, _include_private = false)
      true
    end

    def namespace_name
      name.to_s.split('::').last
    end
  end

  %w[Users Profiles Messages Contacts Forum Blog Notes Polls Tasks
     Calendars Honors Monitors Notifications Feeds System Apps Attachments
     Accounts Activities Admins Auctions Authentication Bans Calls
     ConferenceResources Payments PremiumPackages].each do |group|
    const_set(group, Module.new { extend Namespace })
  end

  # ------------------------------------------------------------- the shapes
  # Open structures rather than fixed ones: what the server answers is a hash
  # and an application reads whichever keys it knows about, so a struct with
  # a fixed member list would refuse a field the server added last week.
  class Record
    def initialize(fields = {})
      @fields = {}
      (fields || {}).each { |key, value| @fields[key.to_s] = value }
    end

    def [](key)
      @fields[key.to_s]
    end

    def []=(key, value)
      @fields[key.to_s] = value
    end

    def to_h
      @fields.dup
    end

    def key?(key)
      @fields.key?(key.to_s)
    end

    def method_missing(name, *arguments)
      key = name.to_s
      if key.end_with?('=')
        @fields[key[0..-2]] = arguments.first
      elsif @fields.key?(key)
        @fields[key]
      elsif key.end_with?('?')
        !!@fields[key[0..-2]]
      end
    end

    def respond_to_missing?(_name, _include_private = false)
      true
    end
  end

  %w[UserInfo UserProfile UserProfileBirthdate UserStatus
     Message MessageConversation MessageConversationsList MessagesList
     MessageUser MessageUsersList
     ForumStructure ForumMember ForumSearchResult ForumGroupSize ForumTag
     ForumThreadPage ForumThreadStats ForumTrashPage ForumTrashThread
     ForumUserPost ForumUserPostsPage
     BlogItem BlogDetails BlogCategory BlogComment BlogFollower
     BlogLibraryEntry BlogManagedEntry BlogMention BlogPostDetails
     BlogPostFollow BlogPostsResult BlogPostSummary BlogReadEntry
     BlogReadResult BlogTag
     Calendar CalendarEvent CalendarInvitation CalendarShare
     Note Poll PollAnswer PollDetails PollResults
     Task TaskProject TaskProjectInvitation TaskProjectShare
     Honor HonorUser Notification BuildInfo
     ClientState ClientStateChat ClientStateCounts
     ClientStateProfile].each do |shape|
    const_set(shape, Class.new(Record))
  end
end


# `Session` - who is signed in. Elten's own
# (`src/eapi/structs.rb`), read directly by applications: the Game Room asks
# `Session.name` thirty times to know whose table it is looking at, and a
# constant that is not there is a `NameError` before the application has
# drawn anything.
#
# It answers with the account Titan already has - the EltenLink one saved in
# the encrypted `titan.IM`, the same one `EltenLink.*` uses - so an
# application sees the person actually using this desktop. **The token is
# never here.** `logged?` is what an application checks, and it can be true
# without any application ever having something to sign in WITH.
module Session
  class << self
    attr_writer :name, :gender, :fullname, :moderator, :greeting, :languages

    def name
      return @name unless @name.nil?

      @name = (EltenBridge.call('elten_whoami') || '').to_s
    rescue StandardError
      @name = ''
    end

    def logged?
      !name.to_s.empty?
    end

    # An application must never be handed a credential, whatever it asks.
    def token
      ''
    end

    def gender; @gender.to_s; end
    def fullname; @fullname.nil? ? name : @fullname.to_s; end
    def moderator; @moderator == true; end
    def greeting; @greeting.to_s; end
    def languages; @languages.to_s; end
    def feeds; @feeds ||= {}; end
    def feeds_clear; @feeds = {}; end
    def feeds_update; nil; end
    def feeds_updated?; false; end
    def notifications_update; nil; end
    def notifications_updated?; false; end
  end
end

# `Configuration` - the user's own preferences. Titan's, where Titan has an
# opinion, and Elten's default where it has not. Applications read these to
# decide how much to say of their own accord, and the answer here is
# "Titan's screen reader is doing that": `controlspresentation` is
# `:sound_and_voice` because a control here really is spoken AND cued.
module Configuration
  class << self
    def usepan; true; end
    def usebilinearhrtf; true; end
    def listtype; :list; end
    def controlspresentation; :sound_and_voice; end
    def contextmenubar; true; end
    def typingecho; :characters; end
    def linewrapping; true; end
    def roundupforms; true; end
    def language; (defined?(EltenGettext) ? EltenGettext.language : 'en').to_s; end
    def soundthemeactivation; true; end
    def autoplay; false; end
    def keyboardscheme; :windows; end
    def volume; 100; end
    def voicerate; 0; end
    def voicevolume; 100; end
    def voicepitch; 0; end

    # Anything else Elten has and Titan has no opinion about answers nil
    # rather than raising: an application reading a preference it will
    # then default is doing the right thing, and a `NoMethodError` there
    # is an application that stops over a setting.
    def method_missing(name, *arguments)
      return nil unless name.to_s =~ /\A[a-z_0-9]+=?\z/

      nil
    end

    def respond_to_missing?(name, include_private = false)
      name.to_s =~ /\A[a-z_0-9]+=?\z/ ? true : super
    end

    def to_h; {}; end
  end
end

module EltenAPI
  module Structs
    Session = ::Session
    Configuration = ::Configuration
  end
  Session = ::Session
  Configuration = ::Configuration
end


# `EltenLink::Apps` - an application's own storage ON the network.
#
# Elten gives a signed application a server-side table of its own
# (`server_app`, `server_table`) and the ELTEN Game Room is built entirely
# on them: a lobby, its tables, its invitations. Some applications reach
# them through `Program.server_table`, which this bridge already backs with
# a real table in the application's own data folder - and some reach
# `EltenLink::Apps.table(client, uuid, name)` DIRECTLY, which was not there
# at all, so the Game Room came up saying "the operation failed" before it
# had listed anything.
#
# Both routes now end at the same local table, which means the honest
# limit: an application's data is real, survives restarts and is shared
# with nothing. A lobby works; the other players are not in it. The
# alternative - publishing to somebody's EltenLink account because they
# opened an application - is the one thing this bridge does not do.
module EltenLink
  module Apps
    class << self
      def table(_client, _uuid, name)
        program = Program.current
        raise Error.new('this application is not running', 'unavailable') if program.nil?

        (@tables ||= {})[name.to_s] ||= Programs::LocalTable.new(program, name.to_s)
      end

      def resources(_client, _uuid)
        []
      end

      def delete(_client, _uuid)
        false
      end

      def register(*_arguments, **_options)
        true
      end
      alias create register
      alias update register
    end
  end

  # `EltenLink.client(program)` - what an application passes about. There
  # is nothing for it to hold: every call goes through the table above and
  # through `CALLS`, so this exists to be passed and not to be used.
  def self.client(_program = nil)
    @client ||= Object.new
  end
end
