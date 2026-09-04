# frozen_string_literal: true

# `EltenAPI` - the namespace applications reach into by name.
#
# Elten's own platform is organised as `module EltenAPI` with `UI`,
# `Controls`, `Tasks`, `HTTPClient` and the rest inside it, and applications
# both `include EltenAPI` (to get its methods as their own) and name things
# through it (`::EltenAPI::Tasks::Cancelled`, `::EltenAPI::HTTPClient`). Both
# have to work, or an application stops on `uninitialized constant` before it
# has drawn anything.
#
# Everything here is a thin front onto what `eapi.rb`, `program.rb` and
# `controls.rb` already do, so there is one implementation and two ways of
# spelling it.

module EltenAPI
  # `include EltenAPI` gets the platform's own methods. They are defined on
  # `Kernel`, so every object already has them - this exists so the include
  # succeeds and so `EltenAPI.speak(...)` works as a module function too.
  module UI; end
  module Controls; end

  # `EltenAPI::KeyboardScheme` - which modifier is the main one on this
  # machine, and what it is called. Applications name it directly as well
  # as through the `main_modifier_name` on Kernel.
  module KeyboardScheme
    class << self
      def current
        :windows
      end

      def main_modifier
        :control
      end

      def word_modifier
        :control
      end

      def modifier_name(modifier = :main_modifier)
        Kernel.instance_method(:modifier_name).bind(Object.new).call(modifier)
      rescue StandardError
        modifier.to_s.upcase
      end

      def binding(_action)
        nil
      end
    end
  end

  Tasks = ::Tasks

  class << self
    def speak(text, **options)
      Speech.speak(text, **options)
    end

    def alert(text, wait = true)
      Kernel.alert(text, wait)
    end

    def confirm(text = '')
      Kernel.confirm(text)
    end
  end

  # `EltenAPI::HTTPClient.readurl` - fetching a page, Elten's own way.
  #
  # **It answers through a BLOCK, on a thread, and that is the whole of
  # it.** `readurl(url, method, body, headers, data, redirects,
  # cancellation_token:) { |body, data, headers| }` - the call returns the
  # thread at once and the answer arrives in the block later. A version
  # that fetched the page synchronously and RETURNED the body looks
  # correct, runs, fetches the right page and never calls the block: the
  # media catalogue pushes into a Queue from inside it and then polls that
  # Queue until something arrives, so it said "Loading..." and stayed there
  # for ever. Every screen behind the first one was unreachable.
  #
  # A failure calls the block with `:error`, because that is what an
  # application tests for (`raise RequestError if body == :error`) - a
  # block that is simply never called is a hang, which is the worst way to
  # report that a page could not be fetched.
  #
  # What is deliberately not here is anything that lets a page decide what
  # runs: this answers bytes, over http and https only, with a cap on how
  # many, a timeout and a redirect limit.
  module HTTPClient
    MAX_REDIRECTS = 5
    MAX_BYTES = 32 * 1024 * 1024
    TIMEOUT = 20.0

    class << self
      def readurl(url, method = 'get', body = '', headers = {}, data = nil,
                  redirects = 0, cancellation_token: nil, &block)
        Thread.new do
          Thread.current.report_on_exception = false
          begin
            answer = readurl_sync(url, method, body, headers, data, redirects,
                                  cancellation_token: cancellation_token)
            _answer(block, answer[:body], data, answer[:headers])
          rescue StandardError => error
            Log.warning("#{url}: #{error.class}: #{error.message}")
            _answer(block, :error, data, {})
          end
        end
      end

      def readurl_sync(url, method = 'get', body = '', headers = {},
                       _data = nil, redirects = 0, cancellation_token: nil)
        require 'net/http'
        require 'uri'
        raise 'too many redirects' if redirects > MAX_REDIRECTS

        _raise_if_cancelled(cancellation_token)
        parsed = URI.parse(url.to_s)
        unless parsed.is_a?(URI::HTTP) || parsed.is_a?(URI::HTTPS)
          raise "refused to fetch #{parsed.scheme.inspect}: only http and https"
        end

        response = Net::HTTP.start(parsed.host, parsed.port,
                                   use_ssl: parsed.is_a?(URI::HTTPS),
                                   open_timeout: TIMEOUT,
                                   read_timeout: TIMEOUT) do |http|
          http.request(_request_for(parsed, method, body, headers))
        end

        if response.is_a?(Net::HTTPRedirection) && response['location']
          return readurl_sync(URI.join(url.to_s, response['location']).to_s,
                              method, body, headers, nil, redirects + 1,
                              cancellation_token: cancellation_token)
        end

        content = response.body.to_s
        raise 'the response is too large' if content.bytesize > MAX_BYTES

        { body: content, headers: _headers_of(response),
          code: response.code.to_i }
      end

      alias read readurl
      alias get readurl

      private

      def _request_for(parsed, method, body, headers)
        name = method.to_s.downcase
        request = case name
                  when 'post' then Net::HTTP::Post.new(parsed)
                  when 'put' then Net::HTTP::Put.new(parsed)
                  when 'delete' then Net::HTTP::Delete.new(parsed)
                  when 'head' then Net::HTTP::Head.new(parsed)
                  else Net::HTTP::Get.new(parsed)
                  end
        request['User-Agent'] = 'Titan-EltenBridge/1.0'
        Hash(headers).each { |key, value| request[key.to_s] = value.to_s }
        request.body = body.to_s unless body.nil? || body.to_s.empty? ||
                                        name == 'get' || name == 'head'
        request
      end

      def _headers_of(response)
        found = {}
        response.each_header { |key, value| found[key.to_s] = value }
        found
      end

      def _raise_if_cancelled(token)
        return if token.nil?
        return unless token.respond_to?(:raise_if_cancelled!)

        token.raise_if_cancelled!
      end

      # An application's own block must not be able to take the fetching
      # thread - and with it every later request - down with it.
      def _answer(block, body, data, headers)
        return if block.nil?

        block.call(body, data, headers)
      rescue StandardError => error
        Log.warning("a page's handler raised: #{error.class}: #{error.message}")
      end
    end
  end
end

# The applications that say `include EltenAPI` expect the platform's methods
# to become theirs. They are on `Kernel` already, so the include is a
# formality - but it must not fail, and `EltenAPI::UI`/`Controls` must exist
# because applications name them.
module EltenAPI
  module UI
    include Kernel
  end

  module Controls
    ListBox = ::ListBox
    EditBox = ::EditBox
    Button = ::Button
    CheckBox = ::CheckBox
    Form = ::Form
    TableBox = ::TableBox
    Menu = ::Menu
    FilesTree = ::FilesTree
    Tree = ::Tree
    GridBox = ::GridBox
    Player = ::Player
    ChoiceListBox = ::ChoiceListBox
  end
end
