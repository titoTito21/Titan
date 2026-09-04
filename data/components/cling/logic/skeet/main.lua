-- Skeet, for Cling.
--
-- The application's own texts are the rules: help.txt says "space bar - launch
-- disc or shoot", pull.txt says "Press spacebar to launch disc", and the game
-- keeps Points, Level and Lives (points.txt, level.txt, lives.txt), ending with
-- gameover.txt "Your score : %s. Level : %s." A miss is ups.txt, "Way out!"
--
-- The disc is the whole game and it is heard, not seen: `throw` is where it
-- leaves from, `flight` follows it across the stereo image, and the shot only
-- counts while the disc is in front of the barrel. Its sounds are the
-- application's own - throw, flight, flight2, bird, bird2, fire, hit, ups.

local WAITING, FLYING, OVER = 'waiting', 'flying', 'over'

local state, points, level, lives, discs
local disc_from, disc_to, disc_at, disc_started, disc_seconds, disc_handle
local aim, music

local function seconds_for(l)
	-- Faster every level, but never so fast that the ear cannot follow it.
	return math.max(1.1, 3.0 - (l - 1) * 0.18)
end

local function say_state()
	cling.show(string.format('%s: %d. %s: %d. %s: %d',
		cling.text('points'), points, cling.text('level'), level,
		cling.text('lives'), lives))
end

local function throw()
	state = FLYING
	-- A disc comes in from one side and crosses; which side is the only thing
	-- the player does not know in advance.
	if math.random(1, 2) == 1 then disc_from, disc_to = -1.0, 1.0
	else disc_from, disc_to = 1.0, -1.0 end
	disc_at = disc_from
	disc_seconds = seconds_for(level)
	disc_started = cling.now()
	cling.play('throw', disc_from, 1.0)
	cling.play(math.random(1, 2) == 1 and 'bird' or 'bird2', disc_from, 0.9)
	disc_handle = cling.loop(math.random(1, 2) == 1 and 'flight' or 'flight2',
	                         disc_from, 0.8)
end

local function quieten()
	if disc_handle then cling.stop_sound(disc_handle) disc_handle = nil end
end

local function lost_one()
	quieten()
	lives = lives - 1
	cling.play('ups')
	cling.show(cling.text('ups'))
	if lives <= 0 then
		state = OVER
		if music then cling.stop_sound(music) music = nil end
		cling.play('gameover')
		cling.show(string.format(cling.text('gameover'), tostring(points),
		                         tostring(level)))
		cling.record_score(points, level)
		cling.publish_score(points, level)
		return
	end
	state = WAITING
	say_state()
	cling.show(cling.text('pull'))
end

local function shoot()
	cling.play('fire', aim, 1.0)
	-- The barrel points straight ahead; a disc is hit when it is in front of
	-- it, and how close to the middle it was is what the shot is worth.
	local offset = math.abs(disc_at - aim)
	if offset <= 0.28 then
		quieten()
		local worth = 10 + math.floor((0.28 - offset) * 30)
		points = points + worth
		discs = discs + 1
		cling.play('hit', disc_at, 1.0)
		cling.show(cling.text('hit'))
		if discs % 5 == 0 then
			level = level + 1
			cling.show(string.format('%s: %d', cling.text('level'), level))
		end
		state = WAITING
		say_state()
		cling.show(cling.text('pull'))
		return
	end
	lost_one()
end

local function new_game()
	points, level, lives, discs = 0, 1, 3, 0
	aim = 0.0
	state = WAITING
	music = cling.loop('music', 0.0, 0.35)
	say_state()
	cling.show(cling.text('pull'))
end

function on_start()
	math.randomseed(os.time())
	cling.show(cling.text('helpstart'))
	new_game()
end

function on_tick(now)
	if state ~= FLYING then return end
	local gone = (now - disc_started) / disc_seconds
	if gone >= 1.0 then
		lost_one()
		return
	end
	disc_at = disc_from + (disc_to - disc_from) * gone
end

function on_key(key)
	if state == OVER then
		if key == 'n' or key == 'space' or key == 'enter' then
			new_game()
			return true
		end
		return false
	end
	if key == 'space' then
		if state == WAITING then throw() else shoot() end
		return true
	end
	if key == 'left' then aim = math.max(-1.0, aim - 0.2) cling.play('ui/focus', aim) return true end
	if key == 'right' then aim = math.min(1.0, aim + 0.2) cling.play('ui/focus', aim) return true end
	if key == 'enter' then say_state() return true end
	if key == 'f1' then cling.show(cling.text('help')) return true end
	return false
end

function status()
	if state == OVER then
		return string.format('%s: %d, %s: %d', cling.text('points'), points,
		                     cling.text('level'), level)
	end
	return string.format('%s %d, %s %d, %s %d', cling.text('points'), points,
	                     cling.text('level'), level, cling.text('lives'), lives)
end

function help() return cling.text('help') end

function on_stop()
	quieten()
	cling.stop_sounds()
end
