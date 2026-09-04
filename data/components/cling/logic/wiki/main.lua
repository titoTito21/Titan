-- Wikipedia Browser, for Cling.
--
-- The application is a client for something, and Cling gives it the one thing
-- such an application needs: `cling.fetch`, an ordinary GET over http or https
-- with a ceiling on what may come back. Everything else - what to ask for, how
-- to read the answer, what to say - is here, and the words are the
-- application's own.
--
-- Wikipedia's REST summary endpoint is used rather than the HTML page: it is
-- what the encyclopedia offers to programs, it comes back small, and it does
-- not need a browser engine to make sense of.

local LANGUAGES = { 'en', 'pl', 'de', 'fr', 'es' }
local language, article, sections, cursor

local function api(path)
	return 'https://' .. language .. '.wikipedia.org/api/rest_v1/' .. path
end

local function escape(text)
	-- A title goes into a path, so anything that is not a plain character is
	-- written as %XX; a title with a space or an accent must not become a
	-- different address.
	return (string.gsub(text, '[^%w%-%_%.%~]', function(c)
		if c == ' ' then return '_' end
		return string.format('%%%02X', string.byte(c))
	end))
end

local function value_for(body, key)
	-- The answer is JSON and Cling has no JSON reader, but what is wanted is
	-- two strings out of a flat object, and a Lua pattern is exactly the tool
	-- for that.
	local found = string.match(body, '"' .. key .. '"%s*:%s*"(.-)[^\\]"')
	if not found then return '' end
	found = string.gsub(found, '\\"', '"')
	found = string.gsub(found, '\\n', '\n')
	found = string.gsub(found, '\\/', '/')
	found = string.gsub(found, '\\u(%x%x%x%x)', function(hex)
		local code = tonumber(hex, 16)
		if code < 128 then return string.char(code) end
		return ''
	end)
	return found
end

local function split(text)
	local out = {}
	for line in string.gmatch(text, '[^\n]+') do
		local trimmed = string.match(line, '^%s*(.-)%s*$')
		if trimmed ~= '' then out[#out + 1] = trimmed end
	end
	return out
end

local function show_article(title)
	cling.show(cling.text('searching') ~= '' and cling.text('searching') or
	           ('Wikipedia (' .. language .. '): ' .. title))
	local body = cling.fetch(api('page/summary/' .. escape(title)))
	if body == '' then
		cling.show(cling.text('neterror') ~= '' and cling.text('neterror') or
		           'The article could not be fetched.')
		return
	end
	local heading = value_for(body, 'title')
	local extract = value_for(body, 'extract')
	if extract == '' then
		cling.show(cling.text('notfound') ~= '' and cling.text('notfound') or
		           ('Nothing was found for ' .. title))
		return
	end
	article = heading ~= '' and heading or title
	sections = split(extract)
	cursor = 1
	cling.set('last', article)
	cling.show(article)
	cling.show(extract)
end

local function search()
	local wanted = cling.ask(cling.text('search') ~= '' and cling.text('search')
	                         or 'What would you like to read about?',
	                         cling.get('last', ''))
	if wanted == '' then return end
	show_article(wanted)
end

function on_start()
	language = cling.get('language', 'en')
	sections = {}
	cursor = 1
	cling.show(cling.text('welcome') ~= '' and cling.text('welcome') or
	           'Wikipedia. Press space to search, l to change the language.')
	local last = cling.get('last', '')
	if last ~= '' then show_article(last) end
end

function on_key(key)
	if key == 'space' or key == 'enter' and #sections == 0 then search() return true end
	if key == 's' then search() return true end
	if key == 'l' then
		for index, code in ipairs(LANGUAGES) do
			if code == language then
				language = LANGUAGES[(index % #LANGUAGES) + 1]
				break
			end
		end
		cling.set('language', language)
		cling.say(language)
		return true
	end
	if #sections == 0 then return false end
	if key == 'up' or key == 'left' then
		cursor = ((cursor - 2) % #sections) + 1
		cling.say(sections[cursor])
		return true
	end
	if key == 'down' or key == 'right' then
		cursor = (cursor % #sections) + 1
		cling.say(sections[cursor])
		return true
	end
	if key == 'enter' then cling.show(sections[cursor]) return true end
	return false
end

function status()
	if article then
		return string.format('%s (%s) %d/%d', article, language, cursor, #sections)
	end
	return 'Wikipedia (' .. tostring(language) .. ')'
end

function help()
	local own = cling.text('help')
	if own ~= '' then return own end
	return 'Space or s - search. Arrows - move through the article. l - change language. Escape - leave.'
end

function on_stop() cling.stop_sounds() end
