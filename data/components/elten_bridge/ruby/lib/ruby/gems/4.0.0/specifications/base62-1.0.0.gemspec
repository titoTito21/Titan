# -*- encoding: utf-8 -*-
# stub: base62 1.0.0 ruby lib

Gem::Specification.new do |s|
  s.name = "base62".freeze
  s.version = "1.0.0".freeze

  s.required_rubygems_version = Gem::Requirement.new(">= 0".freeze) if s.respond_to? :required_rubygems_version=
  s.require_paths = ["lib".freeze]
  s.authors = ["JT Zemp".freeze, "Lasse Bunk".freeze, "Saadiq Rodgers-King".freeze, "Derrick Camerino".freeze]
  s.date = "2014-01-16"
  s.description = "Base62 monkeypatches Integer to add an Integer#base62_encode\n                       instance method to encode an integer in the character set of\n                       0-9 + A-Z + a-z. It also monkeypatches String to add\n                       String#base62_decode to take the string and turn it back\n                       into a valid integer.".freeze
  s.email = ["jtzemp@gmail.com".freeze, "lasse@bunk.io".freeze]
  s.homepage = "https://github.com/jtzemp/base62".freeze
  s.licenses = ["MIT".freeze]
  s.rubygems_version = "2.0.7".freeze
  s.summary = "Monkeypatches Integer and String to allow for base62 encoding and decoding.".freeze

  s.installed_by_version = "4.0.16".freeze

  s.specification_version = 4

  s.add_development_dependency(%q<bundler>.freeze, ["~> 1.3".freeze])
  s.add_development_dependency(%q<rake>.freeze, [">= 0".freeze])
end
