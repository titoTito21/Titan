using System.Windows.Forms;
using System.Speech.Synthesis;
using ScreenReader.Speech;
using ScreenReader.Settings;

namespace ScreenReader;

/// <summary>
/// Dialog ustawień czytnika ekranu z kategoriami
/// Nawigacja: strzałki góra/dół między kategoriami i ich elementami
/// </summary>
public class SettingsDialog : Form
{
    private readonly SpeechManager _speechManager;
    private readonly SettingsManager _settings;

    // Kontrolki główne
    private ListBox _categoryList = null!;
    private Panel _contentPanel = null!;
    private Button _btnOK = null!;
    private Button _btnCancel = null!;
    private Button _btnApply = null!;

    // Panele kategorii
    private Panel? _voicePanel;
    private Panel? _generalPanel;
    private Panel? _verbosityPanel;
    private Panel? _navigationPanel;
    private Panel? _textEditingPanel;

    // Kontrolki głosu
    private ComboBox _synthesizerComboBox = null!;
    private ComboBox _voiceComboBox = null!;
    private NumericUpDown _rateNumeric = null!;
    private NumericUpDown _volumeNumeric = null!;
    private NumericUpDown _pitchNumeric = null!;

    // Kontrolki ogólne
    private CheckBox _chkMuteOutsideTCE = null!;
    private ComboBox _cmbStartupAnnouncement = null!;
    private CheckBox _chkTCEEntrySound = null!;
    private ComboBox _cmbModifier = null!;
    private TextBox _txtWelcomeMessage = null!;
    private CheckBox _chkSpeakHints = null!;

    // Kontrolki szczegółowości
    private CheckBox _chkAnnounceBasicControls = null!;
    private CheckBox _chkAnnounceBlockControls = null!;
    private CheckBox _chkAnnounceListPosition = null!;
    private CheckedListBox _lstMenuInfo = null!;  // Informacja o menu
    private CheckedListBox _lstElementInfo = null!;  // Informacja o elementach
    private ComboBox _cmbToggleKeysMode = null!;

    // Kontrolki nawigacji
    private CheckBox _chkAdvancedNavigation = null!;
    private CheckBox _chkAnnounceControlTypesNav = null!;
    private CheckBox _chkAnnounceHierarchyLevel = null!;
    private ComboBox _cmbWindowBoundsMode = null!;
    private CheckBox _chkPhoneticInDial = null!;
    private CheckedListBox _lstDialElements = null!;  // Elementy pokrętła

    // Kontrolki edycji tekstu
    private CheckBox _chkPhoneticLetters = null!;
    private ComboBox _cmbKeyboardEcho = null!;
    private CheckBox _chkAnnounceTextBounds = null!;

    // Mapowanie głosów OneCore
    private Dictionary<string, string> _oneCoreVoiceMap = new();

    // Flaga zapobiegająca zapisowi podczas ładowania
    private bool _isLoading = true;

    // Flaga informująca czy ustawienia zostały zmienione
    private bool _settingsChanged = false;

    public SettingsDialog(SpeechManager speechManager)
    {
        _speechManager = speechManager;
        _settings = SettingsManager.Instance;
        InitializeComponents();
        LoadCurrentSettings();
        _isLoading = false;
    }

    private void InitializeComponents()
    {
        Text = "Ustawienia czytnika ekranu";
        Width = 700;
        Height = 550;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        TopMost = true;
        KeyPreview = true;

        // Lista kategorii po lewej stronie
        var lblCategories = new Label
        {
            Text = "Kategorie:",
            Left = 10,
            Top = 10,
            Width = 150,
            AutoSize = true
        };

        _categoryList = new ListBox
        {
            Left = 10,
            Top = 30,
            Width = 150,
            Height = 420,
            Font = new System.Drawing.Font("Segoe UI", 10)
        };
        _categoryList.Items.AddRange(new object[] {
            "Głos",
            "Ogólne",
            "Szczegółowość",
            "Nawigacja",
            "Edycja tekstu"
        });
        _categoryList.SelectedIndexChanged += CategoryList_SelectedIndexChanged;

        // Panel zawartości po prawej stronie
        _contentPanel = new Panel
        {
            Left = 170,
            Top = 10,
            Width = 510,
            Height = 440,
            BorderStyle = BorderStyle.FixedSingle,
            AutoScroll = true
        };

        // Przyciski na dole
        _btnOK = new Button
        {
            Text = "OK",
            Left = 350,
            Top = 460,
            Width = 100,
            Height = 30
        };
        _btnOK.Click += BtnOK_Click;

        _btnCancel = new Button
        {
            Text = "Anuluj",
            Left = 460,
            Top = 460,
            Width = 100,
            Height = 30,
            DialogResult = DialogResult.Cancel
        };

        _btnApply = new Button
        {
            Text = "Zastosuj",
            Left = 570,
            Top = 460,
            Width = 100,
            Height = 30
        };
        _btnApply.Click += BtnApply_Click;

        // Utwórz panele kategorii
        CreateVoicePanel();
        CreateGeneralPanel();
        CreateVerbosityPanel();
        CreateNavigationPanel();
        CreateTextEditingPanel();

        Controls.AddRange(new Control[] {
            lblCategories, _categoryList, _contentPanel,
            _btnOK, _btnCancel, _btnApply
        });

        AcceptButton = _btnOK;
        CancelButton = _btnCancel;

        // Domyślnie wybierz pierwszą kategorię
        _categoryList.SelectedIndex = 0;
    }

