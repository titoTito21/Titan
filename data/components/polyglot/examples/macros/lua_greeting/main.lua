-- A macro in Lua. It runs once, like a Titan Script, with the whole Polyglot
-- API: speech, dialogs, sounds and every Titan action.

function main()
  local name = titan.ask("What is your name?", "")
  if name == nil or name == "" then
    titan.speak("Hello")
    return
  end
  titan.speak("Hello, " .. name)
  -- Any add-on's action is one call away: titan.action(addon, action, {args}).
  titan.action("macros", "list_macros")
end
