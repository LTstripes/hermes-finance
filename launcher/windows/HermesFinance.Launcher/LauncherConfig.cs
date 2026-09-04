using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace HermesFinance.Launcher;

public sealed class LauncherConfig
{
    [JsonPropertyName("version")]
    public required int Version { get; init; }

    [JsonPropertyName("canonical_production")]
    public required CanonicalProduction CanonicalProduction { get; init; }

    [JsonPropertyName("profiles")]
    public required List<LauncherProfile> Profiles { get; init; }

    public static LauncherConfig Load(string configPath)
    {
        var json = File.ReadAllText(configPath);
        return JsonSerializer.Deserialize<LauncherConfig>(json, JsonOptions)
            ?? throw new LauncherValidationException("Launcher config is invalid: the document is empty.");
    }

    /// <summary>
    /// Persist the Stable release identity only after the upgrade service has
    /// proven the new immutable tag and switched the configured checkout. The
    /// write is atomic from the launcher's point of view and never changes the
    /// canonical production data paths.
    /// </summary>
    internal static LauncherConfig UpdateStableExpectedRef(string configPath, string expectedRef)
    {
        if (string.IsNullOrWhiteSpace(configPath) || !Path.IsPathFullyQualified(configPath))
        {
            throw new LauncherValidationException("Stable release identity cannot be persisted without an absolute config path.");
        }
        if (string.IsNullOrWhiteSpace(expectedRef)
            || !StableReleaseRefPattern.IsMatch(expectedRef))
        {
            throw new LauncherValidationException("Stable release identity cannot be persisted: expected_ref is not a release tag.");
        }

        var config = Load(configPath);
        ProfileValidator.ValidateConfiguration(config);
        var stable = config.Profiles.SingleOrDefault(
            profile => profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase));
        if (stable is null)
        {
            throw new LauncherValidationException("Stable release identity cannot be persisted: Stable profile is missing.");
        }

