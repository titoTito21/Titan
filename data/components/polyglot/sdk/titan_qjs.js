// Titan for JavaScript on QuickJS - the interpreter Polyglot carries.
// It is included before the program (qjs --std -I titan_qjs.js main.js), so a
// program finds a global `titan`, exactly as a Lua program does:
//
//   titan.speak('Hello');
//   const name = titan.ask('Your name?');
//   const i = titan.choose('Pick one', ['Tea', 'Coffee']);   // from 0, or null
//
// The same program runs on Node.js too: titan.js sets the same global.
'use strict';
(function () {
  let nextId = 0;
  const output = std.out;
  const input = std.in;

  function call(name, ...args) {
    nextId += 1;
    const named = args.length === 1 && args[0] !== null &&
                  typeof args[0] === 'object' && !Array.isArray(args[0]) &&
                  name !== 'action';
    output.puts(JSON.stringify({ id: nextId, call: name,
                                 args: named ? args[0] : args }) + '\n');
    output.flush();
    for (;;) {
      const line = input.getline();
      if (line === null) throw new Error('Titan has gone');
      if (!line.startsWith('{')) continue;
      const reply = JSON.parse(line);
      if (reply.id !== nextId) continue;
      if (!reply.ok) throw new Error(reply.error);
      return reply.value;
    }
  }

  // print and console.log would corrupt the wire; they go to the log.
  const toLog = (...a) => { std.err.puts(a.join(' ') + '\n'); std.err.flush(); };
  globalThis.print = toLog;
  globalThis.console = { log: toLog, error: toLog, warn: toLog, info: toLog };

  const titan = { call };
  for (const name of ['info', 'speak', 'stop_speech', 'play', 'stop_sounds',
    'message', 'ask', 'confirm', 'choose', 'text', 'open_window',
    'close_window', 'next_event', 'wait', 'action', 'data_dir', 'log', 'exit',
    'add_menu', 'title']) {
    titan[name] = (...args) => call(name, ...args);
  }
  globalThis.titan = titan;
})();
