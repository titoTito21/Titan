-- Long Jump, for Cling.
--
-- readme.txt is the specification, in the application's own words: "After you
-- start, you'll hear steps of your athlete. Your task is then to press right
-- and left arrow keys alternately faster and faster... When you'll hear a
-- sound of the board, you'll have to press the spacebar to perform a take
-- off. In the triple jump, you'll have to do two additional leaps."
--
-- So the whole game is rhythm: how fast the alternating arrows got, and how
-- close to the board the space bar came. Both are measured here rather than
-- guessed, and the run-up is heard - the steps speed up with the runner and
-- the board arrives from in front.

local MENU, RUNNING, JUMPING, DONE = 'menu', 'running', 'jumping', 'done'
local RUNWAY = 9.0            -- seconds of run-up before the board
local FOUL_AFTER = 0.28       -- past the board by this much and it is a foul

local state, mode, speed, last_key, last_side, started, leaps, distance
local crowd, chosen, step_due, board_played

local MODES = { { 'mode1', 'mode1_desc', 1 }, { 'mode2', 'mode2_desc', 3 } }

local function say_mode()
	cling.say(cling.text(MODES[chosen][1]))
end

local function menu()
	state = MENU
	chosen = chosen or 1
	cling.show(cling.text('modeq'))
	say_mode()
end

local function begin()
	state = RUNNING
	mode = MODES[chosen]
	speed = 0.0
	last_key = 0.0
	last_side = ''
	leaps = 0
	distance = 0.0
	board_played = false
	started = cling.now()
	step_due = started
	crowd = cling.loop('tlo', 0.0, 0.35)
	cling.play('go')
	cling.show(cling.text('start'))
end

local function finish(foul)
	state = DONE
	if crowd then cling.stop_sound(crowd) crowd = nil end
	if foul then
		cling.play('ups')
		cling.show(cling.text('ups'))
		distance = 0.0
	else
		cling.play('down')
		cling.play(distance > 6.0 and 'jee' or 'boo')
		local said = string.format('%.2f', distance)
		cling.show(string.format(cling.text('distance'), said))
		cling.record_score(math.floor(distance * 100))
		cling.publish_score(math.floor(distance * 100))
	end
	cling.show(cling.text('m_start'))
end

function on_start()
	math.randomseed(os.time())
	cling.show(cling.text('helpstart'))
	menu()
end

function on_tick(now)
	if state ~= RUNNING then return end
	-- The steps ARE the speedometer: they come as fast as the runner is
	-- going, so the player hears whether they are still accelerating.
	local gap = 0.62 - speed * 0.32
	if gap < 0.16 then gap = 0.16 end
	if now >= step_due then
		cling.play('foot', ((now * 3) % 2 < 1) and -0.35 or 0.35, 0.6 + speed * 0.4)
		step_due = now + gap
	end
	-- Speed bleeds away when the arrows stop coming; that is what makes the
	-- rhythm something to keep up rather than something to reach once.
	speed = math.max(0.0, speed - 0.55 * 0.05)
	local gone = now - started
	if not board_played and gone >= RUNWAY then
		board_played = true
		cling.play('start', 0.0, 1.0)
	end
	if gone >= RUNWAY + FOUL_AFTER + 0.6 then
		finish(true)
	end
end

local function stride(side, now)
	if side == last_side then
		-- The same arrow twice is a stumble, not a stride.
		speed = math.max(0.0, speed - 0.08)
		return
	end
	local gap = now - last_key
	last_key = now
	last_side = side
	if gap <= 0 or gap > 1.2 then return end
	-- A gain that is bigger the tighter the rhythm, so smooth acceleration
	-- beats hammering, which is what the readme asks for.
	speed = math.min(1.0, speed + math.max(0.02, 0.16 - gap * 0.10))
end

local function take_off(now)
	local gone = now - started
	local past = gone - RUNWAY
	if past < -0.9 then
		-- Too early: the jump is short rather than a foul.
		state = JUMPING
		leaps = 1
		distance = 2.0 + speed * 2.0
		cling.play('jump')
		if mode[3] == 1 then finish(false) end
		return
	end
	if past > FOUL_AFTER then finish(true) return end
	state = JUMPING
	leaps = 1
	local timing = 1.0 - math.min(1.0, math.abs(past) / FOUL_AFTER) * 0.35
	distance = (3.2 + speed * 5.4) * timing
	cling.play('jump')
	if mode[3] == 1 then finish(false) end
end

function on_key(key)
	local now = cling.now()
	if state == MENU then
		if key == 'up' or key == 'left' then
			chosen = ((chosen - 2) % #MODES) + 1 say_mode() return true
		end
		if key == 'down' or key == 'right' then
			chosen = (chosen % #MODES) + 1 say_mode() return true
		end
		if key == 'i' then cling.show(cling.text(MODES[chosen][2])) return true end
		if key == 's' or key == 'space' or key == 'enter' then begin() return true end
		return false
	end
	if state == DONE then
		if key == 's' or key == 'space' or key == 'enter' then menu() return true end
		return false
	end
	if state == RUNNING then
		if key == 'left' then stride('l', now) return true end
		if key == 'right' then stride('r', now) return true end
		if key == 'space' then take_off(now) return true end
		if key == 'escape' then
			if crowd then cling.stop_sound(crowd) crowd = nil end
			cling.show(cling.text('gamestop'))
			state = DONE
			return true
		end
		return false
	end
	if state == JUMPING and key == 'space' then
		-- Hop, step and jump: each further leap adds to the distance, and
		-- the last one ends the attempt.
		leaps = leaps + 1
		distance = distance + (2.2 + speed * 2.2) * (1.0 - leaps * 0.08)
		cling.play('jump2')
		if leaps >= mode[3] then finish(false) end
		return true
	end
	return false
end

function status()
	if state == RUNNING then
		return string.format('%s %d%%', cling.text('m_start'),
		                     math.floor(speed * 100))
	end
	if state == DONE and distance > 0 then
		return string.format(cling.text('distance'), string.format('%.2f', distance))
	end
	return cling.text('modeq')
end

function help() return cling.text('help') end

function on_stop()
	if crowd then cling.stop_sound(crowd) crowd = nil end
	cling.stop_sounds()
end
