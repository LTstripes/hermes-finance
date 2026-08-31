using HermesFinance.Launcher;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text;

var tests = new (string Name, Action Run)[]
{
    ("loads the canonical config example", LoadsCanonicalConfigExample),
    ("rejects unknown config fields", RejectsUnknownConfigFields),
    ("requires exactly one stable profile", RequiresExactlyOneStableProfile),
    ("rejects preview aliases to the production database before startup", RejectsUnsafeTupleAliases),
    ("rejects preview hardlinks to the production database", RejectsProductionHardlink),
    ("rejects an existing preview database with the wrong sidecar", RejectsWrongPreviewSidecar),
    ("uses the bundled schema probe for a legacy checkout", UsesBundledSchemaProbeForLegacyCheckout),
    ("uses the bundled dependency preparation helper", UsesBundledDependencyPreparationHelper),
    ("resolves PATH commands outside the selected checkout", ResolvesPathCommandsOutsideSelectedCheckout),
    ("fails closed when npm is missing", FailsClosedWhenNpmIsMissing),
    ("packages the branded cat icon", PackagesBrandedCatIcon),
    ("installs shortcuts beside the stable launcher", InstallsShortcutsBesideStableLauncher),
    ("fails closed when the ready sidecar stamp cannot be written", FailsClosedOnReadySidecarFailure),
    ("constructs a PowerShell -File command without splitting spaces", ConstructsQuotedStartCommand),
    ("binds the validated database into the actual child process", BindsValidatedDatabaseToChildProcess),
    ("accepts an annotated release tag that peels to HEAD", AcceptsAnnotatedReleaseTag),
};

var failures = 0;
foreach (var test in tests)
{
    try
    {
        test.Run();
        Console.WriteLine($"PASS {test.Name}");
    }
    catch (Exception exception)
    {
        failures++;
        Console.Error.WriteLine($"FAIL {test.Name}: {exception}");
    }
}
return failures == 0 ? 0 : 1;

static void RejectsUnknownConfigFields()
{
    const string json = """
        {"version":1,"canonical_production":{"checkout":"C:\\stable","data_dir":"C:\\stable\\data","database":"C:\\stable\\data\\finance.db"},"profiles":[],"token":"forbidden"}
        """;
    AssertThrows<JsonException>(() => JsonSerializer.Deserialize<LauncherConfig>(json, LauncherConfig.JsonOptions));
}

static void LoadsCanonicalConfigExample()
{
    var configPath = Path.Combine(AppContext.BaseDirectory, "config.example.json");
    var config = LauncherConfig.Load(configPath);

    Assert(config.Version == 1, "The canonical config example must declare schema version 1.");
    Assert(config.CanonicalProduction.Checkout == "<absolute-stable-checkout>", "The canonical production checkout must use the documented JSON name.");
    Assert(config.CanonicalProduction.DataDir == "<absolute-stable-data-dir>", "The canonical production data directory must use the documented JSON name.");
    Assert(config.CanonicalProduction.Database == "<absolute-stable-database>", "The canonical production database must use the documented JSON name.");
    Assert(config.Profiles.Count == 2, "The canonical config example must load both documented profiles.");
    Assert(config.Profiles[0].Id == "stable", "The stable profile id must use the documented JSON name.");
    Assert(config.Profiles[0].DisplayName == "Hermes Finance — Stable", "The stable profile display name must load from the canonical example.");
    Assert(config.Profiles[0].ExpectedRef == "refs/tags/v0.6.3", "The stable profile expected ref must use the documented JSON name.");
    Assert(config.Profiles[0].DataDir == "<absolute-stable-data-dir>", "The stable profile data directory must use the documented JSON name.");
    Assert(config.Profiles[0].Database == "<absolute-stable-database>", "The stable profile database must use the documented JSON name.");
    Assert(config.Profiles[0].OpenBrowser, "The stable profile browser setting must use the documented JSON name.");
}

static void RequiresExactlyOneStableProfile()
{
    var config = Config("preview", "preview");
    AssertThrows<LauncherValidationException>(() => ProfileValidator.ValidateConfiguration(config));
}

