# frozen_string_literal: true

# The controls an Elten application builds its OWN screens out of - not just
# the three stock dialogs in `eapi.rb`, but `ListBox`, `EditBox`, `Button`
# and `CheckBox` gathered into a `Form`, which is how the real applications
# installed on this machine build their country lists, station lists, player
# screens and settings screens. Elten's own versions of these are an
# internal single-threaded polling loop with no window at all; this file is
# Titan's OWN implementation of the same PUBLIC surface - the constructor
# keywords and the `.on(:event) { }` callbacks an application actually
# writes, matched against `src/ui/controls/*.rb` and `src/ui/form.rb` in
# Elten's own repository, never its code.
#
# Every control is, underneath, a real wx widget in a real Titan window
# (`eltenkit/ui.py`'s `WxUI`). What changes is that Elten's own polling
# loop (`form.update` called every frame) is replaced by ordinary events
# arriving over the bridge - `Form#wait` reads them the same way `Runner`
# reads key events, and a handler is called exactly once per thing that
# really happened rather than once per frame it happened to still be true.

# Every form that is on the screen right now, by the id Titan gave it.
#
# There are two event loops in this API - `Form#wait` and `Runner#run` - and
# either may be the one running when the user clicks something. The file
# manager is the case that proves it: it builds a `FilesTree`, shows it, and
# then drives a `Runner`, so a click on the tree arrives while `Runner` is
# the loop. A control event therefore has to be routable from anywhere,
# which means one registry rather than each loop knowing its own controls.
module EltenForms
  @open = {}

  class << self
    def register(form_id, form)
      @open[form_id] = form
      EltenLoop.surface_changed if defined?(EltenLoop)
    end

    def forget(form_id)
      @open.delete(form_id)
      EltenLoop.surface_changed if defined?(EltenLoop)
    end

    # How many are showing. The frame asks, to decide whether this
    # application has a window with the keyboard at all.
    def count
      @open.size
    end

    # True when the event was about a control somebody is showing.
    def dispatch(message)
      return false unless message.is_a?(Hash) && message['event'] == 'control'

      form = @open[message['form']]
      return false if form.nil?

      form.dispatch_event(message)
      true
    end
  end
end

