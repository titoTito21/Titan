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