static void RejectsUnsafeTupleAliases()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-safety-{Guid.NewGuid():N}");
    var stable = Path.Combine(root, "stable");
    var preview = Path.Combine(root, "preview");
    try
    {
        CreateRuntimeLayout(stable);
        CreateRuntimeLayout(preview);
        Directory.CreateDirectory(Path.Combine(stable, "data"));
        Directory.CreateDirectory(Path.Combine(preview, "data"));
        var config = new LauncherConfig
        {
            Version = 1,
            CanonicalProduction = new CanonicalProduction
            {
                Checkout = stable,
                DataDir = Path.Combine(stable, "data"),
                Database = Path.Combine(stable, "data", "finance.db"),
            },
            Profiles =
            [
                new LauncherProfile { Id = "stable", DisplayName = "Stable", Type = "stable", Checkout = stable, ExpectedRef = "HEAD", DataDir = Path.Combine(stable, "data"), Database = Path.Combine(stable, "data", "finance.db"), OpenBrowser = false },
                new LauncherProfile { Id = "preview", DisplayName = "Preview", Type = "preview", Checkout = preview, ExpectedRef = "HEAD", DataDir = Path.Combine(stable, "data"), Database = Path.Combine(stable, "data", "finance.db"), OpenBrowser = false },
            ],
        };
        AssertThrows<LauncherValidationException>(() => ProfileValidator.Validate(config, config.Profiles[1]));
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}

static void RejectsProductionHardlink()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-hardlink-{Guid.NewGuid():N}");
    try
    {
        var stableData = Path.Combine(root, "stable", "data");
        var previewData = Path.Combine(root, "preview", "data");
        Directory.CreateDirectory(stableData);
        Directory.CreateDirectory(previewData);
        var stableDatabase = Path.Combine(stableData, "finance.db");
        var previewDatabase = Path.Combine(previewData, "finance.db");
        File.WriteAllText(stableDatabase, "production-only synthetic content");
        Assert(NativeMethods.CreateHardLink(previewDatabase, stableDatabase, IntPtr.Zero), "Could not create a synthetic hardlink.");
        AssertThrowsMessage(
            () => ProfileValidator.AssertProfileTuple(
                PreviewProfile(previewData, previewDatabase),
                Path.Combine(root, "stable"),
                stableData,
                stableDatabase,
                Path.Combine(root, "preview"),
                previewData,
                previewDatabase),
            "Data path aliases production.");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}

static void RejectsWrongPreviewSidecar()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-sidecar-{Guid.NewGuid():N}");
    try
    {
        Directory.CreateDirectory(root);
        var database = Path.Combine(root, "finance.db");
        File.WriteAllText(database, "separate synthetic preview content");
        File.WriteAllText(Path.Combine(root, ".hermes-data-identity.json"), """{"kind":"sandbox","profile_id":"preview"}""");
        AssertThrowsMessage(
            () => ProfileValidator.AssertSidecar(PreviewProfile(root, database), root, database),
            "Data sidecar does not match this profile type.");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}

static void UsesBundledSchemaProbeForLegacyCheckout()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-legacy-schema-{Guid.NewGuid():N}");
    var legacyCheckout = Path.Combine(root, "stable-v063");
    var database = Path.Combine(root, "stable-data", "finance.db");
    try
    {
        CreateRuntimeLayout(legacyCheckout);
        var legacyProbe = Path.Combine(legacyCheckout, "scripts", "launcher-schema-check.py");
        var bundledProbe = Path.Combine(AppContext.BaseDirectory, "launcher-schema-check.py");
        Assert(!File.Exists(legacyProbe), "The legacy Stable fixture must not contain the current schema probe.");
        Assert(File.Exists(bundledProbe), "The current launcher must package its schema probe.");

        var command = ProfileValidator.BuildSchemaCheckCommand(legacyCheckout, database);
        Assert(command.WorkingDirectory == Path.Combine(legacyCheckout, "backend"), "Schema probing must run in the selected checkout backend.");
        Assert(
            command.ArgumentList.ToArray().SequenceEqual(
            ["run", "--locked", "python", bundledProbe, "--database", database, "--checkout", legacyCheckout]),
            "Schema probing must use the bundled helper and pass the selected checkout graph.");
    }
    finally
    {
        DeleteSyntheticTree(root);
    }
}