    private void CreateVoicePanel()
    {
        _voicePanel = new Panel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true
        };

        int yPos = 10;

        // Syntezator
        var lblSynthesizer = new Label
        {
            Text = "Syntezator:",
            Left = 10,
            Top = yPos,
            Width = 120,
            AutoSize = true
        };
        _synthesizerComboBox = new ComboBox
        {
            Left = 140,
            Top = yPos,
            Width = 250,
            DropDownStyle = ComboBoxStyle.DropDownList
        };
        _synthesizerComboBox.Items.Add("SAPI 5");
        _synthesizerComboBox.Items.Add("OneCore (Mobile)");
        _synthesizerComboBox.SelectedIndexChanged += SynthesizerComboBox_SelectedIndexChanged;
        yPos += 35;

        // Głos
        var lblVoice = new Label
        {
            Text = "Głos:",
            Left = 10,
            Top = yPos,
            Width = 120,
            AutoSize = true
        };
        _voiceComboBox = new ComboBox
        {
            Left = 140,
            Top = yPos,
            Width = 340,
            DropDownStyle = ComboBoxStyle.DropDownList
        };
        _voiceComboBox.SelectedIndexChanged += VoiceComboBox_SelectedIndexChanged;
        yPos += 35;

        // Głośność
        var lblVolume = new Label
        {
            Text = "Głośność:",
            Left = 10,
            Top = yPos,
            Width = 120,
            AutoSize = true
        };
        _volumeNumeric = new NumericUpDown
        {
            Left = 140,
            Top = yPos,
            Width = 100,
            Minimum = 0,
            Maximum = 100,
            Value = 100
        };
        _volumeNumeric.ValueChanged += VolumeNumeric_ValueChanged;
        var lblVolumeInfo = new Label
        {
            Text = "(0-100)",
            Left = 250,
            Top = yPos + 3,
            Width = 100,
            AutoSize = true
        };
        yPos += 35;

        // Szybkość
        var lblRate = new Label
        {
            Text = "Szybkość:",
            Left = 10,
            Top = yPos,
            Width = 120,
            AutoSize = true
        };
        _rateNumeric = new NumericUpDown
        {
            Left = 140,
            Top = yPos,
            Width = 100,
            Minimum = -10,
            Maximum = 10,
            Value = 0
        };
        _rateNumeric.ValueChanged += RateNumeric_ValueChanged;
        var lblRateInfo = new Label
        {
            Text = "(-10 wolno, 0 normalnie, 10 szybko)",
            Left = 250,
            Top = yPos + 3,
            Width = 220,
            AutoSize = true
        };
        yPos += 35;

        // Wysokość
        var lblPitch = new Label
        {
            Text = "Wysokość:",
            Left = 10,
            Top = yPos,
            Width = 120,
            AutoSize = true
        };
        _pitchNumeric = new NumericUpDown
        {
            Left = 140,
            Top = yPos,
            Width = 100,
            Minimum = -10,
            Maximum = 10,
            Value = 0,
            Enabled = false
        };
        var lblPitchInfo = new Label
        {
            Text = "(nieobsługiwane przez System.Speech)",
            Left = 250,
            Top = yPos + 3,
            Width = 220,
            AutoSize = true,
            ForeColor = System.Drawing.Color.Gray
        };