# One control: what it asked Titan to build, and the handlers an application
# attached to it with `.on`.
class EltenControl
  attr_accessor :control_id
  attr_writer :form

  def initialize(kind, spec = {})
    @kind = kind
    @spec = spec
    @handlers = {}
  end

  # `.on(:press) { ... }`, `.on(:key_left) { |*args| ... }` - Elten's own
  # shape. A control may have more than one handler for the same event, and
  # each fires in the order it was attached.
  def on(event, &block)
    (@handlers[event.to_sym] ||= []) << block
    self
  end

  def trigger(event, *args)
    Array(@handlers[event.to_sym]).each do |block|
      block.call(*args)
    end
  end

  # Two of the properties below are not only remembered - they decide
  # whether the control makes a sound as the cursor moves through it, and
  # Titan's side is what plays that. AudioMemory sets `grid.silent = true`
  # because the game itself sounds every square; cueing over that would be
  # two sounds for one move. So they travel with the control.
  SOUND_PROPERTIES = %w[silent border_sound speech quiet].freeze

  def to_spec
    $stderr.puts("TOSPEC #{@kind} props=#{properties.inspect}") if ENV['ELTEN_SPEC_DEBUG']
    spec = @spec.merge(kind: @kind.to_s)
    SOUND_PROPERTIES.each do |key|
      spec[key.to_sym] = properties[key] if properties.key?(key)
    end
    spec
  end

  # Elten's controls carry a long tail of properties about how much they say
  # of themselves - `speech=`, `silent=`, `autosayoption=`, and more per
  # control. On Titan's side that is the screen reader's business rather
  # than the control's, so they are REMEMBERED and answered rather than
  # acted on. Answering is the point: a control missing one is an
  # application that stops, and stopping an application over a property
  # about announcements is the worst possible trade.
  def method_missing(name, *arguments, &block)
    key = name.to_s
    if key.end_with?('=') && arguments.size == 1
      name = key[0..-2]
      properties[name] = arguments.first
      push(name.to_sym => arguments.first) if SOUND_PROPERTIES.include?(name)
      return arguments.first
    end
    return properties[key] if properties.key?(key)

    super
  end

  def respond_to_missing?(name, include_private = false)
    key = name.to_s
    key.end_with?('=') || properties.key?(key) || super
  end

  def properties
    @properties ||= {}
  end

  # ------------------------------------------------- Elten's `FormBase`
  # Every control has these, because in Elten they are on the base class
  # every control inherits from - a context menu bound to a row, a tip, a
  # header. KlangoArchive binds a context menu to each of its tables, so a
  # control without `bind_context` is an application that stops on its
  # first screen.
  attr_accessor :header

  def bind_context(header = '', &block)
    @contexts ||= []
    @contexts << [block, header]
    self
  end

  def hascontext
    !(@contexts || []).empty?
  end

  # Build the context menu and open it - what Shift+F10 would do. Titan
  # shows it as the same list any other menu is.
  def context(menu = nil, _submenu = true)
    return if (@contexts || []).empty?

    built = menu || Menu.new(@header.to_s)
    @contexts.each { |block, _header| block.call(built) }
    built.open if menu.nil?
    built
  end

  def add_tip(tip)
    @customtips ||= []
    @customtips << tip
    self
  end

  def get_tips
    (@customtips || []) + tips
  end

  def tips
    []
  end

  def params
    @params ||= {}
  end

  # Elten's controls each carry these. They are about how much the control
  # says of its own accord, which on Titan's side is the screen reader's
  # business rather than the control's - so they are remembered and answered
  # and change nothing, which is different from being absent: a control
  # without `silent=` is an application that stops.
  # A real method, so it wins over `method_missing` - which means it has
  # to do `method_missing`'s job as well: record it AND tell the control
  # on Titan's side, because whether the cursor makes a sound as it moves
  # is decided there. AudioMemory sets this because the game already
  # sounds every square, and a board that cued over that was two sounds
  # for one move.
  def silent=(value)
    @silent = !!value
    properties['silent'] = @silent
    push(silent: @silent)
    @silent
  end

  def silent?; @silent == true; end
  def silent; @silent == true; end
  def quiet=(value); @quiet = !!value; end
  def quiet?; @quiet == true; end
  def autosayoption; @autosayoption != false; end
  def autosayoption=(value); @autosayoption = value; end

  def disable_menu; @disable_menu = true; self; end
  def enable_menu; @disable_menu = false; self; end
  def menu_enabled?; @disable_menu != true; end
  def disable_contextinglobal; @disable_contextinglobal = true; self; end
  def enable_contextinglobal; @disable_contextinglobal = false; self; end
  def contextinglobal_enabled?; @disable_contextinglobal != true; end
  # `wait_for_item` - show this control and do not come back until the user
  # has picked a row (or left). Elten's own `form_field.rb`: it is a loop
  # around the same events a `Form` reads, which is exactly what a
  # one-control form already is here.
  WAIT_ACTIONS = %i[select escape expand collapse].freeze

  def wait_for_item(actions: WAIT_ACTIONS)
    actions = Array(actions)
    raise ArgumentError, 'actions cannot be empty' if actions.empty?

    @wait_answer = nil
    @wait_actions = actions
    form = @form || Form.new([self])
    @wait_form = form
    on(:select) { form.resume } unless @wait_bound
    @wait_bound = true
    form.wait
    @wait_answer
  end

  # What `wait_for_item` answers - the row that was activated. A control
  # that has no rows answers nil, which is what Elten's own base class does.
  def wait_item_at(_index)
    nil
  end

  def wait_item_available?(_index)
    false
  end

  # What this control's events are called, and what they carry. A list's
  # `changed` is a `changed`; a board's is a `move`, and it carries where
  # the cursor moved TO - AudioMemory reads `pos[0]`/`pos[1]` off it, and a
  # handler called with nothing stops on `undefined method '[]' for nil`.
  def event_name(wire_name)
    wire_name.to_sym
  end

  def event_args(_name, _message = nil)
    []
  end

  def selected?
    false
  end

  def collapsed?
    false
  end

  def expanded?
    false
  end

  # Put the keyboard here. Elten's applications ask constantly - after a
  # pick, after a dialog, after a round - and until now this answered and
  # did nothing, which left the player with a board on the screen and the
  # keyboard somewhere else. There is no announcement to make: the control
  # is a real wx control and the reader says what it is when it is
  # entered, exactly as anywhere else on this desktop.
  # ------------------------------------------------- the rest of Elten's
  # A control in Elten carries a long tail of methods this bridge does not
  # need to implement, because Titan's side does the same job one layer
  # down - how much a control says of itself, its spell checking, its
  # audio preview, its formatting. They are here because an application
  # CALLS them and a method that is merely absent is a `NoMethodError` in
  # somebody else's program: the media catalogue built its station list,
  # reached `list.add_tip(...)`, and then ended on `set_text` where the
  # search box should have been.
  #
  # Each one answers what its own name promises - a question answers
  # false, a setter records, an action answers self - so a caller carries
  # on being right about everything else.
  def text_utf8(value)
    value.to_s
  end

  def lpos
    50.0
  end

  def lspeak(*_arguments); self; end
  def say_option(*_arguments); self; end
  def foplay(*_arguments); self; end

  # ------------------------------------------------- the control's own menu
  # `bind_context(header) { |menu| menu.option(...) }` is how an
  # application puts commands on a control - the media catalogue's "add to
  # favourites", the file manager's copy, paste, rename and delete. The
  # block was being recorded and never called, so every one of those
  # commands was unreachable: an application could ONLY be used with the
  # keys it happened to bind itself.
  #
  # It becomes a real Windows menu, opened where everybody looks for one -
  # the Applications key, Shift+F10, the right mouse button, and Alt.
  def bind_context(header = '', &block)
    return self if block.nil?

    (@contexts ||= []) << [block, header.to_s]
    push(hascontext: true)
    self
  end
  # Elten's three: the file manager binds all of them and they are
  # different menus, so they keep their own headings rather than being
  # poured into one long list.
  def bind_menu(header = '', &block); bind_context(header, &block); end
  def bind_editmenu(&block); bind_context(_('Edit'), &block); end
  def bind_filesmenu(&block); bind_context(_('File'), &block); end
  def bind_createmenu(&block); bind_context(_('New'), &block); end

  def hascontext
    !(@contexts.nil? || @contexts.empty?)
  end

  # Fill a menu with what was bound. `submenu` is Elten's own: true puts
  # each binding under a heading of its own (which is what the menu BAR
  # does), false pours them straight in (the context menu).
  def context(menu, submenu = true)
    Array(@contexts).each do |block, header|
      if submenu
        name = header.empty? ? _('Context menu') : header
        menu.submenu(name) { |inner| block.call(inner) }
      else
        block.call(menu)
      end
    end
    menu
  end

  # The user asked for it. Building the menu runs the application's own
  # blocks, so it is built fresh every time - which is the point: what is
  # on it depends on the row the cursor is on.
  def open_context_menu(as_menu_bar = false)
    return false unless hascontext

    ensure_shown
    menu = Menu.new('', :context)
    context(menu, as_menu_bar)
    menu.popup(self)
    true
  end
  def subindex; 0; end
  def maxsubindex; 0; end
  def tags; []; end
  def tag; nil; end
  def tag=(value); properties['tag'] = value; end
  def hidden?(_index = nil); false; end
  def disable_item(*_arguments); self; end
  def enable_item(*_arguments); self; end
  def multiselections; []; end
  def item_state?(*_arguments); false; end
  def set_item_state(*_arguments); self; end
  def set_item_status(*_arguments); self; end
  def set_item_states(*_arguments); self; end
  def clear_item_state(*_arguments); self; end
  def clear_item_status(*_arguments); self; end
  def item_audio?(*_arguments); false; end
  def set_item_audio(*_arguments); self; end
  def clear_item_audio(*_arguments); self; end
  def audio?; false; end
  def audio_url; properties['audio_url']; end
  def audio_url=(value); properties['audio_url'] = value; end
  def speech_value_prepend(*_arguments); self; end
  def speech_value_append(*_arguments); self; end
  def speech_value_gsub(*_arguments); self; end
  def setformatting(*_arguments); self; end
  def espellcheck(*_arguments); self; end
  def reload(*_arguments); update; self; end
  def refresh(*_arguments); update; self; end

  def focus(_index = nil, _count = nil, _spk = true, **_options)
    ensure_shown
    return self if @form.nil? || control_id.nil?

    @form.focus_control(control_id)
    self
  end

  def blur; self; end
  def update(*_arguments); ensure_shown; end
  def key_processed(_key); false; end

  # In Elten there is one screen and building a control puts it on it. Here
  # a control usually arrives inside a `Form`, but it does not have to: the
  # file manager builds a `FilesTree` and drives it from a `Runner`, with no
  # form anywhere. So a control with no form makes itself one, the first
  # time anything asks it to be visible - which is what `update` means in
  # Elten's own loop.
  def ensure_shown
    return self if @form

    @form = Form.new([self])
    @form.show
    self
  end

  protected

  def push(changes)
    return if @control_id.nil? || @form.nil?

    @form.push_change(@control_id, changes)
  end
end

class Button < EltenControl
  def initialize(label = '')
    super(:button, { label: label.to_s })
  end

  def label=(value)
    @spec[:label] = value.to_s
    push(label: value.to_s)
  end

  def label
    @spec[:label]
  end

  def enabled=(value)
    push(enabled: !!value)
  end

  # `press` fires the handlers an application attached, exactly as the
  # real button does - that is how an application presses its own Ok.
  def press
    @pressed = true
    trigger(:press)
    self
  end

  def pressed?
    @pressed == true
  end
end

class CheckBox < EltenControl
  def initialize(label = '', checked: false)
    super(:checkbox, { label: label.to_s, checked: !!checked })
    @checked = !!checked
  end

  def checked?
    @checked
  end
  alias value checked?

  def checked=(value)
    @checked = !!value
    push(checked: @checked)
  end
end

