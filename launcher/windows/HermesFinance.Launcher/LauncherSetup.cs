using System.Diagnostics;
using System.Text.RegularExpressions;

namespace HermesFinance.Launcher;

/// <summary>
/// First-time/reconfigure setup binds owner-selected prepared runtimes without
/// network discovery: Stable must be on one local annotated vX.Y.Z tag that
/// peels to HEAD; Preview is pinned to exact local HEAD. It never fetches,
/// follows main, selects a remote release, or mutates either checkout.
/// </summary>
public static class LauncherSetup
{
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
        var stableReleaseRef = ReadStableReleaseRef(stableCheckoutFull);
        var previewHead = ReadExactHead(previewCheckoutFull, "Preview");

        var stable = new LauncherProfile
        {
            Id = "stable",
            DisplayName = "Hermes Finance — Stable",
            Type = "stable",
            Checkout = stableCheckoutFull,
            ExpectedRef = stableReleaseRef,
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
            ExpectedRef = previewHead,
            DataDir = previewDataFull,
            Database = previewDatabaseFull,
            OpenBrowser = true,
        };

        ProfileValidator.AssertProfileTuple(stable, stableCheckoutFull, stableDataFull, stableDatabaseFull, stableCheckoutFull, stableDataFull, stableDatabaseFull);
        ProfileValidator.AssertProfileTuple(preview, stableCheckoutFull, stableDataFull, stableDatabaseFull, previewCheckoutFull, previewDataFull, previewDatabaseFull);

        try
        {
            ProfileValidator.AssertGitIdentity(stable, stableCheckoutFull, stableCheckoutFull);
        }
        catch (LauncherValidationException exception)
        {
            throw new LauncherValidationException($"Setup rejected the Stable checkout: {exception.Message} Select the already prepared production runtime.");
        }
        try
        {
            ProfileValidator.AssertGitIdentity(preview, previewCheckoutFull, stableCheckoutFull);
        }
        catch (LauncherValidationException exception)
        {
            throw new LauncherValidationException($"Setup rejected the Preview checkout: {exception.Message} Select a clean independent prepared Preview clone, never the Stable worktree.");
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

    private static string ReadStableReleaseRef(string checkout)
    {
        var head = ReadExactHead(checkout, "Stable");
        var output = RunGitOutput(
            checkout,
            "for-each-ref",
            "--points-at",
            head,
            "--format=%(refname) %(objecttype)",
            "refs/tags");

        var candidates = output
            .Split('\n', StringSplitOptions.RemoveEmptyEntries)
            .Select(line => line.Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries))
            .Where(parts => parts.Length == 2
                && parts[1].Equals("tag", StringComparison.Ordinal)
                && Regex.IsMatch(parts[0], @"^refs/tags/v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$", RegexOptions.CultureInvariant))
            .Select(parts => parts[0])
            .Where(reference => RunGitOutput(checkout, "rev-parse", "--verify", reference + "^{commit}")
                .Trim()
                .Equals(head, StringComparison.OrdinalIgnoreCase))
            .Distinct(StringComparer.Ordinal)
            .ToArray();

        if (candidates.Length != 1)
        {
            throw new LauncherValidationException(
                "Setup rejected the Stable checkout: HEAD must be pinned by exactly one local annotated vX.Y.Z release tag. Run canonical OPS02 first or select the prepared published Stable runtime.");
        }
        return candidates[0];
    }

    private static string ReadExactHead(string checkout, string description)
    {
        var head = RunGitOutput(checkout, "rev-parse", "--verify", "HEAD").Trim();
        if (head.Length != 40 || !head.All(Uri.IsHexDigit))
        {
            throw new LauncherValidationException($"Setup cannot prove exact {description} HEAD.");
        }
        return head.ToLowerInvariant();
    }

    private static string RunGitOutput(string checkout, params string[] arguments)
    {
        var command = new ProcessStartInfo
        {
            FileName = "git",
            WorkingDirectory = checkout,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var argument in arguments)
        {
            command.ArgumentList.Add(argument);
        }

        try
        {
            using var process = Process.Start(command)
                ?? throw new LauncherValidationException("Setup cannot inspect Git identity.");
            var stdout = process.StandardOutput.ReadToEnd();
            var stderr = process.StandardError.ReadToEnd();
            process.WaitForExit();
            if (process.ExitCode != 0)
            {
                throw new LauncherValidationException(
                    $"Setup cannot inspect Git identity: {(string.IsNullOrWhiteSpace(stderr) ? stdout : stderr).Trim()}");
            }
            return stdout;
        }
        catch (System.ComponentModel.Win32Exception exception)
        {
            throw new LauncherValidationException($"Setup cannot inspect Git identity because git is unavailable: {exception.Message}");
        }
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
