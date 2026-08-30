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