class EditBox < EltenControl
  # Elten's own: a bitmask, so an application can ask for more than one at
  # once (`EditBox::Flags::ReadOnly | EditBox::Flags::MultiLine`).
  module Flags
    ReadOnly = 1
    MultiLine = 2
    Password = 4
  end

  def initialize(header = '', type: 0, text: '', max_length: -1, **_ignored)
    flags = type.to_i
    multiline = (flags & Flags::MultiLine) != 0
    readonly = (flags & Flags::ReadOnly) != 0
    password = (flags & Flags::Password) != 0
    super(:editbox, { header: header.to_s, text: text.to_s,
                      multiline: multiline, readonly: readonly,
                      password: password, max_length: max_length.to_i })
    @text = text.to_s
  end

  def text
    @text
  end

  def text=(value)
    @text = value.to_s
    push(text: @text)
  end

  # Elten's own names for the same thing. `set_text` is the one an
  # application reaches for most - the media catalogue fills its search
  # box with it - and it takes the flags Elten's does (`html:`, `md:`)
  # which Titan's box renders as the words they carry.
  # Elten's own signature exactly: `set_text(text, reset = true,
  # reset_speak_callbacks:)`. The second argument is positional, not a
  # keyword, and reading it as one is `wrong number of arguments (given 2,
  # expected 1)` - which for the media catalogue was the search box.
  def set_text(value, _reset = true, **_options)
    self.text = value
    self
  end
  alias text_str text
  alias value text

  def text_html
    @text
  end

  def text_len
    @text.to_s.length
  end
  alias character_length text_len

  # Writing into the box from the application's side.
  def einsert(value, _at = nil)
    self.text = @text.to_s + value.to_s
    self
  end

  def edelete(*_arguments)
    self.text = ''
    self
  end

  def append_text(value)
    einsert(value)
  end

  def read_text(*_arguments)
    @text
  end

  def get_lines
    @text.to_s.split(/\r\n|\r|\n/)
  end

  def get_vlines
    get_lines
  end

  def get_check(*_arguments)
    @text
  end

  # The clipboard and the undo stack belong to the real wx control the
  # user is typing into, which already does all of this with the keys
  # they expect. Answering rather than raising is the whole point.
  def select_all; self; end
  def copy; self; end
  def cut; self; end
  def paste; self; end
  def eundo; self; end
  def eredo; self; end
  def search(*_arguments); nil; end
  def espeech(*_arguments); self; end
  def esay(*_arguments); self; end
  def find_element(*_arguments); nil; end
end

class ListBox < EltenControl
  module Flags
    AnyDir = 1
  end

  def initialize(options, header: '', index: 0, flags: 0, quiet: true,
                empty_label: nil, **_ignored)
    @options = Array(options)
    @index = index.to_i
    super(:listbox, { header: header.to_s, options: @options.map(&:to_s),
                      index: @index })
  end

  def options
    @options
  end

  def options=(values)
    @options = Array(values)
    @index = 0 if @index >= @options.size
    push(options: @options.map(&:to_s))
  end

  def index
    @index
  end

  def index=(value)
    @index = value.to_i
    push(index: @index)
  end

  # What is highlighted right now - the answer to "which one did they mean"
  # after a `:select`.
  def value
    @options[@index]
  end

  def wait_item_at(index = @index)
    @options[index]
  end

  def wait_item_available?(index = @index)
    index.to_i >= 0 && index.to_i < @options.size
  end

  def clear_options
    self.options = []
    self
  end

  def prepend_options(values)
    self.options = Array(values) + @options
    self
  end

  def append_options(values)
    self.options = @options + Array(values)
    self
  end

  # Move the highlight AND tell the application, which is what Elten's own
  # does - an application asks for a row and then reads `value`.
  def request_select(index)
    self.index = index
    trigger(:changed, @index)
    self
  end

  def option_plain_text(index = @index)
    @options[index.to_i].to_s
  end

  def empty_label=(value)
    push(empty_label: value.to_s)
  end

  # Where in the stereo image this row is, as Elten works it out - the
  # first to the left, the last to the right. Titan pans its own cue by
  # the same number.
  def lpos
    return 50.0 if @options.size <= 1

    @index.to_f / (@options.size - 1).to_f * 100.0
  end
end

# `TableBox.new(columns, rows, ...)` - a list with columns.
#
# KlangoArchive's whole interface is these: a group is a row of four
# (name, forums, threads, posts) and the columns are what makes it readable.
# Rendered as a wx list in report mode, which is the control Titan uses for
# the same job everywhere else and which a screen reader announces column by
# column.
class TableBox < EltenControl
  def initialize(columns = [], rows = [], index: 0, header: '', quiet: true,
                flags: 0, empty_label: nil, **_ignored)
    @columns = Array(columns).map(&:to_s)
    @rows = Array(rows)
    @index = index.to_i
    super(:tablebox, { header: header.to_s, columns: @columns,
                       rows: rendered(@rows), index: @index,
                       empty_label: empty_label&.to_s })
  end

  attr_reader :columns

  def rows
    @rows
  end

  def rows=(values)
    @rows = Array(values)
    @index = 0 if @index >= @rows.size
    push(rows: rendered(@rows))
  end

  def options
    @rows
  end

  def index
    @index
  end

  def index=(value)
    @index = value.to_i
    push(index: @index)
  end

  def value
    @rows[@index]
  end

  def wait_item_at(index = @index)
    @rows[index]
  end

  def wait_item_available?(index = @index)
    index.to_i >= 0 && index.to_i < @rows.size
  end

  # Everything below is Elten's own row-decoration API - a row that is
  # unread, one that carries audio, one that is disabled. Titan's list does
  # not draw any of that yet, so they are recorded and ignored rather than
  # missing: an application that decorates its rows still runs, and still
  # shows them.
  def set_row_state(*_args); self; end
  def set_row_status(*_args); self; end
  def set_row_states(*_args); self; end
  def clear_row_state(*_args); self; end
  def clear_row_states(*_args); self; end
  def set_row_audio(*_args, **_options); self; end
  def row_audio_source(*_args); nil; end
  def row_audio_sources; []; end
  def clear_row_audio(*_args); self; end
  def empty_label; @spec[:empty_label]; end
  def empty_label=(label); @spec[:empty_label] = label&.to_s; end
  def tag; @tag; end
  def tag=(value); @tag = value; end

  private

  # A row may be an array of cells or one value; both become a row of
  # strings, and a nil cell is an empty one rather than the word "nil".
  def rendered(rows)
    rows.map do |row|
      cells = row.is_a?(Array) ? row : [row]
      cells.map { |cell| cell.nil? ? '' : cell.to_s }
    end
  end
end

