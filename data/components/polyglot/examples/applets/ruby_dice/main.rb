# A widget in Ruby. Titan calls these functions by name; Titan.serve answers.
require 'titan'

last = 'Not thrown yet'

Titan.serve(
  'navigate' => ->(_direction) { false },
  'get_current_element' => -> { "Dice: #{last}" },
  'activate_current_element' => lambda {
    a = rand(1..6)
    b = rand(1..6)
    last = "#{a} and #{b}, #{a + b} in all"
    Titan.speak(last)
    nil
  }
)
