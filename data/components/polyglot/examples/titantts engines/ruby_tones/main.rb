# A TTS engine in Ruby. It does not speak words: it plays one short tone per
# letter, higher for vowels, which shows the whole contract - generate()
# answers the path of a WAV file it wrote.
require 'titan'

RATE = 22_050
VOWELS = 'aeiouy'
voice = 'high'
speed = 0
out_dir = Titan.data_dir

def tone(frequency, seconds)
  count = (RATE * seconds).to_i
  (0...count).map do |i|
    fade = [i, count - i, 400].min / 400.0
    (Math.sin(2 * Math::PI * frequency * i / RATE) * 9000 * fade).round
  end
end

def write_wav(path, samples)
  data = samples.pack('s<*')
  header = ['RIFF', 36 + data.bytesize, 'WAVE', 'fmt ', 16, 1, 1, RATE,
            RATE * 2, 2, 16, 'data', data.bytesize].pack('a4Va4a4VvvVVvva4V')
  File.binwrite(path, header + data)
end

Titan.serve(
  'is_available' => -> { true },
  'get_voices' => lambda {
    [{ 'id' => 'high', 'display_name' => 'High' },
     { 'id' => 'low', 'display_name' => 'Low' }]
  },
  'set_voice' => ->(id) { voice = id; nil },
  'set_rate' => ->(rate) { speed = rate.to_i; nil },
  'generate' => lambda { |text, pitch|
    base = voice == 'low' ? 220.0 : 440.0
    base *= 2**(pitch.to_f / 12)
    length = 0.09 - speed * 0.005
    samples = []
    text.to_s.each_char do |c|
      if c =~ /\s/
        samples.concat([0] * (RATE * length).to_i)
      else
        samples.concat(tone(VOWELS.include?(c.downcase) ? base * 1.5 : base,
                            length))
      end
    end
    path = File.join(out_dir, "tones_#{Process.pid}.wav")
    write_wav(path, samples)
    path
  }
)
