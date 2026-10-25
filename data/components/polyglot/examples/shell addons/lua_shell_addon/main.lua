-- A shell add-on in Lua. Each surface calls the hook of the same name a
-- Python add-on defines; an entry's action is a Lua function Titan keeps.

function start_menu_items(api, menu)
  return {
    {id = "lua_hello", label = "Hello from Lua",
     action = function() titan.message("Hello from a shell add-on in Lua") end},
  }
end
