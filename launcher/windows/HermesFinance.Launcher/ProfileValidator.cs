using System.Diagnostics;
using System.ComponentModel;
using System.Net;
using System.Net.NetworkInformation;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace HermesFinance.Launcher;

public sealed record ValidatedProfile(
    LauncherProfile Profile,
    string Checkout,
    string DataDir,
    string Database,
    string Head,
    string SidecarKind,
    DependencyStatus? Dependencies = null);

public static class ProfileValidator
{
    private const string SidecarName = ".hermes-data-identity.json";
    private const string ReadyUrl = "http://127.0.0.1:8000";

    public static ValidatedProfile Validate(LauncherConfig config, LauncherProfile profile)
    {
        ValidateConfiguration(config);

        var canonicalCheckout = ResolveExistingDirectory(config.CanonicalProduction.Checkout, "canonical production checkout");
        var canonicalDataDir = ResolveExistingDirectory(config.CanonicalProduction.DataDir, "canonical production data_dir");
        var canonicalDatabase = ResolvePotentialFile(config.CanonicalProduction.Database, "canonical production database");
        if (!IsWithin(canonicalDatabase, canonicalDataDir))
        {
            throw new LauncherValidationException("Launcher config is invalid: canonical production database is outside canonical data_dir.");
        }

        var checkout = ResolveExistingDirectory(profile.Checkout, $"profile '{profile.Id}' checkout");
        var dataDir = ResolveExistingDirectory(profile.DataDir, $"profile '{profile.Id}' data_dir");
        var database = ResolvePotentialFile(profile.Database, $"profile '{profile.Id}' database");
        if (!IsWithin(database, dataDir))
        {
            throw new LauncherValidationException("Database must be inside the configured data_dir.");
        }

        AssertCheckoutLayout(checkout);
        AssertProfileTuple(profile, canonicalCheckout, canonicalDataDir, canonicalDatabase, checkout, dataDir, database);
        var head = AssertGitIdentity(profile, checkout, canonicalCheckout);
        var sidecarKind = AssertSidecar(profile, dataDir, database);
        AssertSchemaCompatibility(checkout, database, profile.Type);
        var dependencies = DependencyValidator.Check(checkout);
        AssertPortAvailable();

        return new ValidatedProfile(profile, checkout, dataDir, database, head, sidecarKind, dependencies);
    }

    public static void ValidateConfiguration(LauncherConfig config)
    {
        if (config.Version != 1)
        {
            throw new LauncherValidationException("Launcher config is invalid: only version 1 is supported.");
        }

        Require(config.CanonicalProduction.Checkout, "canonical_production.checkout");
        Require(config.CanonicalProduction.DataDir, "canonical_production.data_dir");
        Require(config.CanonicalProduction.Database, "canonical_production.database");
        if (config.Profiles is null || config.Profiles.Count == 0)
        {
            throw new LauncherValidationException("Launcher config is invalid: at least one profile is required.");
        }

        if (config.Profiles.Count(profile => profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase)) != 1)
        {
            throw new LauncherValidationException("Only one production profile is allowed.");
        }

