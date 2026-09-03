using System.Diagnostics;

namespace HermesFinance.Launcher;

/// <summary>
/// Launcher-owned first-time setup: turns explicit owner folder selections
/// into a concrete, boundary-validated config.json. Never guesses private
/// Stable/Preview paths and never writes placeholder configs — every path
/// comes from the owner via the setup dialog, and the file is written only
/// after all safety checks pass. Manual JSON editing stays recovery-only.
/// </summary>
public static class LauncherSetup
{
    private const string StableReleaseRef = "refs/tags/v0.8.0";
    private const string PreviewExpectedRef = "refs/remotes/origin/main";

    public static string DefaultConfigPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "HermesFinance", "launcher", "config.json");

    public static LauncherConfig BuildConfig(
        string stableCheckout,
        string stableDataDir,
        string previewCheckout,
        string previewDataDir,
        string? stableDatabase = null,
        string? previewDatabase = null)
    {
        var stableCheckoutFull = RequireExistingDirectory(stableCheckout, "Stable checkout");
        var stableDataFull = RequireExistingDirectory(stableDataDir, "Stable data directory");
        var previewCheckoutFull = RequireExistingDirectory(previewCheckout, "Preview checkout");
        var previewDataFull = RequireExistingDirectory(previewDataDir, "Preview data directory");

        AssertRuntimeLayout(stableCheckoutFull, "Stable");
        AssertRuntimeLayout(previewCheckoutFull, "Preview");

        var stableDatabaseFull = ResolveDatabasePath(stableDatabase, stableDataFull, "Stable database");
        var previewDatabaseFull = ResolveDatabasePath(previewDatabase, previewDataFull, "Preview database");

        var stable = new LauncherProfile
        {
            Id = "stable",
            DisplayName = "Hermes Finance — Stable",
            Type = "stable",
            Checkout = stableCheckoutFull,
            ExpectedRef = StableReleaseRef,
            DataDir = stableDataFull,
            Database = stableDatabaseFull,
            OpenBrowser = true,
        };
        var preview = new LauncherProfile
        {
            Id = "preview",
            DisplayName = "Hermes Finance — Preview",
            Type = "preview",
            Checkout = previewCheckoutFull,
            ExpectedRef = PreviewExpectedRef,
            DataDir = previewDataFull,
            Database = previewDatabaseFull,
            OpenBrowser = true,
        };

        // Stable must be the canonical production tuple; Preview must be fully
        // isolated from it. Reuses the same preflight boundary rules, read-only.
        ProfileValidator.AssertProfileTuple(stable, stableCheckoutFull, stableDataFull, stableDatabaseFull, stableCheckoutFull, stableDataFull, stableDatabaseFull);
        ProfileValidator.AssertProfileTuple(preview, stableCheckoutFull, stableDataFull, stableDatabaseFull, previewCheckoutFull, previewDataFull, previewDatabaseFull);

        AssertStableReleaseTag(stableCheckoutFull);
        AssertGitRepository(previewCheckoutFull, "Preview");

        return new LauncherConfig
        {
            Version = 1,
            CanonicalProduction = new CanonicalProduction
            {
                Checkout = stableCheckoutFull,
                DataDir = stableDataFull,
                Database = stableDatabaseFull,
            },
            Profiles = [stable, preview],
        };
    }

    public static void WriteConfig(LauncherConfig config, string configPath)
    {
        ProfileValidator.ValidateConfiguration(config);
        if (!LauncherConfig.IsConcreteConfig(config))
        {
            throw new LauncherValidationException("Setup produced a non-concrete config; refusing to write it. Reselect the profile directories.");
        }
        var directory = Path.GetDirectoryName(configPath);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }
        File.WriteAllText(configPath, System.Text.Json.JsonSerializer.Serialize(config, new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
    }

    private static string RequireExistingDirectory(string path, string description)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new LauncherValidationException($"{description} is not selected. Choose it in the setup dialog.");
        }
        var full = Path.IsPathFullyQualified(path)
            ? Path.GetFullPath(path)
            : throw new LauncherValidationException($"{description} must be an absolute path.");
        if (!Directory.Exists(full))
        {
            throw new LauncherValidationException($"{description} does not exist: '{path}'. Select a prepared runtime directory.");
        }
        return full;
    }

    private static string ResolveDatabasePath(string? database, string dataDir, string description)
    {
        var candidate = string.IsNullOrWhiteSpace(database)
            ? Path.Combine(dataDir, "finance.db")
            : database;
        if (!Path.IsPathFullyQualified(candidate))
        {
            throw new LauncherValidationException($"{description} must be an absolute path.");
        }
        var full = Path.GetFullPath(candidate);
        var parent = Path.GetDirectoryName(full);
        if (string.IsNullOrEmpty(parent) || !Directory.Exists(parent))
        {
            throw new LauncherValidationException($"The parent directory for {description} does not exist. Select a prepared data directory first.");
        }
        return full;
    }

    private static void AssertRuntimeLayout(string checkout, string description)
    {
        foreach (var relative in new[] { Path.Combine("scripts", "start-local.ps1"), Path.Combine("backend", "pyproject.toml"), Path.Combine("frontend", "package.json") })
        {
            if (!File.Exists(Path.Combine(checkout, relative)))
            {
                throw new LauncherValidationException($"{description} checkout is not a prepared Hermes Finance runtime (missing {relative}). Select the prepared checkout directory.");
            }
        }
    }

    private static void AssertStableReleaseTag(string stableCheckout)
    {
        try
        {
            var output = RunGit(stableCheckout, "rev-parse", "--verify", StableReleaseRef + "^{commit}");
            if (string.IsNullOrWhiteSpace(output))
            {
                throw new LauncherValidationException(
                    "Stable checkout does not carry the released v0.8.0 tag. Select the prepared Stable checkout at release v0.8.0.");
            }
        }
        catch (LauncherValidationException)
        {
            throw new LauncherValidationException(
                "Stable checkout does not carry the released v0.8.0 tag. Select the prepared Stable checkout at release v0.8.0.");
        }
    }

    private static void AssertGitRepository(string checkout, string description)
    {
        try
        {
            var output = RunGit(checkout, "rev-parse", "--git-dir");
            if (string.IsNullOrWhiteSpace(output))
            {
                throw new LauncherValidationException($"{description} checkout is not a Git repository. Select the prepared Preview checkout.");
            }
        }
        catch (LauncherValidationException)
        {
            throw new LauncherValidationException($"{description} checkout is not a Git repository. Select the prepared Preview checkout.");
        }
    }

    private static string RunGit(string workingDirectory, params string[] arguments)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = "git",
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }
        try
        {
            using var process = Process.Start(startInfo)
                ?? throw new LauncherValidationException("Could not start 'git'.");
            var standardOutput = process.StandardOutput.ReadToEnd();
            var standardError = process.StandardError.ReadToEnd();
            process.WaitForExit();
            if (process.ExitCode != 0)
            {
                throw new LauncherValidationException($"Git probe failed: {standardError.Trim()} {standardOutput.Trim()}".Trim());
            }
            return standardOutput;
        }
        catch (System.ComponentModel.Win32Exception exception)
        {
            throw new LauncherValidationException($"Git is unavailable: {exception.Message}");
        }
    }
}
