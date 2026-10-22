// A Titan application written in JavaScript. It runs on QuickJS, which
// Polyglot carries - `titan` is a global, as in Lua. (On Node.js the SDK's
// titan.js sets the same global.)
const polish = titan.info().language === 'pl';
const t = (en, pl) => (polish ? pl : en);
const name = titan.ask(t('What is your name?', 'Jak masz na imię?'));
if (name !== null) {
  titan.speak(t('Hello from JavaScript, ', 'Cześć z JavaScriptu, ') + name +
              t('. Your name has ', '. Twoje imię ma ') + name.length +
              t(' letters.', ' znaków.'));
  titan.wait(3);
}
