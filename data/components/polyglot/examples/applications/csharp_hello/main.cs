// A Titan application written in C#. Polyglot compiles it with the C#
// compiler every Windows carries, together with its SDK (the Titan class),
// the first time it is opened - and again only when it changes.
using System;

static class Program
{
    static void Main()
    {
        bool polish = Titan.Language == "pl";
        string name = Titan.Ask(polish ? "Jak masz na imię?" : "What is your name?");
        if (name == null) return;
        Titan.Speak((polish ? "Cześć z C#, " : "Hello from C#, ") + name + ". "
                    + Environment.ProcessorCount + (polish ? " rdzeni." : " cores."));
        Titan.Wait(4);
    }
}
