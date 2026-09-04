using System.ComponentModel;
using System.Diagnostics;
using System.Text.Json;

namespace HermesFinance.Launcher;

public sealed class MainForm : Form
{
    private const string ReadyMarker = "Hermes Finance is ready: http://127.0.0.1:8000";
    private const string ReadyUrl = "http://127.0.0.1:8000";
    private static readonly Color WindowBackground = Color.FromArgb(9, 17, 31);
    private static readonly Color PanelBackground = Color.FromArgb(15, 27, 46);
    private static readonly Color MutedText = Color.FromArgb(148, 161, 181);
    private static readonly Color PrimaryText = Color.FromArgb(245, 248, 252);

    private readonly TableLayoutPanel _root = new()
    {
        Dock = DockStyle.Fill,
        ColumnCount = 1,
        RowCount = 6,
        Padding = new Padding(26, 22, 26, 20),
        BackColor = WindowBackground,
    };
    private readonly HeaderLayoutPanel _header = new()
    {
        Dock = DockStyle.Fill,
        // #284: grow with content like the other content-driven blocks, but
        // never beyond the root cell width (see HeaderLayoutPanel).
        AutoSize = true,
        AutoSizeMode = AutoSizeMode.GrowAndShrink,
        ColumnCount = 2,
        RowCount = 3,
        BackColor = Color.Transparent,
        Margin = new Padding(0, 0, 0, 8),
    };
    private readonly Label _brand = new()
    {
        Text = "HERMES FINANCE  /  LAUNCHER",
        // #284: AutoSize without Dock (Dock+AutoSize disagrees on preferred
        // size and the AutoSize root row undermeasures, clipping siblings).
        TextAlign = ContentAlignment.BottomLeft,
        Font = new Font("Segoe UI", 8.5F, FontStyle.Bold),
        ForeColor = Color.FromArgb(102, 227, 190),
        AutoSize = true,
    };
    private readonly Label _title = new()
    {
        Text = "Запуск локального Hermes",
        // #284: see _brand — left-aligned text renders identically.
        TextAlign = ContentAlignment.MiddleLeft,
        Font = new Font("Segoe UI", 21F, FontStyle.Bold),
        ForeColor = PrimaryText,
        AutoSize = true,
    };
    private readonly Label _subtitle = new()
    {
        // • = U+2022; single spaces so the line stays comfortably inside the
        // cell width on every Windows metric (hosted runners measure wider).
        Text = "Выберите подготовленную среду • launcher не меняет Git и не смешивает данные",
        // #284: see _brand — left-aligned text renders identically.
        TextAlign = ContentAlignment.TopLeft,
        Font = new Font("Segoe UI", 9.5F),
        ForeColor = MutedText,
        AutoSize = true,
    };
    private readonly Label _localPill = new()
    {
        Text = "LOCAL ONLY\r\n127.0.0.1:8000",
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleCenter,
        Font = new Font("Segoe UI", 8.5F, FontStyle.Bold),
        ForeColor = Color.FromArgb(164, 190, 225),
        BackColor = Color.FromArgb(22, 38, 64),
        Margin = new Padding(0, 10, 0, 10),
        Padding = new Padding(12, 0, 12, 0),
    };
    private readonly Label _profilesCaption = new()
    {
        Text = "ПОДГОТОВЛЕННЫЕ СРЕДЫ",
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.BottomLeft,
        Font = new Font("Segoe UI", 8.5F, FontStyle.Bold),
        ForeColor = MutedText,
        Margin = new Padding(0, 4, 0, 4),
    };
    private readonly FlowLayoutPanel _profiles = new()
    {
        Dock = DockStyle.Fill,
        // #284: cards wrap instead of clipping when the window is narrow;
        // the row heights itself to the tallest card (see AutoSize root row).
        AutoSize = true,
        AutoSizeMode = AutoSizeMode.GrowAndShrink,
        FlowDirection = FlowDirection.LeftToRight,
        WrapContents = true,
        AutoScroll = false,
        BackColor = Color.Transparent,
        Margin = new Padding(-6, 0, -6, 8),
        Padding = new Padding(0),
    };
    private readonly Panel _selectedPanel = new()
    {
        Dock = DockStyle.Fill,
        BackColor = PanelBackground,
        Padding = new Padding(18, 14, 18, 14),
        Margin = new Padding(0, 0, 0, 8),
        // #284: at small window sizes the flex area scrolls instead of
        // silently clipping readiness/checks content.
        AutoScroll = true,
    };
    private readonly TableLayoutPanel _selectedLayout = new()
    {
        // #284: Dock.Top (not Fill) + AutoSize: the table keeps its content
        // height so the scrollable panel above can actually scroll instead
        // of squeezing the table into a 1px flex row and clipping children.
        Dock = DockStyle.Top,
        AutoSize = true,
        AutoSizeMode = AutoSizeMode.GrowAndShrink,
        ColumnCount = 1,
        RowCount = 5,
        BackColor = Color.Transparent,
    };
    private readonly Label _selectedName = new()
    {
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleLeft,
        Font = new Font("Segoe UI", 14F, FontStyle.Bold),
        ForeColor = PrimaryText,
        AutoEllipsis = true,
    };
    private readonly Label _selectedType = new()
    {
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleRight,
        Font = new Font("Segoe UI", 8.5F, FontStyle.Bold),
        ForeColor = MutedText,
        AutoEllipsis = true,
    };
    private readonly Label _shaSummary = new()
    {
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleLeft,
        Font = new Font("Cascadia Mono", 8F),
        ForeColor = Color.FromArgb(164, 190, 225),
        AutoEllipsis = true,
        Text = "Current SHA: —   Target origin/main: —",
        Margin = new Padding(0, 0, 0, 3),
    };
    private readonly ReadinessContainerPanel _readinessPanel = new()
    {
        Dock = DockStyle.Fill,
        BackColor = Color.FromArgb(21, 35, 57),
        Padding = new Padding(12, 8, 12, 8),
        Margin = new Padding(0, 2, 0, 8),
    };
    private readonly Label _readinessDot = new()
    {
        Text = "●",
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleCenter,
        Font = new Font("Segoe UI", 17F, FontStyle.Bold),
        ForeColor = MutedText,
    };
    private readonly Label _readinessTitle = new()
    {
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.BottomLeft,
        Font = new Font("Segoe UI", 11.5F, FontStyle.Bold),
        ForeColor = PrimaryText,
        AutoEllipsis = true,
    };
    private readonly ReadinessDescriptionLabel _readinessDescription = new()
    {
        // #284: fills the table cell and wraps to the cell width instead of
        // clipping; the row is AutoSize so the height follows the wrapped
        // text. Clamp tracks the cell width (MaximumSize is the wrap hint),
        // and the label itself measures its wrapped height at the real
        // proposed width (see ReadinessDescriptionLabel).
        Dock = DockStyle.Fill,
        AutoSize = false,
        TextAlign = ContentAlignment.TopLeft,
        Font = new Font("Segoe UI", 8.5F),
        ForeColor = MutedText,
        // Spacing is provided by the readiness panel padding and title row;
        // the AutoSize row must not add the Label's default 3px margins.
        Margin = new Padding(0),
        AutoEllipsis = false,
    };
    private readonly TableLayoutPanel _checks = new()
    {
        Dock = DockStyle.Fill,
        ColumnCount = 3,
        RowCount = 4,
        BackColor = Color.Transparent,
        Margin = new Padding(0),
    };
    private readonly Label _identityCheck = new();
    private readonly Label _dataCheck = new();
    private readonly Label _dependenciesCheck = new();
    private readonly Label _serviceCheck = new();
    private readonly ActionTableLayoutPanel _actions = new()
    {
        Dock = DockStyle.Fill,
        AutoSize = true,
        AutoSizeMode = AutoSizeMode.GrowAndShrink,
        ColumnCount = 2,
        RowCount = 2,
        BackColor = Color.Transparent,
        Margin = new Padding(0),
    };
    private readonly FlowLayoutPanel _actionButtons = new()
    {
        Dock = DockStyle.Fill,
        // #284: primary buttons wrap to a second line instead of clipping
        // when labels outgrow one row (narrow window / larger fonts). The
        // row height is sized explicitly (see SizeActionRows): an AutoSize
        // table row cannot measure a wrapping flow panel (unconstrained
        // preferred width collapses to a single column).
        FlowDirection = FlowDirection.LeftToRight,
        WrapContents = true,
        BackColor = Color.Transparent,
        Margin = new Padding(-4, 0, 0, 0),
        Padding = new Padding(0),
    };
    private readonly FlowLayoutPanel _secondaryButtons = new()
    {
        Dock = DockStyle.Fill,
        // #284: secondary actions wrap instead of hiding behind a scrollbar;
        // row height is sized explicitly (see SizeActionRows).
        FlowDirection = FlowDirection.LeftToRight,
        WrapContents = true,
        AutoScroll = true,
        BackColor = Color.Transparent,
        Margin = new Padding(-4, 0, 0, 0),
        Padding = new Padding(0),
    };
    private readonly Button _prepare = new()
    {
        Text = "Подготовить",
        Width = 116,
        Height = 40,
        Enabled = false,
        AccessibleName = "Подготовить зависимости Hermes",
    };
    private readonly Button _repair = new()
    {
        Text = "Исправить",
        Width = 100,
        Height = 40,
        Enabled = false,
        AccessibleName = "Исправить зависимости Hermes",
    };
    private readonly Button _start = new()
    {
        Text = "Запустить",
        Width = 112,
        Height = 40,
        Enabled = false,
        AccessibleName = "Запустить Hermes",
    };
    private readonly Button _stop = new()
    {
        Text = "Остановить",
        Width = 112,
        Height = 40,
        Enabled = false,
        AccessibleName = "Остановить Hermes",
    };
    private readonly Button _open = new()
    {
        Text = "Открыть Hermes",
        Width = 132,
        Height = 40,
        Enabled = false,
        AccessibleName = "Открыть Hermes",
    };
    private readonly Button _refresh = new()
    {
        Text = "Обновить проверку",
        Width = 150,
        Height = 40,
        AccessibleName = "Обновить проверку",
    };
    private readonly Button _detailsToggle = new()
    {
        Text = "Диагностика и логи",
        Width = 154,
        Height = 40,
        AccessibleName = "Показать диагностику и логи",
    };
    private readonly Button _updatePreview = new()
    {
        Text = "Обновить Preview",
        Width = 138,
        Height = 40,
        Enabled = false,
        Visible = true,
        AccessibleName = "Обновить Preview",
    };
    private readonly Button _updateAndStartPreview = new()
    {
        Text = "Обновить и запустить",
        Width = 162,
        Height = 40,
        Enabled = false,
        Visible = true,
        AccessibleName = "Обновить и запустить Preview",
    };
    private readonly Button _setup = new()
    {
        Text = "Настроить…",
        Width = 132,
        Height = 40,
        Enabled = false,
        AccessibleName = "Настроить профили Hermes",
    };
    private readonly Label _lastLaunch = new()
    {
        Text = "Последний запуск: ещё не выполнялся",
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleRight,
        Font = new Font("Segoe UI", 8.5F),
        ForeColor = MutedText,
        AutoEllipsis = true,
        Margin = new Padding(12, 0, 0, 0),
    };
    private readonly Panel _detailsPanel = new()
    {
        Dock = DockStyle.Fill,
        BackColor = Color.FromArgb(11, 21, 37),
        Padding = new Padding(12, 8, 12, 10),
        Visible = false,
        Margin = new Padding(0),
    };
    private readonly Label _detailsTitle = new()
    {
        Text = "Технический слой — raw logs и diagnostics",
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleLeft,
        Font = new Font("Segoe UI", 8.5F, FontStyle.Bold),
        ForeColor = Color.FromArgb(164, 190, 225),
    };
    private readonly TextBox _status = new()
    {
        Dock = DockStyle.Fill,
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Vertical,
        BackColor = Color.FromArgb(7, 14, 25),
        ForeColor = Color.FromArgb(174, 190, 213),
        BorderStyle = BorderStyle.FixedSingle,
        Font = new Font("Cascadia Mono", 8.5F),
        Margin = new Padding(0),
    };
    private readonly Dictionary<string, ProfileCard> _profileCards = new(StringComparer.OrdinalIgnoreCase);
    private LauncherConfig? _config;
    private LauncherProfile? _selectedProfile;
    private ValidatedProfile? _validatedProfile;
    private Process? _launcherProcess;
    private long _validationGeneration;
    private bool _detailsVisible;
    private bool _ready;

