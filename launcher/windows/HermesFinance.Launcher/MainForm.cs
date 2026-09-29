using System.ComponentModel;
using System.Diagnostics;
using System.Net.Http;
using System.Text.Json;

namespace HermesFinance.Launcher;

public sealed class MainForm : Form
{
    private const string ReadyMarker = "Hermes Finance is ready: http://127.0.0.1:8000";
    private const string ReadyUrl = "http://127.0.0.1:8000";
    private static readonly Color WindowBackground = Color.FromArgb(9, 17, 31);
    private static readonly Color MutedText = Color.FromArgb(148, 161, 181);
    private static readonly Color PrimaryText = Color.FromArgb(245, 248, 252);

    private readonly TableLayoutPanel _root = new()
    {
        Dock = DockStyle.Fill,
        ColumnCount = 1,
        RowCount = 6,
        Padding = new Padding(16, 12, 16, 12),
        BackColor = WindowBackground,
    };
    private readonly Label _title = new()
    {
        Text = "Запуск локального Hermes",
        AutoSize = true,
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleLeft,
        Font = new Font("Segoe UI", 14F, FontStyle.Bold),
        ForeColor = PrimaryText,
        Margin = new Padding(0, 0, 0, 2),
    };
    private readonly Label _localPill = new()
    {
        Text = "Локально · 127.0.0.1:8000",
        AutoSize = true,
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleLeft,
        Font = new Font("Segoe UI", 8.5F),
        ForeColor = MutedText,
        Margin = new Padding(0, 0, 0, 6),
    };
    private readonly FlowLayoutPanel _profiles = new()
    {
        Dock = DockStyle.Top,
        AutoSize = true,
        AutoSizeMode = AutoSizeMode.GrowAndShrink,
        FlowDirection = FlowDirection.LeftToRight,
        WrapContents = true,
        BackColor = Color.Transparent,
        Margin = new Padding(0, 2, 0, 6),
        Padding = new Padding(0),
    };
    private readonly Label _shaSummary = new()
    {
        AutoSize = true,
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleLeft,
        Font = new Font("Segoe UI", 9F),
        ForeColor = Color.FromArgb(164, 190, 225),
        Text = "—",
        Margin = new Padding(0, 2, 0, 2),
    };
    private readonly Label _readinessTitle = new()
    {
        AutoSize = true,
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleLeft,
        Font = new Font("Segoe UI", 12F, FontStyle.Bold),
        ForeColor = PrimaryText,
        Text = "Не проверено",
        Margin = new Padding(0, 6, 0, 0),
    };
    private readonly Label _readinessDescription = new()
    {
        AutoSize = true,
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.TopLeft,
        Font = new Font("Segoe UI", 8.5F),
        ForeColor = MutedText,
        Visible = false,
        Margin = new Padding(0, 2, 0, 4),
    };
    private readonly FlowLayoutPanel _actionButtons = new()
    {
        Dock = DockStyle.Top,
        AutoSize = true,
        AutoSizeMode = AutoSizeMode.GrowAndShrink,
        FlowDirection = FlowDirection.LeftToRight,
        WrapContents = true,
        BackColor = Color.Transparent,
        Margin = new Padding(0, 6, 0, 0),
        Padding = new Padding(0),
    };
    private readonly FlowLayoutPanel _secondaryButtons = new()
    {
        Dock = DockStyle.Top,
        AutoSize = true,
        AutoSizeMode = AutoSizeMode.GrowAndShrink,
        FlowDirection = FlowDirection.LeftToRight,
        WrapContents = true,
        BackColor = Color.Transparent,
        Margin = new Padding(0, 2, 0, 0),
        Padding = new Padding(0),
    };
    private readonly Button _start = new()
    {
        Text = "Запустить",
        Width = 148,
        Height = 36,
        Enabled = false,
        Visible = false,
        AccessibleName = "Запустить Hermes",
    };
    private readonly Button _stop = new()
    {
        Text = "Остановить",
        Width = 104,
        Height = 28,
        Enabled = false,
        Visible = false,
        AccessibleName = "Остановить Hermes",
    };
    private readonly Button _open = new()
    {
        Text = "Открыть Hermes",
        Width = 156,
        Height = 36,
        Enabled = false,
        Visible = false,
        AccessibleName = "Открыть Hermes",
    };
    private readonly Button _refresh = new()
    {
        Text = "Обновить проверку",
        Width = 168,
        Height = 36,
        Enabled = false,
        Visible = false,
        AccessibleName = "Обновить проверку",
    };
    private readonly Button _detailsToggle = new()
    {
        Text = "Диагностика и логи",
        Width = 148,
        Height = 28,
        AccessibleName = "Показать диагностику и логи",
    };
    private readonly Button _setup = new()
    {
        Text = "Настроить…",
        Width = 112,
        Height = 28,
        Enabled = false,
        AccessibleName = "Настроить профили Hermes",
    };
    private readonly Panel _detailsPanel = new()
    {
        Dock = DockStyle.Fill,
        BackColor = Color.FromArgb(11, 21, 37),
        Padding = new Padding(8, 6, 8, 8),
        Visible = false,
        Margin = new Padding(0, 8, 0, 0),
    };
    private readonly Label _detailsTitle = new()
    {
        Text = "Диагностика",
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
    private readonly Dictionary<string, ProfileChoice> _profileChoices = new(StringComparer.OrdinalIgnoreCase);
    private LauncherConfig? _config;
    private string _configPath = LauncherSetup.DefaultConfigPath;
    private LauncherProfile? _selectedProfile;
    private ValidatedProfile? _validatedProfile;
    private Process? _launcherProcess;
    private readonly LauncherProcessOwnership _ownership;
    private readonly object _processStateGate = new();
    private readonly HashSet<Process> _ownerStopRequests = new();
    private long _validationGeneration;
    private bool _detailsVisible;
    private bool _ready;
    private bool _healthVerificationPending;
    private string? _pendingHealthFailure;

    public MainForm()
        : this(null, loadConfigOnLoad: true, ownershipDirectory: null)
    {
    }

    internal MainForm(LauncherConfig config)
        : this(config, loadConfigOnLoad: false, ownershipDirectory: null)
    {
    }

    internal MainForm(LauncherConfig config, string ownershipDirectory)
        : this(config, loadConfigOnLoad: false, ownershipDirectory)
    {
    }

    private MainForm(LauncherConfig? config, bool loadConfigOnLoad, string? ownershipDirectory)
    {
        _ownership = new LauncherProcessOwnership(ownershipDirectory);
        Text = "Hermes Finance — Launcher";
        MinimumSize = new Size(440, 280);
        ClientSize = new Size(560, 320);
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
                    ExpectedRef = "synthetic-stable-head",
                    DataDir = stableData,
                    Database = Path.Combine(stableData, "finance.db"),
                    OpenBrowser = false,
                },
                new LauncherProfile
                {
                    Id = "preview",
                    DisplayName = "Hermes Finance — Preview",
                    Type = "preview",
                    Checkout = previewCheckout,
                    ExpectedRef = "synthetic-preview-head",
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
        _root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _root.RowStyles.Add(new RowStyle(SizeType.Absolute, 0));

        var header = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            ColumnCount = 1,
            RowCount = 2,
            BackColor = Color.Transparent,
            Margin = new Padding(0),
        };
        header.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        header.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        header.Controls.Add(_title, 0, 0);
        header.Controls.Add(_localPill, 0, 1);

        var statusBlock = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            ColumnCount = 1,
            RowCount = 2,
            BackColor = Color.Transparent,
            Margin = new Padding(0, 4, 0, 0),
        };
        statusBlock.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        statusBlock.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        statusBlock.Controls.Add(_readinessTitle, 0, 0);
        statusBlock.Controls.Add(_readinessDescription, 0, 1);

