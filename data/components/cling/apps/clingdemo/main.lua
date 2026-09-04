-- Cling Demo: the shortest complete Cling application.
--
-- It ships no sounds of its own on purpose. Every name it plays - 'ui/focus',
-- 'ui/error' - is looked for in the application's own skin FIRST and then in
-- whichever Titan sound theme the user chose, so this game sounds like the
-- desktop it is running on and the whole thing is four text files and this.
--
-- Five functions are the contract, all optional: on_start, on_key, on_tick,
-- on_stop and status. `cling` is the host.

local COLUMNS, ROWS = 3, 3
local SEARCHES = 5

local here, hidden, searches, score, over

local function board()
	-- No .top file, so Cling lays the nine fields out evenly in front of the
	-- listener; a field knows its own pan, height, distance and pitch.
	cling.board('', COLUMNS, ROWS)
end

local function field()
	return cling.field(here)
end

local function announce()
	local f = field()
	cling.play_at('ui/focus', here)
	cling.say_at(string.format('%d, %d', f.column, f.row), here)
end

local function deal()
	board()
	here = 1
	hidden = math.random(1, COLUMNS * ROWS)
	searches = SEARCHES
	over = false
	announce()
end

function on_start()
	math.randomseed(os.time())
	score = cling.get('score', 0)
	cling.show(cling.text('welcome'))
	deal()
end

local function step(dc, dr)
	local f = field()
	local column, row = f.column + dc, f.row + dr
	if column < 1 or column > COLUMNS or row < 1 or row > ROWS then
		cling.play('ui/error')
		return
	end
	here = (column - 1) * ROWS + row
	announce()
end

local function search()
	if over then deal() return end
	searches = searches - 1
	if here == hidden then
		score = score + searches + 1
		cling.set('score', score)
		cling.record_score(score)
		cling.play('ui/select')
		cling.show(string.format(cling.text('found'), SEARCHES - searches, score))
		over = true
		return
	end
	-- Warmer or colder, said as a pitch rather than as a number: the whole
	-- point of a board like this is that it is heard.
	local f, g = cling.field(here), cling.field(hidden)
	local distance = math.abs(f.column - g.column) + math.abs(f.row - g.row)
	cling.play_at('ui/error', here, 1.0 - distance * 0.15)
	if searches <= 0 then
		cling.show(cling.text('lost'))
		over = true
	end
end

function on_key(key)
	if key == 'left' then step(-1, 0) return true end
	if key == 'right' then step(1, 0) return true end
	if key == 'up' then step(0, -1) return true end
	if key == 'down' then step(0, 1) return true end
	if key == 'space' then search() return true end
	if key == 'enter' then cling.show(status()) return true end
	return false
end

function status()
	if over then return 'Press space to play again. Score ' .. tostring(score) end
	return string.format('Score %d, %d searches left', score or 0, searches or 0)
end

function on_stop()
	cling.stop_sounds()
end
