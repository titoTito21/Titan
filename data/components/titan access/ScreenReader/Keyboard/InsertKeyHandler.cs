namespace ScreenReader.Keyboard;

/// <summary>
/// Obsługuje wykrywanie i rozróżnianie klawiszy Insert (zwykły vs numpad)
/// Port z NVDA keyboardHandler.py
/// </summary>
public static class InsertKeyHandler
{
    // Flagi z KBDLLHOOKSTRUCT
    private const int LLKHF_EXTENDED = 0x01;
    private const int LLKHF_INJECTED = 0x10;

    // Virtual key codes
    public const int VK_INSERT = 0x2D;
    public const int VK_CAPSLOCK = 0x14;
    public const int VK_NUMLOCK = 0x90;

    /// <summary>
    /// Typ klawisza Insert
    /// </summary>
    public enum InsertKeyType
    {
        None,
        /// <summary>Zwykły Insert (nad Home/End)</summary>
        ExtendedInsert,
        /// <summary>Insert z numpada (Num0 przy wyłączonym NumLock)</summary>
        NumpadInsert
    }

    /// <summary>
    /// Określa typ klawisza Insert na podstawie kodu i flag
    /// </summary>
    /// <param name="vkCode">Virtual key code</param>
    /// <param name="flags">Flagi z KBDLLHOOKSTRUCT</param>
    /// <returns>Typ klawisza Insert lub None</returns>
    public static InsertKeyType GetInsertKeyType(int vkCode, int flags)
    {
        if (vkCode != VK_INSERT)
            return InsertKeyType.None;

        // Flaga LLKHF_EXTENDED jest ustawiona dla zwykłego Insert (nad Home/End)
        // Nie jest ustawiona dla NumPad Insert
        bool isExtended = (flags & LLKHF_EXTENDED) != 0;
        return isExtended ? InsertKeyType.ExtendedInsert : InsertKeyType.NumpadInsert;
    }

    /// <summary>
    /// Sprawdza czy dany klawisz to modyfikator NVDA
    /// </summary>
    /// <param name="vkCode">Virtual key code</param>
    /// <param name="flags">Flagi z KBDLLHOOKSTRUCT</param>
    /// <param name="config">Konfiguracja modyfikatorów</param>
    /// <returns>True jeśli to modyfikator NVDA</returns>
    public static bool IsNVDAModifierKey(int vkCode, int flags, NVDAModifierConfig config)
    {
        var insertType = GetInsertKeyType(vkCode, flags);

        return insertType switch
        {
            InsertKeyType.ExtendedInsert => config.HasFlag(NVDAModifierConfig.ExtendedInsert),
            InsertKeyType.NumpadInsert => config.HasFlag(NVDAModifierConfig.NumpadInsert),
            _ => vkCode == VK_CAPSLOCK && config.HasFlag(NVDAModifierConfig.CapsLock)
        };
    }

    /// <summary>
    /// Sprawdza czy klawisz został wstrzyknięty (injected)
    /// </summary>
    public static bool IsInjectedKey(int flags)
    {
        return (flags & LLKHF_INJECTED) != 0;
    }

    /// <summary>
    /// Zwraca nazwę klawisza Insert po polsku
    /// </summary>
    public static string GetInsertKeyName(InsertKeyType type)
    {
        return type switch
        {
            InsertKeyType.ExtendedInsert => "Insert",
            InsertKeyType.NumpadInsert => "Insert numeryczny",
            _ => ""
        };
    }
}

/// <summary>
/// Konfiguracja klawiszy modyfikatora NVDA (bitflags)
/// Wzorowane na NVDA config NVDAKey enum
/// </summary>
[Flags]
public enum NVDAModifierConfig
{
    None = 0,
    /// <summary>CapsLock jako modyfikator</summary>
    CapsLock = 1,
    /// <summary>NumPad Insert jako modyfikator</summary>
    NumpadInsert = 2,
    /// <summary>Zwykły Insert jako modyfikator</summary>
    ExtendedInsert = 4,

    /// <summary>Domyślna konfiguracja: oba Insert i CapsLock</summary>
    Default = CapsLock | NumpadInsert | ExtendedInsert
}
