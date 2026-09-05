# Elten's own notifications, in Titan's notification centre.
#
# The rest of this add-on carries Titan INTO Elten. This is the one thing
# that goes the other way, and it exists because the bridge is the only
# thing on the machine that is inside both: Elten keeps its notifications in
# its own process, Titan has a notification centre, a buffer system and an
# AI that can be asked "what have I missed", and neither knew anything about
# the other.
#
# So a notification Elten raises - a private message, a forum reply,
# somebody coming online - is put into Titan's notification centre as
# Titan's own are, with Titan's notification sound and Titan's reader. It is
# then in the Titan category of the buffer system and in front of the AI,
# with nothing else to write on either side.
#
# **Nothing here waits.** It runs on the extension tick, which is Elten's own
# main pump: `active_notifications` is the list Elten's OWN background
# service already keeps in memory, so reading it costs nothing and reaches
# no network, and sending is fire and forget on the bus's worker.

require "json"

class EltenNews
  # How often Elten's own list is looked at, in seconds. It is a read of a
  # local array, so this is about not repeating work rather than about cost.
  INTERVAL = 10.0

  # Titan shows who a notification is from, and this is who these are from.
  # Not translated: it is a name.
  SOURCE = "Elten".freeze

  # A first run must not empty Elten's whole backlog into Titan's
  # notification centre - what the user wants is what arrives from now on,
  # the same rule `TitanWatch` follows in the other direction.
  class << self
    attr_reader :sent

    def start(bus)
      @bus = bus
      @seen = nil
      @sent = 0
      @last_looked = 0.0
      @enabled = true
      @unavailable = false
      true
    end

    def stop
      @bus = nil
    end

    def enabled=(value)
      @enabled = (value == true)
    end

    def enabled?
      @enabled != false
    end

    # Called from the extension tick. Must return at once.
    def tick
      return if !enabled? || @unavailable
      # **Nothing about Elten leaves Elten unasked.** The question is put
      # at the top of the add-on's own window rather than here - a consent
      # dialog on the tick is one the user answers to get rid of - so the
      # only thing this does is respect the answer. Unanswered and refused
      # are both "do not share": what has not been agreed to is not
      # something to send once and apologise for.
      return if !TitanConsent.granted?
      return if @bus == nil || !@bus.connected?
      now = Process.clock_gettime(Process::CLOCK_MONOTONIC)
      return if now - @last_looked < INTERVAL
      @last_looked = now
      current = read_notifications
      # Elten with no notification service of its own - an older client, or
      # one signed out - is still Elten running, and Titan should be able
      # to say so.
      return report([]) if current == nil
      if @seen == nil
        # The first look is what there IS. Announcing it would be
        # announcing the past, in a notification centre, hours later.
        @seen = current.map { |item| item[:id] }
        return
      end
      fresh = current.reject { |item| @seen.include?(item[:id]) }
      @seen = (current.map { |item| item[:id] } + @seen).first(500)
      fresh.each { |item| send_one(item) }
      report(current)
      nil
    rescue Exception
      nil
    end

    # **What Titan is told about Elten, apart from the news.**
    # A notification is something to tell the user about NOW; this is the
    # snapshot Titan keeps so its AI can be asked "is Elten running", "who
    # am I signed in as there", "what is waiting in Elten" - questions
    # Titan cannot answer for itself, because it is not in that process.
    # Sent when it has changed, or every REPORT_EVERY seconds so a Titan
    # that restarted has something recent rather than nothing.
    REPORT_EVERY = 60.0

    def report(current)
      state = {"user" => signed_in_as, "name" => full_name,
               "moderator" => moderator?, "language" => elten_language,
               "version" => elten_version,
               "notifications" => current.map do |item|
                 {"text" => item[:text], "cat" => item[:cat]}
               end,
               "news" => counts_by_kind(current)}
      now = Process.clock_gettime(Process::CLOCK_MONOTONIC)
      digest = state.inspect
      return if digest == @reported && now - @reported_at.to_f < REPORT_EVERY
      @reported = digest
      @reported_at = now
      post("client.report", {"state" => state})
    rescue Exception
      nil
    end

    # What KIND of thing is waiting, counted - which is what somebody
    # asking "anything in Elten?" actually wants to hear, rather than one
    # number.
    def counts_by_kind(current)
      out = {"notifications" => current.size}
      current.each do |item|
        kind = item[:cat].to_s
        next if kind == ""
        out[kind] = out.fetch(kind, 0) + 1
      end
      out
    end

    def full_name
      return "" if !defined?(Session)
      Session.fullname.to_s
    rescue Exception
      ""
    end

    def moderator?
      return false if !defined?(Session)
      Session.moderator == true
    rescue Exception
      false
    end

    def elten_language
      return "" if !defined?(Configuration)
      Configuration.language.to_s
    rescue Exception
      ""
    end

    # ------------------------------------------------ what Titan may ASK
    # The reports above are what this side PUSHES; these are the same
    # things answered on demand, so Titan's AI can ask Elten a question
    # rather than read the last answer it was handed. They run on the bus
    # worker (see `TitanBus#serve`), so every one of them is a read of
    # state Elten's own background service already keeps - no network, no
    # waiting, and nothing that touches Elten's screen.
    #
    # **Consent is checked in each of them, not once at the door.** It can
    # be taken back at any moment, and an answer that was allowed a minute
    # ago is not an answer that is allowed now.
    def handlers
      {
        "status" => proc { |_args| answer_status },
        "notifications" => proc { |_args| answer_notifications },
        "news" => proc { |_args| answer_news },
      }
    end

    # One sentence, said the same way whichever of them was asked - so a
    # refusal reads as a refusal rather than as an empty Elten.
    def refusal
      "Elten has not been given permission to share its data with Titan. " \
      "The TCE bridge asks once, the first time it is opened, and the " \
      "answer is in its own settings."
    end

    def answer_status
      return refusal if !TitanConsent.granted?
      current = read_notifications
      {"running" => true, "user" => signed_in_as, "name" => full_name,
       "moderator" => moderator?, "language" => elten_language,
       "version" => elten_version,
       "notifications" => (current || []).size}
    end

    def answer_notifications
      return refusal if !TitanConsent.granted?
      current = read_notifications
      return {"notifications" => []} if current == nil
      {"notifications" => current.map do |item|
        {"text" => item[:text], "cat" => item[:cat]}
      end}
    end

    def answer_news
      return refusal if !TitanConsent.granted?
      {"news" => counts_by_kind(read_notifications || [])}
    end

    def signed_in_as
      return "" if !defined?(Session)
      Session.name.to_s
    rescue Exception
      ""
    end

    def elten_version
      return "" if !defined?(EltenAPI::ELTEN_API_VERSION)
      EltenAPI::ELTEN_API_VERSION.to_s
    rescue Exception
      ""
    end

    # [{id:, text:, cat:}] out of Elten's own service, or nil when this
    # Elten has no such service - an older client, or one signed out.
    def read_notifications
      return nil if !defined?(EltenAPI::NotificationService)
      rows = EltenAPI::NotificationService.active_notifications
      return nil if !rows.is_a?(Array)
      rows.map do |row|
        text = value_of(row, :alert)
        text = value_of(row, :notification) if text.to_s.strip == ""
        next if text.to_s.strip == ""
        {:id => value_of(row, :id).to_s,
         :text => text.to_s.strip,
         :cat => value_of(row, :cat).to_s}
      end.compact
    rescue Exception
      nil
    end

    # Elten's notification is a Struct in this client and may be a Hash in
    # another; a reader that only knows one of the two is a reader that
    # stops working at the next Elten.
    def value_of(row, key)
      return row[key] if row.is_a?(Hash) && row.key?(key)
      return row[key.to_s] if row.is_a?(Hash) && row.key?(key.to_s)
      return row.send(key) if row.respond_to?(key)
      nil
    end

    # **Nothing here goes through `TitanAPI`, and that is the whole point.**
    # `TitanAPI#call` wraps the bus in `Tasks.run` - a worker AND a progress
    # window - which is right for a screen the user is looking at and quite
    # wrong on the extension tick: it would put "Waiting for TCE..." on the
    # screen every ten seconds, for a thing the user never asked for. The
    # bus's own `call` posts to the worker and returns at once, and the
    # block runs over there with the answer.
    def send_one(item)
      post("notifications.add",
           {"app" => SOURCE, "title" => title_for(item[:cat]),
            "text" => item[:text], "announce" => true}) { @sent += 1 }
    rescue Exception
      nil
    end

    # One typed call, fire and forget. `block` runs on the bus worker when
    # it worked.
    def post(name, args, &block)
      request = JSON.generate({"call" => name.to_s, "args" => args})
      @bus.call("titan", "bridge", {"request" => request}) do |text|
        payload = JSON.parse(text.to_s) rescue nil
        if payload.is_a?(Hash) && payload["ok"] == true
          block.call if block
        elsif payload.is_a?(Hash) && payload["error"].to_s.include?("no bridge call")
          # A Titan older than this add-on. Stopping after the first
          # refusal is the whole of the right behaviour: asking every ten
          # seconds for something this Titan has not got is noise the user
          # cannot act on.
          @unavailable = true
        elsif text == nil
          # Titan is not there. Not a refusal - it will be tried again.
          nil
        end
      end
    rescue Exception
      nil
    end

    # What KIND of news it is, in Elten's own vocabulary, said in Elten's
    # language. A category this add-on does not know keeps Elten's word for
    # it rather than being dropped - a notification with no heading is
    # still a notification.
    CATEGORIES = {"message" => "New message", "messages" => "New message",
                  "forum" => "Forum", "followedforum" => "Forum",
                  "followedforumpost" => "Forum", "post" => "Forum",
                  "friend" => "Friends", "friends" => "Friends",
                  "online" => "Somebody is online",
                  "blog" => "Blog", "comment" => "Comment",
                  "program" => "Programs", "programs" => "Programs",
                  "update" => "Updates", "updates" => "Updates"}.freeze

    def title_for(cat)
      known = CATEGORIES[cat.to_s.downcase]
      known ? _(known) : cat.to_s
    end
  end
end