static void UsesBundledDependencyPreparationHelper()
{
    var helper = Path.Combine(AppContext.BaseDirectory, "prepare-runtime-dependencies.ps1");
    Assert(File.Exists(helper), "The launcher must package its dependency preparation helper.");
    var source = File.ReadAllText(helper);
    Assert(source.Contains("uv sync --locked", StringComparison.Ordinal), "The helper must use the locked uv sync command.");
    Assert(source.Contains("npm ci", StringComparison.Ordinal), "The helper must use npm ci for the locked frontend tree.");
    Assert(!System.Text.RegularExpressions.Regex.IsMatch(source, @"git\s+(pull|switch|checkout|reset)", System.Text.RegularExpressions.RegexOptions.IgnoreCase), "The dependency helper must not mutate Git state.");

    var checkout = "C:\\Stable Runtime With Spaces";
    var command = DependencyValidator.BuildPreparationCommand(checkout);
    Assert(command.WorkingDirectory == checkout, "Dependency preparation must run in the selected checkout.");
    Assert(
        command.ArgumentList.ToArray().SequenceEqual(
        ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", helper, "-Checkout", checkout, "-Prepare"]),
        "Dependency preparation must pass the selected checkout as one argument and request preparation explicitly.");
}

static void ResolvesPathCommandsOutsideSelectedCheckout()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-npm-resolution-{Guid.NewGuid():N}");
    var checkout = Path.Combine(root, "Selected Checkout With Spaces");
    var frontend = Path.Combine(checkout, "frontend");
    var toolDirectory = Path.Combine(root, "External Node Install With Spaces");
    var observedWorkingDirectory = Path.Combine(root, "observed-working-directory.txt");
    var originalPath = Environment.GetEnvironmentVariable("PATH");
    try
    {
        CreateDependencyValidationLayout(checkout);
        Directory.CreateDirectory(toolDirectory);
        WriteCommandShim(
            Path.Combine(toolDirectory, "uv.cmd"),
            "@echo off\r\nexit /b 0\r\n");
        WriteCommandShim(
            Path.Combine(toolDirectory, "npm.cmd"),
            $"@echo off\r\n> {BatchQuote(observedWorkingDirectory)} echo %CD%\r\necho {{\"name\":\"hermes-finance-frontend\",\"version\":\"0.0.0\"}}\r\nexit /b 0\r\n");
        Environment.SetEnvironmentVariable("PATH", toolDirectory);

        var resolvedNpm = DependencyValidator.ResolveCommand("npm.cmd", frontend);
        Assert(Path.IsPathFullyQualified(resolvedNpm), "Resolved npm command must be an absolute path.");
        Assert(
            string.Equals(Path.GetFullPath(resolvedNpm), Path.GetFullPath(Path.Combine(toolDirectory, "npm.cmd")), StringComparison.OrdinalIgnoreCase),
            "Dependency validation must resolve npm.cmd from PATH, outside the selected checkout.");
        Assert(!resolvedNpm.StartsWith(frontend, StringComparison.OrdinalIgnoreCase), "Resolved npm command must not be derived from frontend.");

        var status = DependencyValidator.Check(checkout);
        Assert(status.Ready, "Synthetic PATH-resolved dependency commands must report ready dependencies.");
        Assert(
            File.ReadAllText(observedWorkingDirectory).Trim().Equals(frontend, StringComparison.OrdinalIgnoreCase),
            "The PATH-resolved npm command must retain the selected frontend as its working directory.");
    }
    finally
    {
        Environment.SetEnvironmentVariable("PATH", originalPath);
        DeleteSyntheticTree(root);
    }
}

static void FailsClosedWhenNpmIsMissing()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-missing-npm-{Guid.NewGuid():N}");
    var checkout = Path.Combine(root, "Selected Checkout With Spaces");
    var toolDirectory = Path.Combine(root, "External uv Install With Spaces");
    var originalPath = Environment.GetEnvironmentVariable("PATH");
    try
    {
        CreateDependencyValidationLayout(checkout);
        Directory.CreateDirectory(toolDirectory);
        WriteCommandShim(
            Path.Combine(toolDirectory, "uv.cmd"),
            "@echo off\r\nexit /b 0\r\n");
        Environment.SetEnvironmentVariable("PATH", toolDirectory);

        AssertThrowsMessage(
            () => DependencyValidator.Check(checkout),
            "Missing dependency 'npm.cmd' required for frontend dependency validation. Install Node.js and ensure npm.cmd is on PATH.");
    }
    finally
    {
        Environment.SetEnvironmentVariable("PATH", originalPath);
        DeleteSyntheticTree(root);
    }
}

