// Titan for JavaScript (Node.js) - the Polyglot line protocol.
//   const titan = require('titan');
//   titan.speak('Hello');
//   const name = titan.ask('Your name?');
// Calls are synchronous: each writes one line and reads the answer.
'use strict';
const fs = require('fs');

let nextId = 0;
let buffer = Buffer.alloc(0);

function readLine() {
  const chunk = Buffer.alloc(4096);
  for (;;) {
    const at = buffer.indexOf(10);
    if (at >= 0) {
      const line = buffer.subarray(0, at).toString('utf8');
      buffer = buffer.subarray(at + 1);
      return line;
    }
    let count = 0;
    try {
      count = fs.readSync(0, chunk, 0, chunk.length, null);
    } catch (e) {
      if (e.code === 'EAGAIN') continue;
      throw e;
    }
    if (count === 0) throw new Error('Titan has gone');
    buffer = Buffer.concat([buffer, chunk.subarray(0, count)]);
  }
}

function call(name, ...args) {
  nextId += 1;
  const named = args.length === 1 && args[0] && typeof args[0] === 'object' &&
                !Array.isArray(args[0]) && name !== 'action';
  fs.writeSync(1, JSON.stringify({ id: nextId, call: name,
                                   args: named ? args[0] : args }) + '\n');
  for (;;) {
    const line = readLine();
    if (!line.startsWith('{')) continue;
    const reply = JSON.parse(line);
    if (reply.id !== nextId) continue;
    if (!reply.ok) throw new Error(reply.error);
    return reply.value;
  }
}

// console.log would corrupt the wire; it goes to the log instead.
console.log = (...a) => process.stderr.write(a.join(' ') + '\n');

const titan = { call };
for (const name of ['info', 'speak', 'stop_speech', 'play', 'stop_sounds',
  'message', 'ask', 'confirm', 'choose', 'text', 'open_window', 'close_window',
  'next_event', 'wait', 'action', 'data_dir', 'log', 'exit', 'add_menu',
  'title', 'provide', 'reply']) {
  titan[name] = (...args) => call(name, ...args);
}
// A method of an object Titan handed the program: titan.host(api, 'open_telegram').
titan.host = (target, method, ...args) => call('host', target, method, args);
// A function Titan may keep and call later (a menu entry's action).
titan.fn = (name) => ({ __function: name });
// Every add-on Titan CALLS ends with this: the functions it may call, by
// the same names a Python add-on of that kind defines.
//   titan.serve({ get_statusbar_item_text: () => new Date().toTimeString() });
titan.serve = (handlers, onEvent) => {
  call('provide', Object.keys(handlers));
  for (;;) {
    const event = call('next_event', -1);
    if (!event) continue;
    if (event.type === 'close') return;
    if (event.type === 'call') {
      const handler = handlers[event.name];
      try {
        const value = handler ? handler(...(event.args || [])) : null;
        call('reply', event.id, value === undefined ? null : value);
      } catch (e) {
        call('reply', event.id, null, String(e && e.message || e));
      }
    } else if (onEvent) {
      onEvent(event);
    }
  }
};
globalThis.titan = titan;   // as on QuickJS: programs use the global
module.exports = titan;
