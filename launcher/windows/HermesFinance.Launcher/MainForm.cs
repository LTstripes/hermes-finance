using System.ComponentModel;
using System.Diagnostics;
using System.Text.Json;

namespace HermesFinance.Launcher;

public sealed class MainForm : Form
{
    private const string ReadyMarker = "Hermes Finance is ready: http://127.0.0.1:8000";
    private readonly ListBox _profiles = new() { Dock = DockStyle.Top, Height = 130 };
    private readonly Button _start = new() { Text = "Запустить", Dock = DockStyle.Top, Height = 36 };
    private readonly Button _stop = new() { Text = "Остановить", Dock = DockStyle.Top, Height = 36, Enabled = false };
    private readonly TextBox _status = new()
    {
        Dock = DockStyle.Fill,
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Vertical,
        Font = new Font(FontFamily.GenericMonospace, 9),
    };
    private readonly Label _lastLaunch = new()
    {
        Text = "Последний запуск: ещё не выполнялся",
        Dock = DockStyle.Top,
        Height = 30,
        TextAlign = ContentAlignment.MiddleLeft,
        Padding = new Padding(8, 0, 8, 0),
    };
    private LauncherConfig? _config;
    private Process? _launcherProcess;

    public MainForm()
    {
        Text = "Hermes Finance";
        MinimumSize = new Size(620, 460);
        StartPosition = FormStartPosition.CenterScreen;
        TrySetApplicationIcon();
        Controls.Add(_status);
        Controls.Add(_lastLaunch);
        Controls.Add(_stop);
        Controls.Add(_start);
        Controls.Add(_profiles);
        _start.Click += async (_, _) => await StartSelectedAsync();
        _stop.Click += (_, _) => StopLaunchedStack("Hermes Finance stopped by owner.");
        Load += (_, _) => LoadConfig();
    }