# `FilesTree.new(header, path:, hide_files:, extensions:)` - browsing the
# disk.
#
# The file manager's whole screen is one of these, so it cannot be a button
# that opens a picker: it is a LIST of what is in a folder, which you move
# through, enter and come back out of. Ruby reads the directory itself -
# it has `Dir` and `File` and the application expects exactly their answers
# (`filetype` is decided by extension, `selected` is a real path) - and
# Titan draws the list. That split keeps every file question on the side
# that can answer it.
class FilesTree < EltenControl
  AUDIO_EXTENSIONS = %w[.mp3 .ogg .wav .flac .opus .m4a .aac .wma .mid].freeze
  TEXT_EXTENSIONS = %w[.txt .md .log .ini .csv .json .xml .rb .html].freeze
  ARCHIVE_EXTENSIONS = %w[.zip .7z .rar .tar .gz .xz .bz2].freeze
  DOCUMENT_EXTENSIONS = %w[.doc .docx .odt .pdf .rtf .epub].freeze
  APP_EXTENSIONS = %w[.exe .bat .cmd .com .msi .eltenapp].freeze

  #: What `..` is called. A list whose first row is a bare `..` reads as
  #: nothing at all; this is what it IS.
  UP = '..'

  def initialize(header = '', path: '', hide_files: false, quiet: true,
                extensions: nil, use_sounds: true,
                handle_file_previews: true, **_ignored)
    @header = header.to_s
    @hide_files = !!hide_files
    @extensions = Array(extensions).map { |name| name.to_s.downcase }
    @path = normalise(path.to_s.empty? ? Dir.home : path.to_s)
    @file = nil
    @index = 0
    @entries = []
    @go = false
    read
    super(:listbox, { header: @header, options: labels, index: 0 })
  end

  # ------------------------------------------------------------- where it is
  # An opened path.
  def path(_c = false)
    @path
  end

  def path=(value)
    @path = normalise(value.to_s)
    read
    show
  end

  # The name of the focused entry, and the whole path to it.
  def file
    @file.to_s
  end

  def selected(_c = false)
    return '' if @file.nil?

    EltenPath.join(@path, @file)
  end

  def cfile(full = false)
    full ? selected : @file.to_s
  end

  def directory?
    File.directory?(selected)
  rescue StandardError
    false
  end

  # Elten's own numbering, by extension: 0 a folder, 1 audio, 2 text,
  # 3 archive, 4 document, 5 a program, -1 anything else.
  def filetype
    return 0 if directory?

    extension = File.extname(selected).downcase
    return 1 if AUDIO_EXTENSIONS.include?(extension)
    return 2 if TEXT_EXTENSIONS.include?(extension)
    return 3 if ARCHIVE_EXTENSIONS.include?(extension)
    return 4 if DOCUMENT_EXTENSIONS.include?(extension)
    return 5 if APP_EXTENSIONS.include?(extension)

    -1
  end

  # Elten's file tree carries its own commands, so a file manager has them
  # even when the application binds nothing of its own - which is exactly
  # what Elten's `FilesTree#context` does.
  def hascontext
    true
  end

  def context(menu, submenu = true)
    super
    add = proc do |into|
      into.option(_('Open')) { go }
      into.option(_('Copy'), nil, 'c') { copy }
      into.option(_('Paste'), nil, 'v') { paste }
      into.option(_('Rename')) { rename }
      into.option(_('Delete'), nil, :del) { fdelete }
      into.option(_('Refresh')) { refresh }
    end
    submenu ? menu.submenu(_('File')) { |inner| add.call(inner) } : add.call(menu)
    menu
  end

  # ------------------------------------------------- what Elten's own does
  # Renaming and deleting are real changes to somebody's disk made by an
  # application they merely opened, so they go through the user: the
  # bridge asks, in a Titan dialog, and does nothing at all if the answer
  # is no. `false` back is a refusal the file manager already reports -
  # which is the honest answer, and better than a method that is not there
  # and ends the application at the point somebody pressed Delete.
  # Copy and paste real files, which is what a file manager is for.
  # `copy` only remembers what was pointed at; `paste` is the one that
  # writes, and it refuses to write over something that is already there
  # rather than destroying it silently.
  def copy
    target = selected(true)
    return false if target.nil? || @file == UP

    @@clipboard = target
    true
  end

  def cut
    copy
  end

  def paste
    source = defined?(@@clipboard) ? @@clipboard : nil
    return false if source.nil? || !File.exist?(source)

    destination = File.join(@path, File.basename(source))
    return false if File.exist?(destination)

    require 'fileutils'
    File.directory?(source) ? FileUtils.cp_r(source, destination) : FileUtils.cp(source, destination)
    refresh
    true
  rescue StandardError => error
    Log.warning("paste failed: #{error.class}: #{error.message}")
    false
  end

  def rename(new_name = nil)
    target = selected(true)
    return false if target.nil? || @file == UP

    new_name = Kernel.input_text(_('New name'), text: File.basename(target.to_s)) if new_name.nil?
    return false if new_name.nil? || new_name.to_s.strip.empty?

    File.rename(target, File.join(File.dirname(target), File.basename(new_name.to_s)))
    refresh
    true
  rescue StandardError => error
    Log.warning("rename failed: #{error.class}: #{error.message}")
    false
  end

  def fdelete
    target = selected(true)
    return false if target.nil? || @file == UP
    return false unless Kernel.confirm(format(_('Delete %s?'), File.basename(target.to_s)))

    File.directory?(target) ? Dir.rmdir(target) : File.delete(target)
    refresh
    true
  rescue StandardError => error
    Log.warning("delete failed: #{error.class}: #{error.message}")
    false
  end

  # ---------------------------------------------------------------- moving
  # `go` - enter the folder under the cursor, or step back out of this one.
  # The application calls it and then `update`.
  def go
    if @file == UP
      up
    elsif directory?
      enter(selected)
    end
    self
  end

  def up
    parent = File.dirname(@path)
    return self if parent == @path

    leaving = File.basename(@path)
    @path = normalise(parent)
    read
    # Come back onto the folder just left, which is where somebody stepping
    # out expects to be - not at the top of a list of two hundred names.
    found = @entries.index(leaving)
    @index = found || 0
    @file = @entries[@index]
    show
    self
  end

  def enter(folder)
    @path = normalise(folder)
    read
    @index = 0
    @file = @entries[0]
    show
    self
  end

  def refresh
    read
    @index = 0 if @index >= @entries.size
    @file = @entries[@index]
    show
    self
  end

  def index
    @index
  end

  def index=(value)
    @index = value.to_i
    @file = @entries[@index]
    _say_kind
  end

  def entries
    @entries
  end

  # What KIND of thing the cursor is on, as a sound. Elten's file manager
  # does this on every move and it is not decoration: it is how somebody
  # who cannot see the folder knows a folder from a song from a document
  # before the name has finished being read. The sounds are Titan's own -
  # `play_sound` goes through the user's theme.
  KIND_SOUNDS = { 0 => 'file_dir', 1 => 'file_audio', 2 => 'file_text',
                  3 => 'file_archive', 4 => 'file_document' }.freeze

  def _say_kind
    name = KIND_SOUNDS[filetype]
    play_sound(name, position: lpos_pan) if name
  rescue StandardError
    nil
  end

  # Where this row is, as a pan of -1 to 1 - the first entry to the left,
  # the last to the right, which is how far through the folder you are.
  def lpos_pan
    return 0.0 if @entries.size <= 1

    (@index.to_f / (@entries.size - 1).to_f) * 2.0 - 1.0
  end

  def update(*_arguments)
    ensure_shown
    self
  end

  # ------------------------------------------------------- Elten's own keys
  # Right goes into a folder, Left comes back out, Space plays or reads
  # the file the cursor is on - and with Shift held, the arrows and Space
  # drive whatever is being previewed. This is Elten's file manager, key
  # for key (`FilesTree#update` and `handle_preview_keys`), because
  # somebody who has used it there should not have to learn it again here.
  def key_pressed(name, shift: false)
    case name.to_s
    when 'key_right'
      shift ? _preview_seek(1) : (go if directory?)
    when 'key_left'
      shift ? _preview_seek(-1) : up
    when 'key_space'
      shift ? _preview_toggle : preview
    when 'key_up'
      _preview_volume(0.05) if shift
    when 'key_down'
      _preview_volume(-0.05) if shift
    end
    self
  end

  # `preview` - Space. An audio file plays (and Space again stops it); a
  # text file is READ, which for somebody who cannot see the folder is
  # what "what is in this file" means.
  def preview
    file = selected(true)
    return self if file.to_s.empty? || !File.file?(file)

    case filetype
    when 1 then _preview_audio(file)
    when 2 then _preview_text(file)
    end
    self
  end

  def close_preview
    @preview&.close
    @preview = nil
    @previewing = nil
    self
  end

  private

  def _preview_audio(file)
    if @preview && @previewing == file
      close_preview
      return
    end
    close_preview
    @preview = Player.new(file, label: File.basename(file), autoplay: true,
                          lazy: false)
    if @preview.sound.nil? || @preview.sound.closed?
      close_preview
      alert(_('This file cannot be played.'))
      return
    end
    @previewing = file
  rescue StandardError => error
    close_preview
    Log.warning("preview failed: #{error.class}: #{error.message}")
    alert(_('This file cannot be played.'))
  end

  # Elten's own limits: enough to know what the file is, never the whole
  # of something that could be megabytes.
  TEXT_PREVIEW_BYTES = 65_536
  TEXT_PREVIEW_CHARACTERS = 4096

  def _preview_text(file)
    close_preview
    data = File.binread(file, TEXT_PREVIEW_BYTES)
    text = data.force_encoding(Encoding::UTF_8)
    text = data.force_encoding(Encoding::WINDOWS_1250) unless text.valid_encoding?
    text = text.encode(Encoding::UTF_8, invalid: :replace, undef: :replace)
    words = text[0, TEXT_PREVIEW_CHARACTERS].to_s
    speak(words) unless words.strip.empty?
  rescue StandardError => error
    Log.warning("text preview failed: #{error.class}: #{error.message}")
    alert(_('This file cannot be previewed.'))
  end

  def _preview_toggle
    return if @preview.nil?

    @preview.paused? ? @preview.play : @preview.pause
  end

  def _preview_seek(seconds)
    return if @preview.nil?

    @preview.jump_to_position([@preview.position + seconds, 0].max)
  end

  def _preview_volume(_by)
    nil                      # the volume is Titan's, and the user's
  end

  public

  def wait_item_at(index = @index)
    @entries[index]
  end

  def wait_item_available?(index = @index)
    index.to_i >= 0 && index.to_i < @entries.size
  end

  # The file manager hangs its own commands off the tree - copy, rename,
  # delete, create. They are all `bind_<something>menu { |menu| ... }` and
  # they all mean the same thing: remember a block that builds a menu.
  def method_missing(name, *arguments, &block)
    if name.to_s.start_with?('bind_') && block
      @menus ||= {}
      (@menus[name.to_s] ||= []) << block
      return self
    end
    super
  end

  def respond_to_missing?(name, include_private = false)
    name.to_s.start_with?('bind_') || super
  end

  def menus(kind = nil)
    @menus ||= {}
    kind.nil? ? @menus : (@menus[kind.to_s] || [])
  end

  # Opening it as a dialog of its own, for an application that only wants a
  # folder - Youtube asking where to save a download.
  def choose
    answer = EltenBridge.call('choose_path',
                              { 'header' => @header, 'path' => @path,
                                'directory' => @hide_files,
                                'extensions' => @extensions })
    self.path = answer if answer
    answer
  rescue EltenBridge::Closed
    nil
  end

  private

  def normalise(value)
    EltenPath.normalize(File.expand_path(value.to_s))
  rescue StandardError
    EltenPath.normalize(value.to_s)
  end

  # What is in this folder: folders first, then files, each alphabetically -
  # which is how every file list on this desktop is ordered.
  def read
    folders = []
    files = []
    begin
      Dir.each_child(@path) do |name|
        # PER ENTRY. A user's home directory on Windows is full of things
        # that raise when they are asked about - the "Application Data"
        # junction loops, OneDrive placeholders are not there until they
        # are fetched, and a name in an encoding Ruby cannot read throws on
        # `File.join`. With one rescue around the whole loop, the FIRST such
        # entry ends the listing: the file manager opened on a home folder
        # of forty-four things and showed one row saying "Up one level".
        begin
          full = File.join(@path, name)
          if File.directory?(full)
            folders << name
          elsif !@hide_files && wanted?(name)
            files << name
          end
        rescue StandardError
          next
        end
      end
    rescue SystemCallError => error
      Log.warning("#{@path} could not be read: #{error.message}")
    end
    order = ->(names) { names.sort_by { |name| name.downcase } }
    @entries = []
    @entries << UP unless File.dirname(@path) == @path
    @entries += order.call(folders) + order.call(files)
    @index = 0 if @index >= @entries.size
    @file = @entries[@index]
  end

  def wanted?(name)
    return true if @extensions.empty?

    @extensions.include?(File.extname(name).downcase)
  end

  # A folder says it is one, so a list read aloud is not a wall of names
  # with no shape.
  def labels
    @entries.map do |name|
      begin
        if name == UP
          _('Up one level')
        elsif File.directory?(File.join(@path, name))
          format('%s, %s', name, _('folder'))
        else
          name
        end
      rescue StandardError
        name
      end
    end
  end

  def show
    push(options: labels, index: @index, header: "#{@header} - #{@path}")
  end
