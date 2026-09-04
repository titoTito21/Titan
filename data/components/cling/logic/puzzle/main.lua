-- Simple Puzzle, for Cling.
--
-- Klango's own code for this game is Lua inside an encrypted package that
-- Cling has no key for, so what is here is Cling's implementation of the game
-- the application DESCRIBES: its five levels are named in level1_name..
-- level5_name, its keys in help.txt, its tiles are the texts "1".."24" and its
-- sounds are movebegin, moveend, cantmove, empty, in, out and boardend. The
-- application's own folder is never touched; this file lives beside Cling.
--
-- The board is heard rather than seen: a tile is spoken from where it is, the
-- empty square answers with `empty`, and running into the edge is `cantmove`.

local LEVELS = {
	{ name = 'level1_name', w = 3, h = 3, mask = nil },
	{ name = 'level2_name', w = 4, h = 4, mask = nil },
	{ name = 'level3_name', w = 5, h = 5, mask = nil },
	-- The two special levels are the same game on a board with holes: an
	-- hourglass and a ring. A hole is not a square you can be on.
	{ name = 'level4_name', w = 5, h = 5, mask = {
		1,1,1,1,1,
		0,1,1,1,0,
		0,0,1,0,0,
		0,1,1,1,0,
		1,1,1,1,1 } },
	{ name = 'level5_name', w = 5, h = 5, mask = {
		1,1,1,1,1,
		1,0,0,0,1,
		1,0,0,0,1,
		1,0,0,0,1,
		1,1,1,1,1 } },
}

local level, tiles, empty, here, moves, playing, choosing, choice

local function count(l) 
	local n = 0
	for i = 1, l.w * l.h do
		if not l.mask or l.mask[i] == 1 then n = n + 1 end
	end
	return n
end

local function usable(index)
	if not level.mask then return true end
	return level.mask[index] == 1
end

local function at(column, row)
	if column < 1 or column > level.w or row < 1 or row > level.h then return nil end
	local index = (row - 1) * level.w + column
	if not usable(index) then return nil end
	return index
end

local function column_of(index) return ((index - 1) % level.w) + 1 end
local function row_of(index) return math.floor((index - 1) / level.w) + 1 end

local function field_for(index)
	-- The board is laid out in Cling's own coordinates so that a tile on the
	-- left is heard on the left; `cling.board` is asked for once per level.
	return cling.field((column_of(index) - 1) * level.h + row_of(index))
end

local function tile_name(value)
	if value == 0 then return cling.text('empty') end
	local said = cling.text(tostring(value))
	if said == '' then said = tostring(value) end
	return said
end

local function say_here()
	local f = field_for(here)
	cling.play_at('ui/focus', (column_of(here) - 1) * level.h + row_of(here))
	cling.say_at(tile_name(tiles[here]), (column_of(here) - 1) * level.h + row_of(here))
end

local function solved()
	local wanted = 1
	for row = 1, level.h do
		for column = 1, level.w do
			local index = (row - 1) * level.w + column
			if usable(index) then
				if index ~= empty then
					if tiles[index] ~= wanted then return false end
					wanted = wanted + 1
				end
			end
		end
	end
	return true
end

local function lay_out()
	tiles = {}
	local value = 1
	local last = nil
	for row = 1, level.h do
		for column = 1, level.w do
			local index = (row - 1) * level.w + column
			if usable(index) then
				tiles[index] = value
				value = value + 1
				last = index
			end
		end
	end
	tiles[last] = 0
	empty = last
	here = 1
	while not usable(here) do here = here + 1 end
end

local function neighbours(index)
	-- Appended one at a time rather than written as { at(..), at(..), .. }:
	-- a table constructor with a nil in it has a hole, and `ipairs` stops at
	-- the first hole - so a square at the edge of the board, whose first
	-- neighbour is off it, would come back with no neighbours at all.
	local out = {}
	local column, row = column_of(index), row_of(index)
	local one = at(column - 1, row)
	if one then out[#out + 1] = one end
	one = at(column + 1, row)
	if one then out[#out + 1] = one end
	one = at(column, row - 1)
	if one then out[#out + 1] = one end
	one = at(column, row + 1)
	if one then out[#out + 1] = one end
	return out
end

local function slide(index, quiet)
	-- A tile moves only into the empty square, and only from beside it.
	local ok = false
	for _, candidate in ipairs(neighbours(empty)) do
		if candidate == index then ok = true end
	end
	if not ok then
		if not quiet then cling.play('cantmove') end
		return false
	end
	if not quiet then cling.play('movebegin') end
	tiles[empty] = tiles[index]
	tiles[index] = 0
	empty = index
	moves = moves + 1
	if not quiet then cling.play('moveend') end
	return true
end

local function shuffle(times)
	-- Shuffled by making legal moves backwards, never by dealing the tiles
	-- out at random: half of the random arrangements of a sliding puzzle
	-- cannot be solved at all, and a player cannot be told which half.
	for _ = 1, times do
		local options = neighbours(empty)
		slide(options[math.random(1, #options)], true)
	end
	moves = 0
end

local function start_level(number)
	level = LEVELS[number]
	cling.set('level', number)
	cling.board('', level.w, level.h)
	lay_out()
	shuffle(200 + number * 100)
	playing = true
	cling.show(cling.text(level.name))
	cling.show(cling.text('usemenu'))
	say_here()
end

local function ask_level()
	choosing = true
	choice = tonumber(cling.get('level', 1)) or 1
	cling.show(cling.text('select_level'))
	cling.say(cling.text(LEVELS[choice].name))
end

function on_start()
	math.randomseed(os.time())
	moves = 0
	ask_level()
end

local function move(dc, dr)
	local target = at(column_of(here) + dc, row_of(here) + dr)
	if not target then cling.play('cantmove') return end
	here = target
	say_here()
end

function on_key(key)
	if choosing then
		if key == 'up' or key == 'left' then
			choice = ((choice - 2) % #LEVELS) + 1
			cling.say(cling.text(LEVELS[choice].name))
			return true
		end
		if key == 'down' or key == 'right' then
			choice = (choice % #LEVELS) + 1
			cling.say(cling.text(LEVELS[choice].name))
			return true
		end
		if key == 'enter' or key == 'space' then
			choosing = false
			start_level(choice)
			return true
		end
		return false
	end

	if not playing then
		if key == 'n' or key == 'enter' or key == 'space' then ask_level() return true end
		return false
	end

	if key == 'left' then move(-1, 0) return true end
	if key == 'right' then move(1, 0) return true end
	if key == 'up' then move(0, -1) return true end
	if key == 'down' then move(0, 1) return true end
	if key == 'space' or key == 'enter' then
		if slide(here) then
			if solved() then
				playing = false
				cling.play('boardend')
				cling.show(cling.text('solved'))
				cling.record_score(math.max(1, 10000 - moves))
				cling.publish_score(math.max(1, 10000 - moves), cling.get('level', 1))
			end
		end
		return true
	end
	if key == 'n' then ask_level() return true end
	if key == 's' then
		shuffle(200)
		cling.show(cling.text('shuffled'))
		say_here()
		return true
	end
	if key == 'f1' then cling.show(cling.text('help')) return true end
	return false
end

function status()
	if choosing then return cling.text('select_level') end
	if not playing then return cling.text('solved') end
	return string.format('%s - %d', cling.text(level.name), moves)
end

function help()
	return cling.text('help')
end

function on_stop()
	cling.stop_sounds()
end