    private void LoadConfig()
    {
        var configPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "HermesFinance", "launcher", "config.json");
        try
        {
            _config = LauncherConfig.Load(configPath);
            ProfileValidator.ValidateConfiguration(_config);
            _profiles.DataSource = _config.Profiles;
            _profiles.DisplayMember = nameof(LauncherProfile.DisplayName);
            AppendStatus($"Loaded {configPath}");
            AppendStatus("Select a configured profile, then click Запустить. No Git branch selection is available.");
            AppendStatus("Start checks release/tag, DB/Alembic, and locked frontend/backend dependencies before boot.");
        }
        catch (Exception exception) when (exception is LauncherValidationException or IOException or JsonException)
        {
            AppendStatus($"Launcher config is invalid: {exception.Message}");
            _start.Enabled = false;
        }
    }

    private async Task StartSelectedAsync()
    {
        if (_launcherProcess is not null && !_launcherProcess.HasExited)
        {
            AppendStatus("A Hermes startup process is already active. v1 permits one profile at a time.");
            return;
        }
        if (_config is null || _profiles.SelectedItem is not LauncherProfile profile)
        {
            AppendStatus("Choose a configured profile first.");
            return;
        }

        _start.Enabled = false;
        try
        {
            AppendStatus($"Validating {profile.DisplayName}…");
            var validated = await Task.Run(() => ProfileValidator.Validate(_config, profile));
            AppendStatus($"Release/tag check: passed ({validated.Profile.ExpectedRef} → {validated.Head[..Math.Min(12, validated.Head.Length)]}).");
            AppendStatus("DB/Alembic check: passed (selected database is compatible with this checkout).");
            AppendStatus($"Dependency check: backend {validated.Dependencies?.BackendDetail ?? "not checked"}; frontend {validated.Dependencies?.FrontendDetail ?? "not checked"}.");
            if (validated.Dependencies?.RequiresPreparation == true)
            {
                AppendStatus("Preparing only the missing or stale locked dependencies; repeat launches skip this step when they are ready…");
                await PrepareDependenciesAsync(validated.Checkout);
                validated = await Task.Run(() => ProfileValidator.Validate(_config, profile));
                AppendStatus($"Dependency check after preparation: backend {validated.Dependencies?.BackendDetail}; frontend {validated.Dependencies?.FrontendDetail}.");
            }

            if (validated.Dependencies?.Ready == false)
            {
                throw new LauncherValidationException("Locked frontend/backend dependencies are not ready after preparation.");
            }

            AppendStatus("Starting existing guarded startup and waiting for its health probes…");
            SetLastLaunchStatus($"Последний запуск: стартует {profile.DisplayName}");
            StartProcess(validated);
        }
        catch (Exception exception) when (exception is LauncherValidationException or IOException or UnauthorizedAccessException or Win32Exception)
        {
            AppendStatus($"Start blocked: {exception.Message}");
            SetLastLaunchStatus($"Последний запуск: заблокирован — {exception.Message}");
            _start.Enabled = true;
            _stop.Enabled = false;
        }
    }

    private void StartProcess(ValidatedProfile profile)
    {
        var process = new Process { StartInfo = ProfileValidator.BuildStartCommand(profile), EnableRaisingEvents = true };
        _launcherProcess = process;
        process.OutputDataReceived += (_, eventArgs) => HandleProcessLine(profile, eventArgs.Data);
        process.ErrorDataReceived += (_, eventArgs) => HandleProcessLine(profile, eventArgs.Data);
        process.Exited += (_, _) => BeginInvoke(() =>
        {
            AppendStatus($"Guarded startup exited with code {process.ExitCode}. See details above.");
            SetLastLaunchStatus($"Последний запуск: завершён с кодом {process.ExitCode}");
            if (ReferenceEquals(_launcherProcess, process))
            {
                _launcherProcess = null;
            }
            _stop.Enabled = false;
            _start.Enabled = true;
        });
        process.Start();
        _stop.Enabled = true;
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
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
        BeginInvoke(() =>
        {
            if (line.Contains(ReadyMarker, StringComparison.Ordinal))
            {
                if (!TryCompleteReady(
                        profile,
                        StopLaunchedStack,
                        message => AppendStatus(message)))
                {
                    _start.Enabled = true;
                    _stop.Enabled = false;
                    return;
                }
                AppendStatus(line);
                AppendStatus("Health checks passed. Hermes Finance is ready on loopback. Click Остановить to stop this profile.");
                SetLastLaunchStatus($"Последний запуск: готов — {profile.Profile.DisplayName}");
                if (profile.Profile.OpenBrowser)
                {
                    Process.Start(new ProcessStartInfo("http://127.0.0.1:8000") { UseShellExecute = true });
                }

                return;
            }

            AppendStatus(line);
        });
    }

    private void StopLaunchedStack() =>
        StopLaunchedStack("Launched stack stopped because its data identity could not be established.");

    private void StopLaunchedStack(string successMessage)
    {
        var process = _launcherProcess;
        if (process is null || process.HasExited)
        {
            _stop.Enabled = false;
            return;
        }

        _stop.Enabled = false;
        try
        {
            process.Kill(entireProcessTree: true);
            process.WaitForExit(5000);
            AppendStatus(successMessage);
            SetLastLaunchStatus("Последний запуск: остановлен");
        }
        catch (Exception exception) when (exception is InvalidOperationException or Win32Exception)
        {
            AppendStatus($"BLOCKING ERROR: could not stop the launched stack automatically. {exception.Message}");
            if (!process.HasExited)
            {
                _stop.Enabled = true;
            }
        }
    }

    private void AppendStatus(string message) => _status.AppendText($"[{DateTime.Now:HH:mm:ss}] {message}{Environment.NewLine}");

    private async Task PrepareDependenciesAsync(string checkout)
    {
        using var process = new Process
        {
            StartInfo = DependencyValidator.BuildPreparationCommand(checkout),
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
            AppendStatus($"deps: {line}");
        }
        foreach (var line in error.Split(Environment.NewLine, StringSplitOptions.RemoveEmptyEntries))
        {
            AppendStatus($"deps error: {line}");
        }
        if (process.ExitCode != 0)
        {
            throw new LauncherValidationException($"Dependency preparation failed with exit code {process.ExitCode}.");
        }
    }

    private void SetLastLaunchStatus(string message) => _lastLaunch.Text = message;

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
            AppendStatus($"Application icon could not be loaded: {exception.Message}");
        }
    }
}
