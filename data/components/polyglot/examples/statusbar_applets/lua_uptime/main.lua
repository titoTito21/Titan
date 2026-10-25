-- A statusbar applet in Lua. get_statusbar_item_text is asked every
-- update_interval seconds; Enter on the item calls on_statusbar_item_activate.

local started = os.time()

local function minutes()
  return math.floor((os.time() - started) / 60)
end

function get_statusbar_item_text()
  return "Session: " .. minutes() .. " min"
end

function on_statusbar_item_activate(parent)
  titan.message("Titan has been running for " .. minutes() .. " minutes.")
end