    public MainForm()
        : this(null, loadConfigOnLoad: true)
    {
    }

    internal MainForm(LauncherConfig config)
        : this(config, loadConfigOnLoad: false)
    {
    }

    private MainForm(LauncherConfig? config, bool loadConfigOnLoad)
    {
        Text = "Hermes Finance — Launcher";
        // #284: below 720px the honest content height collapses the flex
        // viewport to scrolling-only; keep the minimum usable.
        MinimumSize = new Size(780, 720);
        // #284: default height fits all content without scrolling on real
        // screens (the honest AutoSize layout no longer clips actions/cards
        // into 660px); ~20px air covers cross-machine font metric variance.
        ClientSize = new Size(960, 820);
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleMode = AutoScaleMode.Font;
        BackColor = WindowBackground;
        ForeColor = PrimaryText;
        KeyPreview = true;
        TrySetApplicationIcon();
        BuildUi();

        if (config is not null)
        {
            _config = config;
            BindProfiles(runInitialPreflight: false);
        }

        if (loadConfigOnLoad)
        {
            Load += async (_, _) => await LoadConfigAsync();
        }
    }

    internal static MainForm CreateSyntheticSmoke()
    {
        var stableCheckout = @"C:\synthetic\hermes-stable";
        var previewCheckout = @"C:\synthetic\hermes-preview";
        var stableData = Path.Combine(stableCheckout, "data");
        var previewData = Path.Combine(previewCheckout, "data");
        var config = new LauncherConfig
        {
            Version = 1,
            CanonicalProduction = new CanonicalProduction
            {
                Checkout = stableCheckout,
                DataDir = stableData,
                Database = Path.Combine(stableData, "finance.db"),
            },
            Profiles =
            [
                new LauncherProfile
                {
                    Id = "stable",
                    DisplayName = "Hermes Finance — Stable",
                    Type = "stable",
                    Checkout = stableCheckout,
                    ExpectedRef = "refs/tags/v0.7.0",
                    DataDir = stableData,
                    Database = Path.Combine(stableData, "finance.db"),
                    OpenBrowser = false,
                },
                new LauncherProfile
                {
                    Id = "preview-0.7",
                    DisplayName = "0.7 Preview",
                    Type = "preview",
                    Checkout = previewCheckout,
                    ExpectedRef = "refs/heads/preview-0.7",
                    DataDir = previewData,
                    Database = Path.Combine(previewData, "finance.db"),
                    OpenBrowser = false,
                },
            ],
        };
        var form = new MainForm(config);
        form.ApplySyntheticSmokePresentation();
        return form;
    }

