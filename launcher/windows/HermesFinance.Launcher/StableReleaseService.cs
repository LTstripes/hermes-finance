using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace HermesFinance.Launcher;

/// <summary>
/// A release identity is deliberately stronger than a version string: the
/// tag must be an annotated remote tag which peels to the recorded commit.
/// </summary>
public sealed record StableReleaseIdentity(
    string Tag,
    string Version,
    string CommitSha,
    string TagObjectSha,
    string? ReleaseUrl)
{
    public string Ref => $"refs/tags/{Tag}";
}

/// <summary>
/// Transient result of an explicit Stable release discovery. It is never
/// persisted in launcher config; only the proven target ref is persisted after
/// the guarded upgrade has completed.
/// </summary>
public sealed record StableUpgradeStatus(
    StableReleaseIdentity? Current,
    StableReleaseIdentity? Target,
    string? FailureReason)
{
    public bool TargetAvailable => Current is not null
        && Target is not null
        && string.IsNullOrWhiteSpace(FailureReason);

    public bool IsCurrentReleaseProven => Current is not null
        && string.IsNullOrWhiteSpace(FailureReason);
}

internal sealed record StableUpgradeResult(
    StableReleaseIdentity Current,
    StableReleaseIdentity Target,
    string BackupId,
    LauncherConfig Config);

/// <summary>
/// Explicit owner-triggered Stable release discovery and upgrade.
///
/// Normal profile validation never calls this type. Discovery is read-only
/// and is invoked only by an explicit owner action. Upgrade is the only path
/// here that may fetch a tag, detach the configured Stable checkout, or write
/// the launcher config.
/// </summary>
internal static class StableReleaseService
{
    private const string ReleasesEndpoint =
        "https://api.github.com/repos/LTstripes/hermes-finance/releases?per_page=100";
    private const string GitTreeEndpoint =
        "https://api.github.com/repos/LTstripes/hermes-finance/git/trees/";
    private const string BackupScriptName = "launcher-production-backup.py";
    private const string BackupDirectoryName = "backups";
    private const string DataIdentityFilename = ".hermes-data-identity.json";
    private const string BackupFilenamePattern =
        "^finance_backup_\\d{8}T\\d{12}Z(?:-\\d+)?\\.sqlite3$";
    private static readonly Regex ReleaseTagPattern = new(
        "^v(?<major>0|[1-9]\\d*)\\.(?<minor>0|[1-9]\\d*)\\.(?<patch>0|[1-9]\\d*)$",
        RegexOptions.CultureInvariant | RegexOptions.Compiled);
    private static readonly Regex ShaPattern = new("^[0-9a-fA-F]{40}$", RegexOptions.Compiled);
    private static readonly Regex BackupFilenameRegex = new(BackupFilenamePattern, RegexOptions.Compiled);

    /// <summary>
    /// Read-only release discovery. No fetch, checkout, config write, backup,
    /// dependency preparation, or startup is performed here.
    /// </summary>
    internal static StableUpgradeStatus Discover(ValidatedProfile profile, HttpMessageHandler? releaseHandler = null)
    {
        EnsureStableProfile(profile);
        var current = ProveCurrentRelease(profile);
        if (!TryParseReleaseTag(current.Tag, out var currentVersion))
        {
            throw new LauncherValidationException("Stable current release identity is invalid; upgrade is blocked.");
        }
        var published = ReadPublishedReleases(releaseHandler);
        var newer = published
            .Where(release => release.VersionValue.CompareTo(currentVersion) > 0)
            .OrderByDescending(release => release.VersionValue)
            .ThenByDescending(release => release.Tag, StringComparer.Ordinal)
            .ToArray();

        if (newer.Length == 0)
        {
            return new StableUpgradeStatus(current, null, null);
        }

        // If the newest published candidate cannot be proven as an annotated
        // remote tag, fail closed. Do not silently downgrade to an older
        // candidate whose publication state may also be stale.
        var candidate = newer[0];
        var target = ProveRemoteRelease(profile.Checkout, candidate.Tag, candidate.VersionValue, candidate.ReleaseUrl);
        return new StableUpgradeStatus(current, target, null);
    }