end

# `Tree` - a hierarchy. Titan shows it as a list of the level being looked
# at, which is how its own Start menu and file browser behave; Left and
# Right step out of and into a branch, which is what the applications bind.
class Tree < ListBox
  def initialize(options = [], header: '', index: 0, **rest)
    super(options, header: header, index: index, **rest)
  end

  def expand(*_arguments); self; end
  def collapse(*_arguments); self; end
  def expanded?(*_arguments); false; end

  # Elten's own tree names. A tree here is a list of the rows the
  # application put in it, so a "way" is the row that is highlighted.
  def createselect(*_arguments); self; end
  def getelements(*_arguments); options; end
  def getwayindex(*_arguments); index; end
  def searchway(*_arguments); value; end
  def get_file(*_arguments); value; end
end

# `ChoiceListBox.new(rows, header:, index:)` - a list where each row is
# itself a choice: the label, and a value cycled through with Left and Right.
# MileByMile's setup screen is these - "players: 2", "board: long".
class ChoiceListBox < EltenControl
  def initialize(rows = [], header: '', index: 0, quiet: true, flags: 0,
                **_ignored)
    @rows = Array(rows)
    @index = index.to_i
    # **A row may say which of its choices it starts on** - Elten's shape
    # is `[label, [choices], index]`, and MileByMile opens its settings
    # form on the game the player set up last time with it. Dropping the
    # third element silently reset every one of them to the first choice.
    @choices = {}
    @rows.each_with_index do |entry, row|
      @choices[row] = entry[2].to_i if entry.is_a?(Array) && entry[2]
    end
    super(:choicelist, { header: header.to_s, rows: choice_rows,
                         index: @index })
  end

  # What Titan builds it out of: one row, one label, its choices, and
  # which of them is current. Rendered as a real combo box each - the
  # control Titan's own settings window uses for exactly this - so the
  # arrows change the value and a screen reader announces the new one
  # itself, with nothing said twice and nothing said by Titan.
  def choice_rows
    (0...@rows.size).map do |row|
      entry = @rows[row]
      options = row_options(entry)
      { label: (entry.is_a?(Array) ? entry[0] : entry).to_s,
        options: options.map(&:to_s),
        index: options.empty? ? 0 : (@choices.fetch(row, 0) % options.size) }
    end
  end

  def rows
    @rows
  end

  def rows=(values)
    @rows = Array(values)
    @choices = {}
    @rows.each_with_index do |entry, row|
      @choices[row] = entry[2].to_i if entry.is_a?(Array) && entry[2]
    end
    push(rows: choice_rows)
  end

  def index
    @index
  end

  def index=(value)
    @index = value.to_i
    push(index: @index)
  end

  # Which choice a row is on now - the widget says so when the user
  # changes a combo box.
  def choose(row, choice)
    @choices[row.to_i] = choice.to_i
    @index = row.to_i
    self
  end

  # The chosen value on a row - Elten's own `value(row = index)`.
  def value(row = @index)
    entry = @rows[row]
    return nil if entry.nil?

    options = row_options(entry)
    return entry if options.empty?

    options[@choices.fetch(row, 0) % options.size]
  end

  def values
    (0...@rows.size).map { |row| value(row) }
  end

  def header
    @spec[:header]
  end

  def header=(value)
    @spec[:header] = value.to_s
    push(header: value.to_s)
  end

  def append(row)
    @rows << row
    push(rows: choice_rows)
    self
  end

  def set_options(values)
    self.rows = values
    self
  end

  def set_value(new_value, row = @index)
    options = row_options(@rows[row])
    found = options.index(new_value)
    @choices[row] = found if found
    push(rows: choice_rows)
    self
  end

  def selected_option
    @rows[@index]
  end

  # `wait_for_choice` - MileByMile's setup screen: show the rows, let the
  # player set each one, and answer with what they chose. In Elten this is
  # a loop around the frame; here the control is inside a form, so this is
  # that form being waited on.
  def wait_for_choice(*_arguments)
    ensure_shown
    @form&.wait
    values
  end

  def value=(new_value)
    options = row_options(@rows[@index])
    found = options.index(new_value)
    @choices[@index] = found if found
    push(rows: choice_rows)
  end

  private

  # A row is either a plain label or `[label, [choices...]]`.
  def row_options(entry)
    return entry[1].to_a if entry.is_a?(Array) && entry[1].is_a?(Array)

    []
  end

  def row_label(row)
    entry = @rows[row]
    return entry.to_s unless entry.is_a?(Array)

    chosen = value(row)
    chosen.nil? ? entry[0].to_s : "#{entry[0]}: #{chosen}"
  end

  def labels
    (0...@rows.size).map { |row| row_label(row) }
  end
