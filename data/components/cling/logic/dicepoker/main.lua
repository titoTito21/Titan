-- Dice poker, for Cling.
--
-- The application's own texts are the rules, and they are unusually complete:
-- readme.txt says "a variation of Yahtzee ... rolling five dice to make certain
-- combinations", cantroll.txt says "You can roll dices only 3 times in one turn.
-- Press tab to go to score card and choose a point category", and the score card
-- is named category by category - ones..sixes, pair, twopairs, threeofkind,
-- fourofkind, fullhouse, smallstraight, bigstraight, poker, chance - with
-- schoolbonus "30 points bonus for good school results", schoolpenalty and
-- figurebonus "30 points bonus for having all big figures".
--
-- So the categories, the bonuses and the three rolls are the application's;
-- what is here is the arithmetic and the turn.

local DICE = 5
local ROLLS = 3

local SCHOOL = { 'ones', 'twos', 'threes', 'fours', 'fives', 'sixes' }
local FIGURES = { 'pair', 'twopairs', 'threeofkind', 'fourofkind',
                  'fullhouse', 'smallstraight', 'bigstraight', 'poker' }

local dice, held, rolls_left, card, where, cursor, over

local function counts()
	local n = {0,0,0,0,0,0}
	for _, value in ipairs(dice) do n[value] = n[value] + 1 end
	return n
end

local function total_of(values)
	local sum = 0
	for _, value in ipairs(values) do sum = sum + value end
	return sum
end

local function score_for(name)
	local n = counts()
	for face = 1, 6 do
		if name == SCHOOL[face] then return n[face] * face end
	end
	if name == 'pair' then
		for face = 6, 1, -1 do if n[face] >= 2 then return face * 2 end end
		return 0
	end
	if name == 'twopairs' then
		local found, sum = 0, 0
		for face = 6, 1, -1 do
			if n[face] >= 2 then found = found + 1 sum = sum + face * 2 end
		end
		if found >= 2 then return sum end
		return 0
	end
	if name == 'threeofkind' then
		for face = 6, 1, -1 do if n[face] >= 3 then return face * 3 end end
		return 0
	end
	if name == 'fourofkind' then
		for face = 6, 1, -1 do if n[face] >= 4 then return face * 4 end end
		return 0
	end
	if name == 'fullhouse' then
		local three, two = 0, 0
		for face = 1, 6 do
			if n[face] == 3 then three = face end
			if n[face] == 2 then two = face end
		end
		if three > 0 and two > 0 then return three * 3 + two * 2 end
		return 0
	end
	if name == 'smallstraight' then
		if n[1] == 1 and n[2] == 1 and n[3] == 1 and n[4] == 1 and n[5] == 1 then
			return 15
		end
		return 0
	end
	if name == 'bigstraight' then
		if n[2] == 1 and n[3] == 1 and n[4] == 1 and n[5] == 1 and n[6] == 1 then
			return 20
		end
		return 0
	end
	if name == 'poker' then
		for face = 1, 6 do if n[face] == 5 then return 50 end end
		return 0
	end
	if name == 'chance' then return total_of(dice) end
	return 0
end

