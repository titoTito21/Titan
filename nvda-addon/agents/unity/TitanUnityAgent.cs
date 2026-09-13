// Titan / NVDA agent for a Unity game.
//
// A game engine draws its text as MESHES through Direct3D. It never calls a
// GDI text function, so the display-model tier on the host - which reads
// exactly what a program passed to such a call, and is the best thing there
// is for an ordinary window - finds nothing at all in a game, and a picture
// read by a model is what is left. That works, and it costs a reading and
// guesses at what is selected.
//
// The engine, meanwhile, knows every string: a `Text` or a `TextMeshPro`
// component holds the words, and `EventSystem` knows exactly which control
// is selected and which one the pointer is over. So this reports them, and
// the reader says them instantly, exactly, with no model involved.
//
// Build (BepInEx 5, any Unity game):
//
//   dotnet build TitanUnityAgent.csproj -c Release
//   copy bin/Release/TitanUnityAgent.dll <game>/BepInEx/plugins/
//
// Then in the game's BepInEx/config/titan.agent.cfg (written on first run)
// put the key from the reader's settings page - **The agent's key...** -
// and the host's address if the game is not on this machine.
//
// Nothing here draws, speaks, or changes the game. It reads two things per
// frame at most, sends only what CHANGED, and every send is on a thread of
// its own: a frame that waited on a socket would be a game that stutters
// because a screen reader was listening.

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Globalization;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Threading;
using BepInEx;
using BepInEx.Configuration;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace Titan.Agent
{
    [BepInPlugin("titan.agent", "Titan reader agent", "1.0.0")]
    public class TitanUnityAgent : BaseUnityPlugin
    {
        private ConfigEntry<string> _host;
        private ConfigEntry<int> _port;
        private ConfigEntry<string> _token;
        private ConfigEntry<bool> _pointer;
        private ConfigEntry<bool> _selection;
        private ConfigEntry<float> _interval;

        private Link _link;
        private float _next;
        private string _wasPointer = "";
        private string _wasSelected = "";
        private readonly List<RaycastResult> _hits = new List<RaycastResult>();

        private void Awake()
        {
            _host = Config.Bind("reader", "host", "127.0.0.1",
                "Where the reader is. Leave it alone unless the game is on "
                + "another computer from the reader.");
            _port = Config.Bind("reader", "port", 37375,
                "The port the reader listens on.");
            _token = Config.Bind("reader", "key", "",
                "The key from the reader's settings page - The agent's "
                + "key... Nothing is sent until this is filled in: a line "
                + "without it is dropped without an answer.");
            _pointer = Config.Bind("what", "pointer", true,
                "Say what the pointer is over.");
            _selection = Config.Bind("what", "selection", true,
                "Say what the game has selected - which is what the arrow "
                + "keys and a gamepad move.");
            _interval = Config.Bind("what", "interval", 0.1f,
                "Seconds between looks. This is not a frame: a game runs at "
                + "sixty and nobody needs sixty announcements a second.");

            if (string.IsNullOrEmpty(_token.Value))
            {
                Logger.LogWarning("Titan agent: no key set, so nothing is "
                    + "sent. Put the key from the reader's settings page "
                    + "into BepInEx/config/titan.agent.cfg.");
                return;
            }
            _link = new Link(_host.Value, _port.Value, _token.Value, Logger);
            Logger.LogInfo(string.Format(CultureInfo.InvariantCulture,
                "Titan agent: talking to {0}:{1}", _host.Value, _port.Value));
        }

        private void OnDestroy()
        {
            if (_link != null) _link.Stop();
        }

        private void Update()
        {
            if (_link == null) return;
            if (Time.unscaledTime < _next) return;
            _next = Time.unscaledTime + Math.Max(0.02f, _interval.Value);

            if (_selection.Value)
            {
                string said = Selected();
                if (!string.IsNullOrEmpty(said) && said != _wasSelected)
                {
                    _wasSelected = said;
                    _link.Send("focus", said);
                }
            }
            if (_pointer.Value)
            {
                string said = UnderPointer();
                if (!string.IsNullOrEmpty(said) && said != _wasPointer)
                {
                    _wasPointer = said;
                    _link.Send("pointer", said);
                }
            }
        }

        // ------------------------------------------------------------------ //
        // What the game has selected - which is what a keyboard or a gamepad
        // moves, and therefore the one thing a player who cannot see the
        // screen is asking about.
        private string Selected()
        {
            EventSystem events = EventSystem.current;
            if (events == null) return "";
            GameObject found = events.currentSelectedGameObject;
            return found == null ? "" : Describe(found);
        }

        // What the POINTER is over, asked of the engine's own raycasters -
        // so it is the control the game itself would consider hit, not
        // whatever happens to be drawn at those pixels.
        private string UnderPointer()
        {
            EventSystem events = EventSystem.current;
            if (events == null) return "";
            PointerEventData where = new PointerEventData(events);
            where.position = Input.mousePosition;
            _hits.Clear();
            events.RaycastAll(where, _hits);
            for (int at = 0; at < _hits.Count; at++)
            {
                GameObject hit = _hits[at].gameObject;
                if (hit == null) continue;
                string said = Describe(hit);
                if (!string.IsNullOrEmpty(said)) return said;
            }
            return "";
        }

        // ------------------------------------------------------------------ //
        // Turning a game object into words.
        //
        // The words are nearly never on the object the raycast hit: a button
        // is an image with a label as a CHILD, and the label is where the
        // text is. So the object's own text is looked for first, then its
        // children's, and the object's NAME is the last resort - a name is
        // the developer's ("BtnStart_01"), which is worth saying only when
        // there is nothing better.
        private string Describe(GameObject found)
        {
            string words = TextIn(found);
            if (string.IsNullOrEmpty(words)) words = TextBelow(found);
            string kind = KindOf(found);
            if (string.IsNullOrEmpty(words))
            {
                words = Readable(found.name);
                if (string.IsNullOrEmpty(words)) return "";
            }
            return string.IsNullOrEmpty(kind) ? words : words + ", " + kind;
        }

        private static string TextIn(GameObject found)
        {
            Text legacy = found.GetComponent<Text>();
            if (legacy != null && !string.IsNullOrEmpty(legacy.text))
                return Clean(legacy.text);
            return Clean(TextMeshIn(found));
        }

        private static string TextBelow(GameObject found)
        {
            Text[] legacy = found.GetComponentsInChildren<Text>(false);
            for (int at = 0; at < legacy.Length; at++)
            {
                if (legacy[at] != null && !string.IsNullOrEmpty(legacy[at].text))
                    return Clean(legacy[at].text);
            }
            Component[] every = found.GetComponentsInChildren<Component>(false);
            for (int at = 0; at < every.Length; at++)
            {
                string said = Clean(TextMeshIn(every[at]));
                if (!string.IsNullOrEmpty(said)) return said;
            }
            return "";
        }

        // **TextMeshPro is reached by REFLECTION and that is deliberate.**
        // A game may not ship it at all, and a plugin with a hard reference
        // to an assembly the game has not got does not load - which is the
        // whole agent missing rather than one tier of it. The property is
        // `text` on any component whose type is named TMP_Text or below it.
        private static string TextMeshIn(object component)
        {
            if (component == null) return "";
            Type kind = component.GetType();
            for (Type walk = kind; walk != null; walk = walk.BaseType)
            {
                if (walk.Name != "TMP_Text" && walk.Name != "TextMeshProUGUI"
                    && walk.Name != "TextMeshPro") continue;
                PropertyInfo property = kind.GetProperty("text",
                    BindingFlags.Public | BindingFlags.Instance);
                if (property == null) return "";
                try
                {
                    return property.GetValue(component, null) as string ?? "";
                }
                catch (Exception)
                {
                    return "";
                }
            }
            return "";
        }

        // What the control IS, in the words a reader uses for one. Taken
        // from the engine's own component, so it is true rather than guessed
        // from how the thing looks.
        private static string KindOf(GameObject found)
        {
            if (found.GetComponent<Button>() != null) return "button";
            if (found.GetComponent<Toggle>() != null) return "check box";
            if (found.GetComponent<Slider>() != null) return "slider";
            if (found.GetComponent<Scrollbar>() != null) return "scroll bar";
            if (found.GetComponent<InputField>() != null) return "edit";
            if (found.GetComponent<Dropdown>() != null) return "combo box";
            // A parent carries the control as often as the hit object does.
            Transform up = found.transform.parent;
            if (up != null)
            {
                if (up.GetComponent<Button>() != null) return "button";
                if (up.GetComponent<Toggle>() != null) return "check box";
                if (up.GetComponent<Slider>() != null) return "slider";
                if (up.GetComponent<InputField>() != null) return "edit";
                if (up.GetComponent<Dropdown>() != null) return "combo box";
            }
            return "";
        }

        // A developer's object name is not a sentence. "BtnStart_01" becomes
        // "Btn Start 01", which is readable; something that is only digits
        // and punctuation becomes nothing, because saying "01" about a
        // control tells a player less than silence.
        private static string Readable(string name)
        {
            if (string.IsNullOrEmpty(name)) return "";
            StringBuilder built = new StringBuilder(name.Length + 8);
            bool anyLetter = false;
            for (int at = 0; at < name.Length; at++)
            {
                char letter = name[at];
                if (letter == '_' || letter == '-' || letter == '.')
                {
                    built.Append(' ');
                    continue;
                }
                if (at > 0 && char.IsUpper(letter) && !char.IsUpper(name[at - 1]))
                    built.Append(' ');
                if (char.IsLetter(letter)) anyLetter = true;
                built.Append(letter);
            }
            return anyLetter ? built.ToString().Trim() : "";
        }

        // Unity's rich text is markup the player never sees; the reader
        // would say every tag of it.
        private static string Clean(string text)
        {
            if (string.IsNullOrEmpty(text)) return "";
            StringBuilder built = new StringBuilder(text.Length);
            bool inside = false;
            for (int at = 0; at < text.Length; at++)
            {
                char letter = text[at];
                if (letter == '<') { inside = true; continue; }
                if (letter == '>') { inside = false; continue; }
                if (inside) continue;
                built.Append(letter == '\n' || letter == '\r' ? ' ' : letter);
            }
            return built.ToString().Trim();
        }
    }

    // ---------------------------------------------------------------------- //
    // The line to the reader. On a thread of its own, because a frame that
    // waits on a socket is a game that stutters.
    internal sealed class Link
    {
        private readonly string _host;
        private readonly int _port;
        private readonly string _token;
        private readonly BepInEx.Logging.ManualLogSource _log;
        private readonly BlockingCollection<string> _queue =
            new BlockingCollection<string>(64);
        private readonly Thread _thread;
        private TcpClient _client;
        private bool _stopping;

        public Link(string host, int port, string token,
                    BepInEx.Logging.ManualLogSource log)
        {
            _host = host; _port = port; _token = token; _log = log;
            _thread = new Thread(Pump);
            _thread.IsBackground = true;
            _thread.Start();
        }

        public void Send(string kind, string said)
        {
            // A queue that is full is dropped rather than waited on: the
            // newest thing seen is the only one worth saying anyway.
            _queue.TryAdd(Line(kind, said));
        }

        public void Stop()
        {
            _stopping = true;
            _queue.CompleteAdding();
            Close();
        }

        private string Line(string kind, string said)
        {
            return "{\"token\":\"" + Escape(_token) + "\",\"kind\":\""
                 + Escape(kind) + "\",\"say\":\"" + Escape(said)
                 + "\",\"rect\":[]}\n";
        }

        private static string Escape(string text)
        {
            StringBuilder built = new StringBuilder(text.Length + 8);
            foreach (char letter in text)
            {
                if (letter == '"' || letter == '\\') built.Append('\\').Append(letter);
                else if (letter < ' ') built.Append(' ');
                else built.Append(letter);
            }
            return built.ToString();
        }

        private void Pump()
        {
            foreach (string line in _queue.GetConsumingEnumerable())
            {
                if (_stopping) return;
                for (int attempt = 0; attempt < 2; attempt++)
                {
                    try
                    {
                        if (_client == null || !_client.Connected)
                        {
                            Close();
                            _client = new TcpClient();
                            _client.Connect(_host, _port);
                        }
                        byte[] bytes = Encoding.UTF8.GetBytes(line);
                        _client.GetStream().Write(bytes, 0, bytes.Length);
                        break;
                    }
                    catch (Exception error)
                    {
                        Close();
                        // Said once per failure and never per line: a reader
                        // that is not running would otherwise fill the log.
                        if (attempt == 1 && _log != null)
                            _log.LogDebug("Titan agent: " + error.Message);
                    }
                }
            }
        }

        private void Close()
        {
            try { if (_client != null) _client.Close(); }
            catch (Exception) { }
            _client = null;
        }
    }
}