        var updated = new LauncherConfig
        {
            Version = config.Version,
            CanonicalProduction = config.CanonicalProduction,
            Profiles = config.Profiles.Select(profile => profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase)
                ? new LauncherProfile
                {
                    Id = profile.Id,
                    DisplayName = profile.DisplayName,
                    Type = profile.Type,
                    Checkout = profile.Checkout,
                    ExpectedRef = expectedRef,
                    DataDir = profile.DataDir,
                    Database = profile.Database,
                    OpenBrowser = profile.OpenBrowser,
                }
                : profile).ToList(),
        };

        var temporary = configPath + $".tmp-{Guid.NewGuid():N}";
        try
        {
            File.WriteAllText(temporary, JsonSerializer.Serialize(updated, new JsonSerializerOptions { WriteIndented = true }));
            File.Move(temporary, configPath, overwrite: true);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            throw new LauncherValidationException($"Stable release identity could not be persisted: {exception.Message}");
        }
        finally
        {
            try
            {
                if (File.Exists(temporary))
                {
                    File.Delete(temporary);
                }
            }
            catch (IOException)
            {
                // The original config is still the authoritative file if the
                // best-effort temporary cleanup loses a race.
            }
        }
        return updated;
    }

    /// <summary>
    /// Loads config. Missing, unknown-field, and stale-ref cases are handled
    /// launcher-first: concrete auto-create only where provably safe, otherwise
    /// fail closed with an actionable launcher-owned message (no placeholder
    /// config that demands manual JSON, no silent rewrites).
    /// </summary>
    public static LauncherConfig LoadOrCreate(string configPath, out string diagnostic)
    {
        diagnostic = "";
        var directory = Path.GetDirectoryName(configPath);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }

        if (!File.Exists(configPath))
        {
            // Auto-create ONLY from a concrete bundled template (no placeholders,
            // absolute paths, valid shape). The shipped config.example.json is a
            // template with <absolute-...> placeholders, so fresh installs fail
            // closed here with setup guidance instead of a placeholder file.
            var bundled = Path.Combine(AppContext.BaseDirectory, "config.example.json");
            if (TryAutoCreateConcrete(bundled, configPath, out var created, out var createDiag) && created is not null)
            {
                diagnostic = createDiag;
                return created;
            }

            var sourceFallback = Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "config.example.json");
            if (TryAutoCreateConcrete(sourceFallback, configPath, out var createdFallback, out var createDiagFallback) && createdFallback is not null)
            {
                diagnostic = createDiagFallback;
                return createdFallback;
            }

            throw new LauncherValidationException(
                $"Launcher config not found at {configPath}. Run install.ps1 to install the launcher, then open it and press «Обновить проверку». Manual JSON editing is recovery-only; see docs for prepared Stable/Preview runtimes.");
        }

        var raw = File.ReadAllText(configPath);
        // Try strict parse first
        try
        {
            var strict = JsonSerializer.Deserialize<LauncherConfig>(raw, JsonOptions);
            if (strict is not null)
            {
                // Auto-migrate stable expected_ref only where provably safe
                var migrated = TryMigrateStableTag(strict, configPath, out var migrateDiag);
                if (!string.IsNullOrWhiteSpace(migrateDiag))
                {
                    diagnostic = migrateDiag;
                }
                return migrated;
            }
        }
        catch (JsonException)
        {
            // Try schema-aware unknown-field strip; fail closed when it cannot
            // produce a valid config (original file left untouched).
            var tolerant = TryStripUnknownFields(raw, configPath, out var stripDiag);
            if (tolerant is not null)
            {
                diagnostic = stripDiag;
                return tolerant;
            }
            throw;
        }

        return JsonSerializer.Deserialize<LauncherConfig>(raw, JsonOptions)
            ?? throw new LauncherValidationException("Launcher config is invalid: the document is empty.");
    }

    private static bool TryAutoCreateConcrete(string templatePath, string configPath, out LauncherConfig? created, out string diagnostic)
    {
        created = null;
        diagnostic = "";
        if (!File.Exists(templatePath))
        {
            return false;
        }
        string text;
        try
        {
            text = File.ReadAllText(templatePath);
        }
        catch
        {
            return false;
        }
        LauncherConfig? candidate;
        try
        {
            candidate = JsonSerializer.Deserialize<LauncherConfig>(text, JsonOptions);
        }
        catch (JsonException)
        {
            return false;
        }
        if (candidate is null || !IsConcreteConfig(candidate))
        {
            return false;
        }
        try
        {
            File.Copy(templatePath, configPath);
            created = Load(configPath);
            diagnostic = $"Launcher config was missing; created concrete config at {configPath} from {templatePath}. No manual JSON needed.";
            return true;
        }
        catch
        {
            created = null;
            return false;
        }
    }

    internal static bool IsConcreteConfig(LauncherConfig config)
    {
        if (config.Version != 1)
        {
            return false;
        }
        if (config.Profiles is null || config.Profiles.Count == 0)
        {
            return false;
        }
        if (config.Profiles.Count(profile => profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase)) != 1)
        {
            return false;
        }
        foreach (var path in new[] { config.CanonicalProduction.Checkout, config.CanonicalProduction.DataDir, config.CanonicalProduction.Database })
        {
            if (string.IsNullOrWhiteSpace(path) || path.Contains('<') || path.Contains('>'))
            {
                return false;
            }
            if (!Path.IsPathFullyQualified(path))
            {
                return false;
            }
        }
        foreach (var profile in config.Profiles)
        {
            if (string.IsNullOrWhiteSpace(profile.Id)
                || string.IsNullOrWhiteSpace(profile.DisplayName)
                || string.IsNullOrWhiteSpace(profile.Type)
                || string.IsNullOrWhiteSpace(profile.ExpectedRef))
            {
                return false;
            }
            foreach (var path in new[] { profile.Checkout, profile.DataDir, profile.Database })
            {
                if (string.IsNullOrWhiteSpace(path) || path.Contains('<') || path.Contains('>'))
                {
                    return false;
                }
                if (!Path.IsPathFullyQualified(path))
                {
                    return false;
                }
            }
        }
        return true;
    }

    private static readonly string[] StaleStableRefs = ["refs/tags/v0.6.3", "refs/tags/v0.7.0", "refs/tags/v0.8.0", "origin/r07"];
    private const string CurrentStableRef = "refs/tags/v0.8.1";
    private static readonly Regex StableReleaseRefPattern = new(
        "^refs/tags/v(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)$",
        RegexOptions.CultureInvariant | RegexOptions.Compiled);

    private static LauncherConfig TryMigrateStableTag(LauncherConfig config, string configPath, out string diagnostic)
    {
        diagnostic = "";
        // Migrate a stale Stable expected_ref ONLY when provably safe: the
        // configured Stable checkout exists, is clean, and its HEAD already
        // equals the v0.8.1 release commit. Otherwise fail closed WITHOUT
        // touching the config file (preflight will surface recovery-only guidance).
        var stable = config.Profiles.FirstOrDefault(p => p.Type.Equals("stable", StringComparison.OrdinalIgnoreCase));
        if (stable is null || !StaleStableRefs.Contains(stable.ExpectedRef, StringComparer.Ordinal))
        {
            return config;
        }
        if (!Directory.Exists(stable.Checkout))
        {
            diagnostic = "Stable expected_ref migration blocked: Stable checkout does not exist; config left unchanged. Recovery-only: verify the prepared Stable runtime, then press «Обновить проверку».";
            return config;
        }
        string? head;
        string? target;
        try
        {
            head = RunGitRef(stable.Checkout, "HEAD");
            target = RunGitRef(stable.Checkout, CurrentStableRef + "^{commit}");
        }
        catch
        {
            diagnostic = "Stable expected_ref migration blocked: release identity cannot be proven (git unavailable or v0.8.1 tag missing); config left unchanged. Recovery-only: verify the prepared Stable runtime, then press «Обновить проверку».";
            return config;
        }
        if (string.IsNullOrWhiteSpace(head) || string.IsNullOrWhiteSpace(target)
            || !head.Equals(target, StringComparison.OrdinalIgnoreCase))
        {
            diagnostic = $"Stable expected_ref migration blocked: checkout HEAD {Short(head)} does not match release v0.8.1 {Short(target)}; config left unchanged. Recovery-only: verify the prepared Stable runtime, then press «Обновить проверку».";
            return config;
        }
        try
        {
            var status = RunGitOutput(stable.Checkout, "status", "--porcelain");
            if (!string.IsNullOrWhiteSpace(status))
            {
                diagnostic = "Stable expected_ref migration blocked: Stable checkout is not clean; config left unchanged. Recovery-only: make the checkout clean, then press «Обновить проверку».";
                return config;
            }
        }
        catch
        {
            diagnostic = "Stable expected_ref migration blocked: checkout cleanliness cannot be proven; config left unchanged. Recovery-only: verify the prepared Stable runtime, then press «Обновить проверку».";
            return config;
        }
        var fromRef = stable.ExpectedRef;
        var updated = new LauncherConfig
        {
            Version = config.Version,
            CanonicalProduction = config.CanonicalProduction,
            Profiles = config.Profiles.Select(p => p.Type.Equals("stable", StringComparison.OrdinalIgnoreCase)
                ? new LauncherProfile
                {
                    Id = p.Id,
                    DisplayName = p.DisplayName,
                    Type = p.Type,
                    Checkout = p.Checkout,
                    ExpectedRef = CurrentStableRef,
                    DataDir = p.DataDir,
                    Database = p.Database,
                    OpenBrowser = p.OpenBrowser,
                }
                : p).ToList(),
        };
        try
        {
            File.WriteAllText(configPath, JsonSerializer.Serialize(updated, new JsonSerializerOptions { WriteIndented = true }));
            diagnostic = $"Launcher config migrated Stable expected_ref to {CurrentStableRef} (from {fromRef}); checkout HEAD proven at release commit.";
        }
        catch
        {
            diagnostic = "";
            return config;
        }
        return updated;
    }

    private static string Short(string? sha) => string.IsNullOrWhiteSpace(sha) ? "—" : sha[..Math.Min(7, sha.Length)];

    private static string RunGitRef(string workingDirectory, string reference)
    {
        var output = RunGitOutput(workingDirectory, "rev-parse", "--verify", reference);
        var value = output.Trim();
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new LauncherValidationException($"Checkout Git identity cannot be read: empty result for '{reference}'.");
        }
        return value;
    }

    private static string RunGitOutput(string workingDirectory, params string[] arguments)
    {
        var startInfo = new System.Diagnostics.ProcessStartInfo
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
        using var process = System.Diagnostics.Process.Start(startInfo)
            ?? throw new LauncherValidationException("Could not start 'git'.");
        var standardOutput = process.StandardOutput.ReadToEnd();
        var standardError = process.StandardError.ReadToEnd();
        process.WaitForExit();
        if (process.ExitCode != 0)
        {
            throw new LauncherValidationException($"Checkout Git identity cannot be read: {(string.IsNullOrWhiteSpace(standardError) ? standardOutput : standardError).Trim()}");
        }
        return standardOutput;
    }

    private static readonly HashSet<string> TopLevelAllowed = new(StringComparer.Ordinal)
    {
        "version", "canonical_production", "profiles",
    };

    private static readonly HashSet<string> CanonicalAllowed = new(StringComparer.Ordinal)
    {
        "checkout", "data_dir", "database",
    };

    private static readonly HashSet<string> ProfileAllowed = new(StringComparer.Ordinal)
    {
        "id", "display_name", "type", "checkout", "expected_ref", "data_dir", "database", "open_browser",
    };

    private static LauncherConfig? TryStripUnknownFields(string raw, string configPath, out string diagnostic)
    {
        diagnostic = "";
        try
        {
            var node = JsonNode.Parse(raw) as JsonObject;
            if (node is null)
            {
                return null;
            }
            var stripped = false;
            foreach (var key in node.Select(entry => entry.Key).ToList())
            {
                if (!TopLevelAllowed.Contains(key))
                {
                    node.Remove(key);
                    stripped = true;
                }
            }
            if (node["canonical_production"] is JsonObject canonical)
            {
                foreach (var key in canonical.Select(entry => entry.Key).ToList())
                {
                    if (!CanonicalAllowed.Contains(key))
                    {
                        canonical.Remove(key);
                        stripped = true;
                    }
                }
            }
            if (node["profiles"] is JsonArray profiles)
            {
                foreach (var item in profiles)
                {
                    if (item is JsonObject profile)
                    {
                        foreach (var key in profile.Select(entry => entry.Key).ToList())
                        {
                            if (!ProfileAllowed.Contains(key))
                            {
                                profile.Remove(key);
                                stripped = true;
                            }
                        }
                    }
                }
            }
            if (!stripped)
            {
                return null;
            }
            var cleanedJson = node.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
            var cfg = JsonSerializer.Deserialize<LauncherConfig>(cleanedJson, JsonOptions);
            if (cfg is null)
            {
                return null;
            }
            diagnostic = "Launcher config contained unknown fields; they were removed automatically. Extra fields are not needed for normal use.";
            try
            {
                File.WriteAllText(configPath, JsonSerializer.Serialize(cfg, new JsonSerializerOptions { WriteIndented = true }));
            }
            catch
            {
                // Migration diagnostic is best-effort; config still usable in memory.
            }
            return cfg;
        }
        catch
        {
            return null;
        }
    }

    public static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = false,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
    };
}

public sealed class CanonicalProduction
{
    [JsonPropertyName("checkout")]
    public required string Checkout { get; init; }

    [JsonPropertyName("data_dir")]
    public required string DataDir { get; init; }

    [JsonPropertyName("database")]
    public required string Database { get; init; }
}

public sealed class LauncherProfile
{
    [JsonPropertyName("id")]
    public required string Id { get; init; }

    [JsonPropertyName("display_name")]
    public required string DisplayName { get; init; }

    [JsonPropertyName("type")]
    public required string Type { get; init; }

    [JsonPropertyName("checkout")]
    public required string Checkout { get; init; }

    [JsonPropertyName("expected_ref")]
    public required string ExpectedRef { get; init; }

    [JsonPropertyName("data_dir")]
    public required string DataDir { get; init; }

    [JsonPropertyName("database")]
    public required string Database { get; init; }

    [JsonPropertyName("open_browser")]
    public required bool OpenBrowser { get; init; }
}

public sealed class LauncherValidationException : Exception
{
    public LauncherValidationException(string message)
        : base(message)
    {
    }
}
