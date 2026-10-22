-- A Titan application written in Lua. Polyglot gives it the global `titan`.
local polish = titan.info().language == "pl"
local function t(en, pl) if polish then return pl else return en end end

local name = titan.ask(t("What is your name?", "Jak masz na imię?"), "")
if name == nil then return end
if name == "" then name = t("stranger", "nieznajomy") end
titan.speak(t("Hello, ", "Cześć, ") .. name .. "!")

local options = {
  t("Say hello", "Przywitaj się"),
  t("What time is it?", "Która godzina?"),
  t("Roll a die", "Rzuć kostką"),
  t("Write a note in Notes", "Zapisz notatkę w Notatkach"),
  t("About this program", "O programie"),
  t("Exit", "Wyjście"),
}
local chosen = 1
while true do
  local i = titan.choose(t("What shall I do?", "Co mam zrobić?"), options, nil, chosen)
  if i == nil or i == #options then break end
  chosen = i
  if i == 1 then
    titan.play("ui/notify.ogg")
    titan.speak(t("Hello from Lua, ", "Cześć z Lua, ") .. name)
  elseif i == 2 then
    titan.speak(os.date("%H:%M"))
  elseif i == 3 then
    titan.speak(t("You rolled ", "Wypadło ") .. math.random(1, 6))
  elseif i == 4 then
    local text = titan.ask(t("What shall the note say?", "Co ma być w notatce?"),
                           "", nil, true)
    if text and text ~= "" then
      local ok, answer = titan.action("tnotes", "create_note",
                                      {title = t("From Lua", "Z Lua"), text = text})
      titan.message(answer)
    end
  elseif i == 5 then
    titan.text(t("This program is written in Lua and runs inside Titan "
                 .. "through the Polyglot component.",
                 "Ten program jest napisany w Lua i działa w Titanie "
                 .. "dzięki komponentowi Polyglot."),
               t("About", "O programie"))
  end
end
titan.speak(t("Goodbye, ", "Do widzenia, ") .. name)
