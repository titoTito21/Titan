# frozen_string_literal: true

# `show_settings` - an application's own settings, as a Titan form.
#
# This is Elten's `src/eapi/program_settings.rb` ported onto this bridge:
# the same Builder (`boolean` / `integer` / `text` / `choice` /
# `multi_choice` / `action`), the same Store (a `settings.json` in the
# application's OWN data folder, so a setting made here is the setting
# Elten reads and the other way round), and the same Dialog - Static,
# controls, then Apply / OK / Cancel with Apply saving without closing.
#
# What is different is only what it is made OF. Elten draws a self-voicing
# screen; here every field is a real Titan control on a real Titan form, so
# a screen reader announces a check box as a check box and the settings of
# an Elten application behave like the settings of anything else on this
# desktop.
#
# The same collector serves `extension(:name) { |service| service.settings
# { |settings| ... } }`, which is where the file manager declares its three
# switches - Elten shows those in its own settings window, and here they
# are shown by `Program.extension_settings`.

require 'monitor'

module Programs
  module ProgramSettings
    SETTINGS_FILE = 'settings.json'
    UNSET = Object.new.freeze

    BoundSetting = Struct.new(:label, :type, :key, :getter, :setter,
                              :mapping, :multi)
    ActionSetting = Struct.new(:label, :callback)

    # What is written, and where. One file per application, in its own data
    # folder, read on demand and written as a whole - which is what makes a
    # failed Apply leave the previous values in place rather than half of
    # each.
    class Store
      def initialize(owner, file = SETTINGS_FILE)
        @owner = owner
        @file = file.to_s
        # A Monitor, not a Mutex: `transaction` holds the lock and the
        # setters it calls go through `set`, which takes it again. Ruby's
        # Mutex is not reentrant, so with one of those an Apply that
        # saved anything at all deadlocked the application.
        @lock = Monitor.new
        @data = nil
        @dirty = false
      end

      def get(key, default)
        @lock.synchronize do
          load
          @data.key?(key.to_s) ? @data[key.to_s] : duplicate(default)
        end
      end

      def set(key, value)
        @lock.synchronize do
          load
          @data[key.to_s] = value
          @dirty = true
        end
        value
      end

      # Everything, or nothing. A setter that raises half way through puts
      # back what was there before it started.
      def transaction
        @lock.synchronize do
          load
          previous = @data.dup
          was_dirty = @dirty
          begin
            yield
            flush
          rescue Exception
            @data = previous
            @dirty = was_dirty
            raise
          end
        end
      end

      private

      def load
        return unless @data.nil?

        value = @owner.read_json(@file, default: {})
        @data = value.is_a?(Hash) ? value.transform_keys(&:to_s) : {}
      end

      def flush
        return true unless @dirty

        raise Programs::ProgramError, 'Cannot save program settings' unless @owner.write_json(@file, @data)

        @dirty = false
        true
      end

      def duplicate(value)
        value.is_a?(Array) || value.is_a?(Hash) ? value.dup : value
      end
    end

    # What a definition block produced, in the order it produced it.
    class Collector
      attr_reader :entries, :category_label

      def initialize
        @entries = []
        @category_label = ''
      end

      # `category` here is the WRITER, because that is the name an
      # extension's settings block calls (`settings.category("...")`).
      # What it was set to is `category_label`.
      def setting_category(label)
        @category_label = label.to_s
        self
      end
      alias category setting_category

      def make_bound_setting(label, type, key, getter, setter, mapping = nil,
                             multi = false)
        @entries << BoundSetting.new(label.to_s, type, key.to_s, getter,
                                     setter, mapping, multi)
        self
      end

      def make_setting(label, type, callback)
        raise Programs::ProgramError, 'Unsupported quick-settings entry' if type != :custom

        @entries << ActionSetting.new(label.to_s, callback)
        self
      end
    end

    # Elten's own `Programs::Extensions::SettingsBuilder`: the shape an
    # extension's `service.settings` block is written against, and the
    # shape `Builder` below is built on top of.
    class SettingsBuilder
      def initialize(collector)
        @collector = collector
      end

      def category(label)
        @collector.setting_category(label)
        self
      end

      def boolean(key, label:, get: nil, set: nil, **_rest)
        @collector.make_bound_setting(label, :bool, key, get, set)
      end

      def integer(key, label:, range: nil, get: nil, set: nil, **_rest)
        @collector.make_bound_setting(label, :number, key, get, set, range)
      end

      def text(key, label:, get: nil, set: nil, **_rest)
        @collector.make_bound_setting(label, :text, key, get, set)
      end

      # **A choice's TYPE is its list of options.** That is Elten's own
      # shape (`ListBox.new(setting.type, header: setting.label, ...)`)
      # and it is worth writing down, because it reads like a mistake:
      # `type` is `:bool`, `:number` or `:text` for everything else and
      # an array of labels here, with `mapping` holding the values those
      # labels stand for.
      def choice(key, label:, choices:, get: nil, set: nil, **_rest)
        labels, values = split_choices(choices)
        @collector.make_bound_setting(label, labels, key, get, set, values, false)
      end

      def multi_choice(key, label:, choices:, get: nil, set: nil, **_rest)
        labels, values = split_choices(choices)
        @collector.make_bound_setting(label, labels, key, get, set, values, true)
      end

      def action(key, label:, &callback)
        @collector.make_setting(label, :custom, callback)
      end

      def render; self; end

      private

      # `{"Alphabetical" => "alpha"}`, `[["Alphabetical", "alpha"]]` and
      # `["alpha", "beta"]` are all ways an application writes a choice,
      # and Elten takes all three.
      def split_choices(choices)
        if choices.is_a?(Hash)
          [choices.keys.map(&:to_s), choices.values]
        else
          pairs = Array(choices).map do |entry|
            entry.is_a?(Array) && entry.size == 2 ? entry : [entry, entry]
          end
          [pairs.map { |label, _value| label.to_s }, pairs.map { |_label, value| value }]
        end
      end
    end

    # The application-facing builder. A field with no `get`/`set` of its own
    # is kept in `settings.json`; one with both is bound to whatever the
    # application keeps it in.
    class Builder
      def initialize(inner, store)
        @inner = inner
        @store = store
      end

      def boolean(key, label:, default: false, get: nil, set: nil)
        getter, setter = binding_for(key, default, get, set)
        @inner.boolean(key, label: label, get: getter, set: setter)
      end

      def integer(key, label:, default: UNSET, range: nil, get: nil, set: nil)
        default = range.begin if default.equal?(UNSET) && range.is_a?(Range)
        default = 0 if default.equal?(UNSET)
        getter, setter = binding_for(key, default, get, set)
        @inner.integer(key, label: label, range: range, get: getter, set: setter)
      end

      def text(key, label:, default: '', get: nil, set: nil)
        getter, setter = binding_for(key, default, get, set)
        @inner.text(key, label: label, get: getter, set: setter)
      end

      def choice(key, label:, choices:, default: UNSET, get: nil, set: nil)
        default = first_choice(choices) if default.equal?(UNSET)
        getter, setter = binding_for(key, default, get, set)
        @inner.choice(key, label: label, choices: choices, get: getter,
                           set: setter)
      end

      def multi_choice(key, label:, choices:, default: [], get: nil, set: nil)
        getter, setter = binding_for(key, default, get, set)
        @inner.multi_choice(key, label: label, choices: choices, get: getter,
                                 set: setter)
      end

      def action(key, label:, &callback)
        @inner.action(key, label: label, &callback)
      end

      def category(label)
        @inner.category(label)
      end

      private

      def binding_for(key, default, getter, setter)
        has_getter = !getter.nil?
        has_setter = !setter.nil?
        if has_getter != has_setter
          raise Programs::ProgramError,
                "Quick setting #{key} must provide both get and set or neither"
        end
        return [getter, setter] if has_getter

        store = @store
        [proc { store.get(key, default) },
         proc { |value| store.set(key, value) }]
      end

      def first_choice(choices)
        return choices.values.first if choices.is_a?(Hash)

        first = Array(choices).first
        first.is_a?(Array) && first.size == 2 ? first[1] : first
      end
    end

    # The form itself. Elten's own layout - the title, the fields, then
    # Apply, OK and Cancel - built out of Titan's controls.
    class Dialog
      def initialize(title, entries, store)
        @title = title.to_s
        @entries = entries
        @store = store
        @controls = []
        @result = :cancel
      end

      def show
        raise Programs::ProgramError, 'Program settings form cannot be empty' if @entries.empty?

        fields = []
        fields << Static.new(@title) unless @title.empty?
        @entries.each do |entry|
          if entry.is_a?(BoundSetting)
            control = control_for(entry)
            @controls << [entry, control]
            fields << control
          else
            fields << action_button(entry)
          end
        end
        apply = Button.new(_('Apply'))
        accept = Button.new(_('OK'))
        cancel = Button.new(_('Cancel'))
        fields.push(apply, accept, cancel)

        form = Form.new(fields, quiet: true, header: @title)
        form.accept_button = accept
        form.cancel_button = cancel
        apply.on(:press) { speak(_('Saved')) if apply_values }
        accept.on(:press) do
          if apply_values
            @result = :ok
            form.resume
          end
        end
        cancel.on(:press) do
          @result = :cancel
          form.resume
        end
        form.wait
        @result
      end

      private

      def control_for(setting)
        current = setting.getter.call
        case setting.type
        when :bool
          CheckBox.new(setting.label, checked: truthy?(current))
        when :number
          EditBox.new(setting.label, type: EditBox::Flags::Numbers,
                                     text: current.to_s, quiet: true)
        when :text
          EditBox.new(setting.label, type: 0, text: current.to_s, quiet: true)
        else
          choice_control(setting, current)
        end
      end

      def choice_control(setting, current)
        values = Array(setting.mapping)
        if setting.multi
          chosen = current.is_a?(Array) ? current : current.to_s.split(',')
          control = ListBox.new(Array(setting.type), header: setting.label,
                                                     index: 0,
                                                     flags: ListBox::Flags::MultiSelection)
          values.each_with_index do |value, index|
            control.selected[index] = true if chosen.map(&:to_s).include?(value.to_s)
          end
          control
        else
          index = values.index { |value| value.to_s == current.to_s } || 0
          ListBox.new(Array(setting.type), header: setting.label, index: index)
        end
      end

      def action_button(setting)
        button = Button.new(setting.label)
        button.on(:press) do
          begin
            setting.callback.call
          rescue Exception => error
            report(error)
          end
        end
        button
      end

      def apply_values
        @store.transaction do
          @controls.each { |setting, control| setting.setter.call(value_of(setting, control)) }
        end
        true
      rescue Exception => error
        report(error)
        false
      end

      def value_of(setting, control)
        return control.checked? if setting.type == :bool
        return control.text.to_i if setting.type == :number
        return control.text.to_s if setting.type == :text

        values = Array(setting.mapping)
        return values[control.index.to_i] unless setting.multi

        picked = []
        values.each_with_index { |value, index| picked << value if control.selected[index] }
        picked
      end

      def truthy?(value)
        return value if [true, false].include?(value)

        %w[true 1 yes on].include?(value.to_s.downcase)
      end

      def report(error)
        Log.error("Cannot apply program settings: #{error.class}: #{error.message}")
        alert(format(_('Cannot save settings: %s'), error.message.to_s))
      end
    end

    class << self
      # `show(owner, title:) { |settings| ... }` - collect, then show.
      def show(owner, title: '', &definition)
        raise Programs::ProgramError, 'Program settings definition is required' unless definition.is_a?(Proc)

        store = Store.new(owner)
        collector = Collector.new
        inner = SettingsBuilder.new(collector)
        inner.category(title.to_s.empty? ? _('Settings') : title.to_s)
        definition.call(Builder.new(inner, store))
        Dialog.new(title, collector.entries, store).show
      end

      # Everything an application's extensions declared, as one form. This
      # is what Elten's own settings window shows for a program, and the
      # only place the file manager's three switches can be reached.
      def show_extensions(owner, title: '')
        store = Store.new(owner)
        collector = Collector.new
        inner = SettingsBuilder.new(collector)
        builder = Builder.new(inner, store)
        owner.extensions.each_value do |recorder|
          recorder.blocks_for('settings').each do |_args, block|
            block&.call(builder)
          end
        end
        return :cancel if collector.entries.empty?

        Dialog.new(title.to_s.empty? ? _('Settings') : title.to_s,
                   collector.entries, store).show
      end
    end
  end
end

class Program
  class << self
    # Elten's own signature. Returns `:ok` or `:cancel`; Apply saves
    # without closing.
    def show_settings(title = nil, **options, &definition)
      title = options[:title] if options.key?(:title)
      title = display_name.to_s if title.nil? || title.to_s.empty?
      Programs::ProgramSettings.show(self, title: title, &definition)
    end

    def extension_settings(title = nil)
      Programs::ProgramSettings.show_extensions(
        self, title: title.to_s.empty? ? display_name.to_s : title.to_s
      )
    end

    # What this application is called, without going near `Class#name` -
    # overriding that is what once made every error message name a class
    # that does not exist.
    def display_name
      app_name
    rescue StandardError
      to_s
    end
  end

  def show_settings(title = nil, **options, &definition)
    self.class.show_settings(title, **options, &definition)
  end

  def extension_settings(title = nil)
    self.class.extension_settings(title)
  end
end
