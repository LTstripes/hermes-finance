using System.Security.Cryptography;

namespace HermesFinance.Launcher;

public sealed record PreviewUpdateStatus(string CurrentSha, string? TargetSha)
{
    public bool TargetAvailable => !string.IsNullOrWhiteSpace(TargetSha);

    public bool IsCurrent => TargetAvailable
        && CurrentSha.Equals(TargetSha, StringComparison.OrdinalIgnoreCase);
}

public sealed record PreviewUpdateResult(string CurrentSha, string TargetSha, bool Updated);

internal static class PreviewUpdateService
{
    private const string TargetRef = "refs/remotes/origin/main";

    internal static PreviewUpdateStatus ReadStatus(ValidatedProfile profile)
    {
        EnsurePreview(profile);
        var current = ReadRequiredRef(profile.Checkout, "HEAD");
        return new PreviewUpdateStatus(current, TryReadRef(profile.Checkout, TargetRef));
    }

    internal static PreviewUpdateResult Update(ValidatedProfile profile)
    {
        EnsurePreview(profile);
        AssertCleanAndExpected(profile);
        var dataSnapshot = PreviewDataSnapshot.Capture(profile);

        RunGit(profile.Checkout, "fetch", "--no-tags", "--no-prune", "origin", "main:refs/remotes/origin/main");
        var target = ReadRequiredRef(profile.Checkout, TargetRef);
        var current = ReadRequiredRef(profile.Checkout, "HEAD");
        if (!IsSha(target))
        {
            throw new LauncherValidationException("Canonical origin/main did not resolve to a commit SHA.");
        }

        if (!current.Equals(target, StringComparison.OrdinalIgnoreCase))
        {
            RunGit(profile.Checkout, "merge", "--ff-only", "--no-edit", TargetRef);
        }

        AssertClean(profile.Checkout);
        var updated = ReadRequiredRef(profile.Checkout, "HEAD");
        if (!updated.Equals(target, StringComparison.OrdinalIgnoreCase))
        {
            throw new LauncherValidationException("Preview checkout did not reach canonical origin/main.");
        }

        dataSnapshot.AssertUnchanged(profile);
        return new PreviewUpdateResult(updated, target, !current.Equals(updated, StringComparison.OrdinalIgnoreCase));
    }

    private static void EnsurePreview(ValidatedProfile profile)
    {
        if (!profile.Profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase))
        {
            throw new LauncherValidationException("Only the configured Preview profile may be updated.");
        }
        if (string.IsNullOrWhiteSpace(profile.Checkout)
            || string.IsNullOrWhiteSpace(profile.DataDir)
            || string.IsNullOrWhiteSpace(profile.Database))
        {
            throw new LauncherValidationException("Preview update requires a fully validated profile tuple.");
        }
    }

    private static void AssertCleanAndExpected(ValidatedProfile profile)
    {
        AssertClean(profile.Checkout);
        var current = ReadRequiredRef(profile.Checkout, "HEAD");
        var expectedReference = profile.Profile.ExpectedRef.EndsWith("^{commit}", StringComparison.Ordinal)
            ? profile.Profile.ExpectedRef
            : profile.Profile.ExpectedRef + "^{commit}";
        var expected = ReadRequiredRef(profile.Checkout, expectedReference);
        if (current.Equals(expected, StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        var canonicalMain = TryReadRef(profile.Checkout, TargetRef);
        if (!current.Equals(canonicalMain, StringComparison.OrdinalIgnoreCase))
        {
            throw new LauncherValidationException("Preview checkout identity is unexpected; update is blocked.");
        }
    }

    private static void AssertClean(string checkout)
    {
        var status = RunGit(checkout, "status", "--porcelain=v1", "--untracked-files=all");
        if (!string.IsNullOrWhiteSpace(status) || RunGit(checkout, "ls-files", "-u").Length > 0)
        {
            throw new LauncherValidationException("Preview checkout is dirty or conflicted; update is blocked.");
        }
    }

    private static string ReadRequiredRef(string checkout, string reference) =>
        RunGit(checkout, "rev-parse", "--verify", reference);

    private static string? TryReadRef(string checkout, string reference)
    {
        try
        {
            return ReadRequiredRef(checkout, reference);
        }
        catch (LauncherValidationException)
        {
            return null;
        }
    }

    private static string RunGit(string checkout, params string[] arguments)
    {
        var startInfo = new System.Diagnostics.ProcessStartInfo
        {
            FileName = "git",
            WorkingDirectory = checkout,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        startInfo.Environment["GIT_TERMINAL_PROMPT"] = "0";
        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        try
        {
            using var process = System.Diagnostics.Process.Start(startInfo)
                ?? throw new LauncherValidationException("Could not start Git for the Preview update.");
            var output = process.StandardOutput.ReadToEnd();
            var error = process.StandardError.ReadToEnd();
            process.WaitForExit();
            if (process.ExitCode != 0)
            {
                throw new LauncherValidationException(
                    $"Preview Git operation failed ({string.Join(" ", arguments)}): {OneLine(error, output)}");
            }
            return output.Trim();
        }
        catch (System.ComponentModel.Win32Exception exception)
        {
            throw new LauncherValidationException($"Preview update cannot run Git: {exception.Message}");
        }
    }

    private static bool IsSha(string value) =>
        value.Length == 40 && value.All(character => Uri.IsHexDigit(character));

    private static string OneLine(string preferred, string fallback)
    {
        var value = string.IsNullOrWhiteSpace(preferred) ? fallback : preferred;
        return value.ReplaceLineEndings(" ").Trim();
    }

    private sealed record PreviewDataSnapshot(bool DatabaseExists, byte[]? DatabaseHash, string? Sidecar)
    {
        private const string SidecarName = ".hermes-data-identity.json";

        public static PreviewDataSnapshot Capture(ValidatedProfile profile)
        {
            var databaseExists = File.Exists(profile.Database);
            var databaseHash = databaseExists ? HashFile(profile.Database) : null;
            var sidecarPath = Path.Combine(profile.DataDir, SidecarName);
            var sidecar = File.Exists(sidecarPath) ? File.ReadAllText(sidecarPath) : null;
            return new PreviewDataSnapshot(databaseExists, databaseHash, sidecar);
        }

        public void AssertUnchanged(ValidatedProfile profile)
        {
            var sidecarPath = Path.Combine(profile.DataDir, SidecarName);
            var currentSidecar = File.Exists(sidecarPath) ? File.ReadAllText(sidecarPath) : null;
            if (currentSidecar != Sidecar)
            {
                throw new LauncherValidationException("Preview data identity changed during code update.");
            }

            var currentDatabaseExists = File.Exists(profile.Database);
            var currentHash = currentDatabaseExists ? HashFile(profile.Database) : null;
            if (currentDatabaseExists != DatabaseExists
                || !HashesEqual(currentHash, DatabaseHash))
            {
                throw new LauncherValidationException("Preview database changed during code update.");
            }
        }

        private static byte[] HashFile(string path)
        {
            using var stream = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            return SHA256.HashData(stream);
        }

        private static bool HashesEqual(byte[]? left, byte[]? right) =>
            left is not null && right is not null && CryptographicOperations.FixedTimeEquals(left, right)
            || left is null && right is null;
    }
}
