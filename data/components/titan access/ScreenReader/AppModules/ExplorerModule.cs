using System.Windows.Automation;

namespace ScreenReader.AppModules;

/// <summary>
/// Moduł dla Eksploratora Windows (explorer.exe)
/// Ulepsza nawigację po plikach i folderach
/// </summary>
public class ExplorerModule : AppModuleBase
{
    public override string ProcessName => "explorer";
    public override string AppName => "Eksplorator plików";

    private string? _lastAnnouncedPath;

    public override string CustomizeElementDescription(AutomationElement element, string defaultDescription)
    {
        try
        {
            var controlType = element.Current.ControlType;
            var className = element.Current.ClassName;

            // Lista plików - dodaj informacje o typie pliku
            if (controlType == ControlType.ListItem || controlType == ControlType.DataItem)
            {
                string name = element.Current.Name;

                // Sprawdź czy to folder czy plik
                if (element.TryGetCurrentPattern(SelectionItemPattern.Pattern, out _))
                {
                    // Sprawdź rozszerzenie pliku
                    if (!string.IsNullOrEmpty(name))
                    {
                        if (name.Contains('.'))
                        {
                            string extension = Path.GetExtension(name).ToLowerInvariant();
                            string fileType = GetFileTypeDescription(extension);
                            return $"{defaultDescription}, {fileType}";
                        }
                        else
                        {
                            // Prawdopodobnie folder
                            return $"{defaultDescription}, folder";
                        }
                    }
                }
            }

            // Pole adresu - ogłoś bieżącą ścieżkę
            if (className == "Edit" && element.Current.Name.Contains("Adres"))
            {
                if (element.TryGetCurrentPattern(ValuePattern.Pattern, out var valuePattern))
                {
                    string path = ((ValuePattern)valuePattern).Current.Value;
                    if (!string.IsNullOrEmpty(path) && path != _lastAnnouncedPath)
                    {
                        _lastAnnouncedPath = path;
                        return $"Adres: {path}";
                    }
                }
            }

            // Drzewo folderów
            if (controlType == ControlType.TreeItem)
            {
                // Sprawdź poziom zagnieżdżenia
                int level = GetTreeItemLevel(element);
                if (level > 0)
                {
                    return $"{defaultDescription}, poziom {level}";
                }
            }
        }
        catch
        {
            // Ignoruj błędy
        }

        return defaultDescription;
    }

    /// <summary>
    /// Pobiera poziom zagnieżdżenia elementu drzewa
    /// </summary>
    private static int GetTreeItemLevel(AutomationElement treeItem)
    {
        int level = 0;
        var walker = TreeWalker.ControlViewWalker;
        var current = walker.GetParent(treeItem);

        while (current != null)
        {
            if (current.Current.ControlType == ControlType.TreeItem)
                level++;
            else if (current.Current.ControlType == ControlType.Tree)
                break;

            current = walker.GetParent(current);
        }

        return level;
    }

    /// <summary>
    /// Zwraca opis typu pliku na podstawie rozszerzenia
    /// </summary>
    private static string GetFileTypeDescription(string extension)
    {
        return extension.ToLowerInvariant() switch
        {
            ".txt" => "plik tekstowy",
            ".pdf" => "dokument PDF",
            ".doc" or ".docx" => "dokument Word",
            ".xls" or ".xlsx" => "arkusz Excel",
            ".ppt" or ".pptx" => "prezentacja PowerPoint",
            ".jpg" or ".jpeg" or ".png" or ".gif" or ".bmp" => "obraz",
            ".mp3" or ".wav" or ".flac" or ".ogg" => "plik audio",
            ".mp4" or ".avi" or ".mkv" or ".mov" => "plik wideo",
            ".zip" or ".rar" or ".7z" => "archiwum",
            ".exe" => "program wykonywalny",
            ".dll" => "biblioteka",
            ".cs" => "kod C#",
            ".py" => "skrypt Python",
            ".js" => "skrypt JavaScript",
            ".html" or ".htm" => "strona HTML",
            ".css" => "arkusz stylów",
            ".json" => "plik JSON",
            ".xml" => "plik XML",
            _ => $"plik {extension}"
        };
    }

    public override void Terminate()
    {
        _lastAnnouncedPath = null;
        base.Terminate();
    }
}
