-- An audio game written in Lua. A ball falls in one of five columns; you
-- hear where, move the basket with Left and Right, and catch it with Space.
local polish = titan.info().language == "pl"
local function t(en, pl) if polish then return pl else return en end end
local function place(column) return (column - 3) / 2 end   -- -1 .. 1

titan.open_window(t("Catch the balls", "Łapanie piłek"))
titan.speak(t("Left and Right move the basket, Space catches, Escape ends.",
              "Strzałki w lewo i w prawo przesuwają koszyk, spacja łapie, "
              .. "Escape kończy."))
titan.wait(3)

local basket, score, misses = 3, 0, 0
local running = true
while running and misses < 3 do
  local ball = math.random(1, 5)
  titan.play("ui/notify.ogg", place(ball))
  local deadline = os.time() + 3
  local caught = false
  while running and os.time() < deadline do
    local e = titan.next_event(0.1)
    if e then
      if e.type == "close" or (e.type == "key" and e.down and e.key == "escape") then
        running = false
      elseif e.type == "key" and e.down then
        if e.key == "left" and basket > 1 then
          basket = basket - 1
          titan.speak(tostring(basket), true, place(basket))
        elseif e.key == "right" and basket < 5 then
          basket = basket + 1
          titan.speak(tostring(basket), true, place(basket))
        elseif e.key == "space" then
          caught = basket == ball
          break
        end
      end
    end
  end
  if not running then break end
  if caught then
    score = score + 1
    titan.play("core/SELECT.ogg", place(ball))
    titan.speak(t("Caught! ", "Złapana! ") .. score, true, place(ball))
  else
    misses = misses + 1
    titan.play("core/error.ogg", place(ball))
    titan.speak(t("Missed, it was in column ", "Pudło, była w kolumnie ") .. ball,
                true, place(ball))
  end
  titan.wait(1.2)
end
titan.speak(t("Game over. Score: ", "Koniec gry. Wynik: ") .. score, true)
titan.wait(2.5)