end

# `Player.new(url, label:, autoplay:)` - a radio station, or a podcast
# episode, ON A FORM.
#
# The media catalogue is nothing else: pick a station and this is the
# screen. Elten plays a stream with the BASS stack it ships; Titan's mixer
# plays files, so what sits between a URL and this desktop's sound is the
# decoding - which happens on Titan's side (`host.Stream`) and then goes
# through Titan's own mixer, at the user's theme volume, on the user's
# output device.
#
# `sound` answers an object with Elten's own `opened?`, `position`,
# `position=`, `length` and `closed?`, because that is what an
# application reads: the media catalogue asks `@player.sound&.opened?`
# before it shows a player at all, and a `sound` that was nil meant every
# station reported "the station could not be played".
class Player < EltenControl
  attr_accessor :label
  attr_reader :file

  def initialize(file, label: '', autoplay: true, quiet: true, stream: nil,
                 lazy: false, **_ignored)
    @label = label.to_s
    @file = file
    @handle = nil
    @state = {}
    @closed = false
    super(:player, { label: @label, status: '' })
    get_sound unless lazy
    autoplay && @handle ? play : (@paused = true)
  end

  # ------------------------------------------------------------ the sound
  def get_sound
    return @sound if @sound
    return nil if @closed || @file.nil?

    answer = EltenBridge.call('stream_open',
                              { 'url' => @file.to_s, 'label' => @label })
    return nil unless answer.is_a?(Hash)

    @handle = answer['handle']
    @state = answer
    @sound = PlayerSound.new(self)
  rescue EltenBridge::Closed
    nil
  end
  alias sound get_sound

  def setsound(file)
    close
    @closed = false
    @file = file
    get_sound
  end
  alias setstream setsound

  # ---------------------------------------------------------- the buttons
  def play
    @paused = false
    _do('play')
    self
  end

  def pause
    @paused = true
    _do('pause')
    self
  end

  def paused?
    @state['paused'] == true
  end
  alias pause? paused?

  def stop
    pause
    jump_to_position(0)
    self
  end

  def completed
    @state['finished'] == true
  end
  alias completed? completed

  def position
    (@state['position'] || 0).to_f
  end

  def duration
    (@state['duration'] || 0).to_f
  end

  def jump_to_position(seconds)
    _do('seek', 'position' => seconds.to_f)
    self
  end

  def fade(*_arguments); self; end
  def is_opus?; false; end
  def savefile; false; end

  def close
    return self if @closed

    @closed = true
    _do('close')
    @handle = nil
    @sound = nil
    self
  end

  # Elten drives a player from its own frame; here the control is real and
  # `update` is where the label is refreshed with where the sound has got
  # to, which is also what the screen reader reads off it.
  def update(*_arguments)
    ensure_shown
    _do('status')
    self
  end

  # The player's own keys, arriving from the real control.
  def event_name(wire_name)
    wire_name.to_s == 'player' ? :player : wire_name.to_sym
  end

  def handle_player(what)
    case what.to_s
    when 'toggle' then paused? ? play : pause
    when 'stop' then stop
    when 'back' then jump_to_position([position - STEP_SECONDS, 0].max)
    when 'forward' then jump_to_position(position + STEP_SECONDS)
    when 'start' then jump_to_position(0)
    when 'end' then jump_to_position([duration - 1, 0].max)
    when 'louder' then _volume(VOLUME_STEP)
    when 'quieter' then _volume(-VOLUME_STEP)
    end
    self
  end

  # Elten's own keys on a player, and the same amounts: Left and Right
  # move by five seconds, Up and Down are the volume, Home and End are
  # the ends, Space plays and pauses. What is deliberately NOT here is
  # Elten's tempo and pitch - Titan's mixer plays a sound, it does not
  # resample one, and a key that pretended to change the speed and
  # changed nothing is worse than a key that is not there.
  STEP_SECONDS = 5.0
  VOLUME_STEP = 0.05

  def volume
    @volume ||= 1.0
  end

  def volume=(value)
    @volume = [[value.to_f, 0.05].max, 1.0].min
    _do('volume', 'volume' => @volume)
    @volume
  end

  def _volume(by)
    self.volume = volume + by
  end

  private

  def _do(what, extra = {})
    return self if @handle.nil?

    answer = EltenBridge.call('stream_do',
                              { 'handle' => @handle, 'do' => what }.merge(extra))
    @state = answer if answer.is_a?(Hash)
    _show
    self
  rescue EltenBridge::Closed
    self
  end

  # What the control SAYS. A player changes while the keyboard is sitting
  # on it, so this is both the text and the accessible name.
  def _show
    push(label: @label, status: _status_words,
         playing: @state['playing'] == true)
  end

  def _status_words
    return 'stopped' if @state['finished']
    return 'paused' if @state['paused']
    return 'playing' unless duration.positive?

    format('%s of %s', _clock(position), _clock(duration))
  end

  def _clock(seconds)
    seconds = seconds.to_i
    format('%d:%02d', seconds / 60, seconds % 60)
  end
