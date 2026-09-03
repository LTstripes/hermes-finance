using HermesFinance.Launcher;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text;

if (args.Contains("--synthetic-ui-smoke", StringComparer.OrdinalIgnoreCase))
{
    Application.EnableVisualStyles();
    Application.SetCompatibleTextRenderingDefault(false);
    using var smokeForm = MainForm.CreateSyntheticSmoke();
    Application.Run(smokeForm);
    return 0;
}

var tests = new (string Name, Action Run)[]
{
    ("loads the canonical config example", LoadsCanonicalConfigExample),
    ("rejects unknown config fields", RejectsUnknownConfigFields),
    ("presents the branded owner launcher surface", PresentsBrandedOwnerSurface),
    ("exposes explicit prepare, repair, start, and stop actions", PresentsExplicitDependencyActions),
    ("exposes explicit Preview update actions and SHA labels", PresentsPreviewUpdateActions),
    ("keeps Stable and Preview data boundaries visibly distinct", KeepsProfileBoundariesDistinct),
    ("sanitizes raw paths from owner-facing blockers", SanitizesOwnerFacingBlockers),
    ("requires exactly one stable profile", RequiresExactlyOneStableProfile),
    ("rejects preview aliases to the production database before startup", RejectsUnsafeTupleAliases),
    ("rejects preview hardlinks to the production database", RejectsProductionHardlink),
    ("rejects an existing preview database with the wrong sidecar", RejectsWrongPreviewSidecar),
    ("uses the bundled schema probe for a legacy checkout", UsesBundledSchemaProbeForLegacyCheckout),
    ("uses the bundled dependency preparation helper", UsesBundledDependencyPreparationHelper),
    ("detects missing and outdated locked dependencies", DetectsDependencyDrift),
    ("keeps an offline backend cache miss actionable", KeepsOfflineBackendCacheMissActionable),
    ("fails closed on non-cache offline backend errors", FailsClosedOnInvalidOfflineBackendProbe),
    ("resolves PATH commands outside the selected checkout", ResolvesPathCommandsOutsideSelectedCheckout),
    ("fails closed when npm is missing", FailsClosedWhenNpmIsMissing),
    ("packages the branded cat icon", PackagesBrandedCatIcon),
    ("installs shortcuts beside the stable launcher", InstallsShortcutsBesideStableLauncher),
    ("starts and stops only a synthetic runtime", StartsAndStopsSyntheticRuntime),
    ("fails closed when the ready sidecar stamp cannot be written", FailsClosedOnReadySidecarFailure),
    ("constructs a PowerShell -File command without splitting spaces", ConstructsQuotedStartCommand),
    ("binds the validated database into the actual child process", BindsValidatedDatabaseToChildProcess),
    ("accepts an annotated release tag that peels to HEAD", AcceptsAnnotatedReleaseTag),
    ("updates only Preview to unreleased origin main and preserves its data", UpdatesPreviewAndPreservesData),
    ("rejects dirty, conflicted, and unexpected Preview checkouts", RejectsUnsafePreviewUpdateStates),
    ("rejects Stable as an update target", RejectsStableUpdate),
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

static void PresentsBrandedOwnerSurface()
{
    using var form = MainForm.CreateSyntheticSmoke();
    var controls = AllControls(form).ToArray();
    var buttons = controls.OfType<Button>().ToArray();
    var labels = controls.OfType<Label>().ToArray();

    Assert(form.Text == "Hermes Finance — Launcher", "The launcher must carry the Hermes Finance title.");
    Assert(labels.Any(label => label.Text == "Запуск локального Hermes"), "The owner-facing launcher title is missing.");
    Assert(buttons.Any(button => button.Text == "Запустить" && button.Enabled), "Start must be the primary enabled action for a ready synthetic profile.");
    Assert(buttons.Any(button => button.Text == "Подготовить" && !button.Enabled), "Prepare must be available as an explicit action and disabled for ready dependencies.");
    Assert(buttons.Any(button => button.Text == "Исправить" && button.Enabled), "Repair must remain available as an explicit recovery action.");
    Assert(buttons.Any(button => button.Text == "Остановить" && !button.Enabled), "Stop must be disabled before a runtime is launched.");
    Assert(buttons.Any(button => button.Text == "Открыть Hermes" && !button.Enabled), "Open Hermes must stay disabled until health probes pass.");
    Assert(buttons.Any(button => button.Text == "Диагностика и логи"), "Raw diagnostics must have a dedicated details action.");
    Assert(labels.Any(label => label.Text == "STABLE  ·  PRODUCTION"), "The Stable owner badge is missing.");
    Assert(labels.Any(label => label.Text == "PREVIEW  ·  ISOLATED"), "The Preview owner badge is missing.");
    Assert(labels.Any(label => label.Text.Contains("Release v0.7.0", StringComparison.Ordinal)), "Profile cards must show a safe release/version badge.");

    var status = controls.OfType<TextBox>().Single();
    Assert(status.Parent is not null && status.Parent.Parent is not null && !status.Parent.Parent.Visible, "Raw logs must be hidden from the primary UX.");
}

static void PresentsExplicitDependencyActions()
{
    var profile = StableProfile("C:\\synthetic\\stable", "C:\\synthetic\\stable\\data", "C:\\synthetic\\stable\\data\\finance.db", "HEAD");
    var config = new LauncherConfig
    {
        Version = 1,
        CanonicalProduction = new CanonicalProduction
        {
            Checkout = profile.Checkout,
            DataDir = profile.DataDir,
            Database = profile.Database,
        },
        Profiles = [profile],
    };
    using var form = new MainForm(config);
    var validated = new ValidatedProfile(
        profile,
        profile.Checkout,
        profile.DataDir,
        profile.Database,
        "synthetic-head",
        "production",
        new DependencyStatus(false, false, "needs preparation: backend", "needs preparation: frontend"));
    var apply = typeof(MainForm).GetMethod("ApplyValidated", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
        ?? throw new InvalidOperationException("Synthetic smoke could not find the launcher validation presentation.");
    apply.Invoke(form, [validated]);

    var buttons = AllControls(form).OfType<Button>().ToArray();
    Assert(buttons.Single(button => button.Text == "Подготовить").Enabled, "Prepare must be the primary enabled action when dependencies are missing or stale.");
    Assert(buttons.Single(button => button.Text == "Исправить").Enabled, "Repair must be enabled for an explicitly validated profile.");
    Assert(!buttons.Single(button => button.Text == "Запустить").Enabled, "Start must remain blocked until dependencies are explicitly prepared.");
    Assert(buttons.Single(button => button.Text == "Остановить").AccessibleName == "Остановить Hermes", "Stop must retain its owner-facing accessible name.");
}

static void PresentsPreviewUpdateActions()
{
    using var form = MainForm.CreateSyntheticSmoke();
    var controls = AllControls(form).ToArray();
    var buttons = controls.OfType<Button>().ToArray();
    var labels = controls.OfType<Label>().ToArray();

    var updateButton = buttons.Single(button => button.Text == "Обновить Preview");
    var updateAndStartButton = buttons.Single(button => button.Text == "Обновить и запустить");
    Assert(updateButton.Parent is FlowLayoutPanel && !updateButton.Enabled, "Preview update must be present but disabled while Stable is selected.");
    Assert(updateAndStartButton.Parent is FlowLayoutPanel && !updateAndStartButton.Enabled, "Update-and-start must be present but disabled while Stable is selected.");
    Assert(labels.Any(label => label.Text.StartsWith("Current SHA:", StringComparison.Ordinal)), "The owner surface must show current and target code identity labels.");
    Assert(updateButton.AccessibleName == "Обновить Preview", "The Preview update action must be accessible by name.");
}

static void KeepsProfileBoundariesDistinct()
{
    Assert(LauncherUi.TypeBadge("stable") != LauncherUi.TypeBadge("preview"), "Stable and Preview badges must differ.");
    Assert(LauncherUi.DataBoundary("stable") == "Canonical production data", "Stable must advertise canonical production data.");
    Assert(LauncherUi.DataBoundary("preview") == "Isolated UAT / synthetic data", "Preview must advertise isolated UAT or synthetic data.");
    Assert(LauncherUi.ReleaseBadge("refs/tags/v0.7.0") == "Release v0.7.0", "Tag refs must become a concise release badge.");
    Assert(LauncherUi.ReleaseBadge("C:\\owner\\private\\release") == "Prepared release", "Release badges must not expose path-like refs.");
    Assert(LauncherUi.AccentFor("stable") != LauncherUi.AccentFor("preview"), "Stable and Preview must use distinct visual accents.");
    Assert(LauncherUi.CardBackgroundFor("stable") != LauncherUi.CardBackgroundFor("preview"), "Stable and Preview must use distinct card backgrounds.");
}

static void SanitizesOwnerFacingBlockers()
{
    const string raw = "The parent directory for profile 'preview' database C:\\owner\\private\\finance.db does not exist.";
    var ownerMessage = LauncherUi.OwnerFacingFailure(raw);
    Assert(!ownerMessage.Contains("C:\\owner", StringComparison.OrdinalIgnoreCase), "Owner-facing blockers must not expose configured filesystem paths.");
    Assert(!ownerMessage.Contains("finance.db", StringComparison.OrdinalIgnoreCase), "Owner-facing blockers must not expose database filenames.");
    Assert(ownerMessage.Contains("не хватает", StringComparison.OrdinalIgnoreCase), "Missing runtime blockers must remain understandable to the owner.");
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
            ["run", "--locked", "--offline", "python", bundledProbe, "--database", database, "--checkout", legacyCheckout]),
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
    Assert(source.Contains("--offline", StringComparison.Ordinal), "Dependency status checks must not reach the network implicitly.");
    Assert(source.Contains("npm ci", StringComparison.Ordinal), "The helper must use npm ci for the locked frontend tree.");
    Assert(source.Contains("$Repair", StringComparison.Ordinal), "The helper must expose an explicit repair mode.");
    Assert(!System.Text.RegularExpressions.Regex.IsMatch(source, @"git\s+(pull|switch|checkout|reset)", System.Text.RegularExpressions.RegexOptions.IgnoreCase), "The dependency helper must not mutate Git state.");

    var checkout = "C:\\Stable Runtime With Spaces";
    var command = DependencyValidator.BuildPreparationCommand(checkout);
    Assert(command.WorkingDirectory == checkout, "Dependency preparation must run in the selected checkout.");
    Assert(
        command.ArgumentList.ToArray().SequenceEqual(
        ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", helper, "-Checkout", checkout, "-Prepare"]),
        "Dependency preparation must pass the selected checkout as one argument and request preparation explicitly.");

    var repairCommand = DependencyValidator.BuildPreparationCommand(checkout, repair: true);
    Assert(
        repairCommand.ArgumentList.ToArray().SequenceEqual(
        ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", helper, "-Checkout", checkout, "-Repair"]),
        "Dependency repair must pass the selected checkout as one argument and request repair explicitly.");
}

static void DetectsDependencyDrift()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-dependency-drift-{Guid.NewGuid():N}");
    var checkout = Path.Combine(root, "Selected Checkout With Spaces");
    var toolDirectory = Path.Combine(root, "External Tools With Spaces");
    var originalPath = Environment.GetEnvironmentVariable("PATH");
    try
    {
        CreateDependencyValidationLayout(checkout);
        Directory.CreateDirectory(toolDirectory);
        WriteCommandShim(
            Path.Combine(toolDirectory, "uv.cmd"),
            "@echo off\r\necho Would install the locked backend environment\r\nexit /b 0\r\n");
        WriteCommandShim(
            Path.Combine(toolDirectory, "npm.cmd"),
            "@echo off\r\necho {\"problems\":[\"missing: hermes-finance-ui\"]}\r\nexit /b 1\r\n");
        Environment.SetEnvironmentVariable("PATH", toolDirectory);

        var status = DependencyValidator.Check(checkout);
        Assert(!status.Ready, "Missing or stale dependency environments must not report ready.");
        Assert(!status.BackendReady, "An offline uv dry-run reporting a pending install must require preparation.");
        Assert(!status.FrontendReady, "npm dependency problems must require preparation.");
        Assert(status.BackendDetail.Contains("needs preparation", StringComparison.Ordinal), "Backend drift must be owner-visible as preparation work.");
        Assert(status.FrontendDetail.Contains("needs preparation", StringComparison.Ordinal), "Frontend drift must be owner-visible as preparation work.");
    }
    finally
    {
        Environment.SetEnvironmentVariable("PATH", originalPath);
        DeleteSyntheticTree(root);
    }
}

static void KeepsOfflineBackendCacheMissActionable()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-offline-cache-miss-{Guid.NewGuid():N}");
    var checkout = Path.Combine(root, "Selected Checkout With Spaces");
    var dataDir = Path.Combine(root, "Stable Data");
    var database = Path.Combine(dataDir, "finance.db");
    var toolDirectory = Path.Combine(root, "External Tools With Spaces");
    var preparationMarker = Path.Combine(root, "network-preparation.marker");
    var originalPath = Environment.GetEnvironmentVariable("PATH");
    try
    {
        CreateDependencyValidationLayout(checkout);
        Directory.CreateDirectory(dataDir);
        RunGit(checkout, "init");
        RunGit(checkout, "config", "user.name", "Hermes Safety Test");
        RunGit(checkout, "config", "user.email", "hermes-safety-test");
        RunGit(checkout, "add", ".");
        RunGit(checkout, "commit", "-m", "initial synthetic runtime");
        Directory.CreateDirectory(toolDirectory);
        var marker = BatchQuote(preparationMarker);
        WriteCommandShim(
            Path.Combine(toolDirectory, "uv.cmd"),
            string.Join("\r\n", new[]
            {
                "@echo off",
                "if \"%~1\"==\"sync\" if \"%~2\"==\"--locked\" if \"%~3\"==\"--dry-run\" if \"%~4\"==\"--offline\" (",
                $"  if exist {marker} exit /b 0",
                "  echo error: No interpreter found for Python 3.13 in managed installations",
                "  echo hint: A managed Python download is available for Python 3.13, but Python downloads are set to 'never'",
                "  exit /b 2",
                ")",
                $"> {marker} echo prepared",
                "exit /b 0",
            }));
        WriteCommandShim(
            Path.Combine(toolDirectory, "npm.cmd"),
            "@echo off\r\necho {\"name\":\"hermes-finance-frontend\"}\r\nexit /b 0\r\n");
        var testPath = string.IsNullOrWhiteSpace(originalPath)
            ? toolDirectory
            : toolDirectory + Path.PathSeparator + originalPath;
        Environment.SetEnvironmentVariable("PATH", testPath);

        var profile = StableProfile(checkout, dataDir, database, "HEAD");
        var config = new LauncherConfig
        {
            Version = 1,
            CanonicalProduction = new CanonicalProduction
            {
                Checkout = checkout,
                DataDir = dataDir,
                Database = database,
            },
            Profiles = [profile],
        };
        var validated = ProfileValidator.Validate(config, profile);
        var dependencies = validated.Dependencies ?? throw new InvalidOperationException("Preflight did not return dependency status.");
        Assert(!dependencies.BackendReady && dependencies.FrontendReady, "An offline managed-Python cache miss must return a not-ready backend dependency status.");
        Assert(dependencies.BackendDetail.Contains("needs preparation", StringComparison.Ordinal), "The offline cache miss must be owner-visible as preparation work.");
        Assert(!File.Exists(preparationMarker), "Read-only preflight must not run network-capable preparation.");

        using var form = new MainForm(config);
        var apply = typeof(MainForm).GetMethod("ApplyValidated", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("Synthetic smoke could not find the launcher validation presentation.");
        apply.Invoke(form, [validated]);
        var buttons = AllControls(form).OfType<Button>().ToArray();
        Assert(buttons.Single(button => button.Text == "Подготовить").Enabled, "Prepare must be enabled after an offline backend cache miss.");
        Assert(!buttons.Single(button => button.Text == "Запустить").Enabled, "Ordinary Start must remain disabled until preparation completes.");

        using var preparation = Process.Start(DependencyValidator.BuildPreparationCommand(checkout))
            ?? throw new InvalidOperationException("Synthetic owner action could not start the bundled preparation helper.");
        preparation.WaitForExit();
        Assert(preparation.ExitCode == 0, "The explicit owner preparation action must complete successfully for the synthetic cache-miss fixture.");
        Assert(File.Exists(preparationMarker), "Network-capable preparation must run only after the explicit owner Prepare action.");
        var prepared = ProfileValidator.Validate(config, profile);
        apply.Invoke(form, [prepared]);
        Assert(buttons.Single(button => button.Text == "Запустить").Enabled, "Start must become enabled after explicit preparation succeeds.");
    }
    finally
    {
        Environment.SetEnvironmentVariable("PATH", originalPath);
        DeleteSyntheticTree(root);
    }
}

static void FailsClosedOnInvalidOfflineBackendProbe()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-invalid-offline-probe-{Guid.NewGuid():N}");
    var checkout = Path.Combine(root, "Selected Checkout");
    var toolDirectory = Path.Combine(root, "External Tools");
    var originalPath = Environment.GetEnvironmentVariable("PATH");
    try
    {
        CreateDependencyValidationLayout(checkout);
        Directory.CreateDirectory(toolDirectory);
        WriteCommandShim(Path.Combine(toolDirectory, "uv.cmd"), "@echo off\r\necho error: invalid uv.lock\r\nexit /b 2\r\n");
        Environment.SetEnvironmentVariable("PATH", toolDirectory + Path.PathSeparator + originalPath);

        AssertThrowsMessage(
            () => DependencyValidator.Check(checkout),
            "Backend dependency check failed: error: invalid uv.lock");
    }
    finally
    {
        Environment.SetEnvironmentVariable("PATH", originalPath);
        DeleteSyntheticTree(root);
    }
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

static void StartsAndStopsSyntheticRuntime()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-start-stop-{Guid.NewGuid():N}");
    Process? process = null;
    MainForm? form = null;
    try
    {
        var checkout = Path.Combine(root, "Synthetic Runtime With Spaces");
        var dataDir = Path.Combine(root, "data");
        var database = Path.Combine(dataDir, "synthetic.db");
        var marker = Path.Combine(root, "started.txt");
        Directory.CreateDirectory(Path.Combine(checkout, "scripts"));
        Directory.CreateDirectory(dataDir);
        var script = Path.Combine(checkout, "scripts", "start-local.ps1");
        File.WriteAllText(
            script,
            $"Set-Content -LiteralPath {PsQuote(marker)} -Encoding UTF8 -Value 'started'\nwhile ($true) {{ Start-Sleep -Seconds 1 }}\n",
            new UTF8Encoding(encoderShouldEmitUTF8Identifier: true));

        var profile = new ValidatedProfile(
            new LauncherProfile { Id = "synthetic", DisplayName = "Synthetic Runtime", Type = "experiment", Checkout = checkout, ExpectedRef = "HEAD", DataDir = dataDir, Database = database, OpenBrowser = false },
            checkout,
            dataDir,
            database,
            "synthetic-head",
            "experiment");
        form = new MainForm(new LauncherConfig
        {
            Version = 1,
            CanonicalProduction = new CanonicalProduction { Checkout = checkout, DataDir = dataDir, Database = database },
            Profiles = [profile.Profile],
        });

        var start = typeof(MainForm).GetMethod("StartProcess", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("Synthetic smoke could not find the launcher Start implementation.");
        start.Invoke(form, [profile]);

        var processField = typeof(MainForm).GetField("_launcherProcess", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("Synthetic smoke could not find the launcher process state.");
        var deadline = DateTime.UtcNow.AddSeconds(15);
        while (DateTime.UtcNow < deadline && (!File.Exists(marker) || (process = processField.GetValue(form) as Process) is null || process.HasExited))
        {
            Thread.Sleep(100);
        }

        process ??= processField.GetValue(form) as Process;
        Assert(File.Exists(marker), "Synthetic runtime did not reach its start marker.");
        Assert(process is not null && !process.HasExited, "Synthetic runtime was not running after launcher Start.");

        var stop = typeof(MainForm).GetMethod(
                "StopLaunchedStack",
                System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic,
                binder: null,
                types: [typeof(string)],
                modifiers: null)
            ?? throw new InvalidOperationException("Synthetic smoke could not find the launcher Stop implementation.");
        stop.Invoke(form, ["Synthetic smoke stopped the runtime."]);
        var startedProcess = process ?? throw new InvalidOperationException("Synthetic runtime process disappeared before launcher Stop.");
        Assert(startedProcess.WaitForExit(5_000), "Synthetic runtime did not stop after launcher Stop.");
    }
    finally
    {
        if (process is not null && !process.HasExited)
        {
            process.Kill(entireProcessTree: true);
            process.WaitForExit(5_000);
        }
        form?.Dispose();
        DeleteSyntheticTree(root);
    }
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
    Assert(command.Environment["UV_OFFLINE"] == "1", "Launcher-started uv commands must remain offline after explicit dependency preparation.");
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

static void UpdatesPreviewAndPreservesData()
{
    var fixture = CreatePreviewUpdateFixture();
    try
    {
        var database = Path.Combine(fixture.DataDir, "finance.db");
        var sidecar = Path.Combine(fixture.DataDir, ".hermes-data-identity.json");
        File.WriteAllText(database, "synthetic Preview database; never Stable");
        File.WriteAllText(sidecar, "{\"kind\":\"preview\",\"profile_id\":\"preview\"}");
        var databaseBefore = File.ReadAllBytes(database);
        var sidecarBefore = File.ReadAllText(sidecar);
        var targetContent = File.ReadAllText(Path.Combine(fixture.Seed, "runtime-marker.txt"));
        var profile = NewValidatedPreviewProfile(fixture.Preview, fixture.DataDir, database, fixture.CurrentSha);
        var cleanStatus = RunGit(fixture.Preview, "status", "--porcelain=v1", "--untracked-files=all");
        Assert(string.IsNullOrWhiteSpace(cleanStatus), $"The clean Preview fixture must start clean: {cleanStatus}");
        Assert(RunGit(fixture.Preview, "rev-parse", "--verify", "refs/remotes/origin/main^{commit}") == fixture.CurrentSha, "The Preview fixture must expose its initial origin/main commit.");

        var result = PreviewUpdateService.Update(profile);

        Assert(result.Updated, "An unreleased origin/main commit must update the Preview checkout.");
        Assert(result.TargetSha == fixture.TargetSha, "Preview must update to the fetched origin/main commit, not a tag.");
        Assert(RunGit(fixture.Preview, "rev-parse", "HEAD") == fixture.TargetSha, "Preview HEAD must equal origin/main after update.");
        Assert(File.ReadAllText(Path.Combine(fixture.Preview, "runtime-marker.txt")) == targetContent, "Preview must receive the canonical main code.");
        Assert(File.ReadAllBytes(database).SequenceEqual(databaseBefore), "Preview database bytes must remain unchanged.");
        Assert(File.ReadAllText(sidecar) == sidecarBefore, "Preview data identity sidecar must remain unchanged.");
        Assert(File.ReadAllText(fixture.StableMarker) == "stable untouched", "Stable data must remain untouched by Preview update.");
        Assert(
            ProfileValidator.AssertGitIdentity(profile.Profile, fixture.Preview, fixture.Seed) == fixture.TargetSha,
            "A clean Preview at unreleased origin/main must remain an accepted identity without editing expected_ref.");
    }
    finally
    {
        DeleteSyntheticTree(fixture.Root);
    }
}

static void RejectsUnsafePreviewUpdateStates()
{
    var dirtyFixture = CreatePreviewUpdateFixture();
    try
    {
        var dirtyProfile = NewValidatedPreviewProfile(dirtyFixture.Preview, dirtyFixture.DataDir, Path.Combine(dirtyFixture.DataDir, "finance.db"), dirtyFixture.CurrentSha);
        File.WriteAllText(Path.Combine(dirtyFixture.Preview, "owner-edit.txt"), "must block");
        AssertThrowsMessage(
            () => PreviewUpdateService.Update(dirtyProfile),
            "Preview checkout is dirty or conflicted; update is blocked.");
    }
    finally
    {
        DeleteSyntheticTree(dirtyFixture.Root);
    }

    var conflictFixture = CreatePreviewUpdateFixture();
    try
    {
        var conflictProfile = NewValidatedPreviewProfile(conflictFixture.Preview, conflictFixture.DataDir, Path.Combine(conflictFixture.DataDir, "finance.db"), conflictFixture.CurrentSha);
        RunGit(conflictFixture.Preview, "fetch", "origin", "main");
        File.WriteAllText(Path.Combine(conflictFixture.Preview, "runtime-marker.txt"), "local conflicting edit");
        RunGit(conflictFixture.Preview, "add", "runtime-marker.txt");
        RunGit(conflictFixture.Preview, "commit", "-m", "synthetic local preview edit");
        Assert(RunGitMayFail(conflictFixture.Preview, "merge", "origin/main") != 0, "The synthetic conflict setup must fail to merge cleanly.");
        var conflictStatus = RunGit(conflictFixture.Preview, "status", "--porcelain=v1", "--untracked-files=all");
        Assert(!string.IsNullOrWhiteSpace(conflictStatus), $"The conflicted Preview fixture must expose a non-clean status: {conflictStatus}");
        AssertThrowsMessage(
            () => PreviewUpdateService.Update(conflictProfile),
            "Preview checkout is dirty or conflicted; update is blocked.");
    }
    finally
    {
        DeleteSyntheticTree(conflictFixture.Root);
    }

    var unexpectedFixture = CreatePreviewUpdateFixture();
    try
    {
        var unexpectedProfile = NewValidatedPreviewProfile(unexpectedFixture.Preview, unexpectedFixture.DataDir, Path.Combine(unexpectedFixture.DataDir, "finance.db"), unexpectedFixture.CurrentSha);
        File.WriteAllText(Path.Combine(unexpectedFixture.Preview, "unexpected-marker.txt"), "unexpected clean commit");
        RunGit(unexpectedFixture.Preview, "add", "unexpected-marker.txt");
        RunGit(unexpectedFixture.Preview, "commit", "-m", "synthetic unexpected preview commit");
        AssertThrowsMessage(
            () => PreviewUpdateService.Update(unexpectedProfile),
            "Preview checkout identity is unexpected; update is blocked.");
    }
    finally
    {
        DeleteSyntheticTree(unexpectedFixture.Root);
    }
}

static void RejectsStableUpdate()
{
    var profile = new ValidatedProfile(
        new LauncherProfile
        {
            Id = "stable",
            DisplayName = "Stable",
            Type = "stable",
            Checkout = "C:\\stable",
            ExpectedRef = "HEAD",
            DataDir = "C:\\stable\\data",
            Database = "C:\\stable\\data\\finance.db",
            OpenBrowser = false,
        },
        "C:\\stable",
        "C:\\stable\\data",
        "C:\\stable\\data\\finance.db",
        "stable-head",
        "production");

    AssertThrowsMessage(
        () => PreviewUpdateService.Update(profile),
        "Only the configured Preview profile may be updated.");
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

static IEnumerable<Control> AllControls(Control root)
{
    foreach (Control child in root.Controls)
    {
        yield return child;
        foreach (var descendant in AllControls(child))
        {
            yield return descendant;
        }
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

static (string Root, string Seed, string Remote, string Preview, string DataDir, string StableMarker, string CurrentSha, string TargetSha) CreatePreviewUpdateFixture()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-preview-update-{Guid.NewGuid():N}");
    var seed = Path.Combine(root, "seed");
    var remote = Path.Combine(root, "preview-origin.git");
    var preview = Path.Combine(root, "configured-preview");
    var dataDir = Path.Combine(root, "preview-data");
    var stableMarker = Path.Combine(root, "stable-data", "stable-marker.txt");
    Directory.CreateDirectory(root);
    Directory.CreateDirectory(Path.GetDirectoryName(stableMarker)!);
    File.WriteAllText(stableMarker, "stable untouched");
    Directory.CreateDirectory(remote);
    RunGit(remote, "init", "--bare");
    CreateRuntimeLayout(seed);
    File.WriteAllText(Path.Combine(seed, "runtime-marker.txt"), "initial Preview runtime");
    RunGit(seed, "init");
    RunGit(seed, "config", "user.name", "Hermes Preview Safety Test");
    RunGit(seed, "config", "user.email", "hermes-preview-safety-test");
    RunGit(seed, "add", ".");
    RunGit(seed, "commit", "-m", "initial synthetic Preview runtime");
    RunGit(seed, "branch", "-M", "main");
    RunGit(seed, "remote", "add", "origin", remote);
    RunGit(seed, "push", "--set-upstream", "origin", "main");
    var currentSha = RunGit(seed, "rev-parse", "HEAD");
    RunGit(root, "clone", "-b", "main", remote, preview);
    RunGit(preview, "config", "--local", "user.name", "Hermes Preview Safety Test");
    RunGit(preview, "config", "--local", "user.email", "hermes-preview-safety-test");
    RunGit(preview, "branch", "legacy-preview", currentSha);

    File.WriteAllText(Path.Combine(seed, "runtime-marker.txt"), "unreleased canonical main runtime");
    RunGit(seed, "add", "runtime-marker.txt");
    RunGit(seed, "commit", "-m", "unreleased canonical main change");
    RunGit(seed, "push", "origin", "main");
    var targetSha = RunGit(seed, "rev-parse", "HEAD");
    Directory.CreateDirectory(dataDir);
    return (root, seed, remote, preview, dataDir, stableMarker, currentSha, targetSha);
}

static ValidatedProfile NewValidatedPreviewProfile(string checkout, string dataDir, string database, string currentSha) =>
    new(
        new LauncherProfile
        {
            Id = "preview",
            DisplayName = "Preview",
            Type = "preview",
            Checkout = checkout,
            ExpectedRef = "refs/heads/legacy-preview",
            DataDir = dataDir,
            Database = database,
            OpenBrowser = false,
        },
        checkout,
        dataDir,
        database,
        currentSha,
        "preview");

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

static int RunGitMayFail(string workingDirectory, params string[] arguments)
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

    using var process = Process.Start(startInfo) ?? throw new InvalidOperationException("Could not start synthetic Git command.");
    _ = process.StandardOutput.ReadToEnd();
    _ = process.StandardError.ReadToEnd();
    process.WaitForExit();
    return process.ExitCode;
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