static void PackagesBrandedCatIcon()
{
    var icon = Path.Combine(AppContext.BaseDirectory, "hermes-finance-cat.ico");
    Assert(File.Exists(icon), "The launcher must package the branded cat icon.");
    using var stream = File.OpenRead(icon);
    Span<byte> header = stackalloc byte[4];
    Assert(stream.Read(header) == header.Length, "The packaged icon must have a complete ICO header.");
    Assert(header.SequenceEqual(new byte[] { 0, 0, 1, 0 }), "The packaged launcher icon must be a valid ICO file.");
}

static void InstallsShortcutsBesideStableLauncher()
{
    var installer = Path.Combine(AppContext.BaseDirectory, "install.ps1");
    var source = File.ReadAllText(installer);
    Assert(source.Contains("LocalApplicationData", StringComparison.Ordinal), "The installer must default to per-user local app storage.");
    Assert(source.Contains("HermesFinance\\launcher", StringComparison.Ordinal), "The installer must use the stable launcher location.");
    Assert(source.Contains("TargetPath = $executable", StringComparison.Ordinal), "The shortcut must target the installed launcher executable.");
    Assert(source.Contains("IconLocation = \"$executable,0\"", StringComparison.Ordinal), "The shortcut must use the installed branded executable icon.");
    Assert(!System.Text.RegularExpressions.Regex.IsMatch(source, @"git\s+(pull|switch|checkout|reset)", System.Text.RegularExpressions.RegexOptions.IgnoreCase), "The installer must not mutate Git state.");
}

static void FailsClosedOnReadySidecarFailure()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-ready-{Guid.NewGuid():N}");
    try
    {
        Directory.CreateDirectory(root);
        var sidecarPath = Path.Combine(root, ".hermes-data-identity.json");
        Directory.CreateDirectory(sidecarPath);
        var profile = new ValidatedProfile(
            new LauncherProfile { Id = "preview", DisplayName = "Preview", Type = "preview", Checkout = root, ExpectedRef = "HEAD", DataDir = root, Database = Path.Combine(root, "preview.db"), OpenBrowser = true },
            root,
            root,
            Path.Combine(root, "preview.db"),
            "abcdef",
            "preview");
        var stopCalls = 0;
        var errors = new List<string>();
        var ready = MainForm.TryCompleteReady(profile, () => stopCalls++, errors.Add);
        Assert(!ready, "A failed sidecar stamp must not declare the stack ready.");
        Assert(stopCalls == 1, "A failed sidecar stamp must stop the launched stack exactly once.");
        Assert(errors.Count == 1 && errors[0].StartsWith("BLOCKING ERROR:", StringComparison.Ordinal), "A failed sidecar stamp must surface a blocking error.");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}

static void ConstructsQuotedStartCommand()
{
    var profile = new ValidatedProfile(
        new LauncherProfile
        {
            Id = "preview",
            DisplayName = "0.7 Preview",
            Type = "preview",
            Checkout = "C:\\Рабочий стол Directory With Spaces\\preview",
            ExpectedRef = "origin/r07",
            DataDir = "C:\\data",
            Database = "C:\\data\\finance.db",
            OpenBrowser = false,
        },
        "C:\\Рабочий стол Directory With Spaces\\preview",
        "C:\\data",
        "C:\\data\\finance.db",
        "abcdef",
        "preview");
    var command = ProfileValidator.BuildStartCommand(profile);
    var arguments = command.ArgumentList.ToArray();
    Assert(arguments.SequenceEqual(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "C:\\Рабочий стол Directory With Spaces\\preview\\scripts\\start-local.ps1"]), "Start command must pass the script as one ArgumentList item.");
    Assert(command.Environment["HERMES_FINANCE_DATABASE_PATH"] == profile.Database, "Start command must bind the validated database path.");
}