        var ids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var profile in config.Profiles)
        {
            Require(profile.Id, "profiles[].id");
            Require(profile.DisplayName, "profiles[].display_name");
            Require(profile.Type, "profiles[].type");
            Require(profile.Checkout, "profiles[].checkout");
            Require(profile.ExpectedRef, "profiles[].expected_ref");
            Require(profile.DataDir, "profiles[].data_dir");
            Require(profile.Database, "profiles[].database");
            if (!IsKnownProfileType(profile.Type))
            {
                throw new LauncherValidationException("Launcher config is invalid: profile type must be stable, preview, or experiment.");
            }
            if (!ids.Add(profile.Id))
            {
                throw new LauncherValidationException("Launcher config is invalid: profile ids must be unique.");
            }
        }
    }

    public static ProcessStartInfo BuildStartCommand(ValidatedProfile profile)
    {
        var powershell = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Windows),
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
        if (!File.Exists(powershell))
        {
            powershell = "powershell.exe";
        }

        var startScript = Path.Combine(profile.Checkout, "scripts", "start-local.ps1");
        var command = new ProcessStartInfo
        {
            FileName = powershell,
            WorkingDirectory = profile.Checkout,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        command.ArgumentList.Add("-NoProfile");
        command.ArgumentList.Add("-ExecutionPolicy");
        command.ArgumentList.Add("Bypass");
        command.ArgumentList.Add("-File");
        command.ArgumentList.Add(startScript);
        // Pydantic gives process environment precedence over the checkout's .env.
        // This binds Alembic's effective database to the same resolved path that
        // completed all tuple, file-identity and schema checks above.
        command.Environment["HERMES_FINANCE_DATABASE_PATH"] = profile.Database;
        return command;
    }

    internal static ProcessStartInfo BuildSchemaCheckCommand(string checkout, string database)
    {
        var script = ResolveBundledSchemaCheckScript();
        var command = new ProcessStartInfo
        {
            FileName = "uv",
            WorkingDirectory = Path.Combine(checkout, "backend"),
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        command.ArgumentList.Add("run");
        command.ArgumentList.Add("--locked");
        command.ArgumentList.Add("python");
        command.ArgumentList.Add(script);
        command.ArgumentList.Add("--database");
        command.ArgumentList.Add(database);
        command.ArgumentList.Add("--checkout");
        command.ArgumentList.Add(checkout);
        return command;
    }

    public static void WriteMissingSidecar(ValidatedProfile profile)
    {
        var sidecarPath = Path.Combine(profile.DataDir, SidecarName);
        if (File.Exists(sidecarPath))
        {
            return;
        }

        var document = new Dictionary<string, string>
        {
            ["kind"] = profile.SidecarKind,
            ["profile_id"] = profile.Profile.Id,
            ["updated_at"] = DateTimeOffset.UtcNow.ToString("O"),
        };
        var temporary = sidecarPath + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(document));
        File.Move(temporary, sidecarPath);
    }

    internal static void AssertProfileTuple(
        LauncherProfile profile,
        string canonicalCheckout,
        string canonicalDataDir,
        string canonicalDatabase,
        string checkout,
        string dataDir,
        string database)
    {
        var isStable = profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase);
        if (isStable)
        {
            if (!SamePath(checkout, canonicalCheckout))
            {
                throw new LauncherValidationException("Stable may use only the production runtime.");
            }
            if (!SamePath(dataDir, canonicalDataDir) || !SamePath(database, canonicalDatabase))
            {
                throw new LauncherValidationException("Stable may use only the production database.");
            }
            return;
        }

        if (SamePath(checkout, canonicalCheckout) || SamePath(dataDir, canonicalDataDir) || SamePath(database, canonicalDatabase))
        {
            throw new LauncherValidationException("This profile cannot open production data.");
        }
        if (File.Exists(database) && File.Exists(canonicalDatabase) && SameFileIdentity(database, canonicalDatabase))
        {
            throw new LauncherValidationException("Data path aliases production.");
        }
    }

    internal static string AssertGitIdentity(LauncherProfile profile, string checkout, string canonicalCheckout)
    {
        var head = RunGit(checkout, "rev-parse", "HEAD");
        var expected = RunGit(checkout, "rev-parse", "--verify", profile.ExpectedRef + "^{commit}");
        if (!head.Equals(expected, StringComparison.OrdinalIgnoreCase))
        {
            throw new LauncherValidationException("Checkout identity does not match this profile.");
        }

        if (profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase) || profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase))
        {
            if (!string.IsNullOrWhiteSpace(RunGit(checkout, "status", "--porcelain")))
            {
                throw new LauncherValidationException("Code identity is ambiguous: Stable and Preview checkouts must be clean.");
            }
        }

        if (!profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase))
        {
            var profileCommonDir = ResolveGitDirectory(checkout, RunGit(checkout, "rev-parse", "--git-common-dir"));
            var canonicalCommonDir = ResolveGitDirectory(canonicalCheckout, RunGit(canonicalCheckout, "rev-parse", "--git-common-dir"));
            if (SamePath(profileCommonDir, canonicalCommonDir))
            {
                throw new LauncherValidationException("Checkout is not independent: linked worktrees are unsafe for this profile.");
            }
        }
        return head;
    }

    internal static string AssertSidecar(LauncherProfile profile, string dataDir, string database)
    {
        var expectedKind = profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase)
            ? "production"
            : profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase) ? "preview" : "sandbox";
        var sidecar = Path.Combine(dataDir, SidecarName);
        if (!File.Exists(sidecar))
        {
            if (profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase) || !File.Exists(database))
            {
                return expectedKind;
            }
            throw new LauncherValidationException("Unstamped data is treated as unsafe.");
        }

        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(sidecar));
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object
                || !root.TryGetProperty("kind", out var kind)
                || kind.ValueKind != JsonValueKind.String
                || !expectedKind.Equals(kind.GetString(), StringComparison.Ordinal))
            {
                throw new LauncherValidationException("Data sidecar does not match this profile type.");
            }
            if (root.TryGetProperty("profile_id", out var profileId)
                && profileId.ValueKind == JsonValueKind.String
                && !profile.Id.Equals(profileId.GetString(), StringComparison.Ordinal))
            {
                throw new LauncherValidationException("Data sidecar belongs to a different profile.");
            }
        }
        catch (JsonException exception)
        {
            throw new LauncherValidationException($"Data sidecar is invalid: {exception.Message}");
        }
        return expectedKind;
    }

    private static void AssertSchemaCompatibility(string checkout, string database, string profileType)
    {
        if (!File.Exists(database))
        {
            return;
        }

        ProcessOutput output;
        try
        {
            output = RunProcess(BuildSchemaCheckCommand(checkout, database));
        }
        catch (Win32Exception exception)
        {
            throw new LauncherValidationException($"Schema compatibility cannot be checked because uv is unavailable: {exception.Message}");
        }
        if (output.ExitCode != 0)
        {
            throw new LauncherValidationException($"Schema compatibility check failed: {OneLine(output.StandardError, output.StandardOutput)}");
        }

        try
        {
            using var result = JsonDocument.Parse(output.StandardOutput);
            var status = result.RootElement.GetProperty("status").GetString();
            if (status is not ("at_head" or "behind"))
            {
                var message = result.RootElement.TryGetProperty("message", out var detail) ? detail.GetString() : status;
                throw new LauncherValidationException($"Schema is not compatible with this code: {message}");
            }
        }
        catch (JsonException exception)
        {
            throw new LauncherValidationException($"Schema compatibility result is invalid: {exception.Message}");
        }
    }

    private static string ResolveBundledSchemaCheckScript()
    {
        var script = Path.Combine(AppContext.BaseDirectory, "launcher-schema-check.py");
        if (!File.Exists(script))
        {
            throw new LauncherValidationException("Schema compatibility check is unavailable: launcher probe is missing.");
        }
        return script;
    }

    private static void AssertPortAvailable()
    {
        if (IPGlobalProperties.GetIPGlobalProperties().GetActiveTcpListeners().Any(endpoint => endpoint.Port == 8000))
        {
            throw new LauncherValidationException("Another Hermes instance is running; v1 is single-instance on port 8000.");
        }
    }

    private static void AssertCheckoutLayout(string checkout)
    {
        foreach (var relative in new[] { "scripts\\start-local.ps1", "backend\\pyproject.toml", "frontend\\package.json" })
        {
            if (!File.Exists(Path.Combine(checkout, relative)))
            {
                throw new LauncherValidationException("Guarded startup is unavailable: the configured checkout is not a Hermes Finance runtime.");
            }
        }
    }

    private static string ResolveExistingDirectory(string path, string description)
    {
        var fullPath = RequireAbsolute(path, description);
        if (!Directory.Exists(fullPath))
        {
            throw new LauncherValidationException($"{description} does not exist.");
        }
        return ResolveExistingPath(fullPath);
    }

    private static string ResolvePotentialFile(string path, string description)
    {
        var fullPath = RequireAbsolute(path, description);
        var parent = Path.GetDirectoryName(fullPath);
        if (string.IsNullOrEmpty(parent) || !Directory.Exists(parent))
        {
            throw new LauncherValidationException($"The parent directory for {description} does not exist.");
        }
        return Path.Combine(ResolveExistingPath(parent), Path.GetFileName(fullPath));
    }

    private static string RequireAbsolute(string path, string description)
    {
        Require(path, description);
        if (!Path.IsPathFullyQualified(path))
        {
            throw new LauncherValidationException($"{description} must be an absolute path.");
        }
        return Path.GetFullPath(path);
    }

    private static string ResolveExistingPath(string path)
    {
        var root = Path.GetPathRoot(path) ?? throw new LauncherValidationException("Path does not have a root.");
        var current = root;
        var remainder = path[root.Length..];
        foreach (var component in remainder.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar))
        {
            if (string.IsNullOrEmpty(component))
            {
                continue;
            }
            current = Path.Combine(current, component);
            var info = Directory.Exists(current) ? new DirectoryInfo(current) : new FileInfo(current) as FileSystemInfo;
            if (info.LinkTarget is not null)
            {
                var target = info.ResolveLinkTarget(true);
                if (target is null)
                {
                    throw new LauncherValidationException("A reparse point could not be resolved.");
                }
                current = target.FullName;
            }
        }
        return Path.GetFullPath(current);
    }

    private static string ResolveGitDirectory(string checkout, string commonDir)
    {
        var resolved = Path.IsPathFullyQualified(commonDir)
            ? commonDir
            : Path.Combine(checkout, commonDir);
        return ResolveExistingDirectory(resolved, "Git common directory");
    }

    private static string RunGit(string checkout, params string[] arguments)
    {
        try
        {
            var output = RunProcess("git", checkout, arguments);
            if (output.ExitCode != 0)
            {
                throw new LauncherValidationException($"Checkout Git identity cannot be read: {OneLine(output.StandardError, output.StandardOutput)}");
            }
            return output.StandardOutput.Trim();
        }
        catch (Win32Exception exception)
        {
            throw new LauncherValidationException($"Checkout Git identity cannot be read because git is unavailable: {exception.Message}");
        }
    }

    private static ProcessOutput RunProcess(string fileName, string workingDirectory, params string[] arguments)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = fileName,
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
        return RunProcess(startInfo);
    }

    private static ProcessOutput RunProcess(ProcessStartInfo startInfo)
    {
        using var process = Process.Start(startInfo) ?? throw new LauncherValidationException($"Could not start '{startInfo.FileName}'.");
        var standardOutput = process.StandardOutput.ReadToEnd();
        var standardError = process.StandardError.ReadToEnd();
        process.WaitForExit();
        return new ProcessOutput(process.ExitCode, standardOutput, standardError);
    }

    private static bool SameFileIdentity(string left, string right)
    {
        if (!OperatingSystem.IsWindows())
        {
            return false;
        }
        using var leftStream = File.Open(left, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        using var rightStream = File.Open(right, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        return GetFileInformationByHandle(leftStream.SafeFileHandle, out var leftInfo)
            && GetFileInformationByHandle(rightStream.SafeFileHandle, out var rightInfo)
            && leftInfo.VolumeSerialNumber == rightInfo.VolumeSerialNumber
            && leftInfo.FileIndexHigh == rightInfo.FileIndexHigh
            && leftInfo.FileIndexLow == rightInfo.FileIndexLow;
    }

    private static bool SamePath(string left, string right) =>
        string.Equals(Path.TrimEndingDirectorySeparator(left), Path.TrimEndingDirectorySeparator(right), StringComparison.OrdinalIgnoreCase);

    private static bool IsWithin(string candidate, string parent) =>
        SamePath(candidate, parent)
        || candidate.StartsWith(Path.TrimEndingDirectorySeparator(parent) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);

    private static bool IsKnownProfileType(string type) =>
        type.Equals("stable", StringComparison.OrdinalIgnoreCase)
        || type.Equals("preview", StringComparison.OrdinalIgnoreCase)
        || type.Equals("experiment", StringComparison.OrdinalIgnoreCase);

    private static void Require(string? value, string description)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new LauncherValidationException($"Launcher config is invalid: {description} is required.");
        }
    }

    private static string OneLine(string preferred, string fallback)
    {
        var value = string.IsNullOrWhiteSpace(preferred) ? fallback : preferred;
        return value.ReplaceLineEndings(" ").Trim();
    }

    private sealed record ProcessOutput(int ExitCode, string StandardOutput, string StandardError);

    [StructLayout(LayoutKind.Sequential)]
    private struct ByHandleFileInformation
    {
        public uint FileAttributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(
        Microsoft.Win32.SafeHandles.SafeFileHandle file,
        out ByHandleFileInformation fileInformation);
}
