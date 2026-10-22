// Titan for C# - the Polyglot line protocol.
//
// Polyglot compiles a .cs program with the C# compiler every Windows carries
// (.NET Framework 4, csc.exe) and compiles THIS file beside it, so a program
// just calls Titan:
//
//   Titan.Speak("Hello");
//   string name = Titan.Ask("Your name?");
//   int? i = Titan.Choose("Pick one", new[] { "Tea", "Coffee" });  // from 0
//
// Written for C# 5 (what csc.exe of .NET Framework 4 compiles) and for the
// JSON serializer the Framework has, so nothing has to be installed.
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;

public static class Titan
{
    static int nextId;
    static readonly JavaScriptSerializer json = new JavaScriptSerializer();
    static readonly TextReader input = new StreamReader(
        Console.OpenStandardInput(), new UTF8Encoding(false));
    static readonly TextWriter output = new StreamWriter(
        Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true };

    /// <summary>Any call of the protocol, with positional arguments.</summary>
    public static object Call(string name, params object[] args)
    {
        nextId++;
        var payload = new Dictionary<string, object> {
            { "id", nextId }, { "call", name }, { "args", args ?? new object[0] } };
        output.WriteLine(json.Serialize(payload));
        while (true)
        {
            string line = input.ReadLine();
            if (line == null) throw new Exception("Titan has gone");
            if (!line.StartsWith("{")) continue;
            var reply = json.Deserialize<Dictionary<string, object>>(line);
            if (Convert.ToInt32(reply["id"]) != nextId) continue;
            if (!(bool)reply["ok"]) throw new Exception(Convert.ToString(reply["error"]));
            object value;
            reply.TryGetValue("value", out value);
            return value;
        }
    }

    public static Dictionary<string, object> Info()
    {
        return (Dictionary<string, object>)Call("info");
    }

    public static string Language { get { return Convert.ToString(Info()["language"]); } }

    public static bool Speak(string text, bool interrupt = true)
    {
        return Convert.ToBoolean(Call("speak", text, interrupt));
    }

    public static void Message(string text) { Call("message", text); }

    public static string Ask(string prompt, string defaultText = "")
    {
        return (string)Call("ask", prompt, defaultText);
    }

    public static bool Confirm(string text) { return Convert.ToBoolean(Call("confirm", text)); }

    public static int? Choose(string prompt, IList<string> options)
    {
        object value = Call("choose", prompt, options);
        return value == null ? (int?)null : Convert.ToInt32(value);
    }

    public static void Text(string text, string title) { Call("text", text, title); }

    public static bool Play(string sound, double position = 0)
    {
        return Convert.ToBoolean(Call("play", sound, position));
    }

    public static void OpenWindow(string title) { Call("open_window", title); }

    /// <summary>The next event, or null; timeout in seconds, negative waits.</summary>
    public static Dictionary<string, object> NextEvent(double timeout = -1)
    {
        return (Dictionary<string, object>)Call("next_event", timeout);
    }

    public static void Wait(double seconds) { Call("wait", seconds); }

    public static void Log(string text) { Call("log", text); }

    /// <summary>Any Titan add-on's action; answers what it said.</summary>
    public static string Action(string addon, string action,
                                Dictionary<string, object> args = null)
    {
        var result = (Dictionary<string, object>)Call(
            "action", addon, action, args ?? new Dictionary<string, object>());
        return Convert.ToString(result["text"]);
    }
}