static void BindsValidatedDatabaseToChildProcess()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-child-{Guid.NewGuid():N}");
    var checkout = Path.Combine(root, "Checkout With Spaces");
    var dataDir = Path.Combine(root, "data");
    var database = Path.Combine(dataDir, "preview.db");
    var observed = Path.Combine(root, "observed.txt");
    try
    {
        Directory.CreateDirectory(Path.Combine(checkout, "scripts"));
        Directory.CreateDirectory(dataDir);
        var script = Path.Combine(checkout, "scripts", "start-local.ps1");
        File.WriteAllText(
            script,
            $"Set-Content -LiteralPath {PsQuote(observed)} -Encoding UTF8 -Value $env:HERMES_FINANCE_DATABASE_PATH\n",
            new UTF8Encoding(encoderShouldEmitUTF8Identifier: true));
        var profile = new ValidatedProfile(
            new LauncherProfile { Id = "preview", DisplayName = "Preview", Type = "preview", Checkout = checkout, ExpectedRef = "HEAD", DataDir = dataDir, Database = database, OpenBrowser = false },
            checkout,
            dataDir,
            database,
            "abcdef",
            "preview");
        using var process = Process.Start(ProfileValidator.BuildStartCommand(profile))
            ?? throw new InvalidOperationException("Could not start the synthetic PowerShell child.");
        Assert(process.WaitForExit(15_000), "Synthetic PowerShell child timed out.");
        Assert(process.ExitCode == 0, "Synthetic PowerShell child failed.");
        Assert(File.ReadAllText(observed).Trim() == database, "Child process did not receive the validated database path.");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}

static void AcceptsAnnotatedReleaseTag()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-git-identity-{Guid.NewGuid():N}");
    var dataDir = Path.Combine(root, "data");
    var database = Path.Combine(dataDir, "finance.db");
    try
    {
        CreateRuntimeLayout(root);
        Directory.CreateDirectory(dataDir);
        RunGit(root, "init");
        RunGit(root, "config", "--local", "user.name", "Hermes Safety Test");
        RunGit(root, "config", "--local", "user.email", "hermes-safety-test");
        RunGit(root, "add", ".");
        RunGit(root, "commit", "-m", "initial synthetic runtime");
        var firstCommit = RunGit(root, "rev-parse", "HEAD");
        RunGit(root, "tag", "-a", "annotated-old", "-m", "old synthetic release", firstCommit);

        File.WriteAllText(Path.Combine(root, "identity-marker.txt"), "synthetic second commit");
        RunGit(root, "add", ".");
        RunGit(root, "commit", "-m", "current synthetic runtime");
        var head = RunGit(root, "rev-parse", "HEAD");
        var branch = RunGit(root, "symbolic-ref", "--short", "HEAD");
        RunGit(root, "tag", "lightweight-current");
        RunGit(root, "tag", "-a", "v0.6.3", "-m", "current synthetic release");

        foreach (var expectedRef in new[]
        {
            branch,
            "refs/tags/lightweight-current",
            "refs/tags/v0.6.3",
        })
        {
            var profile = StableProfile(root, dataDir, database, expectedRef);
            var resolvedHead = ProfileValidator.AssertGitIdentity(profile, root, root);
            Assert(resolvedHead.Equals(head, StringComparison.OrdinalIgnoreCase), $"Expected {expectedRef} to resolve to HEAD.");
        }

        var mismatched = StableProfile(root, dataDir, database, "refs/tags/annotated-old");
        AssertThrowsMessage(
            () => ProfileValidator.AssertGitIdentity(mismatched, root, root),
            "Checkout identity does not match this profile.");
    }
    finally
    {
        DeleteSyntheticTree(root);
    }
}

static LauncherConfig Config(string firstType, string secondType) => new()
{
    Version = 1,
    CanonicalProduction = new CanonicalProduction { Checkout = "C:\\stable", DataDir = "C:\\stable\\data", Database = "C:\\stable\\data\\finance.db" },
    Profiles =
    [
        new LauncherProfile { Id = "first", DisplayName = "First", Type = firstType, Checkout = "C:\\stable", ExpectedRef = "HEAD", DataDir = "C:\\stable\\data", Database = "C:\\stable\\data\\finance.db", OpenBrowser = false },
        new LauncherProfile { Id = "second", DisplayName = "Second", Type = secondType, Checkout = "C:\\preview", ExpectedRef = "HEAD", DataDir = "C:\\preview\\data", Database = "C:\\preview\\data\\finance.db", OpenBrowser = false },
    ],
};

