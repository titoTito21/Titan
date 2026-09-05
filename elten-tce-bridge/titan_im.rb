# Titan IM, in Elten - a client, not a launcher.
#
# In Titan, "Titan IM" is a list of services and each one opens a real
# window: the conversations on one side, the messages in one, and a line to
# write in. That is what this is. The services Titan drives through its web
# engines - WhatsApp and Messenger - are read with `im.*`, which is
# capability-gated on the live page, so a service that is not signed in says
# so instead of showing an empty list. Titan-Net's own private messages are
# the same screen, and the installed Titan IM modules are listed and opened
# exactly as Titan's own view opens them.
#
# Nothing here signs in. Titan is signed in; this speaks through it.

require "json"

class TitanIM
  # The services Titan's own Titan IM view lists, in its order. Each is
  # marked with how Titan can reach it: the web engines answer with whole
  # conversations, Telegram answers with contacts and sending, and Titan-Net
  # and EltenLink have clients of their own.
  SERVICES = [
    ["telegram", "Telegram", :contacts],
    ["messenger", "Messenger", :chats],
    ["whatsapp", "WhatsApp", :chats],
    ["titan_net", "Titan-Net", :titannet],
    ["elten", "EltenLink", :elten],
  ].freeze
  WEB_SERVICES = [["whatsapp", "WhatsApp"], ["messenger", "Messenger"]].freeze

  def initialize(bus)
    @bus = bus
  end

  def open
    return if !TitanUI.require_tce(@bus)
    tabs = [[_("Services"), proc { services }]]
    SERVICES.each do |id, label, kind|
      next if kind != :chats
      tabs.push([label, proc { chats(id) }])
    end
    tabs.push([_("Titan-Net people"), proc { titan_net_people }])
    tabs.push([_("Modules"), proc { modules }])
    TitanUI::Screen.new(@bus, _("Titan IM"), tabs,
                        :on_open => method(:open_row),
                        :on_menu => method(:row_menu)).open
  end

  # The services, exactly as Titan's own Titan IM view lists them, plus the
  # installed modules underneath. This is what the main window's Titan IM
  # tab shows, so pressing Titan IM in Elten lands where it lands in Titan.
  def services
    rows = SERVICES.map do |id, label, kind|
      [label, {"open" => "service", "service" => id, "kind" => kind.to_s}]
    end
    rows + modules
  end

  def open_service(service, kind, label)
    case kind.to_s
    when "chats"
      TitanUI::Screen.new(@bus, label,
                          [[label, proc { chats(service) }]],
                          :on_open => method(:open_row),
                          :on_menu => method(:row_menu)).open
    when "contacts"    then contacts(service, label)
    when "titannet"
      # Titan-Net is a client with its own main screen, and choosing it
      # anywhere must land there. It used to open the list of who is online
      # - one corner of it - which reads as though Titan-Net were a contact
      # list.
      TitanNetClient.new(@bus).main
    when "elten"       then elten_conversations(label)
    end
  end

  # Telegram is reached through Titan's own messenger actions: Titan can
  # list who you can write to and send, but reading a Telegram conversation
  # belongs to its window in Titan, so this says that rather than showing an
  # empty list.
  def contacts(service, label)
    rows = proc do
      answer = TitanUI.ask(@bus, "titan", "list_im_contacts",
                           {"service" => service}, :title => label)
      if !answer.ok?
        [[answer.text.to_s, nil]]
      else
        lines = answer.text.to_s.split("\n").map { |line| line.strip.sub(/\A\d+\.\s*/, "") }
        lines = lines.reject(&:empty?)
        lines.map { |name| [name, {"open" => "write", "service" => service, "name" => name}] }
      end
    end
    TitanUI::Screen.new(@bus, label, [[label, rows]],
                        :on_open => method(:open_row)).open
  end

  def elten_conversations(label)
    rows = proc do
      answer = TitanUI.ask(@bus, "elten", "list_conversations", {}, :title => label)
      return [[answer.text.to_s, nil]] if !answer.ok?
      answer.text.to_s.split("\n").map { |line| line.strip }.reject(&:empty?).map do |line|
        name = line.sub(/\A\d+\.\s*/, "").split(" - ").first.to_s
        [line, {"open" => "elten_chat", "name" => name}]
      end
    end
    TitanUI::Screen.new(@bus, label, [[label, rows]],
                        :on_open => method(:open_row)).open
  end

  # ------------------------------------------------------------------- rows
  # A service that is not signed in answers in a sentence rather than with
  # chats, and that sentence is what the user needs to see - not an empty
  # list that looks like "you have no messages".
  def chats(service)
    answer = TitanUI.ask(@bus, "im", "list_chats", {"service" => service},
                         :title => _("Reading..."))
    return [[answer.text.to_s, nil]] if !answer.ok?
    lines = answer.text.to_s.split("\n").map { |line| line.strip }.reject(&:empty?)
    return [[_("No conversations."), nil]] if lines.empty?
    lines.map do |line|
      name = line.sub(/\A\d+\.\s*/, "").split(" - ").first.to_s
      [line, {"open" => "chat", "service" => service, "chat" => name}]
    end
  end

  def titan_net_people
    answer = TitanUI.ask(@bus, "titannet", "online", {}, :title => _("Reading..."))
    return [[answer.text.to_s, nil]] if !answer.ok?
    data = JSON.parse(answer.text) rescue nil
    users = data.is_a?(Hash) ? (data["users"] || data["online_users"] || []) : []
    rows = users.map do |user|
      name = (user["username"] || user["name"]).to_s
      label = user["full_name"].to_s == "" ? name : "#{name} - #{user['full_name']}"
      [label, {"open" => "titannet", "name" => name}]
    end
    rows.push([_("Somebody else..."), {"open" => "titannet_ask"}])
    rows
  end

  def modules
    answer = TitanUI.ask(@bus, "titan", "inventory", {"kind" => "im_module"},
                         :title => _("Reading Titan..."))
    names = []
    if answer.ok?
      data = JSON.parse(answer.text) rescue nil
      group = data.is_a?(Hash) ? (data["kinds"] || []).first : nil
      names = (group["entries"] || []).map(&:to_s) if group.is_a?(Hash)
    end
    names.map { |name| [name, {"open" => "module", "name" => name}] }
  end

  # ---------------------------------------------------------------- opening
  def open_row(value, label)
    return if !value.is_a?(Hash)
    case value["open"]
    when "service"
      open_service(value["service"].to_s, value["kind"].to_s, label)
    when "write"
      text = input_text(_("Message to %s:") % value["name"], :escapable => true)
      return if text == nil || text.to_s.strip == ""
      answer = TitanUI.perform(@bus, "titan", "send_message",
                               {"service" => value["service"], "recipient" => value["name"],
                                "message" => text.to_s}, :title => _("Sending..."))
      alert(answer.text.to_s) if answer != nil
    when "elten_chat"
      answer = TitanUI.ask(@bus, "elten", "read_conversation",
                           {"username" => value["name"]}, :title => label)
      display_text(answer.text.to_s, :header => label)
    when "chat"
      conversation(value["service"].to_s, value["chat"].to_s, label)
    when "titannet"
      TitanNetClient.new(@bus).conversation(value["name"].to_s)
    when "titannet_ask"
      who = input_text(_("Whose conversation? Their username:"), :escapable => true)
      TitanNetClient.new(@bus).conversation(who.to_s) if who != nil && who.to_s.strip != ""
    when "module"
      answer = TitanUI.perform(@bus, "titan", "launch", {"name" => value["name"]},
                               :title => label)
      alert(answer.text.to_s) if answer != nil
    end
  end

  # One conversation: what was said, and a line to say something back.
  # Enter on a message reads the whole of it, because a row is one line and
  # a message is not.
  def conversation(service, chat, header)
    list = ListBox.new([], :header => header)
    entry = EditBox.new(_("Write a message"))
    send_button = Button.new(_("Send"))
    back = Button.new(_("Back"))
    form = Form.new([list, entry, send_button, back])
    form.cancel_button = back
    form.accept_button = send_button
    running = true
    rows = []

    refresh = proc do
      answer = TitanUI.ask(@bus, "im", "read_chat",
                           {"service" => service, "chat" => chat},
                           :title => header)
      text = answer.text.to_s
      rows = text.split("\n").map { |line| line.strip }.reject(&:empty?)
      rows = [_("Nothing here yet.")] if rows.empty?
      list.options = rows
      list.header = header
      list.index = [rows.size - 1, 0].max
    end

    list.on(:select) do
      index = list.index.to_i
      display_text(rows[index].to_s, :header => header) if rows[index] != nil
    end
    send_button.on(:press) do
      text = entry.text.to_s
      if text.strip != ""
        answer = TitanUI.perform(@bus, "im", "send",
                                 {"service" => service, "chat" => chat,
                                  "text" => text}, :title => _("Sending..."))
        if answer != nil && answer.ok?
          entry.text = ""
          refresh.call
        elsif answer != nil
          alert(answer.text.to_s)
        end
      end
    end
    back.on(:press) { running = false }

    refresh.call
    form.focus
    while running
      loop_update
      form.update
      if key_pressed?(TitanUI::KEY_REFRESH)
        refresh.call
        speak(_("Refreshed."))
      end
    end
  end

  # The rest of what a conversation can do, on the context-menu key.
  def row_menu(value, label)
    return if !value.is_a?(Hash) || value["open"] != "chat"
    service = value["service"].to_s
    chat = value["chat"].to_s
    chosen = select_action([["search", _("Search this conversation")],
                            ["participants", _("Who is in it")],
                            ["mark_read", _("Mark as read")],
                            ["status", _("Is this service signed in")]],
                           :header => label)
    return if chosen == nil
    case chosen
    when "search"
      query = input_text(_("What are you looking for?"), :escapable => true)
      return if query == nil || query.to_s.strip == ""
      answer = TitanUI.ask(@bus, "im", "search",
                           {"service" => service, "chat" => chat,
                            "query" => query.to_s}, :title => label)
      display_text(answer.text.to_s, :header => label)
    when "participants"
      answer = TitanUI.ask(@bus, "im", "list_participants",
                           {"service" => service, "chat" => chat}, :title => label)
      display_text(answer.text.to_s, :header => label)
    when "mark_read"
      answer = TitanUI.perform(@bus, "im", "mark_read",
                               {"service" => service, "chat" => chat},
                               :title => label)
      alert(answer.text.to_s) if answer != nil
    when "status"
      answer = TitanUI.ask(@bus, "im", "status", {"service" => service},
                           :title => label)
      alert(answer.text.to_s)
    end
  end
end
