# frozen_string_literal: true

module HTTP2
  # Default values for SETTINGS frame, as defined by the spec.
  SPEC_DEFAULT_CONNECTION_SETTINGS = {
    settings_header_table_size: 4096,
    settings_enable_push: 1, # enabled for servers
    settings_max_concurrent_streams: Framer::MAX_STREAM_ID, # unlimited
    settings_initial_window_size: 65_535,
    settings_max_frame_size: 16_384,
    settings_max_header_list_size: (2 << 30) - 1 # unlimited
  }.freeze

  Settings = Struct.new(
    :settings_header_table_size,
    :settings_enable_push,
    :settings_max_concurrent_streams,
    :settings_initial_window_size,
    :settings_max_frame_size,
    :settings_max_header_list_size,
    keyword_init: true
  ) do
    def initialize(
      settings_header_table_size: 4096,
      settings_enable_push: 1,
      settings_max_concurrent_streams: 100,
      settings_initial_window_size: 65_535,
      settings_max_frame_size: 16_384,
      settings_max_header_list_size: (2 << 30) - 1
    )
      super
    end

    def each_setting
      each_pair do |k, v|
        next if v == SPEC_DEFAULT_CONNECTION_SETTINGS[k]

        yield k, v
      end
    end
  end
end
