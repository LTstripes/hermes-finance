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
    private const string StableReleaseRef = "refs/tags/v0.8.2";
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

        // Identity proof reuses the exact preflight invariants — no weaker
        // parallel implementation. Stable: HEAD == v0.8.2 tag and clean.
        // Preview: at refs/remotes/origin/main, clean, and independent from
        // Stable (no linked worktree / shared git-common-dir). Read-only:
        // no fetch, no network; Preview update stays an explicit owner action.
        try
        {
            ProfileValidator.AssertGitIdentity(stable, stableCheckoutFull, stableCheckoutFull);
        }
        catch (LauncherValidationException exception)
        {
            throw new LauncherValidationException(
                $"Setup rejected the Stable checkout: {exception.Message} Select a clean prepared Stable checkout at released v0.8.2 (HEAD == refs/tags/v0.8.2).");
        }
        try
        {
            ProfileValidator.AssertGitIdentity(preview, previewCheckoutFull, stableCheckoutFull);
        }
        catch (LauncherValidationException exception)
        {
            throw new LauncherValidationException(
                $"Setup rejected the Preview checkout: {exception.Message} Select a clean independent Preview checkout at refs/remotes/origin/main (not a Stable worktree).");
        }

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
}