static LauncherProfile StableProfile(string checkout, string dataDir, string database, string expectedRef) => new()
{
    Id = "stable",
    DisplayName = "Stable",
    Type = "stable",
    Checkout = checkout,
    ExpectedRef = expectedRef,
    DataDir = dataDir,
    Database = database,
    OpenBrowser = false,
};

static LauncherProfile PreviewProfile(string dataDir, string database) => new()
{
    Id = "preview",
    DisplayName = "Preview",
    Type = "preview",
    Checkout = Path.Combine(dataDir, ".."),
    ExpectedRef = "HEAD",
    DataDir = dataDir,
    Database = database,
    OpenBrowser = false,
};

static void AssertThrows<TException>(Action action) where TException : Exception
{
    try
    {
        action();
    }
    catch (TException)
    {
        return;
    }
    throw new InvalidOperationException($"Expected {typeof(TException).Name}.");
}

static void AssertThrowsMessage(Action action, string expectedMessage)
{
    try
    {
        action();
    }
    catch (LauncherValidationException exception) when (exception.Message == expectedMessage)
    {
        return;
    }
    catch (Exception exception)
    {
        throw new InvalidOperationException($"Expected launcher rejection '{expectedMessage}'.", exception);
    }
    throw new InvalidOperationException($"Expected launcher rejection '{expectedMessage}'.");
}

static void Assert(bool condition, string message)
{
    if (!condition)
    {
        throw new InvalidOperationException(message);
    }
}

static void CreateRuntimeLayout(string root)
{
    Directory.CreateDirectory(Path.Combine(root, "scripts"));
    Directory.CreateDirectory(Path.Combine(root, "backend"));
    Directory.CreateDirectory(Path.Combine(root, "frontend"));
    File.WriteAllText(Path.Combine(root, "scripts", "start-local.ps1"), "# synthetic safety test runtime");
    File.WriteAllText(Path.Combine(root, "backend", "pyproject.toml"), "[project]");
    File.WriteAllText(Path.Combine(root, "frontend", "package.json"), "{}");
    File.WriteAllText(Path.Combine(root, ".gitignore"), "data/\n");
}

static void CreateDependencyValidationLayout(string checkout)
{
    CreateRuntimeLayout(checkout);
    File.WriteAllText(Path.Combine(checkout, "backend", "uv.lock"), "version = 1\n");
    File.WriteAllText(Path.Combine(checkout, "frontend", "package-lock.json"), "{\"name\":\"hermes-finance-frontend\",\"lockfileVersion\":3}\n");
    File.WriteAllText(Path.Combine(checkout, "frontend", "package.json"), "{\"name\":\"hermes-finance-frontend\",\"version\":\"0.0.0\"}\n");
    Directory.CreateDirectory(Path.Combine(checkout, "frontend", "node_modules"));
}

static void WriteCommandShim(string path, string contents)
{
    File.WriteAllText(path, contents, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
}

static string BatchQuote(string value) => "\"" + value.Replace("\"", "\"\"") + "\"";

static string RunGit(string workingDirectory, params string[] arguments)
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

    using var process = Process.Start(startInfo) ?? throw new InvalidOperationException("Could not start synthetic git process.");
    var standardOutput = process.StandardOutput.ReadToEnd();
    var standardError = process.StandardError.ReadToEnd();
    process.WaitForExit();
    Assert(process.ExitCode == 0, $"Synthetic git command failed: {standardError.Trim()} {standardOutput.Trim()}".Trim());
    return standardOutput.Trim();
}

static void DeleteSyntheticTree(string root)
{
    if (!Directory.Exists(root))
    {
        return;
    }

    foreach (var entry in new DirectoryInfo(root).EnumerateFileSystemInfos("*", SearchOption.AllDirectories))
    {
        entry.Attributes = FileAttributes.Normal;
    }
    Directory.Delete(root, recursive: true);
}

static string PsQuote(string value) => "'" + value.Replace("'", "''") + "'";

static class NativeMethods
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    internal static extern bool CreateHardLink(string fileName, string existingFileName, IntPtr securityAttributes);
}
