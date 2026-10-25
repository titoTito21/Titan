-- A Titan IM module in Lua. Titan calls open(parent) when the entry is
-- pressed, and get_status_text() whenever it lists Titan IM.
-- The module's own objects are reachable by name: titan.host("sounds", ...).

local sent = 0

function get_status_text()
  if sent == 0 then return "" end
  return "(" .. sent .. ")"
end

function open(parent)
  titan.host("sounds", "welcome")
  while true do
    local text = titan.ask("Write something. Leave it empty to close.", "",
                           "Lua echo")
    if text == nil or text == "" then
      titan.host("sounds", "goodbye")
      return
    end
    sent = sent + 1
    titan.host("sounds", "message_sent")
    titan.speak("You wrote: " .. text)
  end
end