end

# What `player.sound` answers - Elten's `Sound`, as much of it as an
# application reads off a player.
class PlayerSound
  def initialize(player)
    @player = player
  end

  def opened?
    !closed?
  end

  def closed?
    @player.instance_variable_get(:@handle).nil?
  end

  def playing?
    @player.instance_variable_get(:@state)['playing'] == true
  end

  def position
    @player.position
  end

  def position=(value)
    @player.jump_to_position(value)
  end

  def length
    @player.duration
  end
  alias duration length

  def volume; 1.0; end
  def volume=(value); value; end
  def stop; @player.pause; end
  def play; @player.play; end
  def pause; @player.pause; end
  def close; @player.close; end
  def frequency; 44_100; end
end

# `GridBox.new(width, height, header:, x:, y:)` - a board.
#
# AudioMemory's grid of sounds is one. It is NOT a list, and that distinction
# is the whole accessibility of it: rendered as a list box, MSAA reports a
# list, so a reader announces "item 7 of 16" for a square that is row 2,
# column 3 - and a player who cannot see the board cannot aim at a square
# whose column nobody said. Titan draws it as a real `wx.grid.Grid`, which
# answers MSAA and UI Automation with a row, a column and a cell, so the
# reader says all three.
class GridBox < EltenControl
  attr_reader :width, :height

  def initialize(width, height, header: '', x: 0, y: 0, quiet: true,
                **_ignored)
    @width = width.to_i
    @height = height.to_i
    @x = x.to_i
    @y = y.to_i
    @cells = {}
    super(:gridbox, { header: header.to_s, width: @width, height: @height,
                      x: @x, y: @y, cells: rendered })
  end

  attr_accessor :x, :y

  def position
    [@x, @y]
  end

  def set_position(x, y)
    @x = x.to_i
    @y = y.to_i
    push(x: @x, y: @y)
    self
  end

  def [](x, y = nil)
    # `grid[x, y]` is a cell; `grid[y]` on its own is the row, which is how
    # an application walks a board a line at a time.
    return (0...[@width, 1].max).map { |column| @cells[[column, x.to_i]] } if y.nil?

    @cells[[x.to_i, y.to_i]]
  end

  def []=(x, y, value)
    @cells[[x.to_i, y.to_i]] = value
    push(cells: rendered)
  end

  def value
    @cells[[@x, @y]]
  end

  def wait_item_at(_index = nil)
    value
  end

  def wait_item_available?(_index = nil)
    true
  end

  # A board's cursor moving is a `:move`, not a `:changed`.
  def event_name(wire_name)
    wire_name.to_s == 'changed' ? :move : wire_name.to_sym
  end

  # Every event carries the position - `[x, y]` - and a `:border` carries
  # which way the player walked into the wall as well, because that is
  # what Elten's own grid passes and what an application reads: AudioMemory
  # takes `pos[2]` and plays a sound at the edge that was hit.
  def event_args(name, message = nil)
    return [[@x, @y]] unless name.to_s == 'border' && message.is_a?(Hash)

    direction = message['direction'].to_s
    [[@x, @y, direction.empty? ? nil : direction.to_sym,
      message['dx'].to_i, message['dy'].to_i]]
  end

  # Titan's grid is two-dimensional, so an index is not what moves - but
  # applications still read and write one, counting across the rows.
  def index
    (@y * [@width, 1].max) + @x
  end

  def index=(value)
    width = [@width, 1].max
    @y, @x = value.to_i.divmod(width)
    push(x: @x, y: @y)
  end

  # `replace_cells(rows, resize: true)` - the whole board at once, which is
  # how AudioMemory deals a new round. `rows` is an array of rows of cells.
  def replace_cells(rows, resize: false)
    rows = Array(rows)
    if resize
      @height = rows.size
      @width = rows.map { |row| Array(row).size }.max || 0
    end
    @cells = {}
    rows.each_with_index do |row, y|
      Array(row).each_with_index { |cell, x| @cells[[x, y]] = cell }
    end
    @x = 0 if @x >= @width
    @y = 0 if @y >= @height
    push(width: @width, height: @height, cells: rendered, x: @x, y: @y)
    self
  end

  def cells
    @cells
  end

  private

  # Rows of strings, which is the shape a grid is filled from.
  def rendered
    (0...[@height, 1].max).map do |y|
      (0...[@width, 1].max).map do |x|
        cell = @cells[[x, y]]
        cell.nil? ? '' : cell.to_s
      end
    end
  end
end

# `Menu.new(header, type) { ... }` - what an application's front screen is.
#
# Elten's own, and the behaviour is the part that matters: options are
# arrowed through, Enter runs one, Escape leaves - and **the menu closes
# after an option unless its type is `:returning`**, which is
# `menu.rb`'s `close if @type != :returning`. Skeet's main menu is
# `:returning`, so Start, Scores and Instructions each come back to it and
# only `menu.close` inside the Exit option ends it. Opening an application
# here therefore feels the way it does in Elten; what changed is that the
# list is a wx one.
class Menu
  attr_accessor :header

  def initialize(header = '', type = :default, &block)
    @header = header.to_s
    @type = type
    @options = []
    @closed = true
    if block
      block.arity <= 0 ? instance_eval(&block) : block.call(self)
    end
  end

  # `option(label) { ... }` - a line, and what pressing it does.
  def option(label, value = nil, key = '', &block)
    @options << { label: label.to_s, block: block, value: value, key: key }
    self
  end

  def customoption(label, &block)
    option(label, nil, '', &block)
  end

  def useroption(user)
    @options << { label: user.to_s, block: nil, value: user, user: true }
    self
  end

  # A submenu is opened by its own `Menu`, so a nested one behaves like the
  # top-level one and Escape steps out of exactly one level.
  def submenu(label, &block)
    inner = Menu.new(label.to_s, @type)
    if block
      block.arity <= 0 ? inner.instance_eval(&block) : block.call(inner)
    end
    @options << { label: label.to_s, submenu: inner }
    self
  end

  def scene(label, _scene, *_args)
    @options << { label: label.to_s, block: nil }
    self
  end

  def quickaction(label, action)
    @options << { label: label.to_s, block: nil, quickaction: action }
    self
  end

  def options
    @options
  end

  def opened?
    !@closed
  end

  def close
    @closed = true
    self
  end

  def open
    return self if @options.empty?

    @closed = false
    while !@closed
      labels = @options.map { |entry| entry[:label] }
      chosen = select_item(labels, header: @header, start_index: 0)
      if chosen.nil?
        @closed = true
        break
      end
      entry = @options[chosen]
      break if entry.nil?

      if entry[:submenu]
        entry[:submenu].open
      elsif entry[:block]
        # An option's own `menu.close` must survive the call, so `@closed`
        # is read again afterwards rather than assumed.
        entry[:block].call
      end
      # Elten's own rule: one option and the menu is done, unless it was
      # asked to keep coming back.
      @closed = true if @type != :returning
    end
    self
  end
  alias run open
  alias call open

  # Show this as a real Windows menu on a control, and run whatever was
  # chosen. Used for a context menu and for the menu bar; an
  # application's own main menu stays a list, because that is a screen
  # rather than a menu and Elten treats it as one too.
  def popup(control)
    form = control.instance_variable_get(:@form)
    return self if form.nil?

    at = form.popup_menu(control.control_id, _menu_items)
    return self if at.nil?

    entry = _entry_at(at)
    return self if entry.nil?

    entry[:block]&.call
    self
  end

  # What Titan draws: labels, and nested items for a submenu.
  def _menu_items
    @options.map do |entry|
      if entry[:submenu]
        { 'label' => entry[:label], 'items' => entry[:submenu]._menu_items }
      else
        { 'label' => entry[:label] }
      end
    end
  end

  # `[1, 0]` is the first item of the second submenu.
  def _entry_at(path)
    here = self
    entry = nil
    Array(path).each do |position|
      return nil if here.nil?

      entry = here.instance_variable_get(:@options)[position.to_i]
      return nil if entry.nil?

      here = entry[:submenu]
    end
    entry
  end