    /// <summary>
    /// Perform one guarded upgrade after the UI has obtained an explicit
    /// target. The GitHub publication and remote tag are re-read before the
    /// backup so a stale UI result cannot authorize a different target.
    /// </summary>
    internal static StableUpgradeResult Upgrade(
        ValidatedProfile profile,
        StableReleaseIdentity target,
        string configPath,
        HttpMessageHandler? releaseHandler = null)
    {
        EnsureStableProfile(profile);
        if (string.IsNullOrWhiteSpace(configPath) || !Path.IsPathFullyQualified(configPath))
        {
            throw new LauncherValidationException("Stable upgrade requires an absolute launcher config path.");
        }

        var config = LauncherConfig.Load(configPath);
        ProfileValidator.AssertStableProductionTuple(config, profile);
        var current = ProveCurrentRelease(profile);
        var published = ReadPublishedReleases(releaseHandler);
        var publishedTarget = published.SingleOrDefault(
            release => release.Tag.Equals(target.Tag, StringComparison.Ordinal));
        if (publishedTarget is null
            || !publishedTarget.Version.Equals(target.Version, StringComparison.Ordinal))
        {
            throw new LauncherValidationException("Stable upgrade target is no longer a published non-prerelease release.");
        }

        var remoteTarget = ProveRemoteRelease(
            profile.Checkout,
            publishedTarget.Tag,
            publishedTarget.VersionValue,
            publishedTarget.ReleaseUrl);
        if (!remoteTarget.CommitSha.Equals(target.CommitSha, StringComparison.OrdinalIgnoreCase)
            || !remoteTarget.TagObjectSha.Equals(target.TagObjectSha, StringComparison.OrdinalIgnoreCase))
        {
            throw new LauncherValidationException("Stable upgrade target identity changed; the immutable tag proof no longer matches.");
        }

        // This is a read-only proof. It must finish before the snapshot and
        // backup so a tracked current/target path, reparse traversal, or file
        // alias can never be discovered after the first mutation.
        EnsureProductionDataIsSafeForSwitch(profile, remoteTarget, releaseHandler);
        AssertStableConfigTuple(configPath, profile);
        var productionSnapshot = ProductionDataSnapshot.Capture(profile);
        // This is the first mutating operation. The backup is created before
        // any tag fetch, checkout change, dependency preparation, or config
        // write. The helper uses SQLite's online backup API and the same
        // finance_backup_*.sqlite3 contract as the backend service.
        var backup = CreateProductionBackup(profile);

        RunGit(
            profile.Checkout,
            "fetch",
            "--no-tags",
            "origin",
            $"{remoteTarget.Ref}:{remoteTarget.Ref}");

        AssertFetchedTarget(profile.Checkout, remoteTarget);
        var targetSource = ReadGitFile(profile.Checkout, $"{remoteTarget.Ref}:backend/src/hermes_finance/__init__.py");
        var targetApplicationVersion = ProfileValidator.ParseApplicationVersion(targetSource);
        if (targetApplicationVersion is null)
        {
            throw new LauncherValidationException("Stable upgrade target backend version cannot be proven.");
        }
        if (!targetApplicationVersion.Equals(remoteTarget.Version, StringComparison.Ordinal))
        {
            throw new LauncherValidationException("Stable upgrade target backend version does not match its release tag.");
        }

        AssertClean(profile.Checkout);
        RunGit(profile.Checkout, "switch", "--detach", remoteTarget.Ref);
        AssertClean(profile.Checkout);
        var updatedHead = ReadRequiredRef(profile.Checkout, "HEAD");
        if (!updatedHead.Equals(remoteTarget.CommitSha, StringComparison.OrdinalIgnoreCase))
        {
            throw new LauncherValidationException("Stable checkout did not reach the proven immutable release tag.");
        }
        var checkedOutVersion = ProfileValidator.ReadApplicationVersion(profile.Checkout);
        if (!remoteTarget.Version.Equals(checkedOutVersion, StringComparison.Ordinal))
        {
            throw new LauncherValidationException("Stable backend version and checked-out release identity do not match.");
        }

        // Detect a concurrent data mutation before changing the config. The
        // launcher never attempts a rollback of a checkout after a data race;
        // it fails closed and leaves the owner an explicit recovery signal.
        productionSnapshot.AssertUnchanged(profile);
        var updatedConfig = LauncherConfig.UpdateStableExpectedRef(configPath, remoteTarget.Ref, profile);
        productionSnapshot.AssertUnchanged(profile);

        return new StableUpgradeResult(current, remoteTarget, backup.Id, updatedConfig);
    }

    internal static ProcessStartInfo BuildBackupCommand(ValidatedProfile profile)
    {
        EnsureStableProfile(profile);
        var script = ResolveBundledBackupScript();
        var runner = ResolveBackupRunner(profile.Checkout);
        var command = new ProcessStartInfo
        {
            FileName = runner.FileName,
            WorkingDirectory = profile.Checkout,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        command.Environment["PYTHONNOUSERSITE"] = "1";
        foreach (var argument in runner.PrefixArguments)
        {
            command.ArgumentList.Add(argument);
        }
        command.ArgumentList.Add(script);
        command.ArgumentList.Add("--database");
        command.ArgumentList.Add(profile.Database);
        command.ArgumentList.Add("--backup-dir");
        command.ArgumentList.Add(GetBackupDirectory(profile));
        return command;
    }

    private static StableBackupMetadata CreateProductionBackup(ValidatedProfile profile)
    {
        var backupDirectory = GetBackupDirectory(profile);
        if (!IsWithin(backupDirectory, profile.DataDir))
        {
            throw new LauncherValidationException("Stable backup directory must remain inside canonical production data.");
        }
        if (Directory.Exists(backupDirectory) && IsReparsePoint(backupDirectory))
        {
            throw new LauncherValidationException("Stable backup directory is a reparse point; backup is blocked.");
        }

        ProcessOutput output;
        try
        {
            output = RunProcess(BuildBackupCommand(profile), "production backup");
        }
        catch (Win32Exception exception)
        {
            throw new LauncherValidationException($"Production backup cannot start: {exception.Message}");
        }
        if (output.ExitCode != 0)
        {
            throw new LauncherValidationException(
                $"Production backup failed: {OneLine(output.StandardError, output.StandardOutput)}");
        }

        JsonDocument document;
        try
        {
            document = JsonDocument.Parse(output.StandardOutput);
        }
        catch (JsonException exception)
        {
            throw new LauncherValidationException($"Production backup returned invalid proof: {exception.Message}");
        }

        using (document)
        {
            var root = document.RootElement;
            if (!root.TryGetProperty("status", out var status)
                || status.ValueKind != JsonValueKind.String
                || !status.GetString()!.Equals("ok", StringComparison.Ordinal))
            {
                throw new LauncherValidationException("Production backup did not return a successful proof.");
            }
            var id = ReadJsonString(root, "backup_id");
            var name = ReadJsonString(root, "backup_name");
            if (!BackupFilenameRegex.IsMatch(name)
                || !id.Equals(Path.GetFileNameWithoutExtension(name), StringComparison.Ordinal))
            {
                throw new LauncherValidationException("Production backup returned an unsafe backup identity.");
            }

            var backupPath = Path.Combine(backupDirectory, name);
            if (!SamePath(Path.GetDirectoryName(backupPath)!, backupDirectory)
                || !File.Exists(backupPath)
                || new FileInfo(backupPath).Length <= 0
                || new FileInfo(backupPath).LinkTarget is not null)
            {
                throw new LauncherValidationException("Production backup could not be verified in the configured backup directory.");
            }
            return new StableBackupMetadata(id, name);
        }
    }

    private static StableReleaseIdentity ProveCurrentRelease(ValidatedProfile profile)
    {
        if (!TryParseReleaseRef(profile.Profile.ExpectedRef, out var tag, out var version))
        {
            throw new LauncherValidationException(
                "Stable current identity is not an immutable vX.Y.Z release tag; upgrade is blocked.");
        }

        var expectedRef = $"refs/tags/{tag}";
        var tagType = RunGit(profile.Checkout, "cat-file", "-t", expectedRef);
        if (!tagType.Equals("tag", StringComparison.Ordinal))
        {
            throw new LauncherValidationException("Stable current release tag is not annotated; upgrade is blocked.");
        }

        var head = ReadRequiredRef(profile.Checkout, "HEAD");
        var localCommit = ReadRequiredRef(profile.Checkout, expectedRef + "^{commit}");
        if (!head.Equals(localCommit, StringComparison.OrdinalIgnoreCase)
            || !head.Equals(profile.Head, StringComparison.OrdinalIgnoreCase))
        {
            throw new LauncherValidationException("Stable checkout identity changed; upgrade is blocked.");
        }

        var remote = ReadRemoteTag(profile.Checkout, tag);
        if (!remote.CommitSha.Equals(head, StringComparison.OrdinalIgnoreCase))
        {
            throw new LauncherValidationException("Stable current release tag does not prove the configured checkout commit.");
        }
        return new StableReleaseIdentity(tag, version.Text, head, remote.TagObjectSha, null);
    }

    private static StableReleaseIdentity ProveRemoteRelease(
        string checkout,
        string tag,
        StableVersion version,
        string? releaseUrl)
    {
        if (!TryParseReleaseTag(tag, out var parsed) || parsed.CompareTo(version) != 0)
        {
            throw new LauncherValidationException("Stable upgrade target is not a strict vX.Y.Z release tag.");
        }
        var remote = ReadRemoteTag(checkout, tag);
        return new StableReleaseIdentity(tag, version.Text, remote.CommitSha, remote.TagObjectSha, releaseUrl);
    }

    private static void AssertFetchedTarget(string checkout, StableReleaseIdentity target)
    {
        var tagType = RunGit(checkout, "cat-file", "-t", target.Ref);
        if (!tagType.Equals("tag", StringComparison.Ordinal))
        {
            throw new LauncherValidationException("Fetched Stable target is not an annotated tag.");
        }
        var tagObject = ReadRequiredRef(checkout, target.Ref);
        if (!tagObject.Equals(target.TagObjectSha, StringComparison.OrdinalIgnoreCase))
        {
            throw new LauncherValidationException("Fetched Stable target tag object does not match the published immutable tag proof.");
        }
        var commit = ReadRequiredRef(checkout, target.Ref + "^{commit}");
        if (!commit.Equals(target.CommitSha, StringComparison.OrdinalIgnoreCase))
        {
            throw new LauncherValidationException("Fetched Stable target tag does not peel to the published commit.");
        }
    }

    private static RemoteTagProof ReadRemoteTag(string checkout, string tag)
    {
        var rawRef = $"refs/tags/{tag}";
        var peeledRef = rawRef + "^{}";
        var output = RunGit(checkout, "ls-remote", "--tags", "origin", rawRef, peeledRef);
        string? tagObject = null;
        string? commit = null;
        foreach (var line in output.Split('\n', StringSplitOptions.RemoveEmptyEntries))
        {
            var parts = line.Trim().Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length < 2 || !IsSha(parts[0]))
            {
                continue;
            }
            if (parts[1].Equals(rawRef, StringComparison.Ordinal))
            {
                tagObject = parts[0];
            }
            else if (parts[1].Equals(peeledRef, StringComparison.Ordinal))
            {
                commit = parts[0];
            }
        }
        if (tagObject is null || commit is null)
        {
            throw new LauncherValidationException("Stable release tag is not proven as an immutable annotated remote tag.");
        }
        return new RemoteTagProof(tagObject, commit);
    }

