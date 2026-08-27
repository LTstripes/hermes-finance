using System.Diagnostics;
using System.Text.Json;

namespace HermesFinance.Launcher;

public sealed class MainForm : Form
{
    private const string ReadyMarker = "Hermes Finance is ready: http://127.0.0.1:8000";
    private readonly ListBox _profiles = new() { Dock = DockStyle.Top, Height = 130 };
    private readonly Button _start = new() { Text = "Запустить", Dock = DockStyle.Top, Height = 36 };
    private readonly TextBox _status = new()
    {
        Dock = DockStyle.Fill,
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Vertical,
        Font = new Font(FontFamily.GenericMonospace, 9),
    };
    private LauncherConfig? _config;
    private Process? _launcherProcess;

    public MainForm()
    {
        Text = "Hermes Finance";
        MinimumSize = new Size(620, 420);
        StartPosition = FormStartPosition.CenterScreen;
        Controls.Add(_status);
        Controls.Add(_start);
        Controls.Add(_profiles);
        _start.Click += async (_, _) => await StartSelectedAsync();
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
            AppendStatus($"Validation passed: {validated.Profile.DisplayName} at {validated.Head[..Math.Min(12, validated.Head.Length)]}.");
            AppendStatus("Starting existing guarded startup and waiting for its health probes…");
            StartProcess(validated);
        }
        catch (Exception exception) when (exception is LauncherValidationException or IOException or UnauthorizedAccessException)
        {
            AppendStatus($"Start blocked: {exception.Message}");
            _start.Enabled = true;
        }
    }

    private void StartProcess(ValidatedProfile profile)
    {
        _launcherProcess = new Process { StartInfo = ProfileValidator.BuildStartCommand(profile), EnableRaisingEvents = true };
        _launcherProcess.OutputDataReceived += (_, eventArgs) => HandleProcessLine(profile, eventArgs.Data);
        _launcherProcess.ErrorDataReceived += (_, eventArgs) => HandleProcessLine(profile, eventArgs.Data);
        _launcherProcess.Exited += (_, _) => BeginInvoke(() =>
        {
            AppendStatus($"Guarded startup exited with code {_launcherProcess?.ExitCode}. See details above.");
            _start.Enabled = true;
        });
        _launcherProcess.Start();
        _launcherProcess.BeginOutputReadLine();
        _launcherProcess.BeginErrorReadLine();
    }

    private void HandleProcessLine(ValidatedProfile profile, string? line)
    {
        if (string.IsNullOrWhiteSpace(line))
        {
            return;
        }
        BeginInvoke(() =>
        {
            AppendStatus(line);
            if (line.Contains(ReadyMarker, StringComparison.Ordinal))
            {
                try
                {
                    ProfileValidator.WriteMissingSidecar(profile);
                }
                catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
                {
                    AppendStatus($"Health passed, but the data identity sidecar could not be written: {exception.Message}");
                }
                AppendStatus("Health checks passed. Hermes Finance is ready on loopback.");
                if (profile.Profile.OpenBrowser)
                {
                    Process.Start(new ProcessStartInfo("http://127.0.0.1:8000") { UseShellExecute = true });
                }
            }
        });
    }

    private void AppendStatus(string message) => _status.AppendText($"[{DateTime.Now:HH:mm:ss}] {message}{Environment.NewLine}");
}
