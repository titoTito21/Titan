# frozen_string_literal: false
#
# ---------------------------------------------------------------------------
# `EltenAPI::Resources::Registry` is ELTEN'S OWN CODE, used unchanged.
#
#   From: https://github.com/dawidpieper/elten3  ->  src/eapi/resources.rb
#   Copyright (C) 2014-2026 Dawid Pieper
#   Licensed under the GNU General Public License version 3.
#
# The vendored `Runner` builds one of these for the resources a game holds
# during a round, so it has to be exactly this: `manage(resource,
# release: :close)` takes a symbol OR a block, `close` disposes in reverse,
# and a disposer that raises is logged rather than allowed to stop the rest.
#
# Only the `Registry` is taken. The rest of Elten's `resources.rb` reads
# resources out of Elten's own packaged tree, which is not something a
# `Runner` needs and not how a `.eltenapp` stores anything.
# ---------------------------------------------------------------------------

module EltenAPI
  module Resources
    class Registry
      Entry = Struct.new(:resource, :release)

      def initialize
        @entries = []
        @mutex = Mutex.new
        @closed = false
      end

      def manage(resource, release: :close, &block)
        raise ArgumentError, "resource is required" if resource == nil
        disposer = block || release
        if !disposer.respond_to?(:call) && !resource.respond_to?(disposer)
          raise ArgumentError, "resource cannot be released with #{disposer.inspect}"
        end
        @mutex.synchronize do
          raise RuntimeError, "resource registry is closed" if @closed
          @entries << Entry.new(resource, disposer)
        end
        resource
      end

      def release(resource, close: false)
        entry = @mutex.synchronize do
          index = @entries.rindex { |item| item.resource.equal?(resource) }
          index == nil ? nil : @entries.delete_at(index)
        end
        dispose(entry) if entry != nil && close == true
        entry != nil
      end

      def include?(resource)
        @mutex.synchronize { @entries.any? { |entry| entry.resource.equal?(resource) } }
      end

      def size
        @mutex.synchronize { @entries.size }
      end

      def close
        entries = @mutex.synchronize do
          return 0 if @closed
          @closed = true
          current = @entries
          @entries = []
          current
        end
        entries.reverse_each { |entry| dispose(entry) }
        entries.size
      end

      def closed?
        @mutex.synchronize { @closed == true }
      end

      private

      def dispose(entry)
        disposer = entry.release
        if disposer.respond_to?(:call)
          disposer.arity == 0 ? disposer.call : disposer.call(entry.resource)
        else
          entry.resource.public_send(disposer)
        end
      rescue Exception => e
        Log.warning("Cannot release managed resource: #{e.class}: #{e.message}") if defined?(Log)
        nil
      end
    end
  end
end