local function all_slots()
	local out = {}
	for _, name in ipairs(SCHOOL) do out[#out + 1] = name end
	for _, name in ipairs(FIGURES) do out[#out + 1] = name end
	out[#out + 1] = 'chance'
	return out
end

local SLOTS = all_slots()

local function school_total()
	local sum = 0
	for _, name in ipairs(SCHOOL) do sum = sum + (card[name] or 0) end
	return sum
end

local function figure_total()
	local sum = 0
	for _, name in ipairs(FIGURES) do sum = sum + (card[name] or 0) end
	return sum
end

local function grand_total()
	local school = school_total()
	local figures = figure_total()
	local chance = card['chance'] or 0
	local sum = school + figures + chance
	-- The bonuses the application names, in its own words.
	if school >= 63 then sum = sum + 30 end
	if school > 0 and school < 42 then sum = sum - 30 end
	local complete = true
	for _, name in ipairs(FIGURES) do
		if not card[name] or card[name] == 0 then complete = false end
	end
	if complete then sum = sum + 30 end
	return sum, school, figures, chance
end

local function say_dice()
	local said = {}
	for index, value in ipairs(dice) do
		said[#said + 1] = tostring(value) .. (held[index] and '*' or '')
	end
	cling.show(cling.text('table') .. ': ' .. table.concat(said, ' '))
end

local function roll()
	if rolls_left <= 0 then
		cling.show(cling.text('cantroll'))
		return
	end
	for index = 1, DICE do
		if not held[index] then
			dice[index] = math.random(1, 6)
			-- Each die is thrown from its own place across the table, so five
			-- dice are five sounds rather than one noise.
			local pan = -1.0 + (index - 1) * 0.5
			cling.play('dice' .. tostring(math.random(1, 5)) .. '_1', pan, 0.9)
		end
	end
	rolls_left = rolls_left - 1
	say_dice()
end

local function say_slot()
	local name = SLOTS[cursor]
	local taken = card[name]
	if taken ~= nil then
		cling.say(string.format('%s, %s', cling.text(name),
			string.format(cling.text('pointsfmt'), tostring(taken))))
	else
		cling.say(string.format('%s, %s', cling.text(name),
			string.format(cling.text('possiblepointsfmt'),
			              tostring(score_for(name)))))
	end
end

local function finished()
	for _, name in ipairs(SLOTS) do
		if card[name] == nil then return false end
	end
	return true
end

local function new_turn()
	held = {}
	rolls_left = ROLLS
	where = 'table'
	roll()
end

local function take(name)
	if card[name] ~= nil then
		cling.play('fullslot')
		return
	end
	card[name] = score_for(name)
	cling.play('goodslot')
	local total, school, figures, chance = grand_total()
	cling.show(string.format(cling.text('pointssavedfmt'),
	                         tostring(card[name]), tostring(total)))
	if finished() then
		over = true
		cling.show(string.format(cling.text('gamesummaryfmt'), tostring(total),
		                         tostring(school), tostring(figures),
		                         tostring(chance)))
		cling.record_score(total)
		cling.publish_score(total)
		return
	end
	new_turn()
end

function on_start()
	math.randomseed(os.time())
	dice = {1,1,1,1,1}
	card = {}
	over = false
	cursor = 1
	cling.show(cling.text('letsbegin'))
	cling.show(cling.text('helpstart'))
	new_turn()
end

function on_key(key)
	if over then
		if key == 'n' or key == 'space' or key == 'enter' then on_start() return true end
		return false
	end
	if key == 'tab' then
		where = (where == 'table') and 'card' or 'table'
		cling.show(cling.text(where == 'card' and 'scoreboard' or 'table'))
		if where == 'card' then say_slot() else say_dice() end
		return true
	end
	if key == 'f1' then cling.show(cling.text('help')) return true end

	if where == 'table' then
		-- 1..5 hold and release a die; that is what choosedices.txt asks for.
		for index = 1, DICE do
			if key == tostring(index) then
				held[index] = not held[index]
				cling.play(held[index] and 'emptyslot' or 'fullslot')
				cling.say(tostring(dice[index]) .. (held[index] and ' *' or ''))
				return true
			end
		end
		if key == 'space' or key == 'r' then roll() return true end
		if key == 'enter' then say_dice() return true end
		return false
	end

	if key == 'up' or key == 'left' then
		cursor = ((cursor - 2) % #SLOTS) + 1 say_slot() return true
	end
	if key == 'down' or key == 'right' then
		cursor = (cursor % #SLOTS) + 1 say_slot() return true
	end
	if key == 'enter' or key == 'space' then take(SLOTS[cursor]) return true end
	return false
end

function status()
	if over then return cling.text('summary') end
	local total = grand_total()
	if where == 'card' then
		return string.format('%s - %s', cling.text('scoreboard'), cling.text(SLOTS[cursor]))
	end
	return string.format('%s %d, %s', cling.text('table'), rolls_left,
	                     string.format(cling.text('pointsfmt'), tostring(total)))
end

function help() return cling.text('help') end

function on_stop() cling.stop_sounds() end
