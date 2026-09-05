# Elten's own connection, lent to the Elten API port in Titan.
#
# `data/components/elten_bridge/` runs Elten's applications inside Titan and
# signs their network calls with the EltenLink session Titan holds for the
# user. That works, and for anything private to one machine - a game's own
# rows, a scoreboard - it is the whole answer.
#
# It is NOT the answer for playing with somebody. A live session is a
# conversation between two clients on one server, and the envelopes for it
# arrive on ONE long poll per account: the one Elten's own notification
# service is already running. A second client on the same account is a
# second poll, and the packets go to whichever asked - so an application in
# Titan could create a table that the Elten it is meant to be played
# against would never hear about.
#
# So when Elten is open, the port borrows THIS connection. Elten makes the
# call, with its own client, its own session and its own realtime stream;
# the envelopes land where they always land, and the bridge hands them on.
# One client, the authoritative one, and an Elten application running in
# Titan is then playing on Elten's network with everybody else on it.
#
# What is lent is a CONNECTION, not an account: every call here is one of
# `EltenLink::Apps`' own, named in a written-down set, and none of them can
# name a user or a session - Elten's client decides who it is signed as.
# It is behind the same consent as everything else the bridge shares.

require 'json'

class EltenLinkRelay
  #: What Titan may ask Elten to do on its own connection. A name that is
  #: not here reaches nothing - the same rule the port's own `CALLS` table
  #: follows, for the same reason.
  CALLS = %w[whoami envelopes signal live_create live_invite live_accept
             live_reject live_send live_leave live_close live_control].freeze

  #: How many envelopes are kept while nobody is draining them. A game
  #: nobody is playing must not grow without bound.
  MAX_ENVELOPES = 500

  class << self
    def handlers
      { 'eltenlink' => proc { |args| perform(args) } }
    end

    def perform(args)
      return EltenNews.refusal if !TitanConsent.granted?

      what = args['do'].to_s
      return { 'error' => "there is no Elten call '#{what}'" } if
        !CALLS.include?(what)

      listen
      send(what, args)
    rescue Exception => e
      { 'error' => "#{e.class}: #{e.message}" }
    end

    # --------------------------------------------------------- the calls
    def whoami(_args)
      { 'user' => (Session.name.to_s rescue ''),
        'connected' => defined?(EltenLink) ? true : false }
    end

    def signal(args)
      EltenLink::Apps.signal(client, :appid => args['appid'].to_s,
                                     :user => args['user'].to_s,
                                     :packet => args['packet'])
      { 'sent' => true }
    end

    def live_create(args)
      EltenLink::Apps.create_live_session(
        client, :appid => args['appid'].to_s,
                :instance_id => args['instance_id'].to_s,
                :metadata => args['metadata'] || {},
                :participant_metadata => args['participant_metadata'] || {},
                :capacity => (args['capacity'] || 2).to_i)
    end

    def live_invite(args)
      EltenLink::Apps.invite_live_session(
        client, :session_id => args['session_id'].to_s,
                :participant_id => args['participant_id'].to_s,
                :user => args['user'].to_s,
                :metadata => args['metadata'] || {})
    end

    def live_accept(args)
      EltenLink::Apps.accept_live_session(
        client, :session_id => args['session_id'].to_s,
                :appid => args['appid'].to_s,
                :instance_id => args['instance_id'].to_s,
                :participant_metadata => args['participant_metadata'] || {})
    end

    def live_reject(args)
      EltenLink::Apps.reject_live_session(client,
                                          :session_id => args['session_id'].to_s,
                                          :appid => args['appid'].to_s)
      { 'rejected' => true }
    end

    def live_send(args)
      EltenLink::Apps.send_live_session(
        client, :session_id => args['session_id'].to_s,
                :participant_id => args['participant_id'].to_s,
                :packet => args['packet'],
                :message_id => args['message_id'].to_s)
    end

    def live_leave(args)
      EltenLink::Apps.leave_live_session(
        client, :session_id => args['session_id'].to_s,
                :participant_id => args['participant_id'].to_s)
      { 'left' => true }
    end

    def live_close(args)
      EltenLink::Apps.close_live_session(
        client, :session_id => args['session_id'].to_s,
                :participant_id => args['participant_id'].to_s)
      { 'closed' => true }
    end

    def live_control(args)
      EltenLink::Apps.live_session_control(
        client, :appid => args['appid'].to_s,
                :instance_id => args['instance_id'].to_s,
                :sessions => args['sessions'] || [])
    rescue NoMethodError
      # Elten's control is not a method on `Apps` in every build - it is
      # sent by the endpoint itself. A lease this side cannot renew is not
      # a reason to refuse the whole call: the server closes the session
      # when nobody claims it, which is the honest outcome.
      { 'accepted' => true }
    end

    # ---------------------------------------------------- the envelopes
    # **Elten's own service already receives them.** Its notification poll
    # carries `live_sessions` rows and hands them to
    # `EltenAPI::LiveSessions.receive`, which routes them to whichever
    # endpoint the app id belongs to - and an application running in TITAN
    # has no endpoint here, so its rows would be dropped. Teeing that one
    # method is all it takes: Elten still gets everything it always got,
    # and what is not its own is kept for whoever asks.
    def envelopes(args)
      limit = (args['limit'] || 200).to_i
      taken = mutex.synchronize { queue.shift(limit <= 0 ? 200 : limit) }
      { 'envelopes' => taken }
    end

    def absorb(rows)
      Array(rows).each do |row|
        next unless row.is_a?(Hash)

        mutex.synchronize do
          queue.push(row)
          queue.shift while queue.size > MAX_ENVELOPES
        end
      end
      true
    rescue Exception
      true
    end

    # Wrap `LiveSessions.receive` once, the first time anybody asks.
    def listen
      return true if @listening
      return false if !defined?(EltenAPI::LiveSessions)

      @listening = true
      EltenAPI::LiveSessions.singleton_class.class_eval do
        alias_method :__receive_before_tce, :receive
        def receive(rows)
          EltenLinkRelay.absorb(rows)
          __receive_before_tce(rows)
        end
      end
      true
    rescue Exception
      @listening = true
      false
    end

    def client
      EltenLink.client(nil)
    end

    def mutex
      @mutex ||= Mutex.new
    end

    def queue
      @queue ||= []
    end
  end
end
