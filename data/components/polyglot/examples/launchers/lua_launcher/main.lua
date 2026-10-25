-- A launcher in Lua. Titan calls start(api) and runs until it returns; the
-- launcher API is reached with titan.host(api, "method", {arguments}).

function start(api)
  titan.speak("Lua launcher")
  while true do
    local apps = titan.host(api, "get_applications") or {}
    local names = {}
    for i, app in ipairs(apps) do names[i] = app.name end
    names[#names + 1] = "Settings"
    names[#names + 1] = "Exit"
    local chosen = titan.choose("Titan", names, "Lua launcher")
    if chosen == nil or chosen == #names then
      return
    elseif chosen == #names - 1 then
      titan.host(api, "show_settings")
    else
      titan.host(api, "open_application", {apps[chosen]})
    end
  end
end
