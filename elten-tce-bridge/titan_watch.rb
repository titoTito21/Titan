# Noticing that something arrived on Titan-Net.
#
# An extension stays loaded while Elten runs, even with no window of the
# add-on open, so this is where "you have two new messages" comes from. It
# runs on the extension's tick, which is Elten's own main pump, so the rule
# there is absolute: **return promptly and never wait for the network.**
#
# So the tick does two small things and nothing else. It posts an ASK to the
# bus - fire and forget, answered on the bus's own worker thread - and, if a
# previous answer arrived and said something is new, it says so. The
# speaking happens on the tick rather than in the bus callback on purpose:
# the callback is not Elten's thread, and speech belongs to Elten's thread.
#
# What counts as new is a count that went UP. A count that went down is
# somebody reading their messages, which is not news.

require "json"

class TitanWatch
  # How often Titan is asked. Titan runs every in-process action on its own
  # interface thread, so this is minutes rather than seconds - and it is
  # what the setting below can turn off entirely.
  # How often Titan is asked, in seconds. It is the DEFAULT: the user sets
  # it in Elten's own settings, in minutes, because minutes is what somebody
  # thinks in when they decide how often to be interrupted.
  INTERVAL = 180.0
  KEYS = %w[unread_messages unread_forum_topics new_apps app_updates unread_mail].freeze

  class << self
    attr_reader :news

    def start(bus)
      @bus = bus
      @seen = nil
      @pending = nil
      @news = []
      @last_asked = 0.0
      @enabled = true
      true
    end

    def stop
      @bus = nil
      @pending = nil
    end

    def enabled=(value)
      @enabled = (value == true)
    end

    def enabled?
      @enabled != false
    end

    def interval=(seconds)
      value = seconds.to_f
      @interval = value if value > 0
    end

    def interval
      (@interval || INTERVAL).to_f
    end

    # Called from the extension tick. Must return at once.
    def tick
      announce_pending
      return if !enabled? || @bus == nil || !@bus.connected?
      now = Process.clock_gettime(Process::CLOCK_MONOTONIC)
      return if now - @last_asked < interval
      @last_asked = now
      @bus.call("titannet", "news") { |text| absorb(text) }
      nil
    rescue Exception
      nil
    end

    # On the bus worker: work out what is new and park it. Nothing is said
    # from here.
    def absorb(text)
      counts = JSON.parse(text.to_s) rescue nil
      return if !counts.is_a?(Hash)
      counts = KEYS.each_with_object({}) { |key, out| out[key] = counts[key].to_i if counts.key?(key) }
      if @seen == nil
        # The first answer is what there IS, not what has arrived - saying
        # "you have four unread messages" the moment Elten starts would be
        # announcing the past.
        @seen = counts
        @news = describe(counts)
        return
      end
      grown = counts.select { |key, value| value > @seen[key].to_i }
      @seen = counts
      @news = describe(counts)
      if grown.size > 0
        @pending = describe(grown)
        @pending_keys = grown.keys
      end
    rescue Exception
      nil
    end

    def describe(counts)
      counts.map do |key, value|
        next if value.to_i <= 0
        case key
        when "unread_messages"     then _("%d unread messages") % value
        when "unread_mail"         then _("%d unread letters") % value
        when "unread_forum_topics" then _("%d unread topics") % value
        when "new_apps"            then _("%d new applications") % value
        when "app_updates"         then _("%d updates") % value
        end
      end.compact
    end

    def announce_pending
      return if @pending == nil || @pending.empty?
      lines = @pending
      keys = @pending_keys
      @pending = nil
      @pending_keys = nil
      # Titan plays a sound per kind of news before it says it; so does
      # this, with the same sounds out of the same theme.
      TitanSounds.for_news(keys.first) if keys.is_a?(Array) && !keys.empty?
      # Said without stopping whatever is being read: news is not urgent
      # enough to cut a sentence in half.
      speak(_("Titan-Net: %s") % lines.join(", "), :stop => false)
    rescue Exception
      nil
    end
  end
end
