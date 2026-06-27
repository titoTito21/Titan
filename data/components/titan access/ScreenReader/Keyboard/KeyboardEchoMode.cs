using ScreenReader.Localization;

namespace ScreenReader.Keyboard;

/// <summary>
/// Tryby echa klawiatury
/// </summary>
public enum KeyboardEchoMode
{
    /// <summary>Ogłaszaj każdy wpisany znak</summary>
    Characters,

    /// <summary>Ogłaszaj słowa po spacji/interpunkcji</summary>
    Words,

    /// <summary>Ogłaszaj zarówno znaki jak i słowa</summary>
    WordsAndChars,

    /// <summary>Brak echa klawiatury</summary>
    None
}

/// <summary>
/// Extension methods dla KeyboardEchoMode
/// </summary>
public static class KeyboardEchoModeExtensions
{
    /// <summary>
    /// Zwraca polską nazwę trybu echa (używane w logach diagnostycznych)
    /// </summary>
    public static string GetPolishName(this KeyboardEchoMode mode) => mode switch
    {
        KeyboardEchoMode.Characters => "znaki",
        KeyboardEchoMode.Words => "słowa",
        KeyboardEchoMode.WordsAndChars => "słowa i znaki",
        KeyboardEchoMode.None => "brak",
        _ => "nieznany"
    };

    /// <summary>
    /// Zwraca nazwę trybu echa w bieżącym języku (tekst dla użytkownika)
    /// </summary>
    public static string GetLocalizedName(this KeyboardEchoMode mode) => mode switch
    {
        KeyboardEchoMode.Characters => L.T("keyEcho.characters"),
        KeyboardEchoMode.Words => L.T("keyEcho.words"),
        KeyboardEchoMode.WordsAndChars => L.T("keyEcho.wordsAndChars"),
        KeyboardEchoMode.None => L.T("keyEcho.none"),
        _ => L.T("keyEcho.unknown")
    };

    /// <summary>
    /// Zwraca następny tryb w cyklu
    /// </summary>
    public static KeyboardEchoMode Next(this KeyboardEchoMode mode) => mode switch
    {
        KeyboardEchoMode.Characters => KeyboardEchoMode.Words,
        KeyboardEchoMode.Words => KeyboardEchoMode.WordsAndChars,
        KeyboardEchoMode.WordsAndChars => KeyboardEchoMode.None,
        KeyboardEchoMode.None => KeyboardEchoMode.Characters,
        _ => KeyboardEchoMode.Characters
    };

    /// <summary>
    /// Sprawdza czy tryb zawiera echo znaków
    /// </summary>
    public static bool IncludesCharacters(this KeyboardEchoMode mode) =>
        mode == KeyboardEchoMode.Characters || mode == KeyboardEchoMode.WordsAndChars;

    /// <summary>
    /// Sprawdza czy tryb zawiera echo słów
    /// </summary>
    public static bool IncludesWords(this KeyboardEchoMode mode) =>
        mode == KeyboardEchoMode.Words || mode == KeyboardEchoMode.WordsAndChars;
}
