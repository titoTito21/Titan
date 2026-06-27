using System.Windows.Automation;
using System.Windows.Automation.Text;

namespace ScreenReader.EditableText;

/// <summary>
/// Obsługuje nawigację w tekście edytowalnym
/// Port z NVDA editableText.py i NVDAObjects/window/edit.py
/// </summary>
public class EditableTextHandler : IDisposable
{
    private AutomationElement? _element;
    private TextPattern? _textPattern;
    private int _lastCaretPosition;
    private string _lastText = "";
    private bool _disposed;

    /// <summary>Event wywoływany gdy należy ogłosić tekst</summary>
    public event Action<string>? Announce;

    /// <summary>Aktualny element edycyjny</summary>
    public AutomationElement? CurrentElement => _element;

    /// <summary>Czy jest aktywne pole edycyjne</summary>
    public bool IsActive => _element != null;

    /// <summary>
    /// Ustawia aktualny element edycyjny
    /// </summary>
    public void SetElement(AutomationElement? element)
    {
        _element = element;
        _textPattern = null;

        if (element != null)
        {
            try
            {
                if (element.TryGetCurrentPattern(TextPattern.Pattern, out var pattern))
                {
                    _textPattern = (TextPattern)pattern;
                }

                _lastCaretPosition = GetCaretPosition();
                _lastText = GetFullText();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"EditableTextHandler: Błąd inicjalizacji: {ex.Message}");
            }
        }
    }

    /// <summary>
    /// Sprawdza czy element to pole edycyjne
    /// </summary>
    public static bool IsEditField(AutomationElement element)
    {
        try
        {
            var controlType = element.Current.ControlType;
            return controlType == ControlType.Edit ||
                   controlType == ControlType.Document;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// Czyta bieżący znak
    /// </summary>
    public void ReadCurrentCharacter()
    {
        if (_element == null)
            return;

        try
        {
            // Sprawdź granice tekstu jeśli włączone w ustawieniach
            var settings = Settings.SettingsManager.Instance;
            if (settings.AnnounceTextBounds)
            {
                int position = GetCaretPosition();
                string text = GetFullText();

                if (position == 0 && text.Length > 0)
                {
                    Announce?.Invoke("Początek dokumentu");
                    return;
                }
                else if (position >= text.Length && text.Length > 0)
                {
                    Announce?.Invoke("Koniec dokumentu");
                    return;
                }
            }

            string ch = GetCharacterAtCaret();
            if (!string.IsNullOrEmpty(ch))
            {
                // Użyj alfabetu fonetycznego TYLKO jeśli włączone w ustawieniach
                string announcement;
                if (settings.PhoneticLetters && char.IsLetter(ch[0]))
                {
                    announcement = GetPhoneticAnnouncement(ch);
                }
                else
                {
                    // Bez fonetyki - tylko znak lub jego opis
                    announcement = GetSimpleAnnouncement(ch);
                }
                Announce?.Invoke(announcement);
            }
            else
            {
                Announce?.Invoke("koniec");
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"EditableTextHandler: Błąd odczytu znaku: {ex.Message}");
        }
    }

    /// <summary>
    /// Czyta bieżące słowo
    /// </summary>
    public void ReadCurrentWord()
    {
        if (_element == null)
            return;

        try
        {
            string word = GetWordAtCaret();
            if (!string.IsNullOrEmpty(word))
            {
                Announce?.Invoke(word);
            }
            else
            {
                Announce?.Invoke("brak słowa");
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"EditableTextHandler: Błąd odczytu słowa: {ex.Message}");
        }
    }

    /// <summary>
    /// Czyta bieżącą linię
    /// </summary>
    public void ReadCurrentLine()
    {
        if (_element == null)
            return;

        try
        {
            string line = GetLineAtCaret();
            if (!string.IsNullOrEmpty(line))
            {
                Announce?.Invoke(line);
            }
            else
            {
                Announce?.Invoke("pusta linia");
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"EditableTextHandler: Błąd odczytu linii: {ex.Message}");
        }
    }

    /// <summary>
    /// Czyta informacje o pozycji
    /// </summary>
    public void ReadPosition()
    {
        if (_element == null)
            return;

        try
        {
            int pos = GetCaretPosition();
            var (line, column) = GetLineColumn(pos);

            string announcement = $"Linia {line}, kolumna {column}";
            Announce?.Invoke(announcement);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"EditableTextHandler: Błąd odczytu pozycji: {ex.Message}");
        }
    }

    /// <summary>
    /// Obsługuje zdarzenie ruchu karetki
    /// </summary>
    public void OnCaretMoved()
    {
        if (_element == null)
            return;

        try
        {
            int newPos = GetCaretPosition();

            if (newPos != _lastCaretPosition)
            {
                int delta = newPos - _lastCaretPosition;

                // Pojedynczy znak
                if (Math.Abs(delta) == 1)
                {
                    ReadCurrentCharacter();
                }
                // Słowo
                else if (Math.Abs(delta) <= 20)
                {
                    ReadCurrentWord();
                }
                // Linia lub większy skok
                else
                {
                    ReadCurrentLine();
                }

                _lastCaretPosition = newPos;
            }
        }
        catch { }
    }

    /// <summary>
    /// Obsługuje zdarzenie zmiany tekstu
    /// </summary>
    public void OnTextChanged()
    {
        if (_element == null)
            return;

        try
        {
            string newText = GetFullText();

            if (newText != _lastText)
            {
                // Wykryj co się zmieniło
                if (newText.Length > _lastText.Length)
                {
                    // Wpisano tekst
                    int diff = newText.Length - _lastText.Length;
                    if (diff == 1)
                    {
                        // Pojedynczy znak
                        int pos = GetCaretPosition() - 1;
                        if (pos >= 0 && pos < newText.Length)
                        {
                            string ch = newText[pos].ToString();
                            Announce?.Invoke(ch);
                        }
                    }
                }
                else if (newText.Length < _lastText.Length)
                {
                    // Usunięto tekst
                    Announce?.Invoke("usunięto");
                }

                _lastText = newText;
            }
        }
        catch { }
    }

    /// <summary>
    /// Pobiera pozycję karetki
    /// </summary>
    private int GetCaretPosition()
    {
        if (_textPattern != null)
        {
            try
            {
                var selection = _textPattern.GetSelection();
                if (selection.Length > 0)
                {
                    // Użyj DocumentRange do znalezienia pozycji
                    var docRange = _textPattern.DocumentRange;
                    var caretRange = selection[0].Clone();

                    // Zlicz znaki do karetki
                    var startRange = docRange.Clone();
                    startRange.MoveEndpointByRange(TextPatternRangeEndpoint.End, caretRange, TextPatternRangeEndpoint.Start);
                    string textBefore = startRange.GetText(-1);
                    return textBefore.Length;
                }
            }
            catch { }
        }

        // Fallback: użyj ValuePattern
        if (_element != null && _element.TryGetCurrentPattern(ValuePattern.Pattern, out var valuePattern))
        {
            // Nie mamy dokładnej pozycji, zwróć 0
            return 0;
        }

        return 0;
    }

    /// <summary>
    /// Pobiera znak PRZED karetką (do użycia przy Backspace)
    /// Zwraca null jeśli brak znaku lub błąd
    /// </summary>
    public char? GetCharacterBeforeCaret()
    {
        if (_element == null)
            return null;

        try
        {
            if (_textPattern != null)
            {
                var selection = _textPattern.GetSelection();
                if (selection.Length > 0)
                {
                    var range = selection[0].Clone();
                    // Przesuń początek zakresu o jeden znak wstecz
                    int moved = range.MoveEndpointByUnit(TextPatternRangeEndpoint.Start, TextUnit.Character, -1);
                    if (moved < 0)
                    {
                        // Pobierz ten znak
                        string text = range.GetText(1);
                        if (!string.IsNullOrEmpty(text))
                        {
                            return text[0];
                        }
                    }
                }
            }

            // Fallback: użyj pełnego tekstu i pozycji
            string fullText = GetFullText();
            int pos = GetCaretPosition();
            if (pos > 0 && pos <= fullText.Length)
            {
                return fullText[pos - 1];
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"EditableTextHandler: Błąd GetCharacterBeforeCaret: {ex.Message}");
        }

        return null;
    }

    /// <summary>
    /// Pobiera ogłoszenie dla znaku (publiczna wersja) - respektuje ustawienia fonetyki
    /// </summary>
    public static string GetAnnouncementForCharacter(char ch)
    {
        var settings = Settings.SettingsManager.Instance;
        string chStr = ch.ToString();

        if (settings.PhoneticLetters && char.IsLetter(ch))
        {
            return GetPhoneticAnnouncement(chStr);
        }
        else
        {
            return GetSimpleAnnouncement(chStr);
        }
    }

    /// <summary>
    /// Pobiera fonetyczne ogłoszenie dla znaku (dla kompatybilności wstecznej)
    /// </summary>
    [Obsolete("Użyj GetAnnouncementForCharacter zamiast tego")]
    public static string GetPhoneticForCharacter(char ch)
    {
        return GetPhoneticAnnouncement(ch.ToString());
    }

    /// <summary>
    /// Pobiera znak na pozycji karetki
    /// </summary>
    private string GetCharacterAtCaret()
    {
        if (_textPattern != null)
        {
            try
            {
                var selection = _textPattern.GetSelection();
                if (selection.Length > 0)
                {
                    var range = selection[0].Clone();
                    range.MoveEndpointByUnit(TextPatternRangeEndpoint.End, TextUnit.Character, 1);
                    return range.GetText(1);
                }
            }
            catch { }
        }

        // Fallback
        string text = GetFullText();
        int pos = GetCaretPosition();
        if (pos >= 0 && pos < text.Length)
        {
            return text[pos].ToString();
        }

        return "";
    }

    /// <summary>
    /// Pobiera słowo na pozycji karetki
    /// </summary>
    private string GetWordAtCaret()
    {
        if (_textPattern != null)
        {
            try
            {
                var selection = _textPattern.GetSelection();
                if (selection.Length > 0)
                {
                    var range = selection[0].Clone();
                    range.ExpandToEnclosingUnit(TextUnit.Word);
                    return range.GetText(-1).Trim();
                }
            }
            catch { }
        }

        // Fallback: znajdź słowo w tekście
        string text = GetFullText();
        int pos = GetCaretPosition();
        return GetWordAt(text, pos);
    }

    /// <summary>
    /// Pobiera linię na pozycji karetki
    /// </summary>
    private string GetLineAtCaret()
    {
        if (_textPattern != null)
        {
            try
            {
                var selection = _textPattern.GetSelection();
                if (selection.Length > 0)
                {
                    var range = selection[0].Clone();
                    range.ExpandToEnclosingUnit(TextUnit.Line);
                    return range.GetText(-1).Trim();
                }
            }
            catch { }
        }

        // Fallback: znajdź linię w tekście
        string text = GetFullText();
        int pos = GetCaretPosition();
        return GetLineAt(text, pos);
    }

    /// <summary>
    /// Pobiera pełny tekst elementu
    /// </summary>
    private string GetFullText()
    {
        if (_textPattern != null)
        {
            try
            {
                return _textPattern.DocumentRange.GetText(-1);
            }
            catch { }
        }

        if (_element != null && _element.TryGetCurrentPattern(ValuePattern.Pattern, out var valuePattern))
        {
            return ((ValuePattern)valuePattern).Current.Value;
        }

        return "";
    }

    /// <summary>
    /// Pobiera numer linii i kolumny dla pozycji
    /// </summary>
    private (int line, int column) GetLineColumn(int position)
    {
        string text = GetFullText();
        int line = 1;
        int column = 1;

        for (int i = 0; i < position && i < text.Length; i++)
        {
            if (text[i] == '\n')
            {
                line++;
                column = 1;
            }
            else
            {
                column++;
            }
        }

        return (line, column);
    }

    /// <summary>
    /// Znajduje słowo na danej pozycji w tekście
    /// </summary>
    private static string GetWordAt(string text, int position)
    {
        if (string.IsNullOrEmpty(text) || position < 0 || position >= text.Length)
            return "";

        int start = position;
        int end = position;

        // Znajdź początek słowa
        while (start > 0 && char.IsLetterOrDigit(text[start - 1]))
            start--;

        // Znajdź koniec słowa
        while (end < text.Length && char.IsLetterOrDigit(text[end]))
            end++;

        if (start < end)
            return text.Substring(start, end - start);

        return "";
    }

    /// <summary>
    /// Znajduje linię na danej pozycji w tekście
    /// </summary>
    private static string GetLineAt(string text, int position)
    {
        if (string.IsNullOrEmpty(text))
            return "";

        position = Math.Clamp(position, 0, text.Length);

        int start = position;
        int end = position;

        // Znajdź początek linii
        while (start > 0 && text[start - 1] != '\n')
            start--;

        // Znajdź koniec linii
        while (end < text.Length && text[end] != '\n')
            end++;

        return text.Substring(start, end - start).Trim();
    }

    /// <summary>
    /// Pobiera prosty opis znaku (bez fonetyki)
    /// </summary>
    private static string GetSimpleAnnouncement(string ch)
    {
        if (string.IsNullOrEmpty(ch))
            return "";

        char c = ch[0];

        // Znaki specjalne - zawsze z opisem
        return c switch
        {
            ' ' => "spacja",
            '\n' => "nowa linia",
            '\r' => "powrót karetki",
            '\t' => "tabulator",
            '.' => "kropka",
            ',' => "przecinek",
            ';' => "średnik",
            ':' => "dwukropek",
            '!' => "wykrzyknik",
            '?' => "znak zapytania",
            '-' => "myślnik",
            '_' => "podkreślenie",
            '(' => "nawias otwierający",
            ')' => "nawias zamykający",
            '[' => "nawias kwadratowy otwierający",
            ']' => "nawias kwadratowy zamykający",
            '{' => "nawias klamrowy otwierający",
            '}' => "nawias klamrowy zamykający",
            '<' => "mniejszy niż",
            '>' => "większy niż",
            '/' => "ukośnik",
            '\\' => "ukośnik odwrotny",
            '@' => "małpa",
            '#' => "hash",
            '$' => "dolar",
            '%' => "procent",
            '^' => "daszek",
            '&' => "ampersand",
            '*' => "gwiazdka",
            '+' => "plus",
            '=' => "równa się",
            '"' => "cudzysłów",
            '\'' => "apostrof",
            '`' => "grawis",
            '~' => "tylda",
            '|' => "kreska pionowa",
            // Dla liter i cyfr - po prostu znak
            _ => char.IsUpper(c) ? $"duże {char.ToLower(c)}" : c.ToString()
        };
    }

    /// <summary>
    /// Pobiera fonetyczną reprezentację znaku (polski alfabet fonetyczny)
    /// </summary>
    private static string GetPhoneticAnnouncement(string ch)
    {
        if (string.IsNullOrEmpty(ch))
            return "";

        char c = char.ToUpperInvariant(ch[0]);

        // Polski alfabet fonetyczny (NATO z polskimi adaptacjami)
        return c switch
        {
            'A' => "Adam",
            'Ą' => "ą z ogonkiem",
            'B' => "Barbara",
            'C' => "Celina",
            'Ć' => "Ćma",
            'D' => "Dorota",
            'E' => "Ewa",
            'Ę' => "ę z ogonkiem",
            'F' => "Filip",
            'G' => "Genowefa",
            'H' => "Henryk",
            'I' => "Irena",
            'J' => "Jan",
            'K' => "Karol",
            'L' => "Leon",
            'Ł' => "Łukasz",
            'M' => "Maria",
            'N' => "Natalia",
            'Ń' => "Ńja",
            'O' => "Olga",
            'Ó' => "Ó kreskowane",
            'P' => "Paweł",
            'Q' => "Quebec",
            'R' => "Roman",
            'S' => "Stefan",
            'Ś' => "Śliwa",
            'T' => "Tadeusz",
            'U' => "Urszula",
            'V' => "Violetta",
            'W' => "Wacław",
            'X' => "Xawery",
            'Y' => "Ypsylon",
            'Z' => "Zygmunt",
            'Ź' => "Źrebak",
            'Ż' => "Żaneta",
            ' ' => "spacja",
            '\n' => "nowa linia",
            '\r' => "powrót karetki",
            '\t' => "tabulator",
            '.' => "kropka",
            ',' => "przecinek",
            ';' => "średnik",
            ':' => "dwukropek",
            '!' => "wykrzyknik",
            '?' => "znak zapytania",
            '-' => "myślnik",
            '_' => "podkreślenie",
            '(' => "nawias otwierający",
            ')' => "nawias zamykający",
            '[' => "nawias kwadratowy otwierający",
            ']' => "nawias kwadratowy zamykający",
            '{' => "nawias klamrowy otwierający",
            '}' => "nawias klamrowy zamykający",
            '<' => "mniejszy niż",
            '>' => "większy niż",
            '/' => "ukośnik",
            '\\' => "ukośnik odwrotny",
            '@' => "małpa",
            '#' => "hash",
            '$' => "dolar",
            '%' => "procent",
            '^' => "daszek",
            '&' => "ampersand",
            '*' => "gwiazdka",
            '+' => "plus",
            '=' => "równa się",
            '"' => "cudzysłów",
            '\'' => "apostrof",
            '`' => "grawis",
            '~' => "tylda",
            '|' => "kreska pionowa",
            _ => char.IsDigit(c) ? c.ToString() : ch
        };
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        _element = null;
        _textPattern = null;
        _disposed = true;
    }
}