        var actions = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            ColumnCount = 1,
            RowCount = 2,
            BackColor = Color.Transparent,
            Margin = new Padding(0),
        };
        actions.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        actions.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        actions.Controls.Add(_actionButtons, 0, 0);
        actions.Controls.Add(_secondaryButtons, 0, 1);

        StyleButton(_start, Color.FromArgb(102, 227, 190), Color.FromArgb(8, 29, 31), 0);
        StyleButton(_open, Color.FromArgb(190, 165, 255), Color.FromArgb(32, 23, 55), 1);
        StyleButton(_refresh, Color.FromArgb(91, 124, 167), Color.FromArgb(20, 34, 56), 2);
        StyleButton(_stop, Color.FromArgb(255, 125, 139), Color.FromArgb(49, 22, 34), 3);
        StyleButton(_detailsToggle, Color.FromArgb(91, 124, 167), Color.FromArgb(20, 34, 56), 4);
        StyleButton(_setup, Color.FromArgb(91, 124, 167), Color.FromArgb(20, 34, 56), 5);
        _actionButtons.Controls.Add(_start);
        _actionButtons.Controls.Add(_open);
        _actionButtons.Controls.Add(_refresh);
        _actionButtons.Controls.Add(_stop);
        _secondaryButtons.Controls.Add(_detailsToggle);
        _secondaryButtons.Controls.Add(_setup);

        var detailsLayout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2,
            BackColor = Color.Transparent,
            Margin = new Padding(0),
        };
        detailsLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 22));
        detailsLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        detailsLayout.Controls.Add(_detailsTitle, 0, 0);
        detailsLayout.Controls.Add(_status, 0, 1);
        _detailsPanel.Controls.Add(detailsLayout);

        _root.Controls.Add(header, 0, 0);
        _root.Controls.Add(_profiles, 0, 1);
        _root.Controls.Add(_shaSummary, 0, 2);
        _root.Controls.Add(statusBlock, 0, 3);
        _root.Controls.Add(actions, 0, 4);
        _root.Controls.Add(_detailsPanel, 0, 5);
        Controls.Add(_root);

        _start.Click += async (_, _) => await StartSelectedAsync();
        _stop.Click += (_, _) => StopLaunchedStack("Hermes остановлен владельцем.");
        _open.Click += (_, _) => OpenHermes();
        _refresh.Click += async (_, _) => await RefreshSelectedAsync();
        _setup.Click += async (_, _) => await OpenSetupAsync();
        _detailsToggle.Click += (_, _) => ToggleDetails();
        Resize += (_, _) => FitOwnerText();
        FitOwnerText();
    }

    private async Task LoadConfigAsync()
    {
        var configPath = LauncherSetup.DefaultConfigPath;
        _configPath = configPath;
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
        if (IsLauncherRuntimeActive())
        {
            AppendDiagnostic("Setup refused while a launcher-owned runtime is starting or running.");
            ShowTransientMessage("Настройка недоступна, пока Hermes запускается или работает. Сначала остановите launcher-owned runtime.");
            return;
        }

        using var dialog = new SetupForm(_configPath, IsLauncherRuntimeActive);
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            if (IsLauncherRuntimeActive())
            {
                AppendDiagnostic("Setup save was accepted, but config reload was refused because a launcher-owned runtime became active.");
                ShowTransientMessage("Конфигурация не перезагружена: Hermes запустился во время настройки. Остановите runtime и повторите настройку.");
                return;
            }
            AppendDiagnostic("Setup saved a concrete launcher config; reloading.");
            await LoadConfigAsync();
        }
        else
        {
            AppendDiagnostic("Setup was cancelled; launcher config unchanged.");
        }
    }

    private bool IsLauncherRuntimeActive()
    {
        var process = _launcherProcess;
        if (process is null)
        {
            return false;
        }

        try
        {
            return !process.HasExited;
        }
        catch (InvalidOperationException)
        {
            // AttachProcess assigns the process before Process.Start. Treat
            // an unobservable startup/disposal state as active so setup cannot
            // race it.
            return true;
        }
    }

    private void BindProfiles(bool runInitialPreflight)
    {
        _profiles.SuspendLayout();
        _profiles.Controls.Clear();
        _profileChoices.Clear();
        foreach (var profile in _config?.Profiles ?? [])
        {
            var choice = new ProfileChoice(profile);
            choice.Selected += (_, _) => SelectProfile(profile, runPreflight: true);
            _profileChoices[profile.Id] = choice;
            _profiles.Controls.Add(choice);
        }
        _profiles.ResumeLayout();

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
        foreach (var choice in _profileChoices.Values)
        {
            choice.SetSelected(ReferenceEquals(choice.Profile, profile));
        }
        SetSelectedIdentity(profile);
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
            var validated = await Task.Run(() => ProfileValidator.Validate(config, profile, checkPort: false));
            if (!IsCurrentSelection(profile, generation))
            {
                return null;
            }

            var recovered = _ownership.TryRecover(validated);
            if (recovered is null)
            {
                ProfileValidator.AssertPortAvailable();
            }

            _validatedProfile = validated;
            AppendDiagnostic($"Release/tag check passed: {validated.Profile.ExpectedRef} -> {validated.Head}.");
            AppendDiagnostic("DB/Alembic, data identity, loopback port, and runtime layout checks passed.");
            AppendDiagnostic($"Dependency check: backend {validated.Dependencies?.BackendDetail}; frontend {validated.Dependencies?.FrontendDetail}.");
            ApplyValidated(validated);
            if (recovered is not null)
            {
                AttachRecoveredProcess(validated, recovered);
                ApplyPrimaryPlan(profile, LauncherReadinessState.Running, validated, null);
            }
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

    private async Task StartSelectedAsync()
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
        _start.Enabled = false;
        _refresh.Enabled = false;
        _open.Enabled = false;
        var validated = await RunPreflightAsync(profile);
        if (validated is null)
        {
            _refresh.Enabled = true;
            return;
        }
        if (_ready
            && _launcherProcess is not null
            && _ownership.ProvesOwnership(validated, _launcherProcess))
        {
            return;
        }

        try
        {
            if (validated.Dependencies?.Ready != true)
            {
                SetReadiness(
                    profile,
                    LauncherReadinessState.NeedsPreparation,
                    "Зависимости не готовы. Запуск заблокирован: выполните OPS01 Prepare во внешнем подготовленном runtime, затем обновите проверку.");
                AppendDiagnostic("Start remains read-only: dependency preparation belongs to the external OPS01 Prepare workflow.");
                return;
            }

            SetReadiness(profile, LauncherReadinessState.Starting);
            AppendDiagnostic("Starting selected checkout's existing guarded startup and waiting for health probes.");
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

    private void StartProcess(ValidatedProfile profile)
    {
        _validatedProfile = profile;
        var process = new Process
        {
            StartInfo = ProfileValidator.BuildStartCommand(profile),
            EnableRaisingEvents = true,
        };
        long? processStartTimeUtcTicks = null;
        AttachProcess(profile, process, () => processStartTimeUtcTicks);
        try
        {
            process.Start();
            processStartTimeUtcTicks = process.StartTime.ToUniversalTime().Ticks;
            _ownership.Write(profile, process);
            _profiles.Enabled = false;
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
        }
        catch
        {
            try
            {
                if (!process.HasExited)
                {
                    process.Kill(entireProcessTree: true);
                    process.WaitForExit(5000);
                }
            }
            catch (InvalidOperationException)
            {
                // The process may have exited while its durable marker was being written.
            }
            catch (Win32Exception)
            {
                // Preserve the original startup failure and fail closed.
            }
            _ownership.RemoveIfOwned(profile, process);
            _launcherProcess = null;
            process.Dispose();
            throw;
        }
    }

    private void AttachProcess(ValidatedProfile profile, Process process, Func<long?>? knownStartTimeUtcTicks = null)
    {
        _launcherProcess = process;
        process.OutputDataReceived += (_, eventArgs) => HandleProcessLine(profile, eventArgs.Data);
        process.ErrorDataReceived += (_, eventArgs) => HandleProcessLine(profile, eventArgs.Data);
        process.Exited += (_, _) =>
        {
            var ownerStopRequested = ConsumeOwnerStopRequest(process);
            _ownership.RemoveIfOwned(profile, process, knownStartTimeUtcTicks?.Invoke());
            PostToUi(() =>
            {
            if (ReferenceEquals(_launcherProcess, process))
            {
                _launcherProcess = null;
            }
            _ready = false;
            var exitCode = process.ExitCode;
            if (ownerStopRequested)
            {
                AppendDiagnostic($"Launcher-owned Stop completed; process exited with code {exitCode} as expected.");
                SetReadiness(profile.Profile, LauncherReadinessState.Stopped);
                                if (_validatedProfile is not null)
                {
                    ApplyPrimaryPlan(profile.Profile, LauncherReadinessState.Stopped, _validatedProfile, null);
                }
                else if (_selectedProfile is not null)
                {
                    ApplyPrimaryPlan(_selectedProfile, LauncherReadinessState.Stopped, null, null);
                }
                process.Dispose();
                if (ReferenceEquals(_selectedProfile, profile.Profile))
                {
                    _ = RefreshAfterExpectedOwnerStopAsync(profile.Profile);
                }
                return;
            }

            AppendDiagnostic($"Guarded startup exited with code {exitCode}.");
            var state = exitCode == 0 ? LauncherReadinessState.Stopped : LauncherReadinessState.Blocked;
            SetReadiness(profile.Profile, state, exitCode == 0
                ? LauncherUi.ReadinessDescription(LauncherReadinessState.Stopped)
                : "Hermes завершился до подтверждения готовности. Откройте «Диагностика и логи» — raw детали вторичны.");
                        if (_validatedProfile is not null)
            {
                ApplyPrimaryPlan(profile.Profile, state, _validatedProfile, null);
            }
            else if (_selectedProfile is not null)
            {
                ApplyPrimaryPlan(_selectedProfile, state, null, null);
            }
            process.Dispose();
            });
        };
    }

    private void AttachRecoveredProcess(ValidatedProfile profile, RecoveredLauncherProcess recovered)
    {
        AttachProcess(profile, recovered.Process, () => recovered.Marker.ProcessStartTimeUtcTicks);
        _ready = true;
        SetReadiness(profile.Profile, LauncherReadinessState.Running);
                AppendDiagnostic("Recovered a launcher-owned Hermes process after launcher restart.");
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
            if (_ready || _healthVerificationPending)
            {
                return;
            }

            if (!TryCompleteReady(
                    profile,
                    StopLaunchedStack,
                    message => AppendDiagnostic(message)))
            {
                _ready = false;
                _healthVerificationPending = false;
                _profiles.Enabled = true;
                _open.Enabled = false;
                _open.Visible = false;
                _stop.Enabled = false;
                _stop.Visible = false;
                _refresh.Visible = false;
                _start.Enabled = true;
                _start.Visible = true;
                SetReadiness(
                    profile.Profile,
                    LauncherReadinessState.Blocked,
                    "Identity данных не удалось подтвердить. Исправьте права или sidecar и повторите запуск.");
                                return;
            }

            if (_launcherProcess is null || !_ownership.MarkReady(profile, _launcherProcess))
            {
                AppendDiagnostic("BLOCKING ERROR: durable launcher ownership could not be marked ready; the launched stack will be stopped.");
                StopLaunchedStack();
                return;
            }

            if (profile.ApplicationVersion is null)
            {
                // Synthetic/legacy fixtures may not carry the package version
                // module. The guarded startup marker remains the only proof
                // available for those fixtures; real Hermes runtimes include
                // the module and take the strict /api/health version path.
                CompleteReady(profile, version: null);
                return;
            }

            _healthVerificationPending = true;
            _ = VerifyRunningHealthAsync(profile);
        });
    }

    private async Task VerifyRunningHealthAsync(ValidatedProfile profile)
    {
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
            using var response = await client.GetAsync(ReadyUrl + "/api/health");
            response.EnsureSuccessStatusCode();
            await using var content = await response.Content.ReadAsStreamAsync();
            using var document = await JsonDocument.ParseAsync(content);
            var root = document.RootElement;
            var status = root.TryGetProperty("status", out var statusProperty)
                && statusProperty.ValueKind == JsonValueKind.String
                ? statusProperty.GetString()
                : null;
            var version = root.TryGetProperty("version", out var versionProperty)
                && versionProperty.ValueKind == JsonValueKind.String
                ? versionProperty.GetString()
                : null;
            if (!string.Equals(status, "ok", StringComparison.Ordinal)
                || !string.Equals(version, profile.ApplicationVersion, StringComparison.Ordinal))
            {
                throw new LauncherValidationException(
                    $"Running backend health version '{version ?? "missing"}' does not match launcher identity '{profile.ApplicationVersion}'.");
            }

            PostToUi(() =>
            {
                if (_launcherProcess is null || _launcherProcess.HasExited || !ReferenceEquals(_selectedProfile, profile.Profile))
                {
                    return;
                }
                CompleteReady(profile, version);
            });
        }
        catch (Exception exception) when (exception is HttpRequestException or TaskCanceledException or JsonException or LauncherValidationException)
        {
            PostToUi(() =>
            {
                if (_launcherProcess is null || _launcherProcess.HasExited || !ReferenceEquals(_selectedProfile, profile.Profile))
                {
                    return;
                }
                _healthVerificationPending = false;
                _pendingHealthFailure = "Версия backend не совпала с launcher identity. Запуск остановлен; откройте диагностику и повторите проверку.";
                AppendDiagnostic($"BLOCKING ERROR: running backend health identity failed: {exception.Message}");
                StopLaunchedStack("Launched stack stopped because backend health identity could not be established.");
                _ready = false;
                _open.Enabled = false;
                SetReadiness(profile.Profile, LauncherReadinessState.Blocked, _pendingHealthFailure);
                            });
        }
    }

    private void CompleteReady(ValidatedProfile profile, string? version)
    {
        _healthVerificationPending = false;
        _ready = true;
        SetReadiness(profile.Profile, LauncherReadinessState.Running);
        ApplyPrimaryPlan(profile.Profile, LauncherReadinessState.Running, profile, null);
                AppendDiagnostic(version is null
            ? "Health marker and data identity passed; backend package version was unavailable in this legacy/synthetic runtime. Raw logs remain in «Диагностика»."
            : $"Health checks passed with backend version {version}; it matches launcher release identity. Raw logs remain in «Диагностика».");
        if (profile.Profile.OpenBrowser)
        {
            OpenHermes();
        }
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
        StopLaunchedStack("Launched stack stopped because its data identity could not be established.", ownerRequested: false);

    private void StopLaunchedStack(string successMessage)
        => StopLaunchedStack(successMessage, ownerRequested: true);

    private void StopLaunchedStack(string successMessage, bool ownerRequested)
    {
        var process = _launcherProcess;
        if (process is null || process.HasExited)
        {
            if (process is not null && _selectedProfile is not null && _validatedProfile is not null)
            {
                _ownership.RemoveIfOwned(_validatedProfile, process);
            }
            _ready = false;
            _healthVerificationPending = false;
            if (_selectedProfile is not null)
            {
                var st = _validatedProfile is not null ? LauncherReadinessState.Stopped : LauncherReadinessState.Blocked;
                SetReadiness(_selectedProfile, st);
                ApplyPrimaryPlan(_selectedProfile, st, _validatedProfile, null);
            }
            return;
        }

        if (_selectedProfile is null
            || _validatedProfile is null
            || !ReferenceEquals(_validatedProfile.Profile, _selectedProfile)
            || !_ownership.ProvesOwnership(_validatedProfile, process))
        {
            AppendDiagnostic("BLOCKING ERROR: Stop refused because launcher ownership of the selected profile process could not be proven.");
            _stop.Enabled = false;
            ShowTransientMessage("Остановить можно только доказанный launcher-owned Hermes выбранного профиля.");
            return;
        }

        try
        {
            if (ownerRequested)
            {
                MarkOwnerStopRequested(process);
            }
            var processStartTimeUtcTicks = process.StartTime.ToUniversalTime().Ticks;
            process.Kill(entireProcessTree: true);
            process.WaitForExit(5000);
            _ownership.RemoveIfOwned(_validatedProfile, process, processStartTimeUtcTicks);
            AppendDiagnostic(successMessage);
                        _ready = false;
            _healthVerificationPending = false;
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

    private async Task RefreshAfterExpectedOwnerStopAsync(LauncherProfile profile)
    {
        const int portReleaseTimeoutMilliseconds = 5_000;
        const int portReleasePollMilliseconds = 100;
        var deadline = DateTime.UtcNow.AddMilliseconds(portReleaseTimeoutMilliseconds);
        while (!IsDisposed && DateTime.UtcNow < deadline)
        {
            try
            {
                ProfileValidator.AssertPortAvailable();
                break;
            }
            catch (LauncherValidationException)
            {
                await Task.Delay(portReleasePollMilliseconds);
            }
        }

        if (IsDisposed || !ReferenceEquals(profile, _selectedProfile))
        {
            return;
        }

        AppendDiagnostic("Launcher-owned Stop completed; rerunning read-only preflight after port cleanup.");
        await RunPreflightAsync(profile);
    }

    private void MarkOwnerStopRequested(Process process)
    {
        lock (_processStateGate)
        {
            _ownerStopRequests.Add(process);
        }
    }

    private bool ConsumeOwnerStopRequest(Process process)
    {
        lock (_processStateGate)
        {
            return _ownerStopRequests.Remove(process);
        }
    }

    private void ApplyValidated(ValidatedProfile validated)
    {
        var state = validated.Dependencies?.RequiresPreparation == true
            ? LauncherReadinessState.NeedsPreparation
            : LauncherReadinessState.Ready;
        SetReadiness(validated.Profile, state);
        SetShaSummary(validated);
        _ready = false;
        ApplyPrimaryPlan(validated.Profile, state, validated, null);
    }

    private void ApplyBlocked(
        LauncherProfile profile,
        Exception exception,
        bool allowRetry = false)
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
        SetReadiness(profile, LauncherReadinessState.Blocked, human + actionable);
        ApplyPrimaryPlan(profile, LauncherReadinessState.Blocked, null, exception);
        _profiles.Enabled = true;
    }

    private void ShowConfigurationFailure()
    {
        _selectedProfile = null;
        _validatedProfile = null;
        _ready = false;
        _profiles.Enabled = false;
        _shaSummary.Text = "Конфигурация не задана";
        _readinessTitle.Text = "Нужна настройка";
        _readinessTitle.ForeColor = LauncherUi.StatusColor(LauncherReadinessState.Blocked);
        _readinessDescription.Text = "Нажмите «Настроить…» и выберите подготовленные каталоги Stable и Preview.";
        _readinessDescription.Visible = true;
        Place(_setup, _actionButtons);
        Place(_refresh, _secondaryButtons);
        _start.Enabled = false;
        _start.Visible = false;
        _stop.Enabled = false;
        _stop.Visible = false;
        _open.Enabled = false;
        _open.Visible = false;
        _refresh.Enabled = true;
        _refresh.Visible = true;
        _setup.Enabled = true;
        _setup.Visible = true;
        HighlightPrimary(LauncherPrimaryAction.None);
        _setup.FlatAppearance.BorderSize = 2;
        FitOwnerText();
    }

    private void SetSelectedIdentity(LauncherProfile profile)
    {
        var isStable = profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase);
        var isPreview = profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase);
        if (isStable)
        {
            _shaSummary.Text = $"{LauncherUi.ReleaseBadge(profile.ExpectedRef)}  ·  {LauncherUi.DataBoundary(profile.Type)}";
        }
        else if (isPreview)
        {
            _shaSummary.Text = $"main · UNRELEASED · {LauncherUi.DataBoundary(profile.Type)}";
        }
        else
        {
            _shaSummary.Text = LauncherUi.DataBoundary(profile.Type);
        }

        _shaSummary.ForeColor = LauncherUi.AccentFor(profile.Type);
        FitOwnerText();
    }

    private void SetShaSummary(ValidatedProfile validated)
    {
        if (validated.Profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase))
        {
            _shaSummary.Text = LauncherUi.StableIdentityLabel(validated.Profile, validated.Head, validated.ApplicationVersion);
        }
        else if (validated.Profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase))
        {
            _shaSummary.Text = LauncherUi.PreviewIdentityLabel(validated.Profile, validated.Head);
        }
        else
        {
            _shaSummary.Text = $"SHA {LauncherUi.ShaShort(validated.Head)}  ·  {LauncherUi.DataBoundary(validated.Profile.Type)}";
        }

        _shaSummary.ForeColor = LauncherUi.AccentFor(validated.Profile.Type);
        FitOwnerText();
    }

    private void ApplyPrimaryPlan(LauncherProfile profile, LauncherReadinessState state, ValidatedProfile? validated, Exception? blockedEx)
    {
        var plan = LauncherUi.PlanPrimaryAction(state, validated, profile, blockedEx);
        // Stop is executable only for a launcher-owned running process.
        // An external port collision (Blocked, no owned process) must never
        // present a false Stop action: downgrade to honest Refresh.
        var ownsRunningProcess = _launcherProcess is not null
            && _validatedProfile is not null
            && _selectedProfile is not null
            && ReferenceEquals(_validatedProfile.Profile, _selectedProfile)
            && _ownership.ProvesOwnership(_validatedProfile, _launcherProcess);
        if (plan.Primary == LauncherPrimaryAction.Stop && !ownsRunningProcess && state != LauncherReadinessState.Running)
        {
            plan = new(LauncherPrimaryAction.Refresh, "Порт занят внешним процессом", "Порт 127.0.0.1:8000 занят другим процессом — launcher не останавливает чужие процессы. Остановите его вручную и «Обновить проверку»");
        }
        _start.Enabled = false;
        _stop.Enabled = false;
        _open.Enabled = false;
        _refresh.Enabled = false;
        _setup.Enabled = state != LauncherReadinessState.Starting
            && state != LauncherReadinessState.Running;
        _profiles.Enabled = state != LauncherReadinessState.Starting
            && state != LauncherReadinessState.Running;
        Place(_setup, _secondaryButtons);
        Place(_start, _actionButtons);
        Place(_open, _actionButtons);
        Place(_refresh, _actionButtons);
        Place(_stop, _actionButtons);

        switch (plan.Primary)
        {
            case LauncherPrimaryAction.Start:
                _start.Enabled = true;
                break;
            case LauncherPrimaryAction.Open:
                _open.Enabled = _ready && ownsRunningProcess;
                _stop.Enabled = ownsRunningProcess;
                break;
            case LauncherPrimaryAction.Stop:
                if (ownsRunningProcess)
                {
                    _stop.Enabled = true;
                    _open.Enabled = _ready;
                }
                else
                {
                    _refresh.Enabled = true;
                    plan = new(LauncherPrimaryAction.Refresh, plan.Reason, plan.HumanSummary);
                }
                break;
            case LauncherPrimaryAction.Refresh:
                _refresh.Enabled = true;
                break;
            case LauncherPrimaryAction.None:
                break;
        }

        _start.Visible = _start.Enabled;
        _open.Visible = _open.Enabled;
        _refresh.Visible = _refresh.Enabled;
        _stop.Visible = _stop.Enabled;
        _setup.Visible = true;
        HighlightPrimary(plan.Primary);
        var showDetail = state is LauncherReadinessState.Blocked or LauncherReadinessState.NeedsPreparation;
        ShowOwnerDetail(showDetail ? plan.HumanSummary : string.Empty, showDetail);
    }

    private void HighlightPrimary(LauncherPrimaryAction primary)
    {
        var buttons = new[] { _start, _stop, _open, _refresh, _setup };
        foreach (var b in buttons)
        {
            b.FlatAppearance.BorderSize = 1;
        }
        Button? primaryBtn = primary switch
        {
            LauncherPrimaryAction.Start => _start,
            LauncherPrimaryAction.Stop => _stop,
            LauncherPrimaryAction.Open => _open,
            LauncherPrimaryAction.Refresh => _refresh,
            _ => null,
        };
        if (primaryBtn is not null && primaryBtn.Enabled)
        {
            primaryBtn.FlatAppearance.BorderSize = 2;
        }
    }

    private void SetReadiness(LauncherProfile? profile, LauncherReadinessState state, string? description = null)
    {
        if (!ReferenceEquals(profile, _selectedProfile) && profile is not null)
        {
            return;
        }

        if (profile is not null)
        {
            SetSelectedIdentity(profile);
        }

        _readinessTitle.Text = LauncherUi.ReadinessTitle(state);
        _readinessTitle.ForeColor = LauncherUi.StatusColor(state);
        _readinessTitle.AccessibleName = LauncherUi.ReadinessLabel(state);
        var detail = description ?? LauncherUi.ReadinessDescription(state);
        var showDetail = description is not null
            || state is LauncherReadinessState.Blocked or LauncherReadinessState.NeedsPreparation;
        ShowOwnerDetail(showDetail ? detail : string.Empty, showDetail);
        if (state == LauncherReadinessState.Starting)
        {
            _start.Enabled = false;
            _start.Visible = false;
            _open.Enabled = false;
            _open.Visible = false;
            _stop.Enabled = false;
            _stop.Visible = false;
            _refresh.Enabled = false;
            _refresh.Visible = false;
            _setup.Enabled = false;
        }
        else if (state == LauncherReadinessState.Running)
        {
            _setup.Enabled = false;
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
        foreach (var choice in _profileChoices.Values)
        {
            choice.SetSelected(ReferenceEquals(choice.Profile, stable));
        }
        SetReadiness(stable, LauncherReadinessState.Ready);
        _shaSummary.Text = LauncherUi.StableIdentityLabel(stable, "abc1234");
        _shaSummary.ForeColor = LauncherUi.AccentFor(stable.Type);
        ApplyPrimaryPlan(stable, LauncherReadinessState.Ready, new ValidatedProfile(stable, stable.Checkout, stable.DataDir, stable.Database, "abc1234", "production", new DependencyStatus(true, true, "ready", "ready")), null);
        _profiles.Enabled = true;
        AppendDiagnostic("Synthetic UI smoke: no runtime or owner data was loaded.");
    }

    private void ShowTransientMessage(string message)
    {
        ShowOwnerDetail(message, true);
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

    private void ShowOwnerDetail(string? text, bool show)
    {
        _readinessDescription.Text = text ?? string.Empty;
        _readinessDescription.Visible = show && !string.IsNullOrWhiteSpace(_readinessDescription.Text);
        FitOwnerText();
    }

    private static void Place(Control control, Control parent)
    {
        if (ReferenceEquals(control.Parent, parent))
        {
            return;
        }

        control.Parent?.Controls.Remove(control);
        parent.Controls.Add(control);
    }

    private void FitOwnerText()
    {
        var width = Math.Max(200, ClientSize.Width - _root.Padding.Horizontal - 8);
        var clamp = new Size(width, 0);
        _title.MaximumSize = clamp;
        _localPill.MaximumSize = clamp;
        _shaSummary.MaximumSize = clamp;
        _readinessTitle.MaximumSize = clamp;
        _readinessDescription.MaximumSize = clamp;
    }

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
}