    private void BuildUi()
    {
        // #284: content-driven rows (AutoSize) so translated labels and larger
        // fonts grow their rows instead of clipping. Only the selected-profile
        // area flexes (Percent); the diagnostics row stays Absolute for toggle.
        _root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _root.RowStyles.Add(new RowStyle(SizeType.Absolute, 0));

        _header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        _header.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 148));
        _header.Controls.Add(_brand, 0, 0);
        _header.Controls.Add(_title, 0, 1);
        _header.Controls.Add(_subtitle, 0, 2);
        _header.Controls.Add(_localPill, 1, 0);
        _header.SetRowSpan(_localPill, 3);

        // #284: selected-profile blocks size to content; the Percent filler
        // row keeps the panel top-aligned when extra space is available.
        _selectedLayout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _selectedLayout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _selectedLayout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _selectedLayout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _selectedLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        var selectedHeader = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
        RowCount = 2,
            BackColor = Color.Transparent,
            Margin = new Padding(0),
        };
        selectedHeader.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 60));
        selectedHeader.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 40));
        selectedHeader.Controls.Add(_selectedName, 0, 0);
        selectedHeader.Controls.Add(_selectedType, 1, 0);
        _selectedLayout.Controls.Add(selectedHeader, 0, 0);
        _selectedLayout.Controls.Add(_shaSummary, 0, 1);

        BuildReadinessPanel();
        // #284: re-clamp the wrapping width whenever layout resizes the panel.
        _readinessPanel.Resize += (_, _) => ClampReadinessWrap();
        _selectedLayout.Controls.Add(_readinessPanel, 0, 2);
        BuildChecks();
        _selectedLayout.Controls.Add(_checks, 0, 3);
        _selectedPanel.Controls.Add(_selectedLayout);

        _actions.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        _actions.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 270));
        // #284: action rows are sized explicitly from wrapped content (see
        // SizeActionRows) — an AutoSize row cannot measure a wrapping flow
        // panel, it collapses to a single column and eats the flex area.
        _actions.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
        _actions.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
        _actions.Controls.Add(_actionButtons, 0, 0);
        _actions.Controls.Add(_secondaryButtons, 0, 1);
        _actions.Controls.Add(_lastLaunch, 1, 0);
        _actions.SetRowSpan(_lastLaunch, 2);
        _actions.PrimaryActions = _actionButtons;
        _actions.SecondaryActions = _secondaryButtons;
        StyleButton(_prepare, Color.FromArgb(102, 227, 190), Color.FromArgb(8, 29, 31), 0);
        StyleButton(_repair, Color.FromArgb(255, 196, 116), Color.FromArgb(57, 39, 22), 1);
        StyleButton(_start, Color.FromArgb(102, 227, 190), Color.FromArgb(8, 29, 31), 2);
        StyleButton(_stop, Color.FromArgb(255, 125, 139), Color.FromArgb(49, 22, 34), 3);
        StyleButton(_open, Color.FromArgb(190, 165, 255), Color.FromArgb(32, 23, 55), 4);
        StyleButton(_refresh, Color.FromArgb(91, 124, 167), Color.FromArgb(20, 34, 56), 5);
        StyleButton(_detailsToggle, Color.FromArgb(91, 124, 167), Color.FromArgb(20, 34, 56), 6);
        StyleButton(_updatePreview, Color.FromArgb(190, 165, 255), Color.FromArgb(32, 23, 55), 7);
        StyleButton(_updateAndStartPreview, Color.FromArgb(190, 165, 255), Color.FromArgb(32, 23, 55), 8);
        StyleButton(_setup, Color.FromArgb(102, 227, 190), Color.FromArgb(8, 29, 31), 9);
        _actionButtons.Controls.Add(_prepare);
        _actionButtons.Controls.Add(_repair);
        _actionButtons.Controls.Add(_start);
        _actionButtons.Controls.Add(_stop);
        _secondaryButtons.Controls.Add(_open);
        _secondaryButtons.Controls.Add(_refresh);
        _secondaryButtons.Controls.Add(_detailsToggle);
        _secondaryButtons.Controls.Add(_updatePreview);
        _secondaryButtons.Controls.Add(_updateAndStartPreview);
        _secondaryButtons.Controls.Add(_setup);

        var detailsLayout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2,
            BackColor = Color.Transparent,
            Margin = new Padding(0),
        };
        detailsLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 23));
        detailsLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        detailsLayout.Controls.Add(_detailsTitle, 0, 0);
        detailsLayout.Controls.Add(_status, 0, 1);
        _detailsPanel.Controls.Add(detailsLayout);

        _root.Controls.Add(_header, 0, 0);
        _root.Controls.Add(_profilesCaption, 0, 1);
        _root.Controls.Add(_profiles, 0, 2);
        _root.Controls.Add(_selectedPanel, 0, 3);
        _root.Controls.Add(_actions, 0, 4);
        _root.Controls.Add(_detailsPanel, 0, 5);
        Controls.Add(_root);

        _prepare.Click += async (_, _) => await PrepareSelectedAsync(repair: false);
        _repair.Click += async (_, _) => await PrepareSelectedAsync(repair: true);
        _start.Click += async (_, _) => await StartSelectedAsync();
        _stop.Click += (_, _) => StopLaunchedStack("Hermes остановлен владельцем.");
        _open.Click += (_, _) => OpenHermes();
        _refresh.Click += async (_, _) => await RefreshSelectedAsync();
        _updatePreview.Click += async (_, _) => await UpdatePreviewAsync(startAfter: false);
        _updateAndStartPreview.Click += async (_, _) => await UpdatePreviewAsync(startAfter: true);
        _setup.Click += async (_, _) => await OpenSetupAsync();
        _detailsToggle.Click += (_, _) => ToggleDetails();
        _profiles.Resize += (_, _) => ResizeProfileCards();
        Resize += (_, _) => ResizeProfileCards();
    }

    private void BuildReadinessPanel()
    {
        var layout = new ReadinessLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            ColumnCount = 2,
            RowCount = 2,
            BackColor = Color.Transparent,
            Margin = new Padding(0),
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 30));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 29));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.Controls.Add(_readinessDot, 0, 0);
        layout.SetRowSpan(_readinessDot, 2);
        layout.Controls.Add(_readinessTitle, 1, 0);
        layout.Controls.Add(_readinessDescription, 1, 1);
        layout.Description = _readinessDescription;
        _readinessPanel.ContentControl = layout;
        layout.Resize += (_, _) => ClampReadinessWrap();
        _readinessPanel.Controls.Add(layout);
    }

    private void BuildChecks()
    {
        _checks.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 22));
        _checks.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 55));
        _checks.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 45));
        for (var row = 0; row < 4; row++)
        {
            // #284: check rows size to their (translated) content instead of
            // splitting a fixed 92px that clips larger fonts.
            _checks.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        }
        AddCheckRow(0, "Code identity", _identityCheck);
        AddCheckRow(1, "Data boundary", _dataCheck);
        AddCheckRow(2, "Locked dependencies", _dependenciesCheck);
        AddCheckRow(3, "Loopback service", _serviceCheck);
    }

    private void AddCheckRow(int row, string title, Label status)
    {
        var icon = new Label
        {
            Text = "●",
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleCenter,
            Font = new Font("Segoe UI", 7F, FontStyle.Bold),
            ForeColor = Color.FromArgb(102, 227, 190),
            Margin = new Padding(0),
        };
        var label = new Label
        {
            Text = title,
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft,
            Font = new Font("Segoe UI", 8.5F),
            ForeColor = Color.FromArgb(193, 204, 220),
            Margin = new Padding(0),
        };
        status.Dock = DockStyle.Fill;
        status.TextAlign = ContentAlignment.MiddleRight;
        status.Font = new Font("Segoe UI", 8.5F, FontStyle.Bold);
        status.ForeColor = MutedText;
        status.AutoEllipsis = true;
        status.Margin = new Padding(0);
        _checks.Controls.Add(icon, 0, row);
        _checks.Controls.Add(label, 1, row);
        _checks.Controls.Add(status, 2, row);
    }

    private async Task LoadConfigAsync()
    {
        var configPath = LauncherSetup.DefaultConfigPath;
        try
        {
            _config = LauncherConfig.LoadOrCreate(configPath, out var createDiag);
            if (!string.IsNullOrWhiteSpace(createDiag))
            {
                AppendDiagnostic(createDiag);
            }
            ProfileValidator.ValidateConfiguration(_config);
            AppendDiagnostic($"Loaded launcher config: {configPath}");
            AppendDiagnostic("Launcher-first: Stable — pinned release, Preview — unreleased main. No manual JSON needed for normal use.");
            AppendDiagnostic("Owner UI exposes configured profiles only; no Git branch selection is available.");
            BindProfiles(runInitialPreflight: true);
        }
        catch (Exception exception) when (exception is LauncherValidationException or IOException or JsonException)
        {
            AppendDiagnostic($"Launcher config is invalid: {exception.Message}");
            AppendDiagnostic("Нажмите «Настроить…» и выберите подготовленные Stable/Preview каталоги через launcher — ручное редактирование JSON это recovery-only. Либо переустановите через install.ps1.");
            ShowConfigurationFailure();
        }
        await Task.CompletedTask;
    }

    private async Task OpenSetupAsync()
    {
        using var dialog = new SetupForm(LauncherSetup.DefaultConfigPath);
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            AppendDiagnostic("Setup saved a concrete launcher config; reloading.");
            await LoadConfigAsync();
        }
        else
        {
            AppendDiagnostic("Setup was cancelled; launcher config unchanged.");
        }
    }

    private void BindProfiles(bool runInitialPreflight)
    {
        _profiles.SuspendLayout();
        _profiles.Controls.Clear();
        _profileCards.Clear();
        foreach (var profile in _config?.Profiles ?? [])
        {
            var card = new ProfileCard(profile);
            card.Selected += (_, _) => SelectProfile(profile, runPreflight: true);
            _profileCards[profile.Id] = card;
            _profiles.Controls.Add(card);
        }
        _profiles.ResumeLayout();
        ResizeProfileCards();

        var firstProfile = _config?.Profiles.FirstOrDefault();
        if (firstProfile is not null)
        {
            SelectProfile(firstProfile, runInitialPreflight);
        }
        else
        {
            ShowConfigurationFailure();
        }
    }

    private void SelectProfile(LauncherProfile profile, bool runPreflight)
    {
        if (_launcherProcess is not null && !_launcherProcess.HasExited)
        {
            return;
        }

        _selectedProfile = profile;
        _validatedProfile = null;
        _ready = false;
        foreach (var card in _profileCards.Values)
        {
            card.SetSelected(ReferenceEquals(card.Profile, profile));
        }
        SetSelectedIdentity(profile);
        SetDependencyActions(enabled: false, preparationRequired: false);
        SetPreviewUpdateActions(profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase), enabled: false);
        SetReadiness(profile, LauncherReadinessState.NotChecked);
        if (runPreflight)
        {
            _ = RunPreflightAsync(profile);
        }
    }

    private async Task RefreshSelectedAsync()
    {
        if (_selectedProfile is null)
        {
            ShowConfigurationFailure();
            return;
        }
        await RunPreflightAsync(_selectedProfile);
    }

    private async Task<ValidatedProfile?> RunPreflightAsync(LauncherProfile profile)
    {
        var generation = Interlocked.Increment(ref _validationGeneration);
        SetReadiness(profile, LauncherReadinessState.Checking);
        AppendDiagnostic($"Preflight started for profile '{profile.Id}'.");
        try
        {
            var config = _config ?? throw new LauncherValidationException("Launcher config is not loaded.");
            var validated = await Task.Run(() => ProfileValidator.Validate(config, profile));
            if (!IsCurrentSelection(profile, generation))
            {
                return null;
            }

            _validatedProfile = validated;
            AppendDiagnostic($"Release/tag check passed: {validated.Profile.ExpectedRef} -> {validated.Head}.");
            if (validated.PreviewUpdate is not null)
            {
                AppendDiagnostic($"Preview code identity: current {validated.PreviewUpdate.CurrentSha}; target origin/main {validated.PreviewUpdate.TargetSha ?? "not available locally"}.");
            }
            AppendDiagnostic("DB/Alembic, data identity, loopback port, and runtime layout checks passed.");
            AppendDiagnostic($"Dependency check: backend {validated.Dependencies?.BackendDetail}; frontend {validated.Dependencies?.FrontendDetail}.");
            ApplyValidated(validated);
            return validated;
        }
        catch (Exception exception) when (exception is LauncherValidationException or IOException or UnauthorizedAccessException or Win32Exception or JsonException)
        {
            if (IsCurrentSelection(profile, generation))
            {
                ApplyBlocked(profile, exception);
            }
            return null;
        }
    }

    private async Task PrepareSelectedAsync(bool repair)
    {
        if (_launcherProcess is not null && !_launcherProcess.HasExited)
        {
            ShowTransientMessage("Сначала остановите Hermes: изменение зависимостей во время работы заблокировано.");
            return;
        }
        if (_config is null || _selectedProfile is null)
        {
            ShowConfigurationFailure();
            return;
        }

        var profile = _selectedProfile;
        SetDependencyActions(enabled: false, preparationRequired: false);
        _start.Enabled = false;
        _stop.Enabled = false;
        _open.Enabled = false;
        _refresh.Enabled = false;
        SetPreviewUpdateActions(visible: false, enabled: false);
        _profiles.Enabled = false;

        try
        {
            var validated = await RunPreflightAsync(profile);
            if (validated is null)
            {
                return;
            }

            SetDependencyActions(enabled: false, preparationRequired: false);
            _start.Enabled = false;
            _refresh.Enabled = false;
            _open.Enabled = false;
            if (!repair && validated.Dependencies?.Ready == true)
            {
                AppendDiagnostic("Prepare requested, but both locked dependency environments are already ready; no network action was needed.");
                ApplyValidated(validated);
                SetReadiness(profile, LauncherReadinessState.Ready, "Зависимости уже готовы. Можно нажать «Запустить».");
                return;
            }

            SetReadiness(profile, repair ? LauncherReadinessState.Repairing : LauncherReadinessState.Preparing);
            AppendDiagnostic(repair
                ? "Explicit Repair requested: restoring locked backend and frontend dependencies for this profile."
                : "Explicit Prepare requested: installing only missing or stale locked dependencies for this profile.");
            await PrepareDependenciesAsync(validated.Checkout, repair);

            var refreshed = await RunPreflightAsync(profile);
            if (refreshed?.Dependencies?.Ready != true)
            {
                throw new LauncherValidationException("Locked frontend/backend dependencies are not ready after the requested action.");
            }

            AppendDiagnostic(repair
                ? "Dependency repair completed; no runtime was started."
                : "Dependency preparation completed; no runtime was started.");
        }
        catch (Exception exception) when (exception is LauncherValidationException or IOException or UnauthorizedAccessException or Win32Exception)
        {
            ApplyBlocked(profile, exception, allowDependencyAction: true);
        }
        finally
        {
            if (_launcherProcess is null || _launcherProcess.HasExited)
            {
                _profiles.Enabled = true;
                _refresh.Enabled = true;
            }
        }
    }

    private async Task StartSelectedAsync(bool allowPreparation = false)
    {
        if (_launcherProcess is not null && !_launcherProcess.HasExited)
        {
            ShowTransientMessage("Hermes уже запускается или работает. В v1 одновременно разрешён только один профиль.");
            return;
        }
        if (_config is null || _selectedProfile is null)
        {
            ShowConfigurationFailure();
            return;
        }

        var profile = _selectedProfile;
        SetDependencyActions(enabled: false, preparationRequired: false);
        _start.Enabled = false;
        _refresh.Enabled = false;
        _open.Enabled = false;
        var validated = await RunPreflightAsync(profile);
        if (validated is null)
        {
            _refresh.Enabled = true;
            return;
        }

        try
        {
            if (validated.Dependencies?.Ready != true && allowPreparation)
            {
                SetDependencyActions(enabled: false, preparationRequired: false);
                _start.Enabled = false;
                _refresh.Enabled = false;
                _open.Enabled = false;
                SetReadiness(profile, LauncherReadinessState.Preparing, "Обновление Preview явно запрошено вместе с подготовкой locked-зависимостей…");
                AppendDiagnostic("Update-and-start explicitly authorizes locked dependency preparation for this Preview action.");
                await PrepareDependenciesAsync(validated.Checkout, repair: false);
                validated = await RunPreflightAsync(profile)
                    ?? throw new LauncherValidationException("Preview dependencies are not ready after explicit preparation.");
            }

            if (validated.Dependencies?.Ready != true)
            {
                SetReadiness(
                    profile,
                    LauncherReadinessState.NeedsPreparation,
                    "Нажмите «Подготовить», чтобы owner-triggered восстановить locked-зависимости. Запуск пока заблокирован.");
                AppendDiagnostic("Start remains read-only: dependency download/install requires an explicit Prepare or Repair action.");
                return;
            }

            SetDependencyActions(enabled: false, preparationRequired: false);
            SetReadiness(profile, LauncherReadinessState.Starting);
            AppendDiagnostic("Starting selected checkout's existing guarded startup and waiting for health probes.");
            SetLastLaunchStatus($"Последний запуск: стартует {profile.DisplayName}");
            StartProcess(validated);
        }
        catch (Exception exception) when (exception is LauncherValidationException or IOException or UnauthorizedAccessException or Win32Exception)
        {
            ApplyBlocked(profile, exception, allowRetry: true);
        }
        finally
        {
            if (_launcherProcess is null || _launcherProcess.HasExited)
            {
                _refresh.Enabled = true;
            }
        }
    }

    private async Task UpdatePreviewAsync(bool startAfter)
    {
        if (_launcherProcess is not null && !_launcherProcess.HasExited)
        {
            ShowTransientMessage("Сначала остановите Hermes: обновление Preview во время работы заблокировано.");
            return;
        }
        if (_config is null || _selectedProfile is null)
        {
            ShowConfigurationFailure();
            return;
        }
        if (!_selectedProfile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase))
        {
            ShowTransientMessage("Обновить можно только настроенный Preview; Stable никогда не изменяется этим действием.");
            return;
        }

        var profile = _selectedProfile;
        _updatePreview.Enabled = false;
        _updateAndStartPreview.Enabled = false;
        _start.Enabled = false;
        _refresh.Enabled = false;
        _open.Enabled = false;
        _profiles.Enabled = false;
        var validated = await RunPreflightAsync(profile);
        if (validated is null)
        {
            return;
        }

        SetDependencyActions(enabled: false, preparationRequired: false);
        _start.Enabled = false;
        _refresh.Enabled = false;
        _open.Enabled = false;
        SetPreviewUpdateActions(visible: false, enabled: false);
        _profiles.Enabled = false;

        try
        {
            SetReadiness(profile, LauncherReadinessState.Updating);
            AppendDiagnostic("Explicit Preview update requested: fetching only origin/main for the configured Preview checkout.");
            var result = await Task.Run(() => PreviewUpdateService.Update(validated));
            AppendDiagnostic($"Preview update reached target SHA {result.TargetSha}; current SHA {result.CurrentSha}; changed={result.Updated}.");
            var refreshed = await RunPreflightAsync(profile);
            if (refreshed is null)
            {
                throw new LauncherValidationException("Preview update completed, but the refreshed Preview preflight did not pass.");
            }
            if (startAfter)
            {
                await StartSelectedAsync(allowPreparation: true);
            }
        }
        catch (Exception exception) when (exception is LauncherValidationException or IOException or UnauthorizedAccessException or Win32Exception)
        {
            ApplyBlocked(profile, exception);
        }
        finally
        {
            if (_launcherProcess is null || _launcherProcess.HasExited)
            {
                _refresh.Enabled = true;
                _profiles.Enabled = true;
            }
        }
    }

    private void StartProcess(ValidatedProfile profile)
    {
        var process = new Process
        {
            StartInfo = ProfileValidator.BuildStartCommand(profile),
            EnableRaisingEvents = true,
        };
        _launcherProcess = process;
        process.OutputDataReceived += (_, eventArgs) => HandleProcessLine(profile, eventArgs.Data);
        process.ErrorDataReceived += (_, eventArgs) => HandleProcessLine(profile, eventArgs.Data);
        process.Exited += (_, _) => PostToUi(() =>
        {
            AppendDiagnostic($"Guarded startup exited with code {process.ExitCode}.");
            if (ReferenceEquals(_launcherProcess, process))
            {
                _launcherProcess = null;
            }
            _ready = false;
            var state = process.ExitCode == 0 ? LauncherReadinessState.Stopped : LauncherReadinessState.Blocked;
            SetReadiness(profile.Profile, state, process.ExitCode == 0
                ? LauncherUi.ReadinessDescription(LauncherReadinessState.Stopped)
                : "Hermes завершился до подтверждения готовности. Откройте «Диагностика и логи» — raw детали вторичны.");
            SetLastLaunchStatus($"Последний запуск: завершён с кодом {process.ExitCode}");
            if (_validatedProfile is not null)
            {
                ApplyPrimaryPlan(profile.Profile, state, _validatedProfile, null);
            }
            else if (_selectedProfile is not null)
            {
                ApplyPrimaryPlan(_selectedProfile, state, null, null);
            }
        });
        try
        {
            process.Start();
            _stop.Enabled = true;
            SetPreviewUpdateActions(false, enabled: false);
            _profiles.Enabled = false;
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
        }
        catch
        {
            _launcherProcess = null;
            process.Dispose();
            throw;
        }
    }

    internal static bool TryCompleteReady(
        ValidatedProfile profile,
        Action stopStack,
        Action<string> reportError)
    {
        try
        {
            ProfileValidator.WriteMissingSidecar(profile);
            return true;
        }
        catch (Exception exception)
        {
            reportError($"BLOCKING ERROR: data identity sidecar could not be written; the launched stack will be stopped. {exception.Message}");
            stopStack();
            return false;
        }
    }

    private void HandleProcessLine(ValidatedProfile profile, string? line)
    {
        if (string.IsNullOrWhiteSpace(line))
        {
            return;
        }
        PostToUi(() =>
        {
            AppendDiagnostic(line);
            if (!line.Contains(ReadyMarker, StringComparison.Ordinal))
            {
                return;
            }

            if (!TryCompleteReady(
                    profile,
                    StopLaunchedStack,
                    message => AppendDiagnostic(message)))
            {
                _ready = false;
                _profiles.Enabled = true;
                _open.Enabled = false;
                _start.Enabled = true;
                SetReadiness(
                    profile.Profile,
                    LauncherReadinessState.Blocked,
                    "Identity данных не удалось подтвердить. Исправьте права или sidecar и повторите запуск.");
                SetLastLaunchStatus("Последний запуск: заблокирован");
                return;
            }

            _ready = true;
            SetReadiness(profile.Profile, LauncherReadinessState.Running);
            ApplyPrimaryPlan(profile.Profile, LauncherReadinessState.Running, profile, null);
            SetLastLaunchStatus($"Последний запуск: готов — {profile.Profile.DisplayName}");
            AppendDiagnostic("Health checks passed (health/Alembic/deps/checkout summarized OK). Raw logs remain in «Диагностика».");
            if (profile.Profile.OpenBrowser)
            {
                OpenHermes();
            }
        });
    }

    private void OpenHermes()
    {
        if (!_ready || _launcherProcess is null || _launcherProcess.HasExited)
        {
            ShowTransientMessage("Открыть Hermes можно после успешных health probes.");
            return;
        }

        try
        {
            Process.Start(new ProcessStartInfo(ReadyUrl) { UseShellExecute = true });
            AppendDiagnostic($"Opened {ReadyUrl}.");
        }
        catch (Exception exception) when (exception is Win32Exception or InvalidOperationException)
        {
            AppendDiagnostic($"Could not open Hermes in the browser: {exception.Message}");
            ShowTransientMessage("Не удалось открыть браузер. Сервис всё ещё доступен локально после успешной проверки.");
        }
    }

    private void StopLaunchedStack() =>
        StopLaunchedStack("Launched stack stopped because its data identity could not be established.");

    private void StopLaunchedStack(string successMessage)
    {
        var process = _launcherProcess;
        if (process is null || process.HasExited)
        {
            _ready = false;
            if (_selectedProfile is not null)
            {
                var st = _validatedProfile is not null ? LauncherReadinessState.Stopped : LauncherReadinessState.Blocked;
                SetReadiness(_selectedProfile, st);
                ApplyPrimaryPlan(_selectedProfile, st, _validatedProfile, null);
            }
            return;
        }

        try
        {
            process.Kill(entireProcessTree: true);
            process.WaitForExit(5000);
            AppendDiagnostic(successMessage);
            SetLastLaunchStatus("Последний запуск: остановлен");
            _ready = false;
            if (_selectedProfile is not null)
            {
                SetReadiness(_selectedProfile, LauncherReadinessState.Stopped);
                ApplyPrimaryPlan(_selectedProfile, LauncherReadinessState.Stopped, _validatedProfile, null);
            }
        }
        catch (Exception exception) when (exception is InvalidOperationException or Win32Exception)
        {
            AppendDiagnostic($"BLOCKING ERROR: could not stop the launched stack automatically. {exception.Message}");
            if (!process.HasExited)
            {
                _stop.Enabled = true;
            }
            ShowTransientMessage("Не удалось автоматически остановить Hermes. См. «Диагностика и логи».");
        }
    }

    private void ApplyValidated(ValidatedProfile validated)
    {
        var isPreview = validated.Profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase);
        var state = validated.Dependencies?.RequiresPreparation == true
            ? LauncherReadinessState.NeedsPreparation
            : LauncherReadinessState.Ready;
        // Preview behind origin/main is planned in PlanPrimaryAction:
        // Update (or UpdateAndStart when deps are missing) is primary.
        SetReadiness(validated.Profile, state);
        SetShaSummary(validated);
        // Human plain-language checks (summarized, raw in diagnostics)
        SetCheck(_identityCheck, isPreview ? "main · UNRELEASED" : $"{LauncherUi.ReleaseBadge(validated.Profile.ExpectedRef)} — проверено", true);
        SetCheck(_dataCheck, validated.Profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase) ? "production — isolated OK" : LauncherUi.DataBoundary(validated.Profile.Type) + " — isolated OK", true);
        SetCheck(
            _dependenciesCheck,
            validated.Dependencies?.Ready == true ? "locked — готовы" : "нужна подготовка",
            validated.Dependencies?.Ready == true);
        var alembicNote = validated.Dependencies?.Ready == true ? "порт свободен · Alembic OK" : "порт свободен";
        SetCheck(_serviceCheck, alembicNote, true);
        _ready = false;
        // Single primary CTA enforcement
        ApplyPrimaryPlan(validated.Profile, state, validated, null);
    }

    private void ApplyBlocked(
        LauncherProfile profile,
        Exception exception,
        bool allowRetry = false,
        bool allowDependencyAction = false)
    {
        AppendDiagnostic($"Start blocked for profile '{profile.Id}': {exception.Message}");
        _validatedProfile = null;
        _ready = false;
        var human = LauncherUi.OwnerFacingFailure(exception.Message);
        // Extract actionable hint from failure message
        var plan = LauncherUi.PlanPrimaryAction(LauncherReadinessState.Blocked, null, profile, exception);
        var actionable = plan.Primary != LauncherPrimaryAction.Refresh && plan.Primary != LauncherPrimaryAction.None
            ? $" {plan.Reason} — нажмите primary кнопку ниже."
            : "";
        SetReadiness(
            profile,
            LauncherReadinessState.Blocked,
            human + actionable + "  Откройте «Диагностика» для raw деталей.");
        SetAllChecks("Не подтверждено", false);
        // Update specific failed check with plain language
        var msg = exception.Message.ToLowerInvariant();
        if (msg.Contains("identity") || msg.Contains("checkout") || msg.Contains("expected_ref"))
        {
            SetCheck(_identityCheck, "identity — требует действия", false);
        }
        else if (msg.Contains("sidecar") || msg.Contains("unstamped") || msg.Contains("data"))
        {
            SetCheck(_dataCheck, "data — требует внимания", false);
        }
        else if (msg.Contains("dependency") || msg.Contains("npm") || msg.Contains("uv "))
        {
            SetCheck(_dependenciesCheck, "зависимости — нужна подготовка", false);
        }
        else if (msg.Contains("port") || msg.Contains("another hermes"))
        {
            SetCheck(_serviceCheck, "127.0.0.1:8000 — занят", false);
        }
        ApplyPrimaryPlan(profile, LauncherReadinessState.Blocked, null, exception);
        _profiles.Enabled = true;
        SetLastLaunchStatus("Последний запуск: заблокирован");
    }

    private void ShowConfigurationFailure()
    {
        _selectedProfile = null;
        _validatedProfile = null;
        SetDependencyActions(enabled: false, preparationRequired: false);
        _start.Enabled = false;
        _stop.Enabled = false;
        _open.Enabled = false;
        SetPreviewUpdateActions(false, enabled: false);
        _refresh.Enabled = true;
        _setup.Enabled = true;
        _profiles.Enabled = false;
        _selectedName.Text = "Профили недоступны";
        _selectedType.Text = "CONFIGURATION";
        _selectedType.ForeColor = MutedText;
        _readinessDot.ForeColor = LauncherUi.StatusColor(LauncherReadinessState.Blocked);
        _readinessTitle.Text = "Нужна настройка";
        _readinessDescription.Text = "Конфигурация launcher отсутствует или невалидна. Нажмите «Настроить…» и выберите подготовленные Stable/Preview каталоги — ручной JSON не нужен (он recovery-only).";
        SetAllChecks("Не подтверждено", false);
        SetLastLaunchStatus("Последний запуск: заблокирован");
    }

    private void SetSelectedIdentity(LauncherProfile profile)
    {
        _selectedName.Text = profile.DisplayName;
        var isStable = profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase);
        var isPreview = profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase);
        if (isStable)
        {
            _selectedType.Text = $"{LauncherUi.TypeBadge(profile.Type)}  /  {LauncherUi.ReleaseBadge(profile.ExpectedRef)}  ·  production";
        }
        else if (isPreview)
        {
            _selectedType.Text = $"{LauncherUi.TypeBadge(profile.Type)}  /  main  ·  UNRELEASED  ·  isolated";
        }
        else
        {
            _selectedType.Text = $"{LauncherUi.TypeBadge(profile.Type)}  /  {LauncherUi.DataBoundary(profile.Type)}";
        }
        _selectedType.ForeColor = LauncherUi.AccentFor(profile.Type);
    }

    private void SetShaSummary(ValidatedProfile validated)
    {
        var card = _profileCards.TryGetValue(validated.Profile.Id, out var c) ? c : null;
        if (validated.Profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase))
        {
            var shortSha = LauncherUi.ShaShort(validated.Head);
            var release = LauncherUi.ReleaseBadge(validated.Profile.ExpectedRef);
            _shaSummary.Text = $"{release}  ·  SHA {shortSha}  ·  production data: {validated.DataDir}";
            card?.SetIdentity(validated.Head, null);
            return;
        }
        if (validated.PreviewUpdate is { } preview)
        {
            var cur = LauncherUi.ShaShort(preview.CurrentSha);
            var tgt = preview.TargetSha is null ? "not fetched locally" : LauncherUi.ShaShort(preview.TargetSha);
            var unreleased = preview.IsCurrent ? "UNRELEASED — up to date with origin/main" : "UNRELEASED — update available";
            _shaSummary.Text = $"Preview main {cur} → {tgt}  ·  {unreleased}  ·  isolated data";
            card?.SetIdentity(preview.CurrentSha, preview.TargetSha);
            return;
        }
        // Preview without update info (fallback) or experiment
        _shaSummary.Text = $"SHA {LauncherUi.ShaShort(validated.Head)}  ·  {LauncherUi.DataBoundary(validated.Profile.Type)}";
        card?.SetIdentity(validated.Head, null);
    }

    private void SetDependencyActions(bool enabled, bool preparationRequired)
    {
        _prepare.Enabled = enabled && preparationRequired;
        _repair.Enabled = enabled;
    }

    private void SetPreviewUpdateActions(bool visible, bool enabled)
    {
        _updatePreview.Visible = true;
        _updateAndStartPreview.Visible = true;
        _updatePreview.Enabled = visible && enabled;
        _updateAndStartPreview.Enabled = visible && enabled;
    }

    private void ApplyPrimaryPlan(LauncherProfile profile, LauncherReadinessState state, ValidatedProfile? validated, Exception? blockedEx)
    {
        var plan = LauncherUi.PlanPrimaryAction(state, validated, profile, blockedEx);
        // Stop is executable only for a launcher-owned running process.
        // An external port collision (Blocked, no owned process) must never
        // present a false Stop action: downgrade to honest Refresh.
        var ownsRunningProcess = _launcherProcess is not null && !_launcherProcess.HasExited;
        if (plan.Primary == LauncherPrimaryAction.Stop && !ownsRunningProcess && state != LauncherReadinessState.Running)
        {
            plan = new(LauncherPrimaryAction.Refresh, "Порт занят внешним процессом", "Порт 127.0.0.1:8000 занят другим процессом — launcher не останавливает чужие процессы. Остановите его вручную и «Обновить проверку»");
        }
        // Reset all to secondary disabled state first
        _prepare.Enabled = false;
        _repair.Enabled = false;
        _start.Enabled = false;
        _stop.Enabled = false;
        _open.Enabled = false;
        _refresh.Enabled = false;
        _updatePreview.Enabled = false;
        _updateAndStartPreview.Enabled = false;
        _setup.Enabled = false;

        // Always allow details and refresh as secondary where sensible
        _refresh.Enabled = state != LauncherReadinessState.Checking
            && state != LauncherReadinessState.Preparing
            && state != LauncherReadinessState.Repairing
            && state != LauncherReadinessState.Starting
            && state != LauncherReadinessState.Updating;
        _profiles.Enabled = state != LauncherReadinessState.Starting
            && state != LauncherReadinessState.Running
            && state != LauncherReadinessState.Updating
            && state != LauncherReadinessState.Preparing
            && state != LauncherReadinessState.Repairing;

        // Enable correct primary CTA only — exactly one obvious primary per #279, others secondary or disabled
        switch (plan.Primary)
        {
            case LauncherPrimaryAction.Prepare:
                _prepare.Enabled = true;
                _repair.Enabled = true; // repair always available as explicit recovery
                break;
            case LauncherPrimaryAction.Repair:
                _repair.Enabled = true;
                break;
            case LauncherPrimaryAction.Start:
                _start.Enabled = true;
                _repair.Enabled = true; // repair stays available as recovery even when ready
                // Allow Update as secondary only when the target is actually
                // available; behind without a target keeps Start alone.
                if (validated?.PreviewUpdate is not null && !validated.PreviewUpdate.IsCurrent && validated.PreviewUpdate.TargetAvailable)
                {
                    _updatePreview.Enabled = profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase);
                    _updateAndStartPreview.Enabled = profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase);
                }
                break;
            case LauncherPrimaryAction.Update:
                _updatePreview.Enabled = profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase);
                _updateAndStartPreview.Enabled = profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase);
                break;
            case LauncherPrimaryAction.UpdateAndStart:
                // Single unambiguous CTA for the safe chain (update, then
                // prepare locked deps, then start) — no competing buttons.
                _updateAndStartPreview.Enabled = profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase);
                break;
            case LauncherPrimaryAction.Open:
                _open.Enabled = true;
                _stop.Enabled = true;
                break;
            case LauncherPrimaryAction.Stop:
                _stop.Enabled = true;
                _open.Enabled = _ready;
                break;
            case LauncherPrimaryAction.Refresh:
                _refresh.Enabled = true;
                // For blocked identity mismatch on preview, keep Update enabled as well
                if (blockedEx is not null && blockedEx.Message.ToLowerInvariant().Contains("identity does not match")
                    && profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase))
                {
                    _updatePreview.Enabled = true;
                    _updateAndStartPreview.Enabled = true;
                }
                if (blockedEx is not null && (blockedEx.Message.ToLowerInvariant().Contains("dependency") || blockedEx.Message.ToLowerInvariant().Contains("npm")))
                {
                    _prepare.Enabled = true;
                    _repair.Enabled = true;
                }
                break;
            case LauncherPrimaryAction.None:
                break;
        }

        // Visual primary emphasis: highlight the single primary button
        HighlightPrimary(plan.Primary);
        _readinessDescription.Text = plan.HumanSummary;
    }

    private void HighlightPrimary(LauncherPrimaryAction primary)
    {
        var buttons = new[] { _prepare, _repair, _start, _stop, _open, _refresh, _updatePreview, _updateAndStartPreview };
        foreach (var b in buttons)
        {
            b.FlatAppearance.BorderSize = 1;
        }
        Button? primaryBtn = primary switch
        {
            LauncherPrimaryAction.Prepare => _prepare,
            LauncherPrimaryAction.Repair => _repair,
            LauncherPrimaryAction.Start => _start,
            LauncherPrimaryAction.Stop => _stop,
            LauncherPrimaryAction.Open => _open,
            LauncherPrimaryAction.Refresh => _refresh,
            LauncherPrimaryAction.Update => _updatePreview,
            LauncherPrimaryAction.UpdateAndStart => _updateAndStartPreview,
            _ => null,
        };
        if (primaryBtn is not null && primaryBtn.Enabled)
        {
            primaryBtn.FlatAppearance.BorderSize = 2;
        }
    }

    private void SetReadiness(LauncherProfile? profile, LauncherReadinessState state, string? description = null)
    {
        if (profile is not null && _profileCards.TryGetValue(profile.Id, out var card))
        {
            card.SetState(state);
        }
        if (!ReferenceEquals(profile, _selectedProfile) && profile is not null)
        {
            return;
        }

        if (profile is not null)
        {
            SetSelectedIdentity(profile);
        }
        _readinessDot.ForeColor = LauncherUi.StatusColor(state);
        _readinessTitle.Text = LauncherUi.ReadinessTitle(state);
        _readinessDescription.Text = description ?? LauncherUi.ReadinessDescription(state);
        _readinessPanel.BackColor = state == LauncherReadinessState.Blocked
            ? Color.FromArgb(49, 27, 43)
            : Color.FromArgb(21, 35, 57);
        _readinessDot.AccessibleName = LauncherUi.ReadinessLabel(state);
    }

    private void SetAllChecks(string text, bool passed)
    {
        SetCheck(_identityCheck, text, passed);
        SetCheck(_dataCheck, text, passed);
        SetCheck(_dependenciesCheck, text, passed);
        SetCheck(_serviceCheck, text, passed);
    }

    private static void SetCheck(Label label, string text, bool passed)
    {
        label.Text = text;
        label.ForeColor = passed
            ? Color.FromArgb(102, 227, 190)
            : Color.FromArgb(255, 125, 139);
    }

    private void ClampReadinessWrap()
    {
        // #284: keep the wrapping description clamped to the visible panel
        // width; runs on panel resize (including layout sizing) so the wrap
        // width tracks reality instead of a pre-layout default.
        var availableWidth = _readinessPanel.ClientSize.Width - _readinessPanel.Padding.Horizontal;
        if (availableWidth <= 30)
        {
            return;
        }

        var wrapWidth = availableWidth - 30;
        var clamped = new Size(wrapWidth, 0);
        if (_readinessDescription.MaximumSize != clamped)
        {
            _readinessDescription.MaximumSize = clamped;
        }
    }

    private void ResizeProfileCards()
    {
        ClampReadinessWrap();
        if (_profileCards.Count == 0 || _profiles.ClientSize.Width <= 0)
        {
            return;
        }
        var available = Math.Max(540, _profiles.ClientSize.Width - 18);
        var width = Math.Max(260, (available - ((_profileCards.Count - 1) * 12)) / _profileCards.Count);
        foreach (var card in _profileCards.Values)
        {
            card.Width = width;
        }
    }

    private void ToggleDetails()
    {
        _detailsVisible = !_detailsVisible;
        _detailsPanel.Visible = _detailsVisible;
        _root.RowStyles[5] = new RowStyle(SizeType.Absolute, _detailsVisible ? 184 : 0);
        _detailsToggle.Text = _detailsVisible ? "Скрыть диагностику" : "Диагностика и логи";
        _detailsToggle.AccessibleName = _detailsVisible ? "Скрыть диагностику и логи" : "Показать диагностику и логи";
        if (_detailsVisible)
        {
            _status.SelectionStart = _status.TextLength;
            _status.ScrollToCaret();
        }
    }

    private void ApplySyntheticSmokePresentation()
    {
        var stable = _config?.Profiles.FirstOrDefault(profile => profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase));
        var preview = _config?.Profiles.FirstOrDefault(profile => profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase));
        if (stable is null || preview is null)
        {
            return;
        }

        _selectedProfile = stable;
        SetSelectedIdentity(stable);
        SetReadiness(stable, LauncherReadinessState.Ready, "Synthetic smoke: Stable готов к запуску с canonical production data (pinned release).");
        SetCheck(_identityCheck, "Release v0.8.0 — проверено", true);
        SetCheck(_dataCheck, "production — isolated OK", true);
        SetCheck(_dependenciesCheck, "locked — готовы", true);
        SetCheck(_serviceCheck, "127.0.0.1:8000 — порт свободен · Alembic OK", true);
        _shaSummary.Text = "Release v0.8.0  ·  SHA synthetic  ·  production data: synthetic";
        if (_profileCards.TryGetValue(stable.Id, out var stableCard))
        {
            stableCard.SetIdentity("abc1234", null);
        }
        ApplyPrimaryPlan(stable, LauncherReadinessState.Ready, new ValidatedProfile(stable, stable.Checkout, stable.DataDir, stable.Database, "abc1234", "production", new DependencyStatus(true, true, "ready", "ready")), null);
        _profiles.Enabled = true;
        if (_profileCards.TryGetValue(preview.Id, out var previewCard))
        {
            previewCard.SetState(LauncherReadinessState.Blocked);
            previewCard.SetIdentity("def5678", "abc1234");
            previewCard.AccessibleDescription = "Preview: main · UNRELEASED — synthetic data identity requires confirmation";
        }
        AppendDiagnostic("Synthetic UI smoke: no runtime or owner data was loaded. Stable=ready, Preview=UNRELEASED.");
    }

    private void ShowTransientMessage(string message)
    {
        _readinessDescription.Text = message;
        AppendDiagnostic(message);
    }

    private void AppendDiagnostic(string message)
    {
        if (IsDisposed)
        {
            return;
        }
        _status.AppendText($"[{DateTime.Now:HH:mm:ss}] {message}{Environment.NewLine}");
    }

    private async Task PrepareDependenciesAsync(string checkout, bool repair)
    {
        using var process = new Process
        {
            StartInfo = DependencyValidator.BuildPreparationCommand(checkout, repair),
        };
        if (!process.Start())
        {
            throw new LauncherValidationException("Could not start the dependency preparation helper.");
        }

        var outputTask = process.StandardOutput.ReadToEndAsync();
        var errorTask = process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        var output = await outputTask;
        var error = await errorTask;
        foreach (var line in output.Split(Environment.NewLine, StringSplitOptions.RemoveEmptyEntries))
        {
            AppendDiagnostic($"deps: {line}");
        }
        foreach (var line in error.Split(Environment.NewLine, StringSplitOptions.RemoveEmptyEntries))
        {
            AppendDiagnostic($"deps error: {line}");
        }
        if (process.ExitCode != 0)
        {
            throw new LauncherValidationException(
                $"Dependency {(repair ? "repair" : "preparation")} failed with exit code {process.ExitCode}.");
        }
    }

    private void SetLastLaunchStatus(string message) =>
        _lastLaunch.Text = $"{message}  ·  {DateTime.Now:HH:mm}";

    private bool IsCurrentSelection(LauncherProfile profile, long generation) =>
        ReferenceEquals(profile, _selectedProfile) && generation == Interlocked.Read(ref _validationGeneration);

    private void PostToUi(Action action)
    {
        if (IsDisposed || !IsHandleCreated)
        {
            return;
        }
        try
        {
            BeginInvoke(action);
        }
        catch (InvalidOperationException)
        {
            // The form may be closing while the guarded process is draining output.
        }
    }

    private void StyleButton(Button button, Color border, Color background, int tabIndex)
    {
        // #284: buttons size to their (Russian) labels instead of clipping
        // them at a fixed Width; the old fixed size stays the minimum so the
        // default 100% metrics are unchanged. Single primary emphasis still
        // comes from HighlightPrimary (BorderSize), not from size.
        button.AutoSize = true;
        button.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        button.MinimumSize = new Size(button.Width, button.Height);
        button.FlatStyle = FlatStyle.Flat;
        button.FlatAppearance.BorderSize = 1;
        button.FlatAppearance.BorderColor = border;
        button.BackColor = background;
        button.ForeColor = PrimaryText;
        button.Font = new Font("Segoe UI", 8.5F, FontStyle.Bold);
        button.Margin = new Padding(4, 4, 4, 4);
        button.TabIndex = tabIndex;
        button.UseVisualStyleBackColor = false;
        button.Cursor = Cursors.Hand;
        button.EnabledChanged += (_, _) =>
        {
            button.ForeColor = button.Enabled ? PrimaryText : Color.FromArgb(126, 138, 158);
            button.BackColor = button.Enabled ? background : Color.FromArgb(20, 29, 44);
        };
        button.Paint += (_, eventArgs) =>
        {
            if (button.Enabled)
            {
                return;
            }
            TextRenderer.DrawText(
                eventArgs.Graphics,
                button.Text,
                button.Font,
                button.ClientRectangle,
                Color.FromArgb(126, 138, 158),
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPadding);
        };
        button.ForeColor = button.Enabled ? PrimaryText : Color.FromArgb(126, 138, 158);
        button.BackColor = button.Enabled ? background : Color.FromArgb(20, 29, 44);
    }

    private void TrySetApplicationIcon()
    {
        try
        {
            if (Environment.ProcessPath is { } processPath)
            {
                Icon = Icon.ExtractAssociatedIcon(processPath);
            }
        }
        catch (Exception exception) when (exception is IOException or ArgumentException)
        {
            AppendDiagnostic($"Application icon could not be loaded: {exception.Message}");
        }
    }

    // #284: the readiness description. Dock Fill + AutoSize=false means the
    // base Label reports its current bounds as its preferred size, so an
    // AutoSize table row would keep a stale height when wider font metrics
    // (hosted runners at 150%) wrap the text into an extra line. Measure the
    // wrapped text at the real proposed (cell) width instead, so the row
    // height always fits the text as actually laid out. No ellipsis, no
    // fixed pixel height — the height follows the font metrics.
    private sealed class ReadinessDescriptionLabel : Label
    {
        public override Size GetPreferredSize(Size proposedSize)
        {
            if (string.IsNullOrEmpty(Text))
            {
                return base.GetPreferredSize(proposedSize);
            }

            // The proposed width is the live cell width from the table layout.
            // A stale MaximumSize clamp must never widen the measurement past
            // it: measuring wide would report fewer lines (short height) while
            // the label is actually laid out narrow — exactly the 150% clip.
            var width = proposedSize.Width;
            if (width <= 0)
            {
                width = MaximumSize.Width;
            }
            if (width <= 0)
            {
                width = Width;
            }
            if (width <= 0)
            {
                return base.GetPreferredSize(proposedSize);
            }

            return new Size(width, GetWrappedHeight(width, proposedSize));
        }

        public int GetWrappedHeight(int width, Size? fallbackProposal = null)
        {
            if (string.IsNullOrEmpty(Text) || width <= 0)
            {
                return 0;
            }

            var need = TextRenderer.MeasureText(
                Text, Font, new Size(width, int.MaxValue), TextFormatFlags.WordBreak);
            var fallback = base.GetPreferredSize(fallbackProposal ?? new Size(width, int.MaxValue));
            return Math.Max(need.Height, fallback.Height);
        }

        public void SetWrapWidth(int width)
        {
            var clamped = new Size(Math.Max(1, width), 0);
            if (MaximumSize != clamped)
            {
                MaximumSize = clamped;
            }
        }
    }

    // #284: a plain Panel's preferred size is based on its current bounds.
    // That loses an inner AutoSize table's wrapped height while the selected
    // layout is measuring its AutoSize row. Propagate the inner table's
    // preferred height through the readiness container, using the width that
    // the selected-profile cell can actually provide.
    private sealed class ReadinessContainerPanel : Panel
    {
        public Control? ContentControl { get; set; }

        public override Size GetPreferredSize(Size proposedSize)
        {
            var width = ResolveAvailableWidth(proposedSize.Width);
            if (width <= 0 || ContentControl is null)
            {
                return base.GetPreferredSize(proposedSize);
            }

            var contentWidth = Math.Max(1, width - Padding.Horizontal);
            var contentPreferred = ContentControl.GetPreferredSize(new Size(contentWidth, 0));
            return new Size(width, Padding.Vertical + contentPreferred.Height);
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            base.OnLayout(levent);
            if (ContentControl is not null)
            {
                ContentControl.Bounds = DisplayRectangle;
            }
        }

        private int ResolveAvailableWidth(int proposedWidth)
        {
            var width = proposedWidth;
            for (var parent = Parent; width <= 0 && parent is not null; parent = parent.Parent)
            {
                if (parent.ClientSize.Width > 0)
                {
                    width = parent.ClientSize.Width;
                }
            }

            if (Parent is not null && Parent.ClientSize.Width > 0)
            {
                width = width > 0 ? Math.Min(width, Parent.ClientSize.Width) : Parent.ClientSize.Width;
            }

            return width > 0 ? width : Width;
        }
    }

    // #284: make the inner table expose the same wrapped height it will use
    // during real layout. This closes the second propagation boundary: the
    // outer readiness container can then return that height to selectedLayout.
    private sealed class ReadinessLayoutPanel : TableLayoutPanel
    {
        public ReadinessDescriptionLabel? Description { get; set; }

        public override Size GetPreferredSize(Size proposedSize)
        {
            var width = ResolveAvailableWidth(proposedSize.Width);
            if (width <= 0)
            {
                return base.GetPreferredSize(proposedSize);
            }

            var descriptionWidth = Math.Max(1, width - GetIconColumnWidth());
            Description?.SetWrapWidth(descriptionWidth);
            var preferred = base.GetPreferredSize(new Size(width, 0));
            var wrappedHeight = Description?.GetWrappedHeight(descriptionWidth) ?? 0;
            return new Size(width, Math.Max(preferred.Height, GetTitleRowHeight() + wrappedHeight));
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            var width = ClientSize.Width;
            if (width > 0)
            {
                Description?.SetWrapWidth(Math.Max(1, width - GetIconColumnWidth()));
            }

            base.OnLayout(levent);
        }

        private int GetIconColumnWidth()
        {
            if (ColumnStyles.Count > 0 && ColumnStyles[0].SizeType == SizeType.Absolute)
            {
                return Math.Max(1, (int)Math.Ceiling(ColumnStyles[0].Width));
            }

            var widths = GetColumnWidths();
            return widths.Length > 0 ? Math.Max(1, widths[0]) : 1;
        }

        private int GetTitleRowHeight()
        {
            if (RowStyles.Count > 0 && RowStyles[0].SizeType == SizeType.Absolute)
            {
                return Math.Max(1, (int)Math.Ceiling(RowStyles[0].Height));
            }

            var heights = GetRowHeights();
            return heights.Length > 0 ? Math.Max(1, heights[0]) : 1;
        }

        private int ResolveAvailableWidth(int proposedWidth)
        {
            var width = proposedWidth;
            for (var parent = Parent; width <= 0 && parent is not null; parent = parent.Parent)
            {
                if (parent.ClientSize.Width > 0)
                {
                    width = parent.ClientSize.Width;
                }
            }

            if (Parent is not null && Parent.ClientSize.Width > 0)
            {
                width = width > 0 ? Math.Min(width, Parent.ClientSize.Width) : Parent.ClientSize.Width;
            }

            return width > 0 ? width : Width;
        }
    }

    // #284: the top header. AutoSize (so the root row takes its content
    // height) but its width must never grow the root beyond the window: the
    // root row is AutoSize too, and an unbounded preferred width would push
    // the row (and header) past the content area on wider font metrics.
    // GetPreferredSize therefore reports the constrained parent width and
    // lets the AutoSize rows compute their heights at the real wrap width.
    private sealed class HeaderLayoutPanel : TableLayoutPanel
    {
        public override Size GetPreferredSize(Size proposedSize)
        {
            var width = proposedSize.Width;
            if (width <= 0 && Parent is not null)
            {
                // Docked Fill inside the padded root: usable width is the
                // parent's client width minus the parent's horizontal padding.
                var available = Parent.ClientSize.Width - Parent.Padding.Horizontal;
                width = Math.Max(0, available);
            }

            var preferred = width > 0
                ? base.GetPreferredSize(new Size(width, proposedSize.Height))
                : base.GetPreferredSize(proposedSize);

            if (Parent is not null)
            {
                var cap = Math.Max(0, Parent.ClientSize.Width - Parent.Padding.Horizontal - Margin.Horizontal);
                if (preferred.Width > cap)
                {
                    preferred.Width = cap;
                }
            }

            return preferred;
        }
    }

    // #284: the action area measures its own wrapped rows. Pushing Absolute
    // heights from outside handlers cannot work: TableLayoutPanel ignores a
    // RowStyles index assignment for layout invalidation and a bare
    // PerformLayout is a no-op while no layout is pending. The measurement
    // must be pulled at the right time — root asks during GetPreferredSize
    // and the table arranges during OnLayout, both with a live column width.
    private sealed class ActionTableLayoutPanel : TableLayoutPanel
    {
        public FlowLayoutPanel? PrimaryActions { get; set; }
        public FlowLayoutPanel? SecondaryActions { get; set; }

        public override Size GetPreferredSize(Size proposedSize)
        {
            // During root's AutoSize measurement, proposedSize may be
            // unconstrained (0) — fall back to the parent's width which is
            // already known top-down (form → root). The arranged ClientSize
            // is stale at that moment, but the parent's ClientSize is live.
            var width = proposedSize.Width;
            if (width <= 0)
            {
                width = Parent?.ClientSize.Width ?? 0;
                // Root has padding 26+26; action cell fills it. Parent width
                // already excludes that, so usable width is parent width.
                // If still 0 (very early), fall back to own ClientSize.
                if (width <= 0)
                {
                    width = ClientSize.Width;
                }
            }

            var columnWidth = width > 0 ? width - 270 : 0;
            if (columnWidth > 0 && PrimaryActions is not null && SecondaryActions is not null)
            {
                var h0 = Math.Max(48, PrimaryActions.GetPreferredSize(new Size(columnWidth, 0)).Height);
                var h1 = Math.Max(48, SecondaryActions.GetPreferredSize(new Size(columnWidth, 0)).Height);
                var basePreferred = base.GetPreferredSize(proposedSize);
                return new Size(basePreferred.Width, h0 + h1);
            }

            return base.GetPreferredSize(proposedSize);
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            var columnWidth = ClientSize.Width - 270;
            if (columnWidth > 0 && PrimaryActions is not null && SecondaryActions is not null)
            {
                SyncRow(0, PrimaryActions, columnWidth);
                SyncRow(1, SecondaryActions, columnWidth);
            }

            base.OnLayout(levent);
        }

        private void SyncRow(int row, FlowLayoutPanel panel, int width)
        {
            var needed = Math.Max(48, panel.GetPreferredSize(new Size(width, 0)).Height);
            if (RowStyles.Count > row && RowStyles[row].SizeType == SizeType.Absolute && (int)RowStyles[row].Height == needed)
            {
                return;
            }

            if (RowStyles.Count > row)
            {
                RowStyles[row] = new RowStyle(SizeType.Absolute, needed);
            }
        }
    }
}