        _voicePanel.Controls.AddRange(new Control[] {
            lblSynthesizer, _synthesizerComboBox,
            lblVoice, _voiceComboBox,
            lblVolume, _volumeNumeric, lblVolumeInfo,
            lblRate, _rateNumeric, lblRateInfo,
            lblPitch, _pitchNumeric, lblPitchInfo
        });
    }

    private void CreateGeneralPanel()
    {
        _generalPanel = new Panel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true
        };

        int yPos = 10;

        // Milcz poza środowiskiem TCE
        _chkMuteOutsideTCE = new CheckBox
        {
            Text = "Milcz poza środowiskiem TCE",
            Left = 10,
            Top = yPos,
            Width = 450,
            AutoSize = true
        };
        _chkMuteOutsideTCE.CheckedChanged += SettingChanged;
        yPos += 30;

        // Oznajmiaj uruchamianie i zamykanie
        var lblStartupAnnouncement = new Label
        {
            Text = "Oznajmiaj uruchamianie i zamykanie czytnika ekranu:",
            Left = 10,
            Top = yPos,
            Width = 400,
            AutoSize = true
        };
        yPos += 22;
        _cmbStartupAnnouncement = new ComboBox
        {
            Left = 10,
            Top = yPos,
            Width = 200,
            DropDownStyle = ComboBoxStyle.DropDownList
        };
        _cmbStartupAnnouncement.Items.AddRange(new object[] { "Brak", "Dźwięk", "Mowa", "Mowa i dźwięk" });
        _cmbStartupAnnouncement.SelectedIndexChanged += SettingChanged;
        yPos += 35;

        // Oznajmiaj dźwiękiem wejście/wyjście z Titana
        _chkTCEEntrySound = new CheckBox
        {
            Text = "Oznajmiaj dźwiękiem wejście i wyjście z Titana",
            Left = 10,
            Top = yPos,
            Width = 450,
            AutoSize = true
        };
        _chkTCEEntrySound.CheckedChanged += SettingChanged;
        yPos += 30;

        // Modyfikator czytnika ekranu
        var lblModifier = new Label
        {
            Text = "Modyfikator czytnika ekranu:",
            Left = 10,
            Top = yPos,
            Width = 200,
            AutoSize = true
        };
        yPos += 22;
        _cmbModifier = new ComboBox
        {
            Left = 10,
            Top = yPos,
            Width = 200,
            DropDownStyle = ComboBoxStyle.DropDownList
        };
        _cmbModifier.Items.AddRange(new object[] { "Insert", "CapsLock", "Insert i CapsLock" });
        _cmbModifier.SelectedIndexChanged += SettingChanged;
        yPos += 35;

        // Komunikat powitalny
        var lblWelcomeMessage = new Label
        {
            Text = "Komunikat powitalny:",
            Left = 10,
            Top = yPos,
            Width = 200,
            AutoSize = true
        };
        yPos += 22;
        _txtWelcomeMessage = new TextBox
        {
            Left = 10,
            Top = yPos,
            Width = 450
        };
        _txtWelcomeMessage.TextChanged += SettingChanged;
        yPos += 35;

        // Mów podpowiedzi
        _chkSpeakHints = new CheckBox
        {
            Text = "Mów podpowiedzi",
            Left = 10,
            Top = yPos,
            Width = 450,
            AutoSize = true
        };
        _chkSpeakHints.CheckedChanged += SettingChanged;
        yPos += 30;

        // Opis podpowiedzi
        var lblHintsInfo = new Label
        {
            Text = "Podpowiedzi to komunikaty 2 sekundy po określonej kontrolce:\n" +
                   "- Przycisk: naciśnij Enter lub spację, aby aktywować\n" +
                   "- Pole wyboru: aby zaznaczyć lub odznaczyć, naciśnij spację\n" +
                   "- Edycja/dokument: zacznij pisać, aby edytować",
            Left = 30,
            Top = yPos,
            Width = 450,
            Height = 80,
            ForeColor = System.Drawing.Color.Gray
        };

        _generalPanel.Controls.AddRange(new Control[] {
            _chkMuteOutsideTCE,
            lblStartupAnnouncement, _cmbStartupAnnouncement,
            _chkTCEEntrySound,
            lblModifier, _cmbModifier,
            lblWelcomeMessage, _txtWelcomeMessage,
            _chkSpeakHints, lblHintsInfo
        });
    }

    private void CreateVerbosityPanel()
    {
        _verbosityPanel = new Panel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true
        };

        int yPos = 10;

        // Oznajmiaj typy kontrolek podstawowych
        _chkAnnounceBasicControls = new CheckBox
        {
            Text = "Oznajmiaj typy kontrolek podstawowych",
            Left = 10,
            Top = yPos,
            Width = 450,
            AutoSize = true
        };
        _chkAnnounceBasicControls.CheckedChanged += SettingChanged;
        var lblBasicInfo = new Label
        {
            Text = "(przycisk, pole edycji, pole wyboru)",
            Left = 30,
            Top = yPos + 20,
            Width = 300,
            AutoSize = true,
            ForeColor = System.Drawing.Color.Gray
        };
        yPos += 45;

        // Oznajmiaj typy kontrolek blokowych
        _chkAnnounceBlockControls = new CheckBox
        {
            Text = "Oznajmiaj typy kontrolek blokowych",
            Left = 10,
            Top = yPos,
            Width = 450,
            AutoSize = true
        };
        _chkAnnounceBlockControls.CheckedChanged += SettingChanged;
        var lblBlockInfo = new Label
        {
            Text = "(element listy, element menu, etc.)",
            Left = 30,
            Top = yPos + 20,
            Width = 300,
            AutoSize = true,
            ForeColor = System.Drawing.Color.Gray
        };
        yPos += 45;

        // Oznajmiaj pozycję elementu listy
        _chkAnnounceListPosition = new CheckBox
        {
            Text = "Oznajmiaj pozycję elementu listy",
            Left = 10,
            Top = yPos,
            Width = 450,
            AutoSize = true
        };
        _chkAnnounceListPosition.CheckedChanged += SettingChanged;
        yPos += 30;

        // Informacja o menu - CheckedListBox
        var lblMenuInfo = new Label
        {
            Text = "Informacja o menu:",
            Left = 10,
            Top = yPos,
            Width = 200,
            AutoSize = true,
            Font = new System.Drawing.Font(System.Drawing.SystemFonts.DefaultFont, System.Drawing.FontStyle.Bold)
        };
        yPos += 22;

        _lstMenuInfo = new CheckedListBox
        {
            Left = 10,
            Top = yPos,
            Width = 300,
            Height = 65,
            CheckOnClick = true
        };
        _lstMenuInfo.Items.AddRange(new object[] {
            "Liczba elementów",
            "Nazwa menu",
            "Dźwięki otwierania i zamykania menu"
        });
        _lstMenuInfo.ItemCheck += (s, e) => { if (!_isLoading) _settingsChanged = true; };
        yPos += 75;

        // Informacja o elementach - CheckedListBox
        var lblElementInfo = new Label
        {
            Text = "Informacja o elementach:",
            Left = 10,
            Top = yPos,
            Width = 200,
            AutoSize = true,
            Font = new System.Drawing.Font(System.Drawing.SystemFonts.DefaultFont, System.Drawing.FontStyle.Bold)
        };
        yPos += 22;

        _lstElementInfo = new CheckedListBox
        {
            Left = 10,
            Top = yPos,
            Width = 300,
            Height = 80,
            CheckOnClick = true
        };
        _lstElementInfo.Items.AddRange(new object[] {
            "Nazwa",
            "Typ",
            "Stan kontrolki",
            "Parametr kontrolki (np. URL linku)"
        });
        _lstElementInfo.ItemCheck += (s, e) => { if (!_isLoading) _settingsChanged = true; };
        yPos += 90;

        // Oznajmiaj stany klawiszy
        var lblToggleKeys = new Label
        {
            Text = "Oznajmiaj stany klawiszy (CapsLock, NumLock):",
            Left = 10,
            Top = yPos,
            Width = 350,
            AutoSize = true
        };
        yPos += 22;
        _cmbToggleKeysMode = new ComboBox
        {
            Left = 10,
            Top = yPos,
            Width = 200,
            DropDownStyle = ComboBoxStyle.DropDownList
        };
        _cmbToggleKeysMode.Items.AddRange(new object[] { "Brak (niezalecane)", "Dźwięk", "Mowa", "Mowa i dźwięk" });
        _cmbToggleKeysMode.SelectedIndexChanged += SettingChanged;

        _verbosityPanel.Controls.AddRange(new Control[] {
            _chkAnnounceBasicControls, lblBasicInfo,
            _chkAnnounceBlockControls, lblBlockInfo,
            _chkAnnounceListPosition,
            lblMenuInfo, _lstMenuInfo,
            lblElementInfo, _lstElementInfo,
            lblToggleKeys, _cmbToggleKeysMode
        });
    }

    private void CreateNavigationPanel()
    {
        _navigationPanel = new Panel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true
        };

        int yPos = 10;

        // Nawigacja obiektowa strzałkami
        _chkAdvancedNavigation = new CheckBox
        {
            Text = "Nawigacja obiektowa strzałkami",
            Left = 10,
            Top = yPos,
            Width = 450,
            AutoSize = true
        };
        _chkAdvancedNavigation.CheckedChanged += SettingChanged;
        yPos += 30;

        // Oznajmiaj typy kontrolek w nawigacji
        _chkAnnounceControlTypesNav = new CheckBox
        {
            Text = "Oznajmiaj typy kontrolek w trakcie nawigacji",
            Left = 10,
            Top = yPos,
            Width = 450,
            AutoSize = true
        };
        _chkAnnounceControlTypesNav.CheckedChanged += SettingChanged;
        yPos += 30;

        // Oznajmiaj poziom w hierarchii
        _chkAnnounceHierarchyLevel = new CheckBox
        {
            Text = "Oznajmiaj poziom w hierarchii nawigacji obiektowej",
            Left = 10,
            Top = yPos,
            Width = 450,
            AutoSize = true
        };
        _chkAnnounceHierarchyLevel.CheckedChanged += SettingChanged;
        yPos += 30;

        // Oznajmianie początku i końca okna
        var lblWindowBounds = new Label
        {
            Text = "Oznajmianie początku i końca okna w trakcie nawigacji:",
            Left = 10,
            Top = yPos,
            Width = 400,
            AutoSize = true
        };
        yPos += 22;
        _cmbWindowBoundsMode = new ComboBox
        {
            Left = 10,
            Top = yPos,
            Width = 200,
            DropDownStyle = ComboBoxStyle.DropDownList
        };
        _cmbWindowBoundsMode.Items.AddRange(new object[] { "Brak", "Dźwięk", "Mowa", "Mowa i dźwięk" });
        _cmbWindowBoundsMode.SelectedIndexChanged += SettingChanged;
        yPos += 35;

        // Ogłaszaj przykład fonetyczny w pokrętle
        _chkPhoneticInDial = new CheckBox
        {
            Text = "Ogłaszaj przykład fonetyczny w trakcie nawigacji przy pomocy pokrętła",
            Left = 10,
            Top = yPos,
            Width = 470,
            AutoSize = true
        };
        _chkPhoneticInDial.CheckedChanged += SettingChanged;
        var lblPhoneticInfo = new Label
        {
            Text = "(np. A - Adam zamiast samego A)",
            Left = 30,
            Top = yPos + 20,
            Width = 300,
            AutoSize = true,
            ForeColor = System.Drawing.Color.Gray
        };
        yPos += 50;

        // Elementy pokrętła - CheckedListBox
        var lblDialElements = new Label
        {
            Text = "Elementy pokrętła:",
            Left = 10,
            Top = yPos,
            Width = 200,
            AutoSize = true,
            Font = new System.Drawing.Font(System.Drawing.SystemFonts.DefaultFont, System.Drawing.FontStyle.Bold)
        };
        yPos += 22;

        _lstDialElements = new CheckedListBox
        {
            Left = 10,
            Top = yPos,
            Width = 300,
            Height = 150,
            CheckOnClick = true
        };
        _lstDialElements.Items.AddRange(new object[] {
            "Znaki",
            "Słowa",
            "Przyciski",
            "Nagłówki",
            "Głośność",
            "Szybkość",
            "Głos",
            "Syntezator",
            "Ważne miejsca"
        });
        _lstDialElements.ItemCheck += (s, e) => { if (!_isLoading) _settingsChanged = true; };

        _navigationPanel.Controls.AddRange(new Control[] {
            _chkAdvancedNavigation,
            _chkAnnounceControlTypesNav,
            _chkAnnounceHierarchyLevel,
            lblWindowBounds, _cmbWindowBoundsMode,
            _chkPhoneticInDial, lblPhoneticInfo,
            lblDialElements, _lstDialElements
        });
    }

    private void CreateTextEditingPanel()
    {
        _textEditingPanel = new Panel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true
        };

        int yPos = 10;

        // Oznajmiaj litery fonetycznie
        _chkPhoneticLetters = new CheckBox
        {
            Text = "Oznajmiaj litery fonetycznie",
            Left = 10,
            Top = yPos,
            Width = 450,
            AutoSize = true
        };
        _chkPhoneticLetters.CheckedChanged += SettingChanged;
        var lblPhoneticInfo = new Label
        {
            Text = "(np. A - Adam, B - Barbara zamiast samych liter)",
            Left = 30,
            Top = yPos + 20,
            Width = 400,
            AutoSize = true,
            ForeColor = System.Drawing.Color.Gray
        };
        yPos += 50;

        // Echo klawiatury
        var lblKeyboardEcho = new Label
        {
            Text = "Echo klawiatury:",
            Left = 10,
            Top = yPos,
            Width = 200,
            AutoSize = true
        };
        yPos += 22;
        _cmbKeyboardEcho = new ComboBox
        {
            Left = 10,
            Top = yPos,
            Width = 200,
            DropDownStyle = ComboBoxStyle.DropDownList
        };
        _cmbKeyboardEcho.Items.AddRange(new object[] { "Brak", "Znaki", "Słowa", "Znaki i słowa" });
        _cmbKeyboardEcho.SelectedIndexChanged += SettingChanged;
        yPos += 35;

        // Oznajmiaj początek i koniec tekstu
        _chkAnnounceTextBounds = new CheckBox
        {
            Text = "Oznajmiaj początek i koniec tekstu",
            Left = 10,
            Top = yPos,
            Width = 450,
            AutoSize = true
        };
        _chkAnnounceTextBounds.CheckedChanged += SettingChanged;

        _textEditingPanel.Controls.AddRange(new Control[] {
            _chkPhoneticLetters, lblPhoneticInfo,
            lblKeyboardEcho, _cmbKeyboardEcho,
            _chkAnnounceTextBounds
        });
    }

    private void CategoryList_SelectedIndexChanged(object? sender, EventArgs e)
    {
        _contentPanel.Controls.Clear();

        switch (_categoryList.SelectedIndex)
        {
            case 0: // Głos
                if (_voicePanel != null)
                    _contentPanel.Controls.Add(_voicePanel);
                break;
            case 1: // Ogólne
                if (_generalPanel != null)
                    _contentPanel.Controls.Add(_generalPanel);
                break;
            case 2: // Szczegółowość
                if (_verbosityPanel != null)
                    _contentPanel.Controls.Add(_verbosityPanel);
                break;
            case 3: // Nawigacja
                if (_navigationPanel != null)
                    _contentPanel.Controls.Add(_navigationPanel);
                break;
            case 4: // Edycja tekstu
                if (_textEditingPanel != null)
                    _contentPanel.Controls.Add(_textEditingPanel);
                break;
        }

        // Ogłoś nazwę kategorii
        if (!_isLoading && _categoryList.SelectedItem != null)
        {
            _speechManager.Speak(_categoryList.SelectedItem.ToString() ?? "");
        }
    }

    private void SettingChanged(object? sender, EventArgs e)
    {
        if (!_isLoading)
        {
            _settingsChanged = true;
        }
    }

    private void SynthesizerComboBox_SelectedIndexChanged(object? sender, EventArgs e)
    {
        bool isOneCore = _synthesizerComboBox.SelectedIndex == 1;

        try
        {
            _speechManager.SetSynthesizer(isOneCore ? SynthesizerType.OneCore : SynthesizerType.SAPI5);

            if (!_isLoading)
            {
                _settings.Synthesizer = isOneCore ? "OneCore" : "SAPI5";
                _settingsChanged = true;
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Błąd zmiany syntezatora: {ex.Message}");
        }

        UpdateVoiceList();
    }

    private void VoiceComboBox_SelectedIndexChanged(object? sender, EventArgs e)
    {
        if (_voiceComboBox.SelectedItem == null)
            return;

        string selectedVoice = _voiceComboBox.SelectedItem.ToString()!;
        string shortName = selectedVoice.Split('(')[0].Trim();
        Console.WriteLine($"Wybrano głos: {shortName}");

        if (!_isLoading)
        {
            bool isOneCore = _synthesizerComboBox.SelectedIndex == 1;

            if (isOneCore)
            {
                if (_oneCoreVoiceMap.TryGetValue(selectedVoice, out string? voiceId))
                {
                    _speechManager.SetOneCoreVoice(voiceId);
                    _settings.Voice = voiceId;
                }
                else
                {
                    _speechManager.SetOneCoreVoice(selectedVoice);
                    _settings.Voice = selectedVoice;
                }
            }
            else
            {
                _speechManager.SelectVoice(selectedVoice);
                _settings.Voice = selectedVoice;
            }
            _settingsChanged = true;
        }
    }

    private void UpdateVoiceList()
    {
        _voiceComboBox.Items.Clear();
        _oneCoreVoiceMap.Clear();

        bool isOneCore = _synthesizerComboBox.SelectedIndex == 1;

        try
        {
            if (isOneCore)
            {
                var voices = _speechManager.GetOneCoreVoicesInfo();
                int plIndex = -1;
                int currentVoiceIndex = -1;
                int index = 0;

                string currentVoice = _speechManager.GetCurrentVoice();

                foreach (var voice in voices)
                {
                    string displayName = voice.ToString();
                    _voiceComboBox.Items.Add(displayName);
                    _oneCoreVoiceMap[displayName] = voice.Id;

                    if (plIndex < 0 && voice.Language.StartsWith("pl"))
                    {
                        plIndex = index;
                    }

                    if (!string.IsNullOrEmpty(currentVoice) &&
                        (voice.Id.Contains(currentVoice) || voice.DisplayName.Contains(currentVoice)))
                    {
                        currentVoiceIndex = index;
                    }

                    index++;
                }

                if (_voiceComboBox.Items.Count > 0)
                {
                    if (currentVoiceIndex >= 0)
                        _voiceComboBox.SelectedIndex = currentVoiceIndex;
                    else if (plIndex >= 0)
                        _voiceComboBox.SelectedIndex = plIndex;
                    else
                        _voiceComboBox.SelectedIndex = 0;
                }
            }
            else
            {
                var voices = _speechManager.GetAvailableVoices();
                int plIndex = -1;
                int index = 0;

                foreach (var voice in voices)
                {
                    _voiceComboBox.Items.Add(voice);

                    if (plIndex < 0 && voice.ToLowerInvariant().Contains("polish"))
                    {
                        plIndex = index;
                    }
                    index++;
                }

                var currentVoice = _speechManager.GetCurrentVoice();
                if (!string.IsNullOrEmpty(currentVoice))
                {
                    int voiceIndex = _voiceComboBox.Items.IndexOf(currentVoice);
                    if (voiceIndex >= 0)
                    {
                        _voiceComboBox.SelectedIndex = voiceIndex;
                    }
                    else if (plIndex >= 0)
                    {
                        _voiceComboBox.SelectedIndex = plIndex;
                    }
                    else if (_voiceComboBox.Items.Count > 0)
                    {
                        _voiceComboBox.SelectedIndex = 0;
                    }
                }
                else if (_voiceComboBox.Items.Count > 0)
                {
                    _voiceComboBox.SelectedIndex = plIndex >= 0 ? plIndex : 0;
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Błąd ładowania głosów: {ex.Message}");
        }
    }

    private void RateNumeric_ValueChanged(object? sender, EventArgs e)
    {
        if (_isLoading)
            return;

        int rate = (int)_rateNumeric.Value;
        _speechManager.SetRate(rate);
        _settings.Rate = rate;
        _settingsChanged = true;
    }

    private void VolumeNumeric_ValueChanged(object? sender, EventArgs e)
    {
        if (_isLoading)
            return;

        int volume = (int)_volumeNumeric.Value;
        _speechManager.SetVolume(volume);
        _settings.Volume = volume;
        _settingsChanged = true;
    }

    private void LoadCurrentSettings()
    {
        // ========== Głos ==========
        string savedSynth = _settings.Synthesizer;
        if (savedSynth.Equals("OneCore", StringComparison.OrdinalIgnoreCase))
        {
            _synthesizerComboBox.SelectedIndex = 1;
        }
        else
        {
            _synthesizerComboBox.SelectedIndex = 0;
        }

        _rateNumeric.Value = Math.Clamp(_settings.Rate, -10, 10);
        _volumeNumeric.Value = Math.Clamp(_settings.Volume, 0, 100);

        _speechManager.SetRate(_settings.Rate);
        _speechManager.SetVolume(_settings.Volume);

        string savedVoice = _settings.Voice;
        if (!string.IsNullOrEmpty(savedVoice))
        {
            bool isOneCore = _synthesizerComboBox.SelectedIndex == 1;
            if (isOneCore)
            {
                _speechManager.SetOneCoreVoice(savedVoice);
            }
            else
            {
                try { _speechManager.SelectVoice(savedVoice); } catch { }
            }
        }

        // ========== Ogólne ==========
        _chkMuteOutsideTCE.Checked = _settings.MuteOutsideTCE;
        _cmbStartupAnnouncement.SelectedIndex = (int)_settings.StartupAnnouncement;
        _chkTCEEntrySound.Checked = _settings.TCEEntrySound;
        _cmbModifier.SelectedIndex = (int)_settings.Modifier;
        _txtWelcomeMessage.Text = _settings.WelcomeMessage;
        _chkSpeakHints.Checked = _settings.SpeakHints;

        // ========== Szczegółowość ==========
        _chkAnnounceBasicControls.Checked = _settings.AnnounceBasicControls;
        _chkAnnounceBlockControls.Checked = _settings.AnnounceBlockControls;
        _chkAnnounceListPosition.Checked = _settings.AnnounceListPosition;

        // Informacja o menu - CheckedListBox
        _lstMenuInfo.SetItemChecked(0, _settings.MenuItemCount);  // Liczba elementów
        _lstMenuInfo.SetItemChecked(1, _settings.MenuName);        // Nazwa menu
        _lstMenuInfo.SetItemChecked(2, _settings.MenuSounds);      // Dźwięki

        // Informacja o elementach - CheckedListBox
        _lstElementInfo.SetItemChecked(0, _settings.ElementName);      // Nazwa
        _lstElementInfo.SetItemChecked(1, _settings.ElementType);      // Typ
        _lstElementInfo.SetItemChecked(2, _settings.ElementState);     // Stan
        _lstElementInfo.SetItemChecked(3, _settings.ElementParameter); // Parametr

        _cmbToggleKeysMode.SelectedIndex = (int)_settings.ToggleKeysMode;

        // ========== Nawigacja ==========
        _chkAdvancedNavigation.Checked = _settings.AdvancedNavigation;
        _chkAnnounceControlTypesNav.Checked = _settings.AnnounceControlTypesNavigation;
        _chkAnnounceHierarchyLevel.Checked = _settings.AnnounceHierarchyLevel;
        _cmbWindowBoundsMode.SelectedIndex = (int)_settings.WindowBoundsMode;
        _chkPhoneticInDial.Checked = _settings.PhoneticInDial;

        // Elementy pokrętła - CheckedListBox
        _lstDialElements.SetItemChecked(0, _settings.DialCharacters);       // Znaki
        _lstDialElements.SetItemChecked(1, _settings.DialWords);            // Słowa
        _lstDialElements.SetItemChecked(2, _settings.DialButtons);          // Przyciski
        _lstDialElements.SetItemChecked(3, _settings.DialHeadings);         // Nagłówki
        _lstDialElements.SetItemChecked(4, _settings.DialVolume);           // Głośność
        _lstDialElements.SetItemChecked(5, _settings.DialSpeed);            // Szybkość
        _lstDialElements.SetItemChecked(6, _settings.DialVoice);            // Głos
        _lstDialElements.SetItemChecked(7, _settings.DialSynthesizer);      // Syntezator
        _lstDialElements.SetItemChecked(8, _settings.DialImportantPlaces);  // Ważne miejsca

        // ========== Edycja tekstu ==========
        _chkPhoneticLetters.Checked = _settings.PhoneticLetters;
        _cmbKeyboardEcho.SelectedIndex = (int)_settings.KeyboardEcho;
        _chkAnnounceTextBounds.Checked = _settings.AnnounceTextBounds;
    }

    private void SaveAllSettings()
    {
        // ========== Ogólne ==========
        _settings.MuteOutsideTCE = _chkMuteOutsideTCE.Checked;
        _settings.StartupAnnouncement = (AnnouncementMode)_cmbStartupAnnouncement.SelectedIndex;
        _settings.TCEEntrySound = _chkTCEEntrySound.Checked;
        _settings.Modifier = (ScreenReaderModifier)_cmbModifier.SelectedIndex;
        _settings.WelcomeMessage = _txtWelcomeMessage.Text;
        _settings.SpeakHints = _chkSpeakHints.Checked;

        // ========== Szczegółowość ==========
        _settings.AnnounceBasicControls = _chkAnnounceBasicControls.Checked;
        _settings.AnnounceBlockControls = _chkAnnounceBlockControls.Checked;
        _settings.AnnounceListPosition = _chkAnnounceListPosition.Checked;

        // Informacja o menu - CheckedListBox
        _settings.MenuItemCount = _lstMenuInfo.GetItemChecked(0);
        _settings.MenuName = _lstMenuInfo.GetItemChecked(1);
        _settings.MenuSounds = _lstMenuInfo.GetItemChecked(2);

        // Informacja o elementach - CheckedListBox
        _settings.ElementName = _lstElementInfo.GetItemChecked(0);
        _settings.ElementType = _lstElementInfo.GetItemChecked(1);
        _settings.ElementState = _lstElementInfo.GetItemChecked(2);
        _settings.ElementParameter = _lstElementInfo.GetItemChecked(3);

        _settings.ToggleKeysMode = (AnnouncementMode)_cmbToggleKeysMode.SelectedIndex;

        // ========== Nawigacja ==========
        _settings.AdvancedNavigation = _chkAdvancedNavigation.Checked;
        _settings.AnnounceControlTypesNavigation = _chkAnnounceControlTypesNav.Checked;
        _settings.AnnounceHierarchyLevel = _chkAnnounceHierarchyLevel.Checked;
        _settings.WindowBoundsMode = (AnnouncementMode)_cmbWindowBoundsMode.SelectedIndex;
        _settings.PhoneticInDial = _chkPhoneticInDial.Checked;

        // Elementy pokrętła - CheckedListBox
        _settings.DialCharacters = _lstDialElements.GetItemChecked(0);
        _settings.DialWords = _lstDialElements.GetItemChecked(1);
        _settings.DialButtons = _lstDialElements.GetItemChecked(2);
        _settings.DialHeadings = _lstDialElements.GetItemChecked(3);
        _settings.DialVolume = _lstDialElements.GetItemChecked(4);
        _settings.DialSpeed = _lstDialElements.GetItemChecked(5);
        _settings.DialVoice = _lstDialElements.GetItemChecked(6);
        _settings.DialSynthesizer = _lstDialElements.GetItemChecked(7);
        _settings.DialImportantPlaces = _lstDialElements.GetItemChecked(8);

        // ========== Edycja tekstu ==========
        _settings.PhoneticLetters = _chkPhoneticLetters.Checked;
        _settings.KeyboardEcho = (KeyboardEchoSetting)_cmbKeyboardEcho.SelectedIndex;
        _settings.AnnounceTextBounds = _chkAnnounceTextBounds.Checked;

        // Zapisz do pliku
        _settings.Save();
    }

    private void BtnOK_Click(object? sender, EventArgs e)
    {
        SaveAllSettings();
        _speechManager.Speak("Ustawienia zapisane");
        DialogResult = DialogResult.OK;

        // Pytanie o restart
        if (_settingsChanged)
        {
            var result = MessageBox.Show(
                "Aby niektóre zmiany zostały zastosowane, czytnik ekranu musi zostać uruchomiony ponownie.\n\nCzy chcesz teraz zrestartować czytnik ekranu?",
                "Restart czytnika ekranu",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Question);

            if (result == DialogResult.Yes)
            {
                RestartScreenReader();
            }
        }

        Close();
    }

    private void BtnApply_Click(object? sender, EventArgs e)
    {
        SaveAllSettings();
        _speechManager.Speak("Ustawienia zapisane");
    }

    private void RestartScreenReader()
    {
        try
        {
            var exePath = Environment.ProcessPath;
            if (!string.IsNullOrEmpty(exePath))
            {
                System.Diagnostics.Process.Start(exePath);
            }
            System.Windows.Forms.Application.Exit();
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Błąd restartu: {ex.Message}");
            MessageBox.Show($"Nie udało się zrestartować czytnika ekranu: {ex.Message}", "Błąd", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
