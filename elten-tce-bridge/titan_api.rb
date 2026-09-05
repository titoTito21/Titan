# Titan's own doorway, from Elten.
#
# The bridge was built on Titan's ACTIONS, and actions are written for a
# model: they answer in prose, in the user's language, with argument names
# that differ from one add-on to the next, and a Titan that has not been
# restarted simply does not have the newest ones. Every one of those cost a
# live bug here - folder names where launchable names were needed, `level`
# where the action wanted `percent`, a shell state read out of a translated
# sentence, and "'Titan' has no action 'components'" reaching the user.
#
# `titan.bridge` is one action carrying a whole typed surface
# (`src/titan_core/bridge_api.py`): JSON in, JSON out, one shape for every
# answer, and a version. So there is exactly ONE thing a too-old Titan can
# be missing, and this can say so in a sentence somebody can act on.
#
# Actions are still here - `addons.*` inside that surface - because they are
# the only way to reach an add-on nobody has written a screen for.

require "json"

class TitanAPI
  # What this add-on was written against. Titan answers with its own.
  WANTED = 1

  Answer = Struct.new(:ok, :data, :error) do
    def ok?
      ok == true
    end

    def [](key)
      data.is_a?(Hash) ? data[key] : nil
    end
  end

  def initialize(bus)
    @bus = bus
    @api = nil
    @missing = false
  end

  # One call. Never raises; `answer.ok?` says whether there is data.
  def call(name, args = {}, title: nil)
    request = JSON.generate({"call" => name.to_s, "args" => args || {}})
    answer = TitanUI.ask(@bus, "titan", "bridge", {"request" => request},
                         :title => title)
    if !answer.ok?
      # An action that is not there is the ONE thing a too-old Titan can be
      # missing, and it is worth saying which it is.
      @missing = true if answer.text.to_s.include?("has no action")
      return Answer.new(false, nil, answer.text.to_s)
    end
    payload = JSON.parse(answer.text) rescue nil
    return Answer.new(false, nil, _("TCE answered something unreadable.")) if !payload.is_a?(Hash)
    @api = payload["api"].to_i if payload["api"]
    return Answer.new(true, payload["data"], nil) if payload["ok"] == true
    Answer.new(false, nil, payload["error"].to_s)
  rescue Exception => e
    Answer.new(false, nil, "#{e.class}: #{e.message}")
  end

  # Whether this Titan speaks the surface at all, asked once.
  def available?
    return false if @missing
    return @api.to_i > 0 if @api != nil
    call("hello").ok?
  end

  def api
    available? if @api == nil
    @api.to_i
  end

  # What to say when it does not. Naming the reason is the whole point:
  # "restart Titan" is something the user can do, "no action bridge" is not.
  def unavailable_message
    if @missing
      # One msgid on one line: a message split across two Ruby string
      # literals is looked up as the joined text, which is never what is in
      # the catalogue - it would have stayed English for ever.
      _("This TCE is older than the add-on. Restart Titan and it will have everything the bridge needs.")
    else
      _("TCE did not answer.")
    end
  end

  # The language ELTEN is in, as two letters. Titan writes an add-on's name
  # per language in its manifest and picks by the language IT runs in, so a
  # Polish Titan would hand "Menedzer Plikow" to an English Elten. Asking in
  # Elten's own language is what stops that.
  def language
    value = (Configuration.language.to_s rescue "")
    value = value.tr("_", "-").split("-").first.to_s.downcase
    value.size == 2 ? value : "en"
  end

  # Data or nil, for the callers that only want the list.
  def data(name, args = {}, title: nil)
    answer = call(name, args, :title => title)
    answer.ok? ? answer.data : nil
  end
end
