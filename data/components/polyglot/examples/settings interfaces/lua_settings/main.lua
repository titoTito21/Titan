-- A settings interface in Lua. Titan calls open_settings(api); the settings
-- are read and changed through the same API a Python interface has.

local function label(entry)
  return entry.label or entry.name or entry.id or "?"
end

function open_settings(api)
  while true do
    local categories = titan.host(api, "categories") or {}
    local names = {}
    for i, category in ipairs(categories) do names[i] = label(category) end
    names[#names + 1] = "Save and close"
    local c = titan.choose("Settings", names)
    if c == nil then
      titan.host(api, "cancel")
      return true
    end
    if c == #names then
      titan.host(api, "save")
      return true
    end
    local items = categories[c].items or {}
    local item_names = {}
    for i, item in ipairs(items) do
      item_names[i] = label(item) .. ": " .. tostring(item.value)
    end
    local i = titan.choose(names[c], item_names)
    if i ~= nil then
      local item = items[i]
      local value = titan.ask(label(item), tostring(item.value or ""))
      if value ~= nil then titan.host(api, "set", {item.id, value}) end
    end
  end
end
