# frozen_string_literal: true

# `read_url`, `download_file` - Elten's own `src/eapi/network.rb`.
#
# These are the SYNCHRONOUS half of the network, and the half applications
# reach for most: `EltenAPI::HTTPClient.readurl` answers through a block on
# a thread of its own (which is what the media catalogue's page loading
# uses), while `read_url` blocks and hands back the body. Both exist in
# Elten and applications use both - the YouTube client asks `read_url` for
# its update manifests before it has a screen at all, and a missing one is
# `NoMethodError` at class level, before anything is on the screen to say
# so.
#
# Written against Elten's own signatures: `read_url(url, method:, body:,
# headers:, cancellation_token:)`, where a Hash `body` is sent as a
# multipart form and `headers` is FILLED IN with the response's headers -
# an application reads the content type back out of the hash it passed.
module EltenNetwork
  MAX_SECONDS = 30.0

  module_function

  def read_url(url, method: :get, body: nil, headers: nil,
               cancellation_token: nil)
    _raise_if_cancelled(cancellation_token)
    headers = {} if headers.nil?
    body, headers = _multipart(body, headers) if body.is_a?(Hash)

    answer = EltenAPI::HTTPClient.readurl_sync(
      url.to_s, method.to_s, body.to_s, headers, nil, 0,
      cancellation_token: cancellation_token
    )
    # Elten replaces the caller's hash with the RESPONSE headers, and
    # applications read the content type back out of it.
    if headers.is_a?(Hash)
      headers.clear
      Array(answer[:headers]).each { |key, value| headers[key] = value }
    end
    answer[:body]
  rescue StandardError => error
    Log.warning("#{url} could not be read: #{error.class}: #{error.message}")
    nil
  end

  # Straight to a file, so a download does not have to fit in memory.
  def download_file(source, destination, use_waiting: true, can_cancel: true,
                    override: false, cancellation_token: nil)
    _raise_if_cancelled(cancellation_token)
    if !override && File.exist?(destination.to_s)
      return nil unless Kernel.confirm(_('The file already exists. Do you want to overwrite it?'))
    end

    require 'fileutils'
    FileUtils.mkdir_p(File.dirname(destination.to_s))
    content = read_url(source, cancellation_token: cancellation_token)
    return nil if content.nil?

    File.binwrite(destination.to_s, content)
    destination.to_s
  rescue StandardError => error
    Log.warning("#{source} could not be downloaded: #{error.message}")
    nil
  end

  def html_decode(text)
    text.to_s.gsub('&lt;', '<').gsub('&gt;', '>').gsub('&quot;', '"')
        .gsub('&#39;', "'").gsub('&nbsp;', ' ').gsub('&amp;', '&')
  end

  def html_encode(text)
    text.to_s.gsub('&', '&amp;').gsub('<', '&lt;').gsub('>', '&gt;')
        .gsub('"', '&quot;').gsub("'", '&#39;')
  end

  def _multipart(body, headers)
    boundary = ''
    values = body.values.map { |value| value.to_s.b }
    while boundary.empty? || values.any? { |value| value.include?(boundary) }
      boundary = "----EltBoundary#{rand(36**32).to_s(36)}"
    end
    text = ''.b
    body.each_key do |key|
      text << "--#{boundary}\r\nContent-Disposition: form-data; name=\"#{key}\"\r\n\r\n".b
      text << body[key].to_s.b
      text << "\r\n".b
    end
    text << "--#{boundary}--".b
    headers = headers.dup
    headers['Content-Type'] = "multipart/form-data; boundary=#{boundary}"
    [text, headers]
  end

  def _raise_if_cancelled(token)
    return if token.nil? || !token.respond_to?(:raise_if_cancelled!)

    token.raise_if_cancelled!
  end
end

# On `Object`, because Elten's are: an application calls `read_url` from
# anywhere, at class level as readily as inside a method, and a `Program`
# that has to reach for a module name is a `Program` written for a
# different platform.
module Kernel
  def read_url(url, **options)
    EltenNetwork.read_url(url, **options)
  end

  def download_file(source, destination, **options)
    EltenNetwork.download_file(source, destination, **options)
  end

  def html_decode(text)
    EltenNetwork.html_decode(text)
  end

  def html_encode(text)
    EltenNetwork.html_encode(text)
  end

  # Elten's own spelling of "is there a network at all".
  def netcheck
    true
  end
end