    private static IReadOnlyList<PublishedRelease> ReadPublishedReleases(HttpMessageHandler? releaseHandler)
    {
        using var client = releaseHandler is null
            ? new HttpClient()
            : new HttpClient(releaseHandler, disposeHandler: false);
        client.Timeout = TimeSpan.FromSeconds(15);
        client.DefaultRequestHeaders.UserAgent.ParseAdd("HermesFinance.Launcher/1.0");
        client.DefaultRequestHeaders.Accept.ParseAdd("application/vnd.github+json");
        client.DefaultRequestHeaders.TryAddWithoutValidation("X-GitHub-Api-Version", "2022-11-28");

        string responseBody;
        try
        {
            using var response = client.GetAsync(ReleasesEndpoint).GetAwaiter().GetResult();
            if (!response.IsSuccessStatusCode)
            {
                throw new LauncherValidationException(
                    $"Published Stable release discovery failed: public GitHub API returned HTTP {(int)response.StatusCode}.");
            }
            responseBody = response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
        }
        catch (LauncherValidationException)
        {
            throw;
        }
        catch (TaskCanceledException)
        {
            throw new LauncherValidationException(
                "Published Stable release discovery failed: public GitHub API request timed out.");
        }
        catch (HttpRequestException exception)
        {
            throw new LauncherValidationException(
                $"Published Stable release discovery failed: {OneLine(exception.Message, "public GitHub API unavailable")}");
        }
        catch (IOException exception)
        {
            throw new LauncherValidationException(
                $"Published Stable release discovery failed: {OneLine(exception.Message, "public GitHub API unavailable")}");
        }

        try
        {
            using var document = JsonDocument.Parse(responseBody);
            if (document.RootElement.ValueKind != JsonValueKind.Array)
            {
                throw new LauncherValidationException("Published Stable release discovery returned a non-array result.");
            }

            var releases = new Dictionary<string, PublishedRelease>(StringComparer.Ordinal);
            foreach (var item in document.RootElement.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.Object
                    || !item.TryGetProperty("tag_name", out var tagProperty)
                    || tagProperty.ValueKind != JsonValueKind.String)
                {
                    continue;
                }
                var tag = tagProperty.GetString();
                if (!TryParseReleaseTag(tag, out var version))
                {
                    continue;
                }
                if (!IsFalseBoolean(item, "draft") || !IsFalseBoolean(item, "prerelease"))
                {
                    continue;
                }
                if (!item.TryGetProperty("published_at", out var publishedAt)
                    || publishedAt.ValueKind != JsonValueKind.String
                    || string.IsNullOrWhiteSpace(publishedAt.GetString()))
                {
                    continue;
                }
                var url = item.TryGetProperty("html_url", out var urlProperty)
                    && urlProperty.ValueKind == JsonValueKind.String
                    ? urlProperty.GetString()
                    : null;
                releases[tag!] = new PublishedRelease(tag!, version, url);
            }
            return releases.Values.ToArray();
        }
        catch (JsonException exception)
        {
            throw new LauncherValidationException($"Published Stable release discovery returned invalid JSON: {exception.Message}");
        }
    }

    private static bool IsFalseBoolean(JsonElement item, string name)
    {
        return item.TryGetProperty(name, out var property)
            && property.ValueKind == JsonValueKind.False;
    }

    private static string ReadJsonString(JsonElement root, string propertyName)
    {
        if (!root.TryGetProperty(propertyName, out var property)
            || property.ValueKind != JsonValueKind.String
            || string.IsNullOrWhiteSpace(property.GetString()))
        {
            throw new LauncherValidationException($"Production backup proof is missing '{propertyName}'.");
        }
        return property.GetString()!;
    }

    private static void EnsureStableProfile(ValidatedProfile profile)
    {
        if (!profile.Profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase))
        {
            throw new LauncherValidationException("Only the configured Stable profile may use the Stable release upgrade.");
        }
        if (string.IsNullOrWhiteSpace(profile.Checkout)
            || string.IsNullOrWhiteSpace(profile.DataDir)
            || string.IsNullOrWhiteSpace(profile.Database))
        {
            throw new LauncherValidationException("Stable upgrade requires a fully validated production profile tuple.");
        }
        AssertClean(profile.Checkout);
    }

    private static void EnsureProductionDataIsSafeForSwitch(
        ValidatedProfile profile,
        StableReleaseIdentity target,
        HttpMessageHandler? releaseHandler)
    {
        if (!File.Exists(profile.Database))
        {
            throw new LauncherValidationException("Stable production database is missing; the required backup cannot be created.");
        }

        // Validate both the raw configured paths and the resolved paths. The
        // former catches a reparse-point alias that ProfileValidator resolved
        // before it produced the ValidatedProfile; the latter protects this
        // operation if a path changed between validation and the upgrade.
        AssertNoReparseTraversal(profile.Profile.Checkout, "Stable checkout");
        AssertNoReparseTraversal(profile.Profile.DataDir, "Stable production data_dir");
        AssertNoReparseTraversal(profile.Profile.Database, "Stable production database");
        AssertNoReparseTraversal(profile.Checkout, "Stable checkout");
        AssertNoReparseTraversal(profile.DataDir, "Stable production data_dir");
        AssertNoReparseTraversal(profile.Database, "Stable production database");

        var backupDirectory = GetBackupDirectory(profile);
        AssertNoReparseTraversal(backupDirectory, "Stable production backup directory", allowMissingLeaf: true);
        AssertProductionDataDoesNotOverlapGitMetadata(profile);

        var layout = ProductionGitLayout.Create(profile, backupDirectory);
        var currentTree = ReadTrackedGitTree(profile.Checkout, "HEAD");
        AssertTrackedPathsDoNotCollide("current Stable release", currentTree, layout);
        AssertTrackedPathAncestorsHaveNoReparsePoints(
            profile.Checkout,
            currentTree,
            "current Stable release",
            requireLeaf: true);

        // Read the exact target tree before the first mutation even when the
        // data directory is external: an ignored target-only checkout path
        // can still be a hardlink/reparse alias to production data.
        var targetTree = ReadTargetGitTree(target.CommitSha, releaseHandler);
        AssertTrackedPathsDoNotCollide("target Stable release", targetTree, layout);
        AssertTrackedPathAncestorsHaveNoReparsePoints(
            profile.Checkout,
            targetTree,
            "target Stable release",
            requireLeaf: false);
        AssertNoProductionFileAliases(profile, currentTree, targetTree);
    }

    private static void AssertNoReparseTraversal(string path, string description, bool allowMissingLeaf = false)
    {
        if (string.IsNullOrWhiteSpace(path) || !Path.IsPathFullyQualified(path))
        {
            throw new LauncherValidationException($"{description} path cannot be proven safe for Stable upgrade.");
        }

        var fullPath = Path.GetFullPath(path);
        var root = Path.GetPathRoot(fullPath);
        if (string.IsNullOrWhiteSpace(root))
        {
            throw new LauncherValidationException($"{description} path cannot be proven safe for Stable upgrade.");
        }

        var current = root;
        foreach (var component in fullPath[root.Length..].Split(
            [Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar],
            StringSplitOptions.RemoveEmptyEntries))
        {
            current = Path.Combine(current, component);
            var exists = File.Exists(current) || Directory.Exists(current);
            if (!exists)
            {
                if (allowMissingLeaf && SamePath(current, fullPath))
                {
                    return;
                }
                throw new LauncherValidationException(
                    $"{description} path cannot be proven safe for Stable upgrade because it is missing.");
            }

            try
            {
                if (IsReparsePoint(current))
                {
                    throw new LauncherValidationException(
                        $"{description} path uses a symlink, junction, or reparse point; Stable upgrade is blocked.");
                }
            }
            catch (LauncherValidationException)
            {
                throw;
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
            {
                throw new LauncherValidationException(
                    $"{description} path cannot be proven safe for Stable upgrade: {exception.Message}");
            }
        }
    }

    private static void AssertTrackedPathsDoNotCollide(
        string treeDescription,
        IReadOnlyList<GitTreeEntry> tree,
        ProductionGitLayout layout)
    {
        foreach (var entry in tree)
        {
            if (entry.Mode.Equals("120000", StringComparison.Ordinal))
            {
                throw new LauncherValidationException(
                    $"{treeDescription} contains a tracked symlink; production data safety cannot be proven before upgrade.");
            }

            if (layout.RelativeDatabase is not null
                && SameGitPath(entry.Path, layout.RelativeDatabase))
            {
                throw new LauncherValidationException(
                    $"{treeDescription} tracks the canonical production database path; upgrade is blocked before backup.");
            }
            if (layout.RelativeIdentity is not null
                && SameGitPath(entry.Path, layout.RelativeIdentity))
            {
                throw new LauncherValidationException(
                    $"{treeDescription} tracks the canonical production data identity; upgrade is blocked before backup.");
            }
            if (layout.RelativeBackupDirectory is not null
                && IsGitPathWithin(entry.Path, layout.RelativeBackupDirectory))
            {
                throw new LauncherValidationException(
                    $"{treeDescription} tracks the canonical production backup path; upgrade is blocked before backup.");
            }
            if (layout.RelativeDataDir is not null
                && IsGitPathWithin(entry.Path, layout.RelativeDataDir))
            {
                throw new LauncherValidationException(
                    $"{treeDescription} tracks a path under the canonical production data directory; upgrade is blocked before backup.");
            }
        }
    }

    private static void AssertTrackedPathAncestorsHaveNoReparsePoints(
        string checkout,
        IReadOnlyList<GitTreeEntry> tree,
        string treeDescription,
        bool requireLeaf)
    {
        foreach (var entry in tree)
        {
            var fullPath = GetCheckoutPath(checkout, entry.Path);
            var root = Path.GetPathRoot(fullPath);
            if (string.IsNullOrWhiteSpace(root))
            {
                throw new LauncherValidationException(
                    $"{treeDescription} path safety cannot be proven before upgrade.");
            }

            var current = root;
            var missing = false;
            foreach (var component in fullPath[root.Length..].Split(
                [Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar],
                StringSplitOptions.RemoveEmptyEntries))
            {
                current = Path.Combine(current, component);
                if (!File.Exists(current) && !Directory.Exists(current))
                {
                    missing = true;
                    break;
                }

                try
                {
                    if (IsReparsePoint(current))
                    {
                        throw new LauncherValidationException(
                            $"{treeDescription} tracked path uses a symlink, junction, or reparse point; upgrade is blocked before backup.");
                    }
                }
                catch (LauncherValidationException)
                {
                    throw;
                }
                catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
                {
                    throw new LauncherValidationException(
                        $"{treeDescription} path safety cannot be proven before upgrade: {exception.Message}");
                }
            }

            if (requireLeaf && missing)
            {
                throw new LauncherValidationException(
                    $"{treeDescription} tracked path is missing; upgrade is blocked before backup.");
            }
        }
    }

    private static void AssertProductionDataDoesNotOverlapGitMetadata(ValidatedProfile profile)
    {
        if (IsWithin(profile.Checkout, profile.DataDir) && !SamePath(profile.Checkout, profile.DataDir))
        {
            throw new LauncherValidationException(
                "Stable production data contains the mutable checkout; upgrade is blocked before backup.");
        }

        var gitDirectory = ResolveGitDirectoryPath(profile.Checkout, "--git-dir");
        var commonDirectory = ResolveGitDirectoryPath(profile.Checkout, "--git-common-dir");
        if (PathsOverlap(profile.DataDir, gitDirectory)
            || PathsOverlap(profile.DataDir, commonDirectory))
        {
            throw new LauncherValidationException(
                "Stable production data overlaps Git metadata; upgrade is blocked before backup.");
        }
    }

    private static void AssertStableConfigTuple(string configPath, ValidatedProfile profile)
    {
        try
        {
            ProfileValidator.AssertStableProductionTuple(LauncherConfig.Load(configPath), profile);
        }
        catch (LauncherValidationException)
        {
            throw;
        }
        catch (IOException exception)
        {
            throw new LauncherValidationException(
                $"Stable canonical production identity cannot be re-proven before upgrade: {exception.Message}");
        }
    }

    private static string ResolveGitDirectoryPath(string checkout, string option)
    {
        var value = RunGit(checkout, "rev-parse", option).Trim();
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new LauncherValidationException(
                "Stable Git metadata boundary cannot be proven before upgrade.");
        }
        return Path.GetFullPath(Path.IsPathFullyQualified(value) ? value : Path.Combine(checkout, value));
    }

    private static void AssertNoProductionFileAliases(
        ValidatedProfile profile,
        IReadOnlyList<GitTreeEntry> currentTree,
        IReadOnlyList<GitTreeEntry> targetTree)
    {
        if (!OperatingSystem.IsWindows())
        {
            throw new LauncherValidationException(
                "Stable production file identity cannot be proven outside Windows; upgrade is blocked.");
        }

        IReadOnlyList<string> productionFiles;
        try
        {
            productionFiles = EnumerateProductionFiles(profile.DataDir);
        }
        catch (LauncherValidationException)
        {
            throw;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            throw new LauncherValidationException(
                $"Stable production data cannot be fully inspected before upgrade: {exception.Message}");
        }

        var checkoutPaths = currentTree
            .Concat(targetTree)
            .SelectMany(entry => ExistingCheckoutPathPrefixes(profile.Checkout, entry.Path))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Where(path => File.Exists(path) || Directory.Exists(path))
            .ToArray();
        foreach (var checkoutPath in checkoutPaths)
        {
            try
            {
                if (IsReparsePoint(checkoutPath))
                {
                    throw new LauncherValidationException(
                        "Stable checkout contains a target path with a symlink, junction, or reparse alias; upgrade is blocked before backup.");
                }
            }
            catch (LauncherValidationException)
            {
                throw;
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
            {
                throw new LauncherValidationException(
                    $"Stable checkout target path safety cannot be proven before upgrade: {exception.Message}");
            }
        }

        var trackedFiles = checkoutPaths
            .Where(File.Exists)
            .ToArray();
        foreach (var productionFile in productionFiles)
        {
            foreach (var trackedFile in trackedFiles)
            {
                try
                {
                    if (ProfileValidator.SameFileIdentity(productionFile, trackedFile))
                    {
                        throw new LauncherValidationException(
                            "Stable production data aliases a tracked release file; upgrade is blocked before backup.");
                    }
                }
                catch (LauncherValidationException)
                {
                    throw;
                }
                catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
                {
                    throw new LauncherValidationException(
                        $"Stable production file identity cannot be proven before upgrade: {exception.Message}");
                }
            }
        }
    }

    private static IEnumerable<string> ExistingCheckoutPathPrefixes(string checkout, string gitPath)
    {
        var checkoutFull = Path.GetFullPath(checkout);
        var fullPath = GetCheckoutPath(checkoutFull, gitPath);
        var relative = Path.GetRelativePath(checkoutFull, fullPath)
            .Replace(Path.DirectorySeparatorChar, '/');
        var current = checkoutFull;
        foreach (var component in relative.Split('/', StringSplitOptions.RemoveEmptyEntries))
        {
            current = Path.Combine(current, component);
            if (!File.Exists(current) && !Directory.Exists(current))
            {
                yield break;
            }
            yield return current;
        }
    }

    private static IReadOnlyList<string> EnumerateProductionFiles(string dataDir)
    {
        var files = new List<string>();
        VisitProductionDirectory(new DirectoryInfo(dataDir), files);
        return files;
    }

    private static void VisitProductionDirectory(DirectoryInfo directory, ICollection<string> files)
    {
        if (IsReparsePoint(directory.FullName))
        {
            throw new LauncherValidationException(
                "Stable production data contains a symlink, junction, or reparse point; upgrade is blocked.");
        }

        foreach (var entry in directory.EnumerateFileSystemInfos("*", SearchOption.TopDirectoryOnly))
        {
            if (IsReparsePoint(entry.FullName))
            {
                throw new LauncherValidationException(
                    "Stable production data contains a symlink, junction, or reparse point; upgrade is blocked.");
            }
            if (entry is DirectoryInfo childDirectory)
            {
                VisitProductionDirectory(childDirectory, files);
            }
            else
            {
                files.Add(entry.FullName);
            }
        }
    }

    private static IReadOnlyList<GitTreeEntry> ReadTrackedGitTree(string checkout, string reference)
    {
        var output = RunGit(checkout, "ls-tree", "--full-tree", "-r", "-z", reference);
        var entries = new List<GitTreeEntry>();
        foreach (var item in output.Split('\0', StringSplitOptions.RemoveEmptyEntries))
        {
            var separator = item.IndexOf('\t');
            if (separator <= 0)
            {
                throw new LauncherValidationException(
                    "Current Stable release tree returned an invalid Git path; production data safety cannot be proven.");
            }
            var metadata = item[..separator].Split(' ', StringSplitOptions.RemoveEmptyEntries);
            if (metadata.Length != 3)
            {
                throw new LauncherValidationException(
                    "Current Stable release tree returned an invalid Git entry; production data safety cannot be proven.");
            }
            entries.Add(new GitTreeEntry(
                NormalizeGitPath(item[(separator + 1)..]),
                metadata[0],
                metadata[1]));
        }
        return entries;
    }

    private static IReadOnlyList<GitTreeEntry> ReadTargetGitTree(
        string commitSha,
        HttpMessageHandler? releaseHandler)
    {
        if (!IsSha(commitSha))
        {
            throw new LauncherValidationException(
                "Stable target commit identity is invalid; target Git tree safety cannot be proven.");
        }

        var endpoint = GitTreeEndpoint + commitSha + "?recursive=1";
        using var client = CreateGitHubClient(releaseHandler);
        string responseBody;
        try
        {
            using var response = client.GetAsync(endpoint).GetAwaiter().GetResult();
            if (!response.IsSuccessStatusCode)
            {
                throw new LauncherValidationException(
                    $"Stable target Git tree proof failed: public GitHub API returned HTTP {(int)response.StatusCode}.");
            }
            responseBody = response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
        }
        catch (LauncherValidationException)
        {
            throw;
        }
        catch (TaskCanceledException)
        {
            throw new LauncherValidationException(
                "Stable target Git tree proof failed: public GitHub API request timed out.");
        }
        catch (HttpRequestException exception)
        {
            throw new LauncherValidationException(
                $"Stable target Git tree proof failed: {OneLine(exception.Message, "public GitHub API unavailable")}");
        }
        catch (IOException exception)
        {
            throw new LauncherValidationException(
                $"Stable target Git tree proof failed: {OneLine(exception.Message, "public GitHub API unavailable")}");
        }

        try
        {
            using var document = JsonDocument.Parse(responseBody);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object
                || !root.TryGetProperty("truncated", out var truncated)
                || truncated.ValueKind != JsonValueKind.False
                || !root.TryGetProperty("tree", out var tree)
                || tree.ValueKind != JsonValueKind.Array)
            {
                throw new LauncherValidationException(
                    "Stable target Git tree proof returned an incomplete or truncated result.");
            }

            var entries = new List<GitTreeEntry>();
            foreach (var item in tree.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.Object
                    || !item.TryGetProperty("path", out var path)
                    || path.ValueKind != JsonValueKind.String
                    || !item.TryGetProperty("mode", out var mode)
                    || mode.ValueKind != JsonValueKind.String
                    || !item.TryGetProperty("type", out var type)
                    || type.ValueKind != JsonValueKind.String)
                {
                    throw new LauncherValidationException(
                        "Stable target Git tree proof returned an invalid entry.");
                }
                entries.Add(new GitTreeEntry(
                    NormalizeGitPath(path.GetString()!),
                    mode.GetString()!,
                    type.GetString()!));
            }
            return entries;
        }
        catch (JsonException exception)
        {
            throw new LauncherValidationException(
                $"Stable target Git tree proof returned invalid JSON: {exception.Message}");
        }
    }

    private static HttpClient CreateGitHubClient(HttpMessageHandler? releaseHandler)
    {
        var client = releaseHandler is null
            ? new HttpClient()
            : new HttpClient(releaseHandler, disposeHandler: false);
        client.Timeout = TimeSpan.FromSeconds(15);
        client.DefaultRequestHeaders.UserAgent.ParseAdd("HermesFinance.Launcher/1.0");
        client.DefaultRequestHeaders.Accept.ParseAdd("application/vnd.github+json");
        client.DefaultRequestHeaders.TryAddWithoutValidation("X-GitHub-Api-Version", "2022-11-28");
        return client;
    }

    private static string GetCheckoutPath(string checkout, string gitPath)
    {
        var relative = gitPath.Replace('/', Path.DirectorySeparatorChar);
        var path = Path.GetFullPath(Path.Combine(checkout, relative));
        if (!IsWithin(path, checkout))
        {
            throw new LauncherValidationException(
                "A tracked Git path escapes the Stable checkout; production data safety cannot be proven.");
        }
        return path;
    }

    private static string NormalizeGitPath(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || path.Contains('\\'))
        {
            throw new LauncherValidationException(
                "A tracked Git path is not a safe relative path; production data safety cannot be proven.");
        }
        var components = path.Split('/', StringSplitOptions.None);
        if (components.Any(component => string.IsNullOrEmpty(component) || component is "." or ".."))
        {
            throw new LauncherValidationException(
                "A tracked Git path is not a normalized relative path; production data safety cannot be proven.");
        }
        return string.Join('/', components);
    }

    private static string? ToGitRelativePath(string checkout, string path)
    {
        var checkoutFull = Path.GetFullPath(checkout);
        var pathFull = Path.GetFullPath(path);
        if (!IsWithin(pathFull, checkoutFull))
        {
            return null;
        }
        var relative = Path.GetRelativePath(checkoutFull, pathFull);
        return relative == "." ? "" : NormalizeGitPath(relative.Replace(Path.DirectorySeparatorChar, '/'));
    }

    private static bool SameGitPath(string left, string right) =>
        string.Equals(left, right, StringComparison.OrdinalIgnoreCase);

    private static bool IsGitPathWithin(string path, string parent) =>
        string.IsNullOrEmpty(parent)
        || SameGitPath(path, parent)
        || path.StartsWith(parent + "/", StringComparison.OrdinalIgnoreCase);

    private static bool IsReparsePoint(string path) =>
        (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0;

    private static void AssertClean(string checkout)
    {
        var status = RunGit(checkout, "status", "--porcelain=v1", "--untracked-files=all");
        if (!string.IsNullOrWhiteSpace(status) || RunGit(checkout, "ls-files", "-u").Length > 0)
        {
            throw new LauncherValidationException("Stable checkout is dirty or conflicted; upgrade is blocked.");
        }
    }

    private static string ReadRequiredRef(string checkout, string reference) =>
        RunGit(checkout, "rev-parse", "--verify", reference);

    private static string ReadGitFile(string checkout, string objectPath) =>
        RunGit(checkout, "show", objectPath);

    private static string RunGit(string checkout, params string[] arguments)
    {
        try
        {
            var output = RunProcess(
                "git",
                checkout,
                arguments,
                environment: new Dictionary<string, string> { ["GIT_TERMINAL_PROMPT"] = "0" },
                operation: "Stable release operation");
            if (output.ExitCode != 0)
            {
                throw new LauncherValidationException(
                    $"Stable release Git operation failed ({string.Join(" ", arguments)}): {OneLine(output.StandardError, output.StandardOutput)}");
            }
            return output.StandardOutput.Trim();
        }
        catch (Win32Exception exception)
        {
            throw new LauncherValidationException($"Stable release operation cannot run Git: {exception.Message}");
        }
    }

    private static ProcessOutput RunProcess(
        string fileName,
        string workingDirectory,
        string[] arguments,
        IReadOnlyDictionary<string, string>? environment,
        string operation)
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
        if (environment is not null)
        {
            foreach (var pair in environment)
            {
                startInfo.Environment[pair.Key] = pair.Value;
            }
        }

        var process = Process.Start(startInfo)
            ?? throw new LauncherValidationException($"Could not start {operation}.");
        using (process)
        {
            var stdoutTask = process.StandardOutput.ReadToEndAsync();
            var stderrTask = process.StandardError.ReadToEndAsync();
            process.WaitForExit();
            return new ProcessOutput(
                process.ExitCode,
                stdoutTask.GetAwaiter().GetResult(),
                stderrTask.GetAwaiter().GetResult());
        }
    }

    private static ProcessOutput RunProcess(ProcessStartInfo startInfo, string operation)
    {
        var process = Process.Start(startInfo)
            ?? throw new LauncherValidationException($"Could not start {operation}.");
        using (process)
        {
            var stdoutTask = process.StandardOutput.ReadToEndAsync();
            var stderrTask = process.StandardError.ReadToEndAsync();
            process.WaitForExit();
            return new ProcessOutput(
                process.ExitCode,
                stdoutTask.GetAwaiter().GetResult(),
                stderrTask.GetAwaiter().GetResult());
        }
    }

    private static BackupRunner ResolveBackupRunner(string checkout)
    {
        foreach (var command in new[] { "python", "py" })
        {
            try
            {
                return new BackupRunner(DependencyValidator.ResolveCommand(command, checkout), []);
            }
            catch (LauncherValidationException)
            {
                // Try the Windows Python launcher after python.exe. Both are
                // read-only command resolution steps; failure remains closed.
            }
        }
        try
        {
            // uv is already a launcher preflight dependency. The helper is
            // stdlib-only, so use uv's managed Python without resolving or
            // installing the checkout's application dependencies here.
            return new BackupRunner(
                DependencyValidator.ResolveCommand("uv", checkout),
                ["run", "--no-project", "--offline", "python"]);
        }
        catch (LauncherValidationException)
        {
            throw new LauncherValidationException("Production backup requires Python with the standard sqlite3 module or an offline uv-managed Python.");
        }
    }

    private static string ResolveBundledBackupScript()
    {
        var script = Path.Combine(AppContext.BaseDirectory, BackupScriptName);
        if (File.Exists(script))
        {
            return script;
        }
        throw new LauncherValidationException("Production backup is unavailable: bundled backup helper is missing.");
    }

    private static bool TryParseReleaseRef(string? expectedRef, out string tag, out StableVersion version)
    {
        tag = "";
        version = default;
        if (string.IsNullOrWhiteSpace(expectedRef))
        {
            return false;
        }
        var value = expectedRef.Trim();
        if (value.StartsWith("refs/tags/", StringComparison.Ordinal))
        {
            value = value["refs/tags/".Length..];
        }
        if (!TryParseReleaseTag(value, out version))
        {
            return false;
        }
        tag = value;
        return true;
    }

    private static bool TryParseReleaseTag(string? tag, out StableVersion version)
    {
        version = default;
        if (string.IsNullOrWhiteSpace(tag))
        {
            return false;
        }
        var match = ReleaseTagPattern.Match(tag);
        if (!match.Success
            || !int.TryParse(match.Groups["major"].Value, NumberStyles.None, CultureInfo.InvariantCulture, out var major)
            || !int.TryParse(match.Groups["minor"].Value, NumberStyles.None, CultureInfo.InvariantCulture, out var minor)
            || !int.TryParse(match.Groups["patch"].Value, NumberStyles.None, CultureInfo.InvariantCulture, out var patch))
        {
            return false;
        }
        version = new StableVersion(major, minor, patch, $"{major}.{minor}.{patch}");
        return true;
    }

    private static bool IsSha(string value) => ShaPattern.IsMatch(value);

    private static bool SamePath(string left, string right) =>
        string.Equals(
            Path.TrimEndingDirectorySeparator(Path.GetFullPath(left)),
            Path.TrimEndingDirectorySeparator(Path.GetFullPath(right)),
            StringComparison.OrdinalIgnoreCase);

    private static string GetBackupDirectory(ValidatedProfile profile)
    {
        var databaseDirectory = Path.GetDirectoryName(profile.Database);
        if (string.IsNullOrWhiteSpace(databaseDirectory))
        {
            throw new LauncherValidationException("Stable production backup directory cannot be resolved safely.");
        }
        return Path.GetFullPath(Path.Combine(databaseDirectory, BackupDirectoryName));
    }

    private static bool IsWithin(string candidate, string parent) =>
        SamePath(candidate, parent)
        || Path.GetFullPath(candidate).StartsWith(
            Path.TrimEndingDirectorySeparator(Path.GetFullPath(parent)) + Path.DirectorySeparatorChar,
            StringComparison.OrdinalIgnoreCase);

    private static bool PathsOverlap(string left, string right) =>
        SamePath(left, right) || IsWithin(left, right) || IsWithin(right, left);

    private static string OneLine(string preferred, string fallback)
    {
        var value = string.IsNullOrWhiteSpace(preferred) ? fallback : preferred;
        return value.ReplaceLineEndings(" ").Trim();
    }

    private sealed record PublishedRelease(string Tag, StableVersion VersionValue, string? ReleaseUrl)
    {
        public string Version => VersionValue.Text;
    }

    private sealed record GitTreeEntry(string Path, string Mode, string Type);

    private sealed record ProductionGitLayout(
        string? RelativeDataDir,
        string? RelativeDatabase,
        string? RelativeIdentity,
        string? RelativeBackupDirectory)
    {
        public static ProductionGitLayout Create(ValidatedProfile profile, string backupDirectory)
        {
            var relativeDataDir = ToGitRelativePath(profile.Checkout, profile.DataDir);
            var relativeDatabase = ToGitRelativePath(profile.Checkout, profile.Database);
            var relativeIdentity = ToGitRelativePath(
                profile.Checkout,
                Path.Combine(profile.DataDir, DataIdentityFilename));
            var relativeBackupDirectory = ToGitRelativePath(profile.Checkout, backupDirectory);

            if ((relativeDataDir is null) != (relativeDatabase is null)
                || (relativeDataDir is null) != (relativeIdentity is null)
                || (relativeDataDir is null) != (relativeBackupDirectory is null))
            {
                throw new LauncherValidationException(
                    "Stable production data paths do not have one canonical checkout boundary; upgrade is blocked.");
            }

            return new ProductionGitLayout(
                relativeDataDir,
                relativeDatabase,
                relativeIdentity,
                relativeBackupDirectory);
        }
    }

    private sealed record RemoteTagProof(string TagObjectSha, string CommitSha);

    private sealed record StableBackupMetadata(string Id, string Name);

    private sealed record BackupRunner(string FileName, IReadOnlyList<string> PrefixArguments);

    private sealed record ProcessOutput(int ExitCode, string StandardOutput, string StandardError);

    private readonly record struct StableVersion(int Major, int Minor, int Patch, string Text) : IComparable<StableVersion>
    {
        public int CompareTo(StableVersion other)
        {
            var major = Major.CompareTo(other.Major);
            if (major != 0)
            {
                return major;
            }
            var minor = Minor.CompareTo(other.Minor);
            return minor != 0 ? minor : Patch.CompareTo(other.Patch);
        }
    }

    private sealed class ProductionDataSnapshot
    {
        private const string SidecarName = ".hermes-data-identity.json";

        private ProductionDataSnapshot(string database, byte[] databaseHash, string? sidecar)
        {
            Database = database;
            DatabaseHash = databaseHash;
            Sidecar = sidecar;
        }

        private string Database { get; }
        private byte[] DatabaseHash { get; }
        private string? Sidecar { get; }

        public static ProductionDataSnapshot Capture(ValidatedProfile profile)
        {
            if (!File.Exists(profile.Database))
            {
                throw new LauncherValidationException("Stable production database is missing; the required backup cannot be created.");
            }
            var sidecarPath = Path.Combine(profile.DataDir, SidecarName);
            return new ProductionDataSnapshot(
                profile.Database,
                HashFile(profile.Database),
                File.Exists(sidecarPath) ? File.ReadAllText(sidecarPath) : null);
        }

        public void AssertUnchanged(ValidatedProfile profile)
        {
            if (!SamePath(Database, profile.Database)
                || !File.Exists(Database)
                || !CryptographicOperations.FixedTimeEquals(DatabaseHash, HashFile(Database)))
            {
                throw new LauncherValidationException("Stable production database changed during release upgrade.");
            }
            var sidecarPath = Path.Combine(profile.DataDir, SidecarName);
            var currentSidecar = File.Exists(sidecarPath) ? File.ReadAllText(sidecarPath) : null;
            if (!string.Equals(currentSidecar, Sidecar, StringComparison.Ordinal))
            {
                throw new LauncherValidationException("Stable production data identity changed during release upgrade.");
            }
        }

        private static byte[] HashFile(string path)
        {
            using var stream = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            return SHA256.HashData(stream);
        }
    }
}
