# A Titan application written in Ruby.
require 'titan'

polish = Titan.info['language'] == 'pl'
t = ->(en, pl) { polish ? pl : en }

name = Titan.ask(t.('What is your name?', 'Jak masz na imię?'))
exit if name.nil?
Titan.speak(t.('Hello from Ruby, ', 'Cześć z Ruby, ') + name)
fruits = [t.('Apple', 'Jabłko'), t.('Pear', 'Gruszka'), t.('Plum', 'Śliwka')]
index = Titan.choose(t.('Pick a fruit', 'Wybierz owoc'), fruits)
Titan.message(t.('You picked: ', 'Wybrano: ') + fruits[index]) unless index.nil?
