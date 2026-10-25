-- A widget in Lua, driven by the Invisible UI. The functions are the ones a
-- Python widget's instance has: navigate, get_current_element,
-- activate_current_element.

local counters = {0, 0, 0}
local names = {"Apples", "Pears", "Plums"}
local at = 1

function get_widget_info()
  return {name = "Lua counter", type = "grid"}
end

function create()
  at = 1
end

function navigate(direction)
  if direction == "left" and at > 1 then
    at = at - 1
  elseif direction == "right" and at < #names then
    at = at + 1
  else
    return {false, at - 1, #names}
  end
  return {true, at - 1, #names}
end

function get_current_element()
  return names[at] .. ": " .. counters[at]
end

function activate_current_element()
  counters[at] = counters[at] + 1
  titan.speak(get_current_element())
end
