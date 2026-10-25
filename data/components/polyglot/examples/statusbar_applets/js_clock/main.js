// A statusbar applet in JavaScript (QuickJS, carried by Polyglot).
// titan.serve answers Titan's calls by the names a Python applet defines.
function two(n) { return (n < 10 ? '0' : '') + n; }

titan.serve({
  get_statusbar_item_text: () => {
    const now = new Date();
    return 'JS ' + two(now.getHours()) + ':' + two(now.getMinutes());
  },
  on_statusbar_item_activate: () => {
    titan.speak(new Date().toString());
    return null;
  },
});
