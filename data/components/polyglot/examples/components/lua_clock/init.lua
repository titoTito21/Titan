-- A Titan component written in Lua. It runs inside Titan for as long as
-- Titan runs, and adds an entry to the Components menu.
local polish = titan.info().language == "pl"

local function say_time()
  if polish then
    titan.speak("Jest godzina " .. os.date("%H:%M"))
  else
    titan.speak("It is " .. os.date("%H:%M"))
  end
end

titan.add_menu(polish and "Zegar Lua: powiedz godzinę" or "Lua clock: say the time",
               say_time)

function initialize()
  titan.log("Lua clock is ready")
end

function shutdown()
  titan.log("Lua clock stopped")
end