end

# `Form.new([controls...], quiet:, silent:)` - the screen itself.
#
# `wait` blocks the caller until `resume` is called, exactly like Elten's
# own: the difference is what fills the time between them. Elten's polls a
# keyboard every frame from inside `wait`; this reads one event at a time off
# the bridge and dispatches it to whichever control it named, which is the
# same design `Runner` uses for a game loop one file over.
class Form
  attr_accessor :cancel_button, :accept_button
  attr_reader :fields

  def initialize(fields = [], index: 0, quiet: false, silent: false, header: '')
    @fields = Array(fields)
    @header = header.to_s
    @fields.each { |field| field.form = self }
    @waiting = false
    @form_id = nil
  end

  # Put it on the screen and return - for a control being driven by
  # somebody else's loop.
  def show
    open! if @form_id.nil?
    self
  end

  # One control event, routed to the field it names. Public because the
  # registry calls it: whichever loop is running hands events here.
  def dispatch_event(message)
    dispatch(message)
  end

  def wait
    open! if @form_id.nil?
    if @form_id.nil?
      # No window to show this in - a headless run, or Titan not yet ready.
      # Elten's own `wait` would sit in a loop reading a keyboard that is
      # not there; answering at once is the honest equivalent.
      return self
    end
    @waiting = true
    # The same frame everything else runs on. Reading the queue directly
    # here would make this a SECOND consumer, and two loops draining one
    # queue lose each other's events - a key press swallowed by whichever
    # asked first. `loop_update` is the one place a frame happens, and it
    # hands a control event to whichever form owns it.
    while @waiting
      loop_update(0.05)
      break if EltenLoop.closed?
    end
    self
  ensure
    close
  end

  def resume
    @waiting = false
    self
  end

  def close
    return if @form_id.nil?

    EltenForms.forget(@form_id)
    EltenBridge.notify('form_close', { 'form' => @form_id })
    @form_id = nil
  end

  def popup_menu(control_id, items)
    return nil if @form_id.nil?

    EltenBridge.call('popup_menu', { 'form' => @form_id,
                                     'control' => control_id,
                                     'items' => items })
  rescue EltenBridge::Closed
    nil
  end

  def focus_control(control_id)
    return false if @form_id.nil?

    !!EltenBridge.call('control_focus',
                       { 'form' => @form_id, 'control' => control_id })
  rescue EltenBridge::Closed
    false
  end

  # For a control to report a change it made locally back to the window -
  # `list.options = [...]` while the form is on screen.
  def push_change(control_id, changes)
    return if @form_id.nil?

    EltenBridge.notify('control_set',
                       changes.merge('form' => @form_id, 'control' => control_id))
  end

  private

  def open!
    specs = @fields.map(&:to_spec)
    @form_id = EltenBridge.call('form_open',
                                { 'controls' => specs, 'header' => @header,
                                  'cancel' => index_of(@cancel_button),
                                  'accept' => index_of(@accept_button) })
    return if @form_id.nil?

    @fields.each_with_index { |field, index| field.control_id = index }
    EltenForms.register(@form_id, self)
  rescue EltenBridge::Closed
    @form_id = nil
  end

  def index_of(field)
    return nil if field.nil?

    @fields.index(field)
  end

  def dispatch(message)
    return unless message.is_a?(Hash) && message['event'] == 'control'
    return unless message['form'] == @form_id

    index = message['control']
    name = message['name'].to_s

    if index.nil?
      # Not about one control - Escape, or the window's own close box.
      if name == 'escape'
        if @cancel_button
          @cancel_button.trigger(:press)
        else
          resume
        end
      end
      return
    end

    field = @fields[index.to_i]
    return if field.nil?

    case name
    when 'changed', 'select'
      if field.is_a?(ChoiceListBox) && message.key?('row')
        field.choose(message['row'], message['choice'])
      end
      apply_change(field, message)
      event = field.event_name(name)
      arguments = field.event_args(event)
      arguments = change_args(field) if arguments.empty?
      field.trigger(event, *arguments)
    when 'context', 'menu'
      field.open_context_menu(name == 'menu') if field.respond_to?(:open_context_menu)
    when 'player'
      field.handle_player(message['do']) if field.respond_to?(:handle_player)
      field.trigger(:player, message['do'])
    when 'press'
      field.trigger(:press)
    else
      # A control acts on the key itself first - the file tree's Left,
      # Right and Space are its own, exactly as in Elten - and the
      # application is told afterwards, so a handler it bound still runs.
      if field.respond_to?(:key_pressed)
        field.key_pressed(name, shift: message['shift'] == true)
      end
      field.trigger(name.to_sym, *field.event_args(name.to_sym, message))
    end
  end

  def apply_change(field, message)
    if field.is_a?(GridBox)
      # A grid answers with a place, not a position in a list.
      field.instance_variable_set(:@x, message['x'].to_i) if message.key?('x')
      field.instance_variable_set(:@y, message['y'].to_i) if message.key?('y')
    elsif field.is_a?(ListBox) && message.key?('index')
      field.instance_variable_set(:@index, message['index'].to_i)
    elsif field.is_a?(CheckBox) && message.key?('checked')
      field.instance_variable_set(:@checked, !!message['checked'])
    elsif field.is_a?(EditBox) && message.key?('text')
      field.instance_variable_set(:@text, message['text'].to_s)
    end
  end

  def change_args(field)
    return [field.checked?] if field.is_a?(CheckBox)
    return [field.text] if field.is_a?(EditBox)

    []
  end
end
