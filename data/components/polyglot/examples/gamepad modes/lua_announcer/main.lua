-- A gamepad mode in Lua. handle_button and the others are called with what
-- the pad did; answer true when the mode used it. The gamepad helpers
-- (tap, press, type_text) are titan.host("gamepad", "tap", {"ctrl+c"}).

function on_activate(manager)
  titan.speak("Button announcer")
end

function handle_button(button)
  titan.speak("Button " .. button)
  return true
end

function handle_hat(x, y)
  if x == 1 then titan.host("gamepad", "tap", {"right"})
  elseif x == -1 then titan.host("gamepad", "tap", {"left"})
  elseif y == 1 then titan.host("gamepad", "tap", {"up"})
  elseif y == -1 then titan.host("gamepad", "tap", {"down"})
  end
  return true
end
