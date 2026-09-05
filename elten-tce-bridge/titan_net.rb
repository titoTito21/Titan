# Titan-Net, as a client rather than as a page of text.
#
# Titan's Titan-Net actions come in two shapes, and this uses both for what
# each is good for: the RECORDS (`titannet.rooms`, `room_messages`,
# `conversation`, `topics`, `topic`, `mailbox`) build the lists - a row per
# room, per message, per topic - and the sentence-shaped ones do the writing
# (`send_room_message`, `post_topic`, `reply`, `send_mail`), because what
# comes back from those is one line saying whether it worked.
#
# It speaks as whoever Titan is signed in as. Nothing here asks for a
# password and nothing here holds one: the sign-in is the one Titan already
# has, which is also why the title says who that is - a client that is vague
# about whose account it is showing is a client nobody should trust.
#
# It does not poll. Every action Titan runs in-process runs on Titan's GUI
# thread, so a client refreshing itself every few seconds would make Titan's
# own interface stutter for as long as it was open. F5 reads again.

require "json"

class TitanNetClient
  def self.entries
    [
      # First, and it is the whole client: everything under it is a
      # shortcut into one of its tabs.
      [_("Titan-Net"), {"do" => "titannet", "screen" => "main"}],
      [_("Chat rooms"), {"do" => "titannet", "screen" => "rooms"}],
      [_("Who is online"), {"do" => "titannet", "screen" => "online"}],
      [_("Private messages"), {"do" => "titannet", "screen" => "private"}],
      [_("Forum"), {"do" => "titannet", "screen" => "forum"}],
      [_("Mail"), {"do" => "titannet", "screen" => "mail"}],
      [_("Groups"), {"do" => "titannet", "screen" => "groups"}],
      [_("Feedback Hub"), {"do" => "titannet", "screen" => "feedback"}],
      [_("App repository"), {"do" => "titannet", "screen" => "repository"}],
      [_("Announcements"), {"do" => "titannet", "screen" => "announcements"}],
      [_("What's new"), {"do" => "titannet", "screen" => "whats_new"}],
    ]
  end

  def initialize(bus)
    @bus = bus
    @me = nil
  end

  def open(screen = "")
    return if !TitanUI.require_tce(@bus)
    case screen
    when "main", ""  then main
    when "rooms"     then rooms
    when "online"    then online
    when "private"   then private_messages
    when "forum"     then forum
    when "mail"      then mail
    when "groups"    then list(_("Groups"), "groups", "groups") { |g| group_row(g) }
    when "feedback"      then feedback
    when "repository"    then repository
    when "announcements" then announcements
    when "whats_new" then page("whats_new", {}, _("What's new"))
    else main
    end
  end

  # One window with Titan-Net's own areas on the tab bar, which is how
  # Titan-Net looks in Titan.
  def main
    tabs = [
      [_("Rooms"), proc { rows("rooms", "rooms") { |r| room_row(r) } }],
      [_("Online"), proc { rows("online", "users") { |u| user_row(u) } }],
      [_("Forum"), proc { rows("topics", "topics") { |t| topic_row(t) } }],
      [_("Mail"), proc { rows("mailbox", "mail", {"folder" => "inbox"}) { |m| mail_row(m) } }],
      [_("Feedback Hub"), proc { rows("feedback", "items") { |i| feedback_row(i) } }],
      [_("App repository"), proc { rows("repository", "apps") { |a| app_row(a) } }],
      [_("Announcements"), proc { rows("announcements", "files") { |f| announcement_row(f) } }],
      [_("Groups"), proc { rows("groups", "groups") { |g| group_row(g) } }],
      [_("My account"), proc { account_rows }],
    ]
    screen = TitanUI::Screen.new(@bus, title, tabs, :on_open => method(:open_entry),
                                 :on_menu => method(:entry_menu))
    screen.open
  end

  # What Titan-Net's own window does to the PLACE rather than in it: making
  # a room, joining or leaving one, blocking somebody, the account's own
  # address. Each is on the context-menu key of the row it belongs to.
  def account_rows
    [[_("My address"), {"open" => "email"}],
     [_("Who I have blocked"), {"open" => "blocked"}],
     [_("Make a room..."), {"open" => "new_room"}],
     [_("Make a group..."), {"open" => "new_group"}],
     [_("Send a message to everybody..."), {"open" => "broadcast"}],
     [_("Is Titan-Net connected"), {"open" => "status"}]]
  end

  def entry_menu(value, label)
    return if !value.is_a?(Hash)
    case value["open"]
    when "room"         then room_menu(value["name"].to_s, label)
    when "conversation" then person_menu(value["name"].to_s, label)
    when "group"        then group_menu(value["id"].to_s, label)
    end
  end

  def room_menu(name, label)
    chosen = select_action([["join_room", _("Join it")],
                            ["leave_room", _("Leave it")],
                            ["delete_room", _("Delete it")]],
                           :header => label)
    return if chosen == nil
    if chosen == "delete_room"
      return if !confirm(_("Delete the room %s?") % name)
    end
    args = {"room" => name}
    if chosen == "join_room"
      password = input_text(_("Password (empty if it has none):"), :escapable => true)
      args["password"] = password.to_s if password != nil
    end
    answer = TitanUI.perform(@bus, "titannet", chosen, args, :title => label)
    alert(answer.text.to_s) if answer != nil
  end

  def person_menu(name, label)
    chosen = select_action([["write", _("Write to them")],
                            ["block", _("Block them")],
                            ["unblock", _("Unblock them")]],
                           :header => label)
    return if chosen == nil
    if chosen == "write"
      return conversation(name)
    end
    return if chosen == "block" && !confirm(_("Block %s?") % name)
    answer = TitanUI.perform(@bus, "titannet", chosen, {"username" => name},
                             :title => label)
    alert(answer.text.to_s) if answer != nil
  end

  def group_menu(id, label)
    chosen = select_action([["join_group_by_id", _("Join it")],
                            ["group_forums", _("Its forums")]],
                           :header => label)
    return if chosen == nil
    key = chosen == "group_forums" ? "group" : "group"
    answer = TitanUI.perform(@bus, "titannet", chosen, {key => id}, :title => label)
    TitanUI.tell(answer, label) if answer != nil
  end

  def title
    _("Titan-Net (%s)") % signed_in_as
  end

  def signed_in_as
    return @me if @me != nil
    answer = TitanUI.ask(@bus, "titannet", "whoami", {})
    name = ""
    if answer.ok?
      data = JSON.parse(answer.text) rescue nil
      name = data["username"].to_s if data.is_a?(Hash)
    end
    @me = name == "" ? _("not signed in") : name
  end

  # ------------------------------------------------------------------- rows
  # Every listing goes through here: ask Titan for the records, turn each
  # into [what the user hears, what pressing it does].
  def rows(action, key, args = {})
    answer = TitanUI.ask(@bus, "titannet", action, args, :title => _("Reading..."))
    if !answer.ok?
      @last_error = answer.text.to_s
      return [[answer.text.to_s, nil]]
    end
    data = JSON.parse(answer.text) rescue nil
    return [] if !data.is_a?(Hash)
    records = data[key]
    records = data.values.find { |value| value.is_a?(Array) } if !records.is_a?(Array)
    (records || []).map { |record| yield(record) }
  rescue Exception => e
    [["#{e.class}: #{e.message}", nil]]
  end

  def room_row(room)
    name = room["name"].to_s
    kind = room["type"].to_s
    locked = room["has_password"] == true ? _(", password") : ""
    ["#{name} (#{kind}#{locked})",
     {"open" => "room", "id" => room["id"], "name" => name}]
  end

  def user_row(user)
    name = (user["username"] || user["name"]).to_s
    [name, {"open" => "conversation", "name" => name}]
  end

  def topic_row(topic)
    title = topic["title"].to_s
    who = (topic["author"] || topic["username"] || "").to_s
    replies = topic["reply_count"] || topic["replies"] || 0
    ["#{title} - #{who} (#{replies})",
     {"open" => "topic", "id" => topic["id"], "title" => title}]
  end

  def mail_row(message)
    subject = (message["subject"] || _("(no subject)")).to_s
    who = (message["from"] || message["sender"] || message["from_addr"]).to_s
    unread = message["read"] == false ? _("unread, ") : ""
    ["#{subject} - #{who} (#{unread}#{message['date'] || message['created_at']})",
     {"open" => "mail", "id" => message["id"], "subject" => subject}]
  end

  def group_row(group)
    [group["name"].to_s, {"open" => "group", "id" => group["id"]}]
  end

  def feedback_row(item)
    kind = item["item_type"] || item["type"] || ""
    status = item["status"].to_s
    votes = item["votes"] || item["upvotes"] || 0
    ["#{item['title']} (#{kind}#{status == '' ? '' : ', ' + status}, #{votes})",
     {"open" => "feedback_item", "id" => item["id"], "title" => item["title"].to_s}]
  end

  def app_row(app)
    who = (app["author"] || app["username"] || "").to_s
    version = app["version"].to_s
    ["#{app['name']} #{version} - #{who}",
     {"open" => "repository_item", "id" => app["id"], "name" => app["name"].to_s}]
  end

  def announcement_row(file)
    name = file.is_a?(Hash) ? (file["name"] || file["filename"]).to_s : file.to_s
    [name, {"open" => "announcement", "name" => name}]
  end

  # ------------------------------------------------------------- the hub
  # The Feedback Hub as it is in Titan: what people asked for, what is
  # being worked on, and a way to add to it or vote for something.
  def feedback
    tabs = [[_("Everything"), proc { rows("feedback", "items") { |i| feedback_row(i) } }],
            [_("Ideas"), proc { rows("feedback", "items", {"kind" => "idea"}) { |i| feedback_row(i) } }],
            [_("Bugs"), proc { rows("feedback", "items", {"kind" => "bug"}) { |i| feedback_row(i) } }]]
    TitanUI::Screen.new(@bus, _("Feedback Hub"), tabs,
                        :on_open => method(:open_entry),
                        :on_menu => proc { |_value, _label| feedback_menu }).open
  end

  def feedback_menu
    chosen = select_action([["new", _("Write something new")]],
                           :header => _("Feedback Hub"))
    return if chosen == nil
    values = collect(_("Feedback Hub"), [["title", _("Title")],
                                         ["content", _("What do you want to say?")]])
    return if values == nil
    kind = selector([_("Feedback"), _("Idea"), _("Bug")],
                    :header => _("What kind is it?"), :cancel_index => -1)
    return if kind == nil || kind < 0
    values["kind"] = %w[feedback idea bug][kind]
    answer = TitanUI.perform(@bus, "titannet", "feedback_new", values,
                             :title => _("Feedback Hub"))
    alert(answer.text.to_s) if answer != nil
  end

  def repository
    TitanUI::Screen.new(@bus, _("App repository"),
                        [[_("Packages"), proc { rows("repository", "apps") { |a| app_row(a) } }]],
                        :on_open => method(:open_entry),
                        :on_menu => proc { |value, label| repository_menu(value, label) }).open
  end

  def repository_menu(value, label)
    return if !value.is_a?(Hash)
    chosen = select_action([["download", _("Download it")],
                            ["details", _("What it is")]],
                           :header => label)
    return if chosen == nil
    if chosen == "download"
      return if !confirm(_("Download %s?") % label)
      answer = TitanUI.perform(@bus, "titannet", "repository_download",
                               {"app" => value["id"].to_s}, :title => label)
      alert(answer.text.to_s) if answer != nil
    else
      page("repository_item", {"app" => value["id"].to_s}, label)
    end
  end

  def announcements
    TitanUI::Screen.new(@bus, _("Announcements"),
                        [[_("Announcements"), proc { rows("announcements", "files") { |f| announcement_row(f) } }]],
                        :on_open => method(:open_entry)).open
  end

  def open_entry(value, label)
    return if !value.is_a?(Hash)
    case value["open"]
    when "room"         then room(value["name"].to_s)
    when "conversation" then conversation(value["name"].to_s)
    when "topic"        then topic(value["id"].to_s, value["title"].to_s)
    when "mail"         then one_mail(value["id"].to_s, value["subject"].to_s)
    when "group"        then page("group_forums", {"group" => value["id"].to_s}, label)
    when "feedback_item" then feedback_item(value["id"].to_s, value["title"].to_s)
    when "repository_item" then page("repository_item", {"app" => value["id"].to_s}, label)
    when "announcement" then page("announcement", {"name" => value["name"].to_s}, label)
    when "email"
      answer = TitanUI.ask(@bus, "titannet", "account_email", {}, :title => label)
      display_text(answer.text.to_s, :header => label)
      address = ask_for(_("A new address? (empty to leave it)"))
      return if address == nil
      written = TitanUI.perform(@bus, "titannet", "account_email",
                                {"email" => address}, :title => label)
      alert(written.text.to_s) if written != nil
    when "blocked"  then page("blocked", {}, label)
    when "status"   then page("status", {}, label)
    when "new_room"
      values = collect(_("Make a room"), [["name", _("Name")],
                                          ["description", _("What it is for")]])
      return if values == nil
      answer = TitanUI.perform(@bus, "titannet", "create_room", values, :title => label)
      alert(answer.text.to_s) if answer != nil
    when "new_group"
      values = collect(_("Make a group"), [["name", _("Name")],
                                           ["description", _("What it is for")]])
      return if values == nil
      answer = TitanUI.perform(@bus, "titannet", "create_group", values, :title => label)
      alert(answer.text.to_s) if answer != nil
    when "broadcast"
      text = ask_for(_("What should everybody hear?"))
      return if text == nil
      return if !confirm(_("Send this to everybody on Titan-Net?"))
      answer = TitanUI.perform(@bus, "titannet", "broadcast", {"message" => text},
                               :title => label)
      alert(answer.text.to_s) if answer != nil
    end
  end

  # ------------------------------------------------------------------ rooms
  def rooms
    screen = TitanUI::Screen.new(@bus, title,
                                 [[_("Rooms"), proc { rows("rooms", "rooms") { |r| room_row(r) } }]],
                                 :on_open => method(:open_entry),
                                 :on_menu => method(:entry_menu))
    screen.open
  end

  # A room: what has been said in it, and a line to say something back.
  # Enter on a message reads the whole of it, because a row is one line and
  # a message is not.
  def room(name)
    conversation_screen(_("Room %s") % name,
                        proc { rows("room_messages", "messages", {"room" => name}) { |m| message_row(m) } },
                        proc { |text| TitanUI.perform(@bus, "titannet", "send_room_message",
                                                      {"room" => name, "message" => text},
                                                      :title => _("Sending...")) })
  end

  def conversation(name)
    conversation_screen(_("Conversation with %s") % name,
                        proc { rows("conversation", "messages", {"username" => name}) { |m| message_row(m) } },
                        proc { |text| TitanUI.perform(@bus, "titan", "send_message",
                                                      {"service" => "titan_net", "recipient" => name,
                                                       "message" => text},
                                                      :title => _("Sending...")) })
  end

  def message_row(message)
    who = (message["sender"] || message["username"] || message["from"] || "?").to_s
    body = (message["message"] || message["content"] || "").to_s
    when_ = (message["timestamp"] || message["created_at"] || "").to_s
    line = body.gsub("\n", " ")
    line = line[0, 120] + "..." if line.length > 120
    ["#{who}: #{line}", {"open" => "text", "text" => "#{who} (#{when_})\n\n#{body}"}]
  end

  # The shape both a room and a private conversation have: the messages, a
  # field to write in, and Enter on a row to read one in full.
  def conversation_screen(header, reader, sender)
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
      rows = reader.call
      list.options = rows.map { |row| row[0].to_s }
      list.header = header
      # The newest message is the one somebody wants to be on.
      list.index = [rows.size - 1, 0].max
    end

    list.on(:select) do
      index = list.index.to_i
      value = rows[index] != nil ? rows[index][1] : nil
      display_text(value["text"].to_s, :header => header) if value.is_a?(Hash) && value["text"]
    end
    send_button.on(:press) do
      text = entry.text.to_s
      if text.strip != ""
        answer = sender.call(text)
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

  # ------------------------------------------------------------------ forum
  def forum
    tabs = [[_("Topics"), proc { rows("topics", "topics") { |t| topic_row(t) } }]]
    screen = TitanUI::Screen.new(@bus, _("Titan-Net forum"), tabs,
                                 :on_open => method(:open_entry),
                                 :on_menu => proc { |_value, _label| forum_menu })
    screen.open
  end

  def forum_menu
    chosen = select_action([["post", _("Write a new topic")],
                            ["search", _("Search the forum")]],
                           :header => _("Forum"))
    return if chosen == nil
    case chosen
    when "post" then write("post_topic", _("New topic"),
                           [["title", _("Title")], ["content", _("Text")]])
    when "search"
      text = ask_for(_("What are you looking for?"))
      page("search_forum", {"query" => text}, _("Search results")) if text != nil
    end
  end

  # A topic and its replies as one page, with a reply field under it.
  def topic(id, title_text)
    answer = TitanUI.ask(@bus, "titannet", "topic", {"topic" => id},
                         :title => title_text)
    return alert(answer.text.to_s) if !answer.ok?
    data = JSON.parse(answer.text) rescue {}
    head = data.is_a?(Hash) ? (data["topic"] || {}) : {}
    parts = ["#{head['title']}",
             "#{head['author'] || head['username']} - #{head['created_at']}",
             "", head["content"].to_s]
    (data["replies"] || []).each do |reply|
      parts.push("", "---", "#{reply['author'] || reply['username']} - #{reply['created_at']}",
                 reply["content"].to_s)
    end
    text = parts.join("\n")
    reply = Button.new(_("Reply"))
    back = Button.new(_("Back"))
    body = EditBox.new(title_text,
                       :type => EditBox::Flags::ReadOnly | EditBox::Flags::MultiLine,
                       :text => text)
    form = Form.new([body, reply, back])
    form.cancel_button = back
    running = true
    back.on(:press) { running = false }
    reply.on(:press) do
      what = ask_for(_("Your reply:"))
      if what != nil
        answer = TitanUI.perform(@bus, "titannet", "reply",
                                 {"topic" => id, "text" => what},
                                 :title => _("Replying..."))
        alert(answer.text.to_s) if answer != nil
      end
    end
    form.focus
    while running
      loop_update
      form.update
    end
  end

  # ------------------------------------------------------------------- mail
  def mail
    tabs = [
      [_("Inbox"), proc { rows("mailbox", "mail", {"folder" => "inbox"}) { |m| mail_row(m) } }],
      [_("Unread"), proc { rows("mailbox", "mail", {"folder" => "unread"}) { |m| mail_row(m) } }],
      [_("Sent"), proc { rows("mailbox", "mail", {"folder" => "sent"}) { |m| mail_row(m) } }],
    ]
    screen = TitanUI::Screen.new(@bus, _("Titan Mail"), tabs,
                                 :on_open => method(:open_entry),
                                 :on_menu => proc { |_value, _label| mail_menu })
    screen.open
  end

  def mail_menu
    chosen = select_action([["write", _("Write a message")],
                            ["address", _("My address")]],
                           :header => _("Titan Mail"))
    return if chosen == nil
    case chosen
    when "write" then write("send_mail", _("New message"),
                            [["to", _("To")], ["subject", _("Subject")],
                             ["body", _("Message")]])
    when "address" then page("mail_address", {}, _("My address"))
    end
  end

  def one_mail(id, subject)
    answer = TitanUI.ask(@bus, "titannet", "mail", {"mail" => id}, :title => subject)
    return alert(answer.text.to_s) if !answer.ok?
    data = JSON.parse(answer.text) rescue {}
    message = data.is_a?(Hash) ? (data["mail"] || data["message"] || {}) : {}
    text = ["#{message['subject']}",
            "#{_('From')}: #{message['from'] || message['sender'] || message['from_addr']}",
            "#{_('Date')}: #{message['date'] || message['created_at']}",
            "", (message["body"] || message["content"]).to_s].join("\n")
    chosen = nil
    display_text(text, :header => subject)
    chosen = select_action([["reply", _("Reply")], ["delete", _("Delete")],
                            ["close", _("Close")]], :header => subject)
    case chosen
    when "reply"
      what = ask_for(_("Your reply:"))
      if what != nil
        answer = TitanUI.perform(@bus, "titannet", "reply_mail",
                                 {"message" => id, "body" => what},
                                 :title => _("Replying..."))
        alert(answer.text.to_s) if answer != nil
      end
    when "delete"
      return if !confirm(_("Delete this message?"))
      answer = TitanUI.perform(@bus, "titannet", "delete_mail", {"message" => id},
                               :title => _("Deleting..."))
      alert(answer.text.to_s) if answer != nil
    end
  end

  # One Feedback Hub item: what was said, and the two things one does with
  # it - vote for it, or answer it.
  def feedback_item(id, title_text)
    answer = TitanUI.ask(@bus, "titannet", "feedback_item", {"item" => id},
                         :title => title_text)
    return alert(answer.text.to_s) if !answer.ok?
    data = JSON.parse(answer.text) rescue {}
    item = data.is_a?(Hash) ? (data["item"] || data["feedback"] || {}) : {}
    text = ["#{item['title']}",
            "#{item['username'] || item['author']} - #{item['created_at']}",
            "#{_('Status')}: #{item['status']}",
            "", item["content"].to_s].join("\n")
    (item["comments"] || []).each do |comment|
      text += "\n\n---\n#{comment['username']}: #{comment['content']}"
    end
    display_text(text, :header => title_text)
    chosen = select_action([["vote", _("Vote for it")]], :header => title_text)
    return if chosen == nil
    voted = TitanUI.perform(@bus, "titannet", "feedback_upvote", {"item" => id},
                            :title => title_text)
    alert(voted.text.to_s) if voted != nil
  end

  # ------------------------------------------------------------------ other
  def online
    screen = TitanUI::Screen.new(@bus, title,
                                 [[_("Online"), proc { rows("online", "users") { |u| user_row(u) } }],
                                  [_("Everybody"), proc { rows("people", "users") { |u| user_row(u) } }]],
                                 :on_open => method(:open_entry),
                                 :on_menu => method(:entry_menu))
    screen.open
  end

  def private_messages
    who = ask_for(_("Whose conversation? Their username:"))
    conversation(who) if who != nil
  end

  def list(header, action, key)
    screen = TitanUI::Screen.new(@bus, header,
                                 [[header, proc { rows(action, key) { |record| yield(record) } }]],
                                 :on_open => method(:open_entry))
    screen.open
  end

  def page(action, args, header)
    answer = TitanUI.ask(@bus, "titannet", action, args, :title => header)
    text = answer.text.to_s
    text = _("Nothing came back.") if text.strip == ""
    display_text(text, :header => header)
  end

  def ask_for(prompt)
    text = input_text(prompt, :escapable => true)
    text == nil || text.to_s.strip == "" ? nil : text.to_s
  end

  def write(action, header, fields)
    boxes = fields.map { |name, label| [name, EditBox.new(label)] }
    ok = Button.new(_("Send"))
    cancel = Button.new(_("Cancel"))
    form = Form.new(boxes.map { |_name, box| box } + [ok, cancel])
    form.cancel_button = cancel
    form.accept_button = ok
    values = nil
    done = false
    ok.on(:press) do
      values = {}
      boxes.each { |name, box| values[name] = box.text.to_s }
      done = true
    end
    cancel.on(:press) { done = true }
    form.focus
    until done
      loop_update
      form.update
    end
    return if values == nil
    answer = TitanUI.perform(@bus, "titannet", action, values, :title => header)
    alert(answer.text.to_s) if answer != nil
  end
end
