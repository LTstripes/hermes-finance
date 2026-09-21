using HermesFinance.Launcher;
using System.ComponentModel;
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text;
using System.Text.RegularExpressions;

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
    ("keeps the ordinary launcher surface free of updater and Git mutation paths", NoUpdaterOrGitMovementSurface),
    ("keeps dependency blockers read-only and points to external OPS01 Prepare", PresentsDependencyBlockerReadOnly),
    ("keeps Stable and Preview data boundaries visibly distinct", KeepsProfileBoundariesDistinct),
    ("sanitizes raw paths from owner-facing blockers", SanitizesOwnerFacingBlockers),
    ("requires exactly one stable profile", RequiresExactlyOneStableProfile),
    ("rejects preview aliases to the production database before startup", RejectsUnsafeTupleAliases),
    ("rejects preview hardlinks to the production database", RejectsProductionHardlink),
    ("rejects an existing preview database with the wrong sidecar", RejectsWrongPreviewSidecar),
    ("uses the bundled schema probe for a legacy checkout", UsesBundledSchemaProbeForLegacyCheckout),
    ("detects missing and outdated locked dependencies", DetectsDependencyDrift),
    ("keeps an offline backend cache miss actionable", KeepsOfflineBackendCacheMissActionable),
    ("fails closed on non-cache offline backend errors", FailsClosedOnInvalidOfflineBackendProbe),
    ("resolves PATH commands outside the selected checkout", ResolvesPathCommandsOutsideSelectedCheckout),
    ("fails closed when npm is missing", FailsClosedWhenNpmIsMissing),
    ("packages the branded cat icon", PackagesBrandedCatIcon),
    ("installs shortcuts beside the stable launcher", InstallsShortcutsBesideStableLauncher),
    ("starts and stops only a synthetic runtime", StartsAndStopsSyntheticRuntime),
    ("blocks setup during the real StartSelected lifecycle and restores it after Stop", SetupIsBlockedDuringOwnedStartAndRestoredAfterStop),
    ("returns Ready and enables Start after launcher-owned Stop", OwnerStopReturnsToReady),
    ("recovers Stable ownership after launcher restart", RecoversStableOwnershipAfterLauncherRestart),
    ("recovers Preview ownership after launcher restart", RecoversPreviewOwnershipAfterLauncherRestart),
    ("rejects an unrelated loopback port occupant", RejectsUnrelatedLoopbackPortOccupant),
    ("rejects stale ownership after PID reuse", RejectsStaleOwnershipAfterPidReuse),
    ("cleans ownership when the owned process exits", CleansOwnershipWhenProcessExits),
    ("forbids cross-profile ownership stop", ForbidsCrossProfileOwnershipStop),
    ("fails closed when the ready sidecar stamp cannot be written", FailsClosedOnReadySidecarFailure),
    ("constructs a PowerShell -File command without splitting spaces", ConstructsQuotedStartCommand),
    ("binds the validated database into the actual child process", BindsValidatedDatabaseToChildProcess),
    ("accepts an annotated release tag that peels to HEAD", AcceptsAnnotatedReleaseTag),
    ("rejects Preview identity mismatch despite origin/main matching HEAD", RejectsPreviewExpectedRefMismatchDespiteOriginMain),
    ("shows Stable pinned release identity and production data", ShowsStablePinnedIdentity),
    ("shows Preview main SHA as unreleased with isolated data", ShowsPreviewUnreleasedIdentity),
    ("offers launcher-owned action for identity mismatch", OffersActionableMismatch),
    ("exposes exactly one primary CTA per state", ExposesSinglePrimaryCta),
    ("summarizes health alembic deps checkout in plain language", SummarizesChecksPlainLanguage),
    ("missing config fails closed without placeholder", MissingConfigFailsClosedWithoutPlaceholder),
    ("strips real unknown fields or fails closed", StripsRealUnknownFieldsOrFailsClosed),
    ("offers Refresh not Stop for external port collision", PortCollisionOffersRefreshNotStop),
    ("marks Stable identity mismatch recovery-only", StableMismatchIsRecoveryOnly),
    ("reconfigures an identity-mismatched profile to exact local HEAD", ReconfigureRebindsExactLocalHead),
    ("Stable Ready offers Start primary", StableReadyStartsPrimary),
    ("setup flow creates concrete config from owner selections", SetupFlowCreatesConcreteConfig),
    ("shows application version and SHA for a SHA-pinned Stable setup", ShowsShaPinnedStableVersionAndIdentity),
    ("setup rejects Preview sharing Stable git dir", SetupRejectsPreviewSharingStableGitDir),
    ("prepared setup passes the next preflight identity stage", PreparedSetupPassesPreflightIdentity),
    ("configuration failure offers executable setup action", ConfigFailureOffersSetupAction),
    ("layout keeps the default window free of overlap and clipping", LayoutKeepsDefaultWindowClean),
    ("layout fits Russian labels at 100, 125, and 150 percent scaling", LayoutFitsRussianLabelsWhenScaled),
    ("layout survives narrow and wide resizes", LayoutSurvivesCommonResizes),
    ("layout keeps cards comparable with one obvious primary CTA", LayoutKeepsCardsComparableAndPrimaryObvious),
    ("owner title derives from validated identity, never stale display copy", OwnerTitleDerivesFromValidatedIdentity),
    ("last-run footer derives from validated owner title, never stale display copy", LastRunFooterDerivesFromValidatedIdentity),
    ("loopback badge keeps the address readable without digit wrap", LoopbackBadgeKeepsAddressReadable),
    ("selected and card titles fit without clipping when scaled", SelectedAndCardTitlesFitWhenScaled),
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
    Assert(config.Profiles[0].ExpectedRef == "<exact-prepared-stable-commit>", "The stable profile expected ref must document an exact prepared commit.");
    Assert(config.Profiles[0].DataDir == "<absolute-stable-data-dir>", "The stable profile data directory must use the documented JSON name.");
    Assert(config.Profiles[0].Database == "<absolute-stable-database>", "The stable profile database must use the documented JSON name.");
    Assert(config.Profiles[0].OpenBrowser, "The stable profile browser setting must use the documented JSON name.");
    Assert(config.Profiles[1].Id == "preview", "Preview profile id must be preview.");
    Assert(config.Profiles[1].ExpectedRef == "<exact-prepared-preview-commit>", "Preview expected_ref must document an exact prepared commit.");
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
    Assert(!buttons.Any(button => button.Text is "Подготовить" or "Исправить"), "Launcher must not expose dependency mutation actions.");
    Assert(buttons.Any(button => button.Text == "Остановить" && !button.Enabled), "Stop must be disabled before a runtime is launched.");
    Assert(buttons.Any(button => button.Text == "Открыть Hermes" && !button.Enabled), "Open Hermes must stay disabled until health probes pass.");
    Assert(buttons.Any(button => button.Text == "Диагностика и логи"), "Raw diagnostics must have a dedicated details action.");
    Assert(labels.Any(label => label.Text == "STABLE  ·  PRODUCTION"), "The Stable owner badge is missing.");
    Assert(labels.Any(label => label.Text == "PREVIEW  ·  ISOLATED"), "The Preview owner badge is missing.");
    Assert(labels.Any(label => label.Text.Contains("Release v1.0.0", StringComparison.Ordinal) || label.Text.Contains("UNRELEASED", StringComparison.Ordinal)), "Profile cards must show Stable pinned release or Preview UNRELEASED badge.");

    var status = controls.OfType<TextBox>().Single();
    Assert(status.Parent is not null && status.Parent.Parent is not null && !status.Parent.Parent.Visible, "Raw logs must be hidden from the primary UX.");
}

static void NoUpdaterOrGitMovementSurface()
{
    using var form = MainForm.CreateSyntheticSmoke();
    var buttons = AllControls(form).OfType<Button>().Select(button => button.Text).ToArray();
    foreach (var obsolete in new[] { "Обновить Preview", "Обновить и запустить", "Обновить Stable" })
    {
        Assert(!buttons.Contains(obsolete, StringComparer.Ordinal), $"obsolete updater CTA remains: {obsolete}");
    }

    var sourceRoot = Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..");
    foreach (var file in new[] { "MainForm.cs", "LauncherUi.cs", "ProfileValidator.cs", "LauncherConfig.cs" })
    {
        var source = File.ReadAllText(Path.Combine(sourceRoot, "HermesFinance.Launcher", file));
        Assert(!source.Contains("PreviewUpdateService", StringComparison.Ordinal), $"{file} must not reference PreviewUpdateService");
        Assert(!source.Contains("StableReleaseService", StringComparison.Ordinal), $"{file} must not reference StableReleaseService");
        Assert(!Regex.IsMatch(source, @"(?i)\bgit\s+(fetch|pull|switch|reset)\b"), $"{file} must not expose Git mutation commands");
        Assert(!Regex.IsMatch(source, @"(?i)[""'](fetch|pull|switch|reset)[""']"), $"{file} must not invoke Git mutation verbs");
    }
}

static void PresentsDependencyBlockerReadOnly()
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
    Assert(!buttons.Any(button => button.Text is "Подготовить" or "Исправить"), "Dependency mutation actions must not be present.");
    Assert(!buttons.Single(button => button.Text == "Запустить").Enabled, "Start must remain blocked until dependencies are explicitly prepared.");
    var readiness = AllControls(form).OfType<Label>().Single(label => label.Text.Contains("OPS01 Prepare", StringComparison.Ordinal));
    Assert(readiness.Text.Contains("внешнем подготовленном runtime", StringComparison.Ordinal), "Dependency blockers must point to external preparation.");
    Assert(buttons.Single(button => button.Text == "Остановить").AccessibleName == "Остановить Hermes", "Stop must retain its owner-facing accessible name.");
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
        WriteCommandShim(
            Path.Combine(toolDirectory, "uv.cmd"),
            string.Join("\r\n", new[]
            {
                "@echo off",
                "if \"%~1\"==\"sync\" if \"%~2\"==\"--locked\" if \"%~3\"==\"--dry-run\" if \"%~4\"==\"--offline\" (",
                "  echo error: No interpreter found for Python 3.13 in managed installations",
                "  echo hint: A managed Python download is available for Python 3.13, but Python downloads are set to 'never'",
                "  exit /b 2",
                ")",
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
        using var form = new MainForm(config);
        var apply = typeof(MainForm).GetMethod("ApplyValidated", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("Synthetic smoke could not find the launcher validation presentation.");
        apply.Invoke(form, [validated]);
        var buttons = AllControls(form).OfType<Button>().ToArray();
        Assert(!buttons.Any(button => button.Text is "Подготовить" or "Исправить"), "Offline dependency blockers must not expose mutation actions.");
        Assert(!buttons.Single(button => button.Text == "Запустить").Enabled, "Ordinary Start must remain disabled until preparation completes.");
        Assert(AllControls(form).OfType<Label>().Any(label => label.Text.Contains("OPS01 Prepare", StringComparison.Ordinal)), "Offline dependency blockers must point to external OPS01 Prepare.");
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
        var ownershipDirectory = Path.Combine(root, "ownership");
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
        }, ownershipDirectory);

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

static void SetupIsBlockedDuringOwnedStartAndRestoredAfterStop()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-setup-owner-{Guid.NewGuid():N}");
    var originalPath = Environment.GetEnvironmentVariable("PATH");
    Process? process = null;
    MainForm? form = null;
    try
    {
        var checkout = Path.Combine(root, "stable-runtime");
        var dataDir = Path.Combine(checkout, "data");
        var database = Path.Combine(dataDir, "finance.db");
        var ownershipDirectory = Path.Combine(root, "ownership");
        var toolDirectory = Path.Combine(root, "tools");
        Directory.CreateDirectory(root);
        CreateDependencyValidationLayout(checkout);
        Directory.CreateDirectory(dataDir);
        Directory.CreateDirectory(toolDirectory);
        File.WriteAllText(
            Path.Combine(checkout, "scripts", "start-local.ps1"),
            "$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 8000)\n"
                + "$listener.Start()\n"
                + "Write-Output 'Hermes Finance is ready: http://127.0.0.1:8000'\n"
                + "while ($true) { Start-Sleep -Milliseconds 100 }\n",
            new UTF8Encoding(true));
        RunGit(checkout, "init");
        RunGit(checkout, "config", "user.name", "Hermes launcher safety test");
        RunGit(checkout, "config", "user.email", "hermes-launcher-safety-test");
        RunGit(checkout, "add", ".");
        RunGit(checkout, "commit", "-m", "synthetic setup lifecycle runtime");
        WriteCommandShim(Path.Combine(toolDirectory, "uv.cmd"), "@echo off\r\nexit /b 0\r\n");
        WriteCommandShim(
            Path.Combine(toolDirectory, "npm.cmd"),
            "@echo off\r\necho {\"dependencies\":{}}\r\nexit /b 0\r\n");
        Environment.SetEnvironmentVariable("PATH", toolDirectory + Path.PathSeparator + originalPath);

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

        form = new MainForm(config, ownershipDirectory)
        {
            ShowInTaskbar = false,
            StartPosition = FormStartPosition.Manual,
            Location = new Point(-2000, -2000),
        };
        form.Show();
        form.Hide();

        var validated = ProfileValidator.Validate(config, profile);
        Assert(validated.Dependencies?.Ready == true, "Real preflight fixture must prove locked dependencies ready before StartSelectedAsync.");
        var applyValidated = typeof(MainForm).GetMethod("ApplyValidated", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("Setup lifecycle regression could not find ApplyValidated.");
        applyValidated.Invoke(form, [validated]);
        Assert(GetPrivate<Label>(form, "_readinessTitle").Text == "Готово к запуску", "Real preflight did not establish the Ready state before StartSelectedAsync.");
        Assert(GetButton(form, "Настроить…").Enabled, "Setup must be available in the genuine Ready state.");

        var start = typeof(MainForm).GetMethod("StartSelectedAsync", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("Setup lifecycle regression could not find StartSelectedAsync.");
        var startTask = (Task)start.Invoke(form, null)!;
        var processField = typeof(MainForm).GetField("_launcherProcess", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("Setup lifecycle regression could not find launcher process state.");
        WaitForUi(
            form,
            () => processField.GetValue(form) is not null
                && GetPrivate<Label>(form, "_readinessTitle").Text == "Hermes запускается",
            $"StartSelectedAsync did not expose the Starting/owned-process window (title={GetPrivate<Label>(form, "_readinessTitle").Text}; status={GetPrivate<TextBox>(form, "_status").Text}; task={startTask.Status}; error={startTask.Exception?.GetBaseException().Message}).");
        process = (Process?)processField.GetValue(form);
        Assert(!GetButton(form, "Настроить…").Enabled, "Setup must be disabled immediately while the launcher-owned runtime is starting.");
        startTask.GetAwaiter().GetResult();

        var openSetup = typeof(MainForm).GetMethod("OpenSetupAsync", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("Setup lifecycle regression could not find OpenSetupAsync.");
        var openSetupTask = (Task)openSetup.Invoke(form, null)!;
        openSetupTask.GetAwaiter().GetResult();
        Assert(
            GetPrivate<TextBox>(form, "_status").Text.Contains("Setup refused while a launcher-owned runtime is starting or running.", StringComparison.Ordinal),
            "Setup entry must refuse without opening a modal while the owned runtime is active.");

        var blockedConfig = Path.Combine(root, "blocked-config.json");
        using (var guardedSetup = new SetupForm(blockedConfig, () => true))
        {
            var save = typeof(SetupForm).GetMethod("Save", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
                ?? throw new InvalidOperationException("Setup lifecycle regression could not find SetupForm.Save.");
            save.Invoke(guardedSetup, null);
        }
        Assert(!File.Exists(blockedConfig), "Setup Save must refuse while a launcher-owned runtime is active.");

        WaitForUi(
            form,
            () => GetPrivate<bool>(form, "_ready")
                && GetButton(form, "Остановить").Enabled,
            "Synthetic runtime did not reach Running after StartSelectedAsync.");
        var stop = typeof(MainForm).GetMethod(
                "StopLaunchedStack",
                System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic,
                binder: null,
                types: [typeof(string)],
                modifiers: null)
            ?? throw new InvalidOperationException("Setup lifecycle regression could not find launcher Stop.");
        stop.Invoke(form, ["Synthetic setup lifecycle stopped the runtime."]);
        var startedProcess = process ?? throw new InvalidOperationException("Synthetic process disappeared before Stop.");
        Assert(startedProcess.WaitForExit(5_000), "Synthetic runtime did not stop after launcher-owned Stop.");
        WaitForUi(
            form,
            () => GetPrivate<Label>(form, "_readinessTitle").Text == "Готово к запуску"
                && GetButton(form, "Настроить…").Enabled,
            "Setup was not restored after launcher-owned Stop returned to Ready.");
        process = null;
    }
    finally
    {
        StopSyntheticProcess(process);
        form?.Dispose();
        Environment.SetEnvironmentVariable("PATH", originalPath);
        DeleteSyntheticTree(root);
    }
}

static void OwnerStopReturnsToReady()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-owner-stop-{Guid.NewGuid():N}");
    var originalPath = Environment.GetEnvironmentVariable("PATH");
    Process? process = null;
    MainForm? form = null;
    try
    {
        var checkout = Path.Combine(root, "stable-runtime");
        var dataDir = Path.Combine(checkout, "data");
        var database = Path.Combine(dataDir, "finance.db");
        var ownershipDirectory = Path.Combine(root, "ownership");
        var toolDirectory = Path.Combine(root, "tools");
        Directory.CreateDirectory(root);
        CreateDependencyValidationLayout(checkout);
        Directory.CreateDirectory(dataDir);
        Directory.CreateDirectory(toolDirectory);
        File.WriteAllText(
            Path.Combine(checkout, "scripts", "start-local.ps1"),
            "$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 8000)\n"
                + "$listener.Start()\n"
                + "Write-Output 'Hermes Finance is ready: http://127.0.0.1:8000'\n"
                + "while ($true) { Start-Sleep -Milliseconds 100 }\n",
            new UTF8Encoding(true));
        RunGit(checkout, "init");
        RunGit(checkout, "config", "user.name", "Hermes launcher safety test");
        RunGit(checkout, "config", "user.email", "hermes-launcher-safety-test");
        RunGit(checkout, "add", ".");
        RunGit(checkout, "commit", "-m", "synthetic launcher owner-stop runtime");
        var head = RunGit(checkout, "rev-parse", "HEAD");

        WriteCommandShim(
            Path.Combine(toolDirectory, "uv.cmd"),
            "@echo off\r\nexit /b 0\r\n");
        WriteCommandShim(
            Path.Combine(toolDirectory, "npm.cmd"),
            "@echo off\r\necho {\"dependencies\":{}}\r\nexit /b 0\r\n");
        Environment.SetEnvironmentVariable("PATH", toolDirectory + Path.PathSeparator + originalPath);

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
        var validated = new ValidatedProfile(
            profile,
            checkout,
            dataDir,
            database,
            head,
            "production",
            new DependencyStatus(true, true, "ready", "ready"));

        form = new MainForm(config, ownershipDirectory)
        {
            ShowInTaskbar = false,
            StartPosition = FormStartPosition.Manual,
            Location = new Point(-2000, -2000),
        };
        form.Show();
        form.Hide();

        var startMethod = typeof(MainForm).GetMethod("StartProcess", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("Owner-stop regression could not find the launcher Start implementation.");
        startMethod.Invoke(form, [validated]);
        var processField = typeof(MainForm).GetField("_launcherProcess", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("Owner-stop regression could not find launcher process state.");
        process = (Process?)processField.GetValue(form);
        Assert(process is not null, "Launcher Start must retain the started process for the owner-stop cycle.");
        var startedProcess = process ?? throw new InvalidOperationException("Launcher process was not retained.");

        WaitForUi(
            form,
            () => GetPrivate<bool>(form, "_ready")
                && GetButton(form, "Остановить").Enabled,
            "Synthetic runtime did not reach Running before owner Stop.");
        var markerPath = new LauncherProcessOwnership(ownershipDirectory).GetMarkerPath(validated);
        Assert(File.Exists(markerPath), "Running synthetic runtime must have durable ownership metadata.");

        var stopMethod = typeof(MainForm).GetMethod(
                "StopLaunchedStack",
                System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic,
                binder: null,
                types: [typeof(string)],
                modifiers: null)
            ?? throw new InvalidOperationException("Owner-stop regression could not find the launcher Stop implementation.");
        stopMethod.Invoke(form, ["Synthetic owner-stop regression stopped the runtime."]);
        Assert(startedProcess.WaitForExit(5_000), "Synthetic runtime did not exit after launcher-owned Stop.");

        WaitForUi(
            form,
            () => GetButton(form, "Запустить").Enabled
                && GetPrivate<Label>(form, "_readinessTitle").Text == "Готово к запуску",
            "Launcher-owned Stop did not complete cleanup, preflight, and return the UI to Ready with Start enabled.");
        Assert(!File.Exists(markerPath), "Launcher-owned Stop must remove ownership metadata before Ready is restored.");
        ProfileValidator.AssertPortAvailable();
        Assert(
            !GetPrivate<Label>(form, "_lastLaunch").Text.Contains("код -1", StringComparison.Ordinal),
            "Expected launcher-owned Stop must not remain a fatal exit-code -1 launch status.");
        Assert(
            GetPrivate<Label>(form, "_serviceCheck").ForeColor == Color.FromArgb(102, 227, 190),
            "Automatic post-stop preflight must leave the loopback/Alembic check green.");
        process = null;
    }
    finally
    {
        StopSyntheticProcess(process);
        form?.Dispose();
        Environment.SetEnvironmentVariable("PATH", originalPath);
        DeleteSyntheticTree(root);
    }
}

static void RecoversStableOwnershipAfterLauncherRestart() =>
    RecoversOwnershipAfterLauncherRestart("stable");

static void RecoversPreviewOwnershipAfterLauncherRestart() =>
    RecoversOwnershipAfterLauncherRestart("preview");

static void RecoversOwnershipAfterLauncherRestart(string profileType)
{
    var fixture = CreateOwnershipFixture(profileType);
    Process? process = null;
    try
    {
        var started = StartOwnedSyntheticRuntime(fixture);
        process = started.Process;
        started.Form.Dispose();

        using var reopened = new MainForm(fixture.Config, fixture.OwnershipDirectory);
        var recovered = fixture.Ownership.TryRecover(fixture.ValidatedProfile);
        Assert(recovered is not null, $"A running {profileType} process must be recovered after launcher restart.");
        var recoveredProcess = recovered ?? throw new InvalidOperationException("Recovery unexpectedly returned no process.");
        Assert(recoveredProcess.Marker.Ready, "Only a process that reached the ready marker may be recovered as Running.");

        var validatedField = typeof(MainForm).GetField("_validatedProfile", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
        validatedField.SetValue(reopened, fixture.ValidatedProfile);
        var attach = typeof(MainForm).GetMethod("AttachRecoveredProcess", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
        attach.Invoke(reopened, [fixture.ValidatedProfile, recoveredProcess]);
        Assert((bool)typeof(MainForm).GetField("_ready", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(reopened)!, "Recovered process must be presented as ready/running.");

        var stop = typeof(MainForm).GetMethod("StopLaunchedStack", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic, binder: null, types: [typeof(string)], modifiers: null)!;
        stop.Invoke(reopened, [$"Synthetic {profileType} restart recovery stopped the runtime."]);
        Assert(process.WaitForExit(5_000), "Recovered launcher-owned process did not stop through its proven process tree.");
        Assert(!File.Exists(fixture.Ownership.GetMarkerPath(fixture.ValidatedProfile)), "Stopping a recovered process must remove its ownership marker.");
        process = null;
    }
    finally
    {
        StopSyntheticProcess(process);
        fixture.Form?.Dispose();
        DeleteSyntheticTree(fixture.Root);
    }
}

static void RejectsUnrelatedLoopbackPortOccupant()
{
    using var listener = new TcpListener(IPAddress.Loopback, 8000);
    listener.Start();
    AssertThrows<LauncherValidationException>(ProfileValidator.AssertPortAvailable);
    listener.Stop();
}

static void RejectsStaleOwnershipAfterPidReuse()
{
    var fixture = CreateOwnershipFixture("preview");
    Process? process = null;
    try
    {
        var started = StartOwnedSyntheticRuntime(fixture);
        process = started.Process;
        var markerPath = fixture.Ownership.GetMarkerPath(fixture.ValidatedProfile);
        var marker = JsonSerializer.Deserialize<LauncherOwnershipMarker>(File.ReadAllText(markerPath))!
            with { ProcessStartTimeUtcTicks = started.Process.StartTime.ToUniversalTime().Ticks - 1 };
        File.WriteAllText(markerPath, JsonSerializer.Serialize(marker));

        Assert(fixture.Ownership.TryRecover(fixture.ValidatedProfile) is null, "A reused PID with a different process start time must fail closed.");
        Assert(!File.Exists(markerPath), "A stale PID marker must be removed or ignored before another process can be considered owned.");
    }
    finally
    {
        StopSyntheticProcess(process);
        fixture.Form?.Dispose();
        DeleteSyntheticTree(fixture.Root);
    }
}

static void CleansOwnershipWhenProcessExits()
{
    var fixture = CreateOwnershipFixture("stable");
    Process? process = null;
    try
    {
        var started = StartOwnedSyntheticRuntime(fixture);
        process = started.Process;
        var markerPath = fixture.Ownership.GetMarkerPath(fixture.ValidatedProfile);
        Assert(File.Exists(markerPath), "A started runtime must have durable ownership metadata.");
        process.Kill(entireProcessTree: true);
        Assert(process.WaitForExit(5_000), "Synthetic owned process did not exit.");
        var deadline = DateTime.UtcNow.AddSeconds(5);
        while (DateTime.UtcNow < deadline && File.Exists(markerPath))
        {
            Thread.Sleep(50);
        }
        Assert(!File.Exists(markerPath), "Owned process exit must clean its durable ownership marker.");
        process = null;
    }
    finally
    {
        StopSyntheticProcess(process);
        fixture.Form?.Dispose();
        DeleteSyntheticTree(fixture.Root);
    }
}

static void ForbidsCrossProfileOwnershipStop()
{
    var fixture = CreateOwnershipFixture("stable");
    Process? process = null;
    try
    {
        var previewCheckout = Path.Combine(fixture.Root, "preview-checkout");
        var previewData = Path.Combine(fixture.Root, "preview-data");
        Directory.CreateDirectory(previewCheckout);
        Directory.CreateDirectory(previewData);
        var preview = new ValidatedProfile(
            new LauncherProfile
            {
                Id = "preview",
                DisplayName = "Preview",
                Type = "preview",
                Checkout = previewCheckout,
                ExpectedRef = "preview-head",
                DataDir = previewData,
                Database = Path.Combine(previewData, "finance.db"),
                OpenBrowser = false,
            },
            previewCheckout,
            previewData,
            Path.Combine(previewData, "finance.db"),
            "preview-head",
            "preview");
        var config = new LauncherConfig
        {
            Version = 1,
            CanonicalProduction = new CanonicalProduction { Checkout = fixture.ValidatedProfile.Checkout, DataDir = fixture.ValidatedProfile.DataDir, Database = fixture.ValidatedProfile.Database },
            Profiles = [fixture.Profile, preview.Profile],
        };
        using var form = new MainForm(config, fixture.OwnershipDirectory);
        var start = typeof(MainForm).GetMethod("StartProcess", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
        start.Invoke(form, [fixture.ValidatedProfile]);
        process = (Process)typeof(MainForm).GetField("_launcherProcess", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(form)!;
        WaitForOwnedMarker(fixture, process);
        Assert(fixture.Ownership.MarkReady(fixture.ValidatedProfile, process), "Synthetic Stable ownership should become ready before cross-profile stop test.");

        typeof(MainForm).GetField("_validatedProfile", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.SetValue(form, fixture.ValidatedProfile);
        typeof(MainForm).GetField("_selectedProfile", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.SetValue(form, preview.Profile);
        var stop = typeof(MainForm).GetMethod("StopLaunchedStack", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic, binder: null, types: [typeof(string)], modifiers: null)!;
        stop.Invoke(form, ["cross-profile stop probe"]);
        Assert(!process.HasExited, "Stable ownership must not be stoppable while Preview is selected.");
        Assert(File.Exists(fixture.Ownership.GetMarkerPath(fixture.ValidatedProfile)), "Cross-profile Stop must preserve Stable ownership metadata.");
    }
    finally
    {
        StopSyntheticProcess(process);
        fixture.Form?.Dispose();
        DeleteSyntheticTree(fixture.Root);
    }
}

static (string Root, string OwnershipDirectory, LauncherProfile Profile, ValidatedProfile ValidatedProfile, LauncherConfig Config, LauncherProcessOwnership Ownership, MainForm? Form) CreateOwnershipFixture(string profileType)
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-ownership-{profileType}-{Guid.NewGuid():N}");
    var checkout = Path.Combine(root, "checkout");
    var dataDir = Path.Combine(root, "data");
    var database = Path.Combine(dataDir, "finance.db");
    var ownershipDirectory = Path.Combine(root, "ownership");
    Directory.CreateDirectory(Path.Combine(checkout, "scripts"));
    Directory.CreateDirectory(dataDir);
    var script = Path.Combine(checkout, "scripts", "start-local.ps1");
    File.WriteAllText(script, ""
        + "$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 8000)\n"
        + "$listener.Start()\n"
        + "Write-Output 'Hermes Finance is ready: http://127.0.0.1:8000'\n"
        + "while ($true) { Start-Sleep -Milliseconds 100 }\n", new UTF8Encoding(true));
    var profile = new LauncherProfile
    {
        Id = profileType,
        DisplayName = profileType,
        Type = profileType,
        Checkout = checkout,
        ExpectedRef = $"{profileType}-head",
        DataDir = dataDir,
        Database = database,
        OpenBrowser = false,
    };
    var validated = new ValidatedProfile(profile, checkout, dataDir, database, $"{profileType}-head", profileType == "stable" ? "production" : "preview");
    var config = new LauncherConfig
    {
        Version = 1,
        CanonicalProduction = new CanonicalProduction { Checkout = checkout, DataDir = dataDir, Database = database },
        Profiles = [profile],
    };
    return (root, ownershipDirectory, profile, validated, config, new LauncherProcessOwnership(ownershipDirectory), null);
}

static (MainForm Form, Process Process) StartOwnedSyntheticRuntime((string Root, string OwnershipDirectory, LauncherProfile Profile, ValidatedProfile ValidatedProfile, LauncherConfig Config, LauncherProcessOwnership Ownership, MainForm? Form) fixture)
{
    var form = new MainForm(fixture.Config, fixture.OwnershipDirectory);
    var start = typeof(MainForm).GetMethod("StartProcess", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
    start.Invoke(form, [fixture.ValidatedProfile]);
    var process = (Process)typeof(MainForm).GetField("_launcherProcess", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(form)!;
    WaitForOwnedMarker(fixture, process);
    Assert(fixture.Ownership.MarkReady(fixture.ValidatedProfile, process), "Synthetic runtime must be able to persist a ready ownership marker.");
    return (form, process);
}

static void WaitForOwnedMarker((string Root, string OwnershipDirectory, LauncherProfile Profile, ValidatedProfile ValidatedProfile, LauncherConfig Config, LauncherProcessOwnership Ownership, MainForm? Form) fixture, Process process)
{
    var deadline = DateTime.UtcNow.AddSeconds(15);
    while (DateTime.UtcNow < deadline
        && (!File.Exists(fixture.Ownership.GetMarkerPath(fixture.ValidatedProfile))
            || process.HasExited
            || !LauncherProcessOwnership.IsLoopbackPortOwnedByProcessTree(process.Id)))
    {
        Thread.Sleep(100);
    }
    Assert(!process.HasExited, "Synthetic launcher-owned process exited before the ownership probe completed.");
    Assert(File.Exists(fixture.Ownership.GetMarkerPath(fixture.ValidatedProfile)), "Synthetic launcher Start must write an ownership marker.");
}

static void StopSyntheticProcess(Process? process)
{
    if (process is null)
    {
        return;
    }
    try
    {
        if (!process.HasExited)
        {
            process.Kill(entireProcessTree: true);
            process.WaitForExit(5_000);
        }
    }
    catch (InvalidOperationException)
    {
    }
    catch (Win32Exception)
    {
    }
}

static T GetPrivate<T>(MainForm form, string fieldName)
{
    var field = typeof(MainForm).GetField(fieldName, System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
        ?? throw new InvalidOperationException($"Could not find launcher field '{fieldName}'.");
    return (T)(field.GetValue(form) ?? throw new InvalidOperationException($"Launcher field '{fieldName}' is null."));
}

static Button GetButton(MainForm form, string text) =>
    AllControls(form).OfType<Button>().Single(button => button.Text == text);

static void WaitForUi(MainForm form, Func<bool> condition, string failureMessage)
{
    var deadline = DateTime.UtcNow.AddSeconds(20);
    while (DateTime.UtcNow < deadline && !condition())
    {
        Application.DoEvents();
        Thread.Sleep(50);
    }
    Application.DoEvents();
    Assert(condition(), failureMessage);
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


static void RejectsPreviewExpectedRefMismatchDespiteOriginMain()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-preview-identity-{Guid.NewGuid():N}");
    var stableCheckout = Path.Combine(root, "stable");
    var previewCheckout = Path.Combine(root, "preview");
    var previewData = Path.Combine(root, "preview-data");
    try
    {
        CreateRuntimeLayout(stableCheckout);
        InitSyntheticRepo(stableCheckout, "synthetic stable identity");
        CreateRuntimeLayout(previewCheckout);
        Directory.CreateDirectory(previewData);
        InitSyntheticRepo(previewCheckout, "synthetic preview configured identity");
        RunGit(previewCheckout, "tag", "configured-preview");
        File.WriteAllText(Path.Combine(previewCheckout, "identity-marker.txt"), "synthetic current preview");
        RunGit(previewCheckout, "add", ".");
        RunGit(previewCheckout, "commit", "-m", "synthetic preview HEAD");
        RunGit(previewCheckout, "update-ref", "refs/remotes/origin/main", "HEAD");

        var profile = new LauncherProfile
        {
            Id = "preview",
            DisplayName = "Hermes Finance — Preview",
            Type = "preview",
            Checkout = previewCheckout,
            ExpectedRef = "refs/tags/configured-preview",
            DataDir = previewData,
            Database = Path.Combine(previewData, "finance.db"),
            OpenBrowser = false,
        };
        AssertThrowsMessage(
            () => ProfileValidator.AssertGitIdentity(profile, previewCheckout, stableCheckout),
            "Checkout identity does not match this profile.");
    }
    finally
    {
        DeleteSyntheticTree(root);
    }
}

static void ShowsStablePinnedIdentity()
{
    var stable = new LauncherProfile
    {
        Id = "stable",
        DisplayName = "Hermes Finance — Stable",
        Type = "stable",
        Checkout = "C:\\synthetic\\stable",
        ExpectedRef = "refs/tags/v1.0.0",
        DataDir = "C:\\synthetic\\stable\\data",
        Database = "C:\\synthetic\\stable\\data\\finance.db",
        OpenBrowser = false,
    };
    // Stable must show pinned release tag/SHA + production data identity without manual JSON
    var label = LauncherUi.StableIdentityLabel(stable, "d04f46696a991ea59066b59d4870980ac4b69089");
    Assert(label.Contains("v1.0.0", StringComparison.Ordinal), "Stable identity must show pinned release version/tag.");
    Assert(label.Contains("d04f466", StringComparison.Ordinal), "Stable identity must show short SHA.");
    Assert(label.Contains("production", StringComparison.OrdinalIgnoreCase), "Stable identity must show production data identity.");
    Assert(!label.Contains("UNRELEASED", StringComparison.OrdinalIgnoreCase), "Stable must not be marked unreleased.");
    // Card must also carry production data boundary
    Assert(LauncherUi.DataBoundary("stable") == "Canonical production data", "Stable data boundary must be canonical production.");
}

static void ShowsPreviewUnreleasedIdentity()
{
    var preview = new LauncherProfile
    {
        Id = "preview",
        DisplayName = "Hermes Finance — Preview",
        Type = "preview",
        Checkout = "C:\\synthetic\\preview",
        ExpectedRef = "refs/remotes/origin/main",
        DataDir = "C:\\synthetic\\preview\\data",
        Database = "C:\\synthetic\\preview\\data\\finance.db",
        OpenBrowser = false,
    };
    var labelBehind = LauncherUi.PreviewIdentityLabel(preview, "aaaaaaa1111111111111111111111111111111111");
    Assert(labelBehind.Contains("main", StringComparison.OrdinalIgnoreCase), "Preview must show main.");
    Assert(labelBehind.Contains("UNRELEASED", StringComparison.Ordinal), "Preview must be clearly marked UNRELEASED.");
    Assert(labelBehind.Contains("Isolated", StringComparison.OrdinalIgnoreCase) || labelBehind.Contains("isolated", StringComparison.OrdinalIgnoreCase), "Preview must show isolated data identity.");
    var labelCurrent = LauncherUi.PreviewIdentityLabel(preview, "cccccccc33333333333333333333333333333333333");
    Assert(labelCurrent.Contains("UNRELEASED", StringComparison.Ordinal), "Preview at origin/main is still UNRELEASED code.");
    // Card data boundary for preview must be distinct from stable
    Assert(LauncherUi.DataBoundary("preview") != LauncherUi.DataBoundary("stable"), "Preview and Stable data boundaries must differ.");
}

static void OffersActionableMismatch()
{
    var preview = new LauncherProfile { Id = "preview", DisplayName = "Preview", Type = "preview", Checkout = "C:\\p", ExpectedRef = "HEAD", DataDir = "C:\\p\\data", Database = "C:\\p\\data\\finance.db", OpenBrowser = false };
    var stable = new LauncherProfile { Id = "stable", DisplayName = "Stable", Type = "stable", Checkout = "C:\\s", ExpectedRef = "refs/tags/v1.0.0", DataDir = "C:\\s\\data", Database = "C:\\s\\data\\finance.db", OpenBrowser = false };

    var mismatch = new LauncherValidationException("Checkout identity does not match this profile.");
    var planPreview = LauncherUi.PlanPrimaryAction(LauncherReadinessState.Blocked, null, preview, mismatch);
    Assert(planPreview.Primary == LauncherPrimaryAction.Refresh, "Identity mismatch on Preview must offer read-only Refresh, not an update action.");

    var planBlockedGeneric = LauncherUi.PlanPrimaryAction(LauncherReadinessState.Blocked, null, stable, mismatch);
    Assert(planBlockedGeneric.Primary != LauncherPrimaryAction.None, "Blocked state must offer at least one actionable CTA.");

    var human = LauncherUi.OwnerFacingFailure(mismatch.Message);
    Assert(human.Contains("expected_ref", StringComparison.OrdinalIgnoreCase) || human.Contains("Code identity", StringComparison.OrdinalIgnoreCase), "Human failure must explain mismatch without implying launcher update.");
    Assert(!human.Contains("C:\\", StringComparison.Ordinal), "Human message must not leak raw paths.");
}

static void ExposesSinglePrimaryCta()
{
    var stable = StableProfile("C:\\synthetic\\stable", "C:\\synthetic\\stable\\data", "C:\\synthetic\\stable\\data\\finance.db", "refs/tags/v1.0.0");
    var config = new LauncherConfig
    {
        Version = 1,
        CanonicalProduction = new CanonicalProduction { Checkout = stable.Checkout, DataDir = stable.DataDir, Database = stable.Database },
        Profiles = [stable],
    };
    using var formReady = new MainForm(config);
    var validatedReady = new ValidatedProfile(stable, stable.Checkout, stable.DataDir, stable.Database, "abc1234567890", "production", new DependencyStatus(true, true, "ready", "ready"));
    var apply = typeof(MainForm).GetMethod("ApplyValidated", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
    apply.Invoke(formReady, [validatedReady]);
    var buttonsReady = AllControls(formReady).OfType<Button>().ToArray();
    var primaryReady = buttonsReady.Where(b => b.Enabled && (b.Text == "Запустить" || b.Text == "Открыть Hermes" || b.Text == "Остановить")).ToList();
    Assert(primaryReady.Count == 1 && primaryReady[0].Text == "Запустить", $"Ready state must have exactly one primary CTA 'Запустить', found {string.Join(",", primaryReady.Select(b=>b.Text))}.");

    using var formNeeds = new MainForm(config);
    var validatedNeeds = new ValidatedProfile(stable, stable.Checkout, stable.DataDir, stable.Database, "abc", "production", new DependencyStatus(false, false, "needs preparation", "needs preparation"));
    apply.Invoke(formNeeds, [validatedNeeds]);
    var buttonsNeeds = AllControls(formNeeds).OfType<Button>().ToArray();
    Assert(!buttonsNeeds.Any(b => b.Text is "Подготовить" or "Исправить"), "NeedsPreparation must not expose dependency mutation CTAs.");
    Assert(buttonsNeeds.Single(b => b.Text == "Обновить проверку").Enabled, "NeedsPreparation must offer read-only Refresh as the primary CTA.");
    Assert(!buttonsNeeds.Single(b=>b.Text=="Запустить").Enabled, "Start must not be primary when preparation needed.");

    // Blocked identity mismatch on Preview remains read-only Refresh.
    var preview = new LauncherProfile { Id="preview", DisplayName="Preview", Type="preview", Checkout="C:\\p", ExpectedRef="HEAD", DataDir="C:\\p\\data", Database="C:\\p\\data\\finance.db", OpenBrowser=false };
    var previewConfig = new LauncherConfig
    {
        Version = 1,
        CanonicalProduction = new CanonicalProduction { Checkout = stable.Checkout, DataDir = stable.DataDir, Database = stable.Database },
        Profiles = [stable, preview],
    };
    using var formBlocked = new MainForm(previewConfig);
    var applyBlocked = typeof(MainForm).GetMethod("ApplyBlocked", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
    // Use overload with exception
    applyBlocked.Invoke(formBlocked, [preview, new LauncherValidationException("Checkout identity does not match this profile."), false]);
    var buttonsBlocked = AllControls(formBlocked).OfType<Button>().ToArray();
    Assert(buttonsBlocked.Single(b=>b.Text=="Обновить проверку").Enabled, "Blocked Preview identity mismatch must enable Refresh as actionable primary.");
}

static void SummarizesChecksPlainLanguage()
{
    // Human checks must be plain language, raw diagnostics secondary
    var stable = StableProfile("C:\\s", "C:\\s\\data", "C:\\s\\data\\finance.db", "refs/tags/v1.0.0");
    var config = new LauncherConfig
    {
        Version = 1,
        CanonicalProduction = new CanonicalProduction { Checkout = stable.Checkout, DataDir = stable.DataDir, Database = stable.Database },
        Profiles = [stable],
    };
    using var form = new MainForm(config);
    var validated = new ValidatedProfile(stable, stable.Checkout, stable.DataDir, stable.Database, "abc", "production", new DependencyStatus(true, true, "ready (locked environment is synchronized)", "ready (package-lock dependency tree is present)"), null);
    var apply = typeof(MainForm).GetMethod("ApplyValidated", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
    apply.Invoke(form, [validated]);
    var labels = AllControls(form).OfType<Label>().ToArray();
    // Checks are the 4 rows: we look for human labels
    Assert(labels.Any(l => l.Text.Contains("production", StringComparison.OrdinalIgnoreCase) || l.Text.Contains("isolated", StringComparison.OrdinalIgnoreCase)), "Data boundary check must be human language.");
    // Diagnostics TextBox must be hidden (secondary layer)
    var status = AllControls(form).OfType<TextBox>().Single();
    Assert(!status.Parent!.Parent!.Visible, "Raw diagnostics must remain secondary (hidden) layer.");
    // Health/Alembic summarized: service check should mention port or Alembic OK in plain language, not raw paths
    var checks = AllControls(form).OfType<Label>().Where(l => l.Text.Contains("locked") || l.Text.Contains("порт") || l.Text.Contains("Alembic")).ToArray();
    Assert(checks.Length > 0, "Health/Alembic/deps must be summarized in human plain language.");
}

static void MissingConfigFailsClosedWithoutPlaceholder()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-missing-config-{Guid.NewGuid():N}");
    Directory.CreateDirectory(root);
    try
    {
        var configPath = Path.Combine(root, "launcher", "config.json");
        Assert(!File.Exists(configPath), "Fixture must start without a config file.");
        try
        {
            LauncherConfig.LoadOrCreate(configPath, out _);
            throw new InvalidOperationException("Missing config must fail closed, not auto-create.");
        }
        catch (LauncherValidationException exception)
        {
            Assert(exception.Message.Contains("not found", StringComparison.OrdinalIgnoreCase), "Missing config failure must say the config was not found.");
            Assert(exception.Message.Contains("install.ps1", StringComparison.OrdinalIgnoreCase), "Missing config failure must point at launcher-owned setup (install.ps1).");
        }
        Assert(!File.Exists(configPath), "Missing config must NOT create a placeholder file demanding manual JSON.");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}

static void StripsRealUnknownFieldsOrFailsClosed()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-unknown-fields-{Guid.NewGuid():N}");
    Directory.CreateDirectory(root);
    try
    {
        var checkout = Path.Combine(root, "checkout");
        var dataDir = Path.Combine(root, "data");
        var database = Path.Combine(dataDir, "finance.db");
        var configPath = Path.Combine(root, "launcher", "config.json");
        Directory.CreateDirectory(Path.GetDirectoryName(configPath)!);
        var valid = new LauncherConfig
        {
            Version = 1,
            CanonicalProduction = new CanonicalProduction { Checkout = checkout, DataDir = dataDir, Database = database },
            Profiles =
            [
                new LauncherProfile { Id = "stable", DisplayName = "Stable", Type = "stable", Checkout = checkout, ExpectedRef = "refs/tags/v1.0.0", DataDir = dataDir, Database = database, OpenBrowser = false },
            ],
        };
        var node = System.Text.Json.Nodes.JsonNode.Parse(JsonSerializer.Serialize(valid)) as System.Text.Json.Nodes.JsonObject
            ?? throw new InvalidOperationException("Could not build unknown-field fixture.");
        node["token"] = "forbidden";
        (node["canonical_production"] as System.Text.Json.Nodes.JsonObject)!["extra_canonical"] = "strip-me";
        (node["profiles"] as System.Text.Json.Nodes.JsonArray)![0]!["unknown_field"] = 123;
        File.WriteAllText(configPath, node.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));

        var stripped = LauncherConfig.LoadOrCreate(configPath, out var diag);
        Assert(stripped.Profiles.Count == 1 && stripped.Profiles[0].ExpectedRef == "refs/tags/v1.0.0", "Stripped config must keep known fields intact.");
        Assert(diag.Contains("removed", StringComparison.OrdinalIgnoreCase) || diag.Contains("unknown", StringComparison.OrdinalIgnoreCase), "Unknown-field strip must be diagnosable.");
        var rewritten = File.ReadAllText(configPath);
        Assert(!rewritten.Contains("token", StringComparison.Ordinal), "Rewritten config must not keep the top-level unknown field.");
        Assert(!rewritten.Contains("unknown_field", StringComparison.Ordinal), "Rewritten config must not keep the profile unknown field.");
        Assert(!rewritten.Contains("extra_canonical", StringComparison.Ordinal), "Rewritten config must not keep the canonical unknown field.");

        // Fail-closed: unknown field plus a schema break that stripping cannot repair.
        var brokenPath = Path.Combine(root, "launcher", "broken.json");
        File.WriteAllText(brokenPath, """{"version":1,"canonical_production":{"checkout":"C:\\x","data_dir":"C:\\x\\data","database":"C:\\x\\data\\finance.db"},"profiles":"not-an-array","token":"forbidden"}""");
        var before = File.ReadAllText(brokenPath);
        AssertThrows<JsonException>(() => LauncherConfig.LoadOrCreate(brokenPath, out _));
        Assert(File.ReadAllText(brokenPath) == before, "Unrepairable config must be left untouched (fail closed).");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}


static void PortCollisionOffersRefreshNotStop()
{
    var stable = StableProfile("C:\\synthetic\\stable", "C:\\synthetic\\stable\\data", "C:\\synthetic\\stable\\data\\finance.db", "refs/tags/v1.0.0");
    var preview = new LauncherProfile { Id = "preview", DisplayName = "Preview", Type = "preview", Checkout = "C:\\p", ExpectedRef = "HEAD", DataDir = "C:\\p\\data", Database = "C:\\p\\data\\finance.db", OpenBrowser = false };
    var portEx = new LauncherValidationException("Another Hermes instance is running; v1 is single-instance on port 8000.");

    var planStable = LauncherUi.PlanPrimaryAction(LauncherReadinessState.Blocked, null, stable, portEx);
    var planPreview = LauncherUi.PlanPrimaryAction(LauncherReadinessState.Blocked, null, preview, portEx);
    Assert(planStable.Primary == LauncherPrimaryAction.Refresh, $"External port collision must offer Refresh, not {planStable.Primary} (Stable).");
    Assert(planPreview.Primary == LauncherPrimaryAction.Refresh, $"External port collision must offer Refresh, not {planPreview.Primary} (Preview).");

    var human = LauncherUi.OwnerFacingFailure(portEx.Message);
    Assert(!human.Contains("«Остановить»", StringComparison.Ordinal), "Port-collision guidance must not promise a launcher Stop action.");
    Assert(human.Contains("«Обновить проверку»", StringComparison.Ordinal), "Port-collision guidance must point at Refresh after manual stop.");

    // Running (launcher-owned process) keeps Stop as the executable primary.
    var planRunning = LauncherUi.PlanPrimaryAction(LauncherReadinessState.Running, null, stable, null);
    Assert(planRunning.Primary == LauncherPrimaryAction.Stop, "Running state must keep Stop for the launcher-owned process.");

    // UI level: Blocked port must not enable Stop when the launcher owns no process.
    var config = new LauncherConfig
    {
        Version = 1,
        CanonicalProduction = new CanonicalProduction { Checkout = stable.Checkout, DataDir = stable.DataDir, Database = stable.Database },
        Profiles = [stable],
    };
    using var form = new MainForm(config);
    var applyBlocked = typeof(MainForm).GetMethod("ApplyBlocked", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
        ?? throw new InvalidOperationException("Could not find ApplyBlocked for port-collision presentation.");
    applyBlocked.Invoke(form, [stable, portEx, false]);
    var buttons = AllControls(form).OfType<Button>().ToArray();
    Assert(!buttons.Single(button => button.Text == "Остановить").Enabled, "Stop must be disabled for an external port collision the launcher cannot stop.");
    Assert(buttons.Single(button => button.Text == "Обновить проверку").Enabled, "Refresh must be enabled for an external port collision.");
}

static void StableMismatchIsRecoveryOnly()
{
    var stable = StableProfile("C:\\s", "C:\\s\\data", "C:\\s\\data\\finance.db", "refs/tags/v1.0.0");
    var preview = new LauncherProfile { Id = "preview", DisplayName = "Preview", Type = "preview", Checkout = "C:\\p", ExpectedRef = "HEAD", DataDir = "C:\\p\\data", Database = "C:\\p\\data\\finance.db", OpenBrowser = false };
    var mismatch = new LauncherValidationException("Checkout identity does not match this profile.");

    var planStable = LauncherUi.PlanPrimaryAction(LauncherReadinessState.Blocked, null, stable, mismatch);
    Assert(planStable.Primary == LauncherPrimaryAction.Refresh, $"Stable identity mismatch must be recovery-only Refresh, not {planStable.Primary}. No launcher-owned fix may be promised.");
    var human = LauncherUi.OwnerFacingFailure(mismatch.Message);
    Assert(!human.Contains("C:\\", StringComparison.Ordinal), "Human message must not leak raw paths.");
    Assert(human.Contains("expected_ref", StringComparison.OrdinalIgnoreCase) || human.Contains("Обновить проверку", StringComparison.Ordinal), "Stable mismatch guidance must point at released-tag verification plus Refresh.");

    // Preview mismatch is also read-only: current-main synchronization is outside the launcher.
    var planPreview = LauncherUi.PlanPrimaryAction(LauncherReadinessState.Blocked, null, preview, mismatch);
    Assert(planPreview.Primary == LauncherPrimaryAction.Refresh, "Preview identity mismatch must remain read-only Refresh.");
}

static void ReconfigureRebindsExactLocalHead()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-reconfigure-{Guid.NewGuid():N}");
    var stableCheckout = Path.Combine(root, "stable");
    var stableData = Path.Combine(root, "stable-data");
    var previewCheckout = Path.Combine(root, "preview");
    var previewData = Path.Combine(root, "preview-data");
    try
    {
        CreateRuntimeLayout(stableCheckout);
        Directory.CreateDirectory(stableData);
        InitSyntheticRepo(stableCheckout, "synthetic Stable initial identity");
        CreateRuntimeLayout(previewCheckout);
        Directory.CreateDirectory(previewData);
        InitSyntheticRepo(previewCheckout, "synthetic Preview identity");

        var original = LauncherSetup.BuildConfig(stableCheckout, stableData, previewCheckout, previewData);
        var stable = original.Profiles.Single(profile => profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase));
        File.WriteAllText(Path.Combine(stableCheckout, "identity-marker.txt"), "synthetic Stable replacement identity");
        RunGit(stableCheckout, "add", ".");
        RunGit(stableCheckout, "commit", "-m", "synthetic Stable replacement HEAD");
        var newHead = RunGit(stableCheckout, "rev-parse", "HEAD");

        using var form = new MainForm(original);
        var applyBlocked = typeof(MainForm).GetMethod("ApplyBlocked", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("Could not find ApplyBlocked for reconfigure presentation.");
        applyBlocked.Invoke(form, [stable, new LauncherValidationException("Checkout identity does not match this profile."), false]);
        var buttons = AllControls(form).OfType<Button>().ToArray();
        Assert(buttons.Single(button => button.Text == "Настроить…").Enabled, "Identity mismatch must expose Reconfigure as a secondary action.");
        Assert(!buttons.Single(button => button.Text == "Запустить").Enabled, "Identity mismatch must keep Start fail-closed until setup saves a new identity.");

        var rebound = LauncherSetup.BuildConfig(stableCheckout, stableData, previewCheckout, previewData);
        var configPath = Path.Combine(root, "launcher", "config.json");
        LauncherSetup.WriteConfig(rebound, configPath);
        var saved = LauncherConfig.Load(configPath);
        var savedStable = saved.Profiles.Single(profile => profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase));
        Assert(savedStable.ExpectedRef == newHead, "Saving Setup must rebind Stable to the new exact local HEAD.");
        var resolvedSavedHead = ProfileValidator.AssertGitIdentity(savedStable, stableCheckout, stableCheckout);
        Assert(resolvedSavedHead == newHead, "Saved Setup identity must pass the next Stable preflight at the new exact local HEAD.");
    }
    finally
    {
        DeleteSyntheticTree(root);
    }
}

static string[] PrimaryCtaTexts() =>
[
    "Запустить", "Открыть Hermes", "Остановить",
];

static List<string> EnabledPrimaries(MainForm form) =>
    AllControls(form).OfType<Button>().Where(button => button.Enabled
        && PrimaryCtaTexts().Contains(button.Text)).Select(button => button.Text).ToList();

static void ApplyValidatedOn(MainForm form, ValidatedProfile validated)
{
    var apply = typeof(MainForm).GetMethod("ApplyValidated", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
        ?? throw new InvalidOperationException("Could not find ApplyValidated for CTA planning.");
    apply.Invoke(form, [validated]);
}


static void StableReadyStartsPrimary()
{
    var stable = StableProfile("C:\\synthetic\\stable", "C:\\synthetic\\stable\\data", "C:\\synthetic\\stable\\data\\finance.db", "refs/tags/v1.0.0");
    using var form = new MainForm(new LauncherConfig
    {
        Version = 1,
        CanonicalProduction = new CanonicalProduction { Checkout = stable.Checkout, DataDir = stable.DataDir, Database = stable.Database },
        Profiles = [stable],
    });
    var validated = new ValidatedProfile(
        stable, stable.Checkout, stable.DataDir, stable.Database, "abc1234567890",
        "production", new DependencyStatus(true, true, "ready", "ready"));
    ApplyValidatedOn(form, validated);
    var primaries = EnabledPrimaries(form);
    Assert(primaries.Count == 1 && primaries[0] == "Запустить", $"Stable Ready must have exactly one primary CTA 'Запустить', found [{string.Join(",", primaries)}].");
}

// #302: a validated v1.0.0 Stable must never be called "Stable 0.8.0".
// Older installs may carry the stale version inside display_name; the
// owner title is derived from the profile without that stale token while
// the version itself comes only from validated release identity.
static void OwnerTitleDerivesFromValidatedIdentity()
{
    LauncherProfile StaleStable() => new()
    {
        Id = "stable",
        DisplayName = "Hermes Finance — Stable 0.8.0",
        Type = "stable",
        Checkout = "C:\\synthetic\\stable",
        ExpectedRef = "refs/tags/v1.0.0",
        DataDir = "C:\\synthetic\\stable\\data",
        Database = "C:\\synthetic\\stable\\data\\finance.db",
        OpenBrowser = false,
    };
    Assert(LauncherUi.OwnerTitle(StaleStable()) == "Hermes Finance — Stable",
        "OwnerTitle must strip the stale trailing version from a Stable display name.");
    var stalePreview = new LauncherProfile
    {
        Id = "preview",
        DisplayName = "Hermes Finance БЂ 0.7 Preview",
        Type = "preview",
        Checkout = "C:\\synthetic\\preview",
        ExpectedRef = "refs/remotes/origin/main",
        DataDir = "C:\\synthetic\\preview\\data",
        Database = "C:\\synthetic\\preview\\data\\finance.db",
        OpenBrowser = false,
    };
    Assert(LauncherUi.OwnerTitle(stalePreview) == "Hermes Finance — Preview",
        "OwnerTitle must replace a legacy mojibake/version Preview display name with the canonical Unicode owner title.");

    var stable = StaleStable();
    using var form = new MainForm(new LauncherConfig
    {
        Version = 1,
        CanonicalProduction = new CanonicalProduction { Checkout = stable.Checkout, DataDir = stable.DataDir, Database = stable.Database },
        Profiles = [stable],
    });
    ForceLayout(form, new Size(960, 820));
    var beforeLabels = AllControls(form).OfType<Label>().Select(label => label.Text).ToArray();
    Assert(!beforeLabels.Any(text => text.Contains("0.8.0", StringComparison.Ordinal)),
        "No owner-facing label may show the stale 0.8.0 display copy, even before validation.");

    var validated = new ValidatedProfile(
        stable, stable.Checkout, stable.DataDir, stable.Database, "d04f46696a991ea59066b59d4870980ac4b69089",
        "production", new DependencyStatus(true, true, "ready", "ready"));
    ApplyValidatedOn(form, validated);
    ForceLayout(form, new Size(960, 820));
    var afterLabels = AllControls(form).OfType<Label>().Select(label => label.Text).ToArray();
    Assert(!afterLabels.Any(text => text.Contains("0.8.0", StringComparison.Ordinal)),
        "A validated v1.0.0 Stable must never show Stable 0.8.0 anywhere.");
    Assert(afterLabels.Any(text => text.Contains("v1.0.0", StringComparison.Ordinal)),
        "The validated Stable identity must show the proven v1.0.0 release.");
    var selectedName = (Label)typeof(MainForm)
        .GetField("_selectedName", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!
        .GetValue(form)!;
    Assert(selectedName.Text == "Hermes Finance — Stable",
        $"The selected-profile title must be the version-free owner title, found '{selectedName.Text}'.");
}

// #308: bottom-right last-run footer must never surface stale
// profiles[].display_name (e.g. "Hermes Finance — Stable 0.8.0").
// The footer label is normalized through LauncherUi.OwnerTitle and the
// time suffix "  ·  HH:mm" stays intact.
static void LastRunFooterDerivesFromValidatedIdentity()
{
    LauncherProfile StaleStable() => new()
    {
        Id = "stable",
        DisplayName = "Hermes Finance — Stable 0.8.0",
        Type = "stable",
        Checkout = "C:\\synthetic\\stable",
        ExpectedRef = "refs/tags/v1.0.0",
        DataDir = "C:\\synthetic\\stable\\data",
        Database = "C:\\synthetic\\stable\\data\\finance.db",
        OpenBrowser = false,
    };

    // LauncherUi.OwnerTitle itself is the canonical normalization.
    Assert(LauncherUi.OwnerTitle(StaleStable()) == "Hermes Finance — Stable",
        "OwnerTitle must normalize a stale Stable display_name for the footer.");
    var startFooter = $"Последний запуск: стартует {LauncherUi.OwnerTitle(StaleStable())}";
    Assert(startFooter == "Последний запуск: стартует Hermes Finance — Stable",
        $"Start footer must use the normalized owner title, found '{startFooter}'.");
    Assert(!startFooter.Contains("0.8.0", StringComparison.Ordinal),
        "Start footer must not leak the stale 0.8.0 version.");
    Assert(startFooter.Contains("стартует", StringComparison.Ordinal),
        "Start footer must preserve the status text.");

    var stalePreview = new LauncherProfile
    {
        Id = "preview",
        DisplayName = "Hermes Finance БЂ 0.7 Preview",
        Type = "preview",
        Checkout = "C:\\synthetic\\preview",
        ExpectedRef = "refs/remotes/origin/main",
        DataDir = "C:\\synthetic\\preview\\data",
        Database = "C:\\synthetic\\preview\\data\\finance.db",
        OpenBrowser = false,
    };
    Assert(LauncherUi.OwnerTitle(stalePreview) == "Hermes Finance — Preview",
        "OwnerTitle must normalize a mojibake Preview display_name for the footer.");

    // Presentation-only: no state-machine, runtime, or release changes.
    // Ready/recovered footers share the same path — prove the actual
    // MainForm wiring does not use raw DisplayName.
    var stable = StaleStable();
    using var form = new MainForm(new LauncherConfig
    {
        Version = 1,
        CanonicalProduction = new CanonicalProduction { Checkout = stable.Checkout, DataDir = stable.DataDir, Database = stable.Database },
        Profiles = [stable],
    });
    var validated = new ValidatedProfile(
        stable, stable.Checkout, stable.DataDir, stable.Database, "d04f46696a991ea59066b59d4870980ac4b69089",
        "production", new DependencyStatus(true, true, "ready", "ready"));
    var completeReady = typeof(MainForm).GetMethod("CompleteReady", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
        ?? throw new InvalidOperationException("Could not find CompleteReady for last-run footer.");
    completeReady.Invoke(form, [validated, "v1.0.0"]);
    var lastLaunch = GetPrivate<Label>(form, "_lastLaunch").Text;
    Assert(lastLaunch.Contains("Hermes Finance — Stable", StringComparison.Ordinal),
        $"Ready footer must show the normalized owner title, found '{lastLaunch}'.");
    Assert(!lastLaunch.Contains("0.8.0", StringComparison.Ordinal),
        $"Ready footer must not leak stale 0.8.0, found '{lastLaunch}'.");
    Assert(lastLaunch.Contains("готов —", StringComparison.Ordinal),
        "Ready footer must preserve the ready status text.");
    Assert(lastLaunch.Contains(" · ", StringComparison.Ordinal),
        "Ready footer must preserve the ' · HH:mm' time separator.");

    using var formPreview = new MainForm(new LauncherConfig
    {
        Version = 1,
        CanonicalProduction = new CanonicalProduction { Checkout = stable.Checkout, DataDir = stable.DataDir, Database = stable.Database },
        Profiles = [stalePreview],
    });
    var validatedPreview = new ValidatedProfile(
        stalePreview, stalePreview.Checkout, stalePreview.DataDir, stalePreview.Database, "abc1234",
        "preview", new DependencyStatus(true, true, "ready", "ready"));
    completeReady.Invoke(formPreview, [validatedPreview, null]);
    var lastPreview = GetPrivate<Label>(formPreview, "_lastLaunch").Text;
    Assert(lastPreview.Contains("Hermes Finance — Preview", StringComparison.Ordinal),
        $"Recovered/ready Preview footer must show normalized title, found '{lastPreview}'.");
    Assert(!lastPreview.Contains("БЂ", StringComparison.Ordinal) && !lastPreview.Contains("0.7", StringComparison.Ordinal),
        $"Preview footer must not leak mojibake/stale version, found '{lastPreview}'.");
    Assert(lastPreview.Contains(" · ", StringComparison.Ordinal),
        "Preview footer must preserve the time suffix.");
}

// #302: the LOCAL ONLY / 127.0.0.1:8000 badge must keep the address on its
// own explicit line — the last digit must never wrap onto a separate line
// at 100%, 125% or 150% scaling.
static void LoopbackBadgeKeepsAddressReadable()
{
    foreach (var factor in new[] { 1f, 1.25f, 1.5f })
    {
        var scenario = $"{factor * 100:0}% scaled";
        using var form = MainForm.CreateSyntheticSmoke();
        if (factor == 1f)
        {
            ForceLayout(form, new Size(960, 820));
        }
        else
        {
            ScaleLayoutForDpi(form, factor, new Size((int)(960 * factor), (int)(820 * factor)));
        }
        var pill = (Label)typeof(MainForm)
            .GetField("_localPill", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!
            .GetValue(form)!;
        const string address = "127.0.0.1:8000";
        Assert(pill.Text.Contains(address, StringComparison.Ordinal),
            $"{scenario}: the loopback badge must show the full {address}.");
        var need = TextRenderer.MeasureText(address, pill.Font, new Size(int.MaxValue, int.MaxValue), TextFormatFlags.SingleLine | TextFormatFlags.NoPadding);
        var usable = pill.Width - pill.Padding.Horizontal;
        Assert(need.Width <= usable + 1,
            $"{scenario}: the address needs {need.Width}px but the badge fits {usable}px; the last digit would wrap.");
        var needFull = TextRenderer.MeasureText(pill.Text, pill.Font, new Size(Math.Max(50, pill.Width), int.MaxValue), TextFormatFlags.WordBreak);
        Assert(needFull.Height <= pill.Height + 2,
            $"{scenario}: the badge needs height {needFull.Height} but is {pill.Height}; text clips.");
    }
}

// #302: card titles and the selected-profile header must not clip at
// supported scaling. AutoEllipsis labels are exempt from the generic
// AssertLabelFits by design, so this covers them explicitly.
static void SelectedAndCardTitlesFitWhenScaled()
{
    foreach (var factor in new[] { 1f, 1.25f, 1.5f })
    {
        var scenario = $"{factor * 100:0}% scaled";
        using var form = MainForm.CreateSyntheticSmoke();
        if (factor == 1f)
        {
            ForceLayout(form, new Size(960, 820));
        }
        else
        {
            ScaleLayoutForDpi(form, factor, new Size((int)(960 * factor), (int)(820 * factor)));
        }
        var selectedName = (Label)typeof(MainForm)
            .GetField("_selectedName", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!
            .GetValue(form)!;
        var needTitle = TextRenderer.MeasureText(selectedName.Text, selectedName.Font, new Size(int.MaxValue, int.MaxValue), TextFormatFlags.SingleLine | TextFormatFlags.NoPadding);
        Assert(needTitle.Width <= selectedName.Width + 1,
            $"{scenario}: selected title '{selectedName.Text}' needs width {needTitle.Width} but the header fits {selectedName.Width}.");
        Assert(needTitle.Height <= selectedName.Height + 2,
            $"{scenario}: selected title needs height {needTitle.Height} but the header fits {selectedName.Height}.");
        foreach (var card in AllControls(form).OfType<ProfileCard>().ToArray())
        {
            var cardName = (Label)typeof(ProfileCard)
                .GetField("_name", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!
                .GetValue(card)!;
            var need = TextRenderer.MeasureText(cardName.Text, cardName.Font, new Size(int.MaxValue, int.MaxValue), TextFormatFlags.SingleLine | TextFormatFlags.NoPadding);
            Assert(need.Width <= cardName.Width + 1,
                $"{scenario}: card title '{cardName.Text}' needs width {need.Width} but the card fits {cardName.Width}.");
            Assert(need.Height <= cardName.Height + 2,
                $"{scenario}: card title needs height {need.Height} but the card fits {cardName.Height}.");
        }
        AssertLayoutClean(form, scenario);
    }
}

static void SetupFlowCreatesConcreteConfig()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-setup-{Guid.NewGuid():N}");
    var stableCheckout = Path.Combine(root, "stable");
    var stableData = Path.Combine(root, "stable-data");
    var previewCheckout = Path.Combine(root, "preview");
    var previewData = Path.Combine(root, "preview-data");
    try
    {
        CreateRuntimeLayout(stableCheckout);
        Directory.CreateDirectory(stableData);
        RunGit(stableCheckout, "init");
        RunGit(stableCheckout, "config", "--local", "user.name", "Hermes Safety Test");
        RunGit(stableCheckout, "config", "--local", "user.email", "hermes-safety-test");
        RunGit(stableCheckout, "add", ".");
        RunGit(stableCheckout, "commit", "-m", "synthetic stable at release");
        CreateRuntimeLayout(previewCheckout);
        Directory.CreateDirectory(previewData);
        RunGit(previewCheckout, "init");
        RunGit(previewCheckout, "config", "--local", "user.name", "Hermes Safety Test");
        RunGit(previewCheckout, "config", "--local", "user.email", "hermes-safety-test");
        RunGit(previewCheckout, "add", ".");
        RunGit(previewCheckout, "commit", "-m", "synthetic preview local identity");

        // Synthetic owner selections become a concrete valid config — no manual JSON.
        var config = LauncherSetup.BuildConfig(stableCheckout, stableData, previewCheckout, previewData);
        var stableHead = RunGit(stableCheckout, "rev-parse", "HEAD");
        var previewHead = RunGit(previewCheckout, "rev-parse", "HEAD");
        Assert(config.Profiles[0].ExpectedRef == stableHead, "Setup must persist the exact prepared local Stable identity.");
        Assert(config.Profiles[1].ExpectedRef == previewHead, "Setup must persist the exact prepared local Preview identity.");
        Assert(LauncherConfig.IsConcreteConfig(config), "Setup result must be concrete (absolute paths, no placeholders).");

        var configPath = Path.Combine(root, "launcher", "config.json");
        LauncherSetup.WriteConfig(config, configPath);

        // The next preflight config stage works without manual JSON.
        var loaded = LauncherConfig.Load(configPath);
        ProfileValidator.ValidateConfiguration(loaded);
        Assert(LauncherConfig.IsConcreteConfig(loaded), "Reloaded setup config must stay concrete.");

        // Boundaries are enforced: Preview on production paths is rejected.
        AssertThrows<LauncherValidationException>(() => LauncherSetup.BuildConfig(stableCheckout, stableData, stableCheckout, stableData));
        // Nothing is guessed: missing selections fail closed.
        AssertThrows<LauncherValidationException>(() => LauncherSetup.BuildConfig("", stableData, previewCheckout, previewData));
    }
    finally
    {
        DeleteSyntheticTree(root);
    }
}

static void ShowsShaPinnedStableVersionAndIdentity()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-setup-version-{Guid.NewGuid():N}");
    var stableCheckout = Path.Combine(root, "stable");
    var stableData = Path.Combine(root, "stable-data");
    var previewCheckout = Path.Combine(root, "preview");
    var previewData = Path.Combine(root, "preview-data");
    try
    {
        CreateRuntimeLayout(stableCheckout);
        Directory.CreateDirectory(Path.Combine(stableCheckout, "backend", "src", "hermes_finance"));
        File.WriteAllText(Path.Combine(stableCheckout, "backend", "src", "hermes_finance", "__init__.py"), "__version__ = '1.0.0'\n");
        Directory.CreateDirectory(stableData);
        InitSyntheticRepo(stableCheckout, "synthetic SHA-pinned Stable");
        CreateRuntimeLayout(previewCheckout);
        Directory.CreateDirectory(previewData);
        InitSyntheticRepo(previewCheckout, "synthetic Preview");

        var config = LauncherSetup.BuildConfig(stableCheckout, stableData, previewCheckout, previewData);
        var stable = config.Profiles.Single(profile => profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase));
        Assert(stable.ExpectedRef.Length == 40 && stable.ExpectedRef.All(char.IsAsciiHexDigit), "Setup Stable identity must be an exact local SHA.");
        var validated = new ValidatedProfile(
            stable,
            stableCheckout,
            stableData,
            stable.Database,
            stable.ExpectedRef,
            "production",
            new DependencyStatus(true, true, "ready", "ready"),
            "1.0.0");
        using var form = new MainForm(config);
        var apply = typeof(MainForm).GetMethod("ApplyValidated", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("Could not find ApplyValidated for Stable identity presentation.");
        apply.Invoke(form, [validated]);
        var summary = (Label)typeof(MainForm)
            .GetField("_shaSummary", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!
            .GetValue(form)!;
        Assert(summary.Text.Contains("Version 1.0.0", StringComparison.Ordinal), "SHA-pinned Stable presentation must retain the validated application version.");
        Assert(summary.Text.Contains($"SHA {stable.ExpectedRef[..7]}", StringComparison.Ordinal), "SHA-pinned Stable presentation must show the exact SHA.");
    }
    finally
    {
        DeleteSyntheticTree(root);
    }
}

static void InitSyntheticRepo(string checkout, string commitMessage)
{
    RunGit(checkout, "init");
    RunGit(checkout, "config", "--local", "user.name", "Hermes Safety Test");
    RunGit(checkout, "config", "--local", "user.email", "hermes-safety-test");
    RunGit(checkout, "add", ".");
    RunGit(checkout, "commit", "-m", commitMessage);
}

static void SetupRejectsPreviewSharingStableGitDir()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-setup-worktree-{Guid.NewGuid():N}");
    var stableCheckout = Path.Combine(root, "stable");
    var stableData = Path.Combine(root, "stable-data");
    var previewCheckout = Path.Combine(root, "linked-preview");
    var previewData = Path.Combine(root, "preview-data");
    try
    {
        CreateRuntimeLayout(stableCheckout);
        Directory.CreateDirectory(stableData);
        InitSyntheticRepo(stableCheckout, "synthetic stable at release");
        RunGit(stableCheckout, "tag", "v1.0.0");
        RunGit(stableCheckout, "branch", "-M", "main");
        RunGit(stableCheckout, "update-ref", "refs/remotes/origin/main", "HEAD");
        // Linked worktree: same git-common-dir as Stable, HEAD at origin/main.
        RunGit(stableCheckout, "worktree", "add", "--detach", previewCheckout);
        Directory.CreateDirectory(previewData);

        try
        {
            LauncherSetup.BuildConfig(stableCheckout, stableData, previewCheckout, previewData);
            throw new InvalidOperationException("Setup must reject a Preview sharing the Stable git-common-dir.");
        }
        catch (LauncherValidationException exception)
        {
            Assert(exception.Message.Contains("Preview", StringComparison.Ordinal), "Worktree rejection must name the Preview checkout.");
        }
    }
    finally
    {
        DeleteSyntheticTree(root);
    }
}

static void PreparedSetupPassesPreflightIdentity()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-setup-identity-{Guid.NewGuid():N}");
    var stableCheckout = Path.Combine(root, "stable");
    var stableData = Path.Combine(root, "stable-data");
    var previewCheckout = Path.Combine(root, "preview");
    var previewData = Path.Combine(root, "preview-data");
    try
    {
        CreateRuntimeLayout(stableCheckout);
        Directory.CreateDirectory(stableData);
        InitSyntheticRepo(stableCheckout, "synthetic stable at release");
        RunGit(stableCheckout, "tag", "v1.0.0");
        CreateRuntimeLayout(previewCheckout);
        Directory.CreateDirectory(previewData);
        InitSyntheticRepo(previewCheckout, "synthetic preview at origin/main");
        RunGit(previewCheckout, "update-ref", "refs/remotes/origin/main", "HEAD");

        var configPath = Path.Combine(root, "launcher", "config.json");
        LauncherSetup.WriteConfig(LauncherSetup.BuildConfig(stableCheckout, stableData, previewCheckout, previewData), configPath);

        // The identity stage of the next real preflight passes on first try.
        var loaded = LauncherConfig.Load(configPath);
        ProfileValidator.ValidateConfiguration(loaded);
        var stable = loaded.Profiles.Single(profile => profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase));
        var preview = loaded.Profiles.Single(profile => profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase));
        var stableHead = ProfileValidator.AssertGitIdentity(stable, stable.Checkout, stable.Checkout);
        Assert(!string.IsNullOrWhiteSpace(stableHead), "Stable identity stage must resolve HEAD.");
        var previewHead = ProfileValidator.AssertGitIdentity(preview, preview.Checkout, stable.Checkout);
        Assert(!string.IsNullOrWhiteSpace(previewHead), "Preview identity stage must resolve HEAD.");
    }
    finally
    {
        DeleteSyntheticTree(root);
    }
}

static void ConfigFailureOffersSetupAction()
{
    var stable = StableProfile("C:\\s", "C:\\s\\data", "C:\\s\\data\\finance.db", "refs/tags/v1.0.0");
    using var form = new MainForm(new LauncherConfig
    {
        Version = 1,
        CanonicalProduction = new CanonicalProduction { Checkout = stable.Checkout, DataDir = stable.DataDir, Database = stable.Database },
        Profiles = [stable],
    });
    var show = typeof(MainForm).GetMethod("ShowConfigurationFailure", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
        ?? throw new InvalidOperationException("Could not find ShowConfigurationFailure for setup presentation.");
    show.Invoke(form, []);
    var buttons = AllControls(form).OfType<Button>().ToArray();
    Assert(buttons.Single(button => button.Text == "Настроить…").Enabled, "Configuration failure must offer an enabled executable setup action.");
    Assert(buttons.Single(button => button.Text == "Обновить проверку").Enabled, "Refresh must stay available beside setup.");
    Assert(!buttons.Single(button => button.Text == "Запустить").Enabled, "Start must stay disabled until setup completes.");
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

// #284 layout regressions: deterministic WinForms checks (no screenshots).
// A synthetic smoke form is laid out headless (handle forced, never shown)
// and then inspected for containment, sibling overlap and text fit.
static void LayoutKeepsDefaultWindowClean()
{
    using var form = MainForm.CreateSyntheticSmoke();
    ForceLayout(form, new Size(960, 820));
    AssertLayoutClean(form, "default 960x820");
}

static void LayoutFitsRussianLabelsWhenScaled()
{
    // Faithful DPI emulation: fonts AND window AND absolute table metrics
    // scale together (real 125/150% scales the whole form, not just fonts).
    // The longest Russian readiness text (NeedsPreparation) is used.
    foreach (var factor in new[] { 1f, 1.25f, 1.5f })
    {
        using var form = LayoutNeedsPreparationForm();
        ScaleLayoutForDpi(form, factor, new Size((int)(960 * factor), (int)(820 * factor)));
        AssertReadinessHeightPropagates(form, $"{factor * 100:0}% scaled");
        AssertLayoutClean(form, $"{factor * 100:0}% scaled");
    }
}

static void LayoutSurvivesCommonResizes()
{
    using var narrow = LayoutNeedsPreparationForm();
    ForceLayout(narrow, new Size(780, 720));
    AssertReadinessHeightPropagates(narrow, "minimum 780x720");
    AssertLayoutClean(narrow, "minimum 780x720");
    using var defaultSize = LayoutNeedsPreparationForm();
    ForceLayout(defaultSize, new Size(960, 820));
    AssertReadinessHeightPropagates(defaultSize, "default 960x820 with NeedsPreparation");
    AssertLayoutClean(defaultSize, "default 960x820 with NeedsPreparation");
    using var wide = LayoutNeedsPreparationForm();
    ForceLayout(wide, new Size(1280, 800));
    AssertReadinessHeightPropagates(wide, "wide 1280x800 with NeedsPreparation");
    AssertLayoutClean(wide, "wide 1280x800");
    // Opening diagnostics must not break the layout either.
    var toggle = typeof(MainForm).GetMethod("ToggleDetails", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
    toggle.Invoke(wide, []);
    ForceLayout(wide, new Size(1280, 800));
    AssertLayoutClean(wide, "wide with diagnostics open");
    toggle.Invoke(wide, []);
    ForceLayout(wide, new Size(1280, 800));
    AssertLayoutClean(wide, "wide with diagnostics closed again");
}

static void AssertReadinessHeightPropagates(MainForm form, string scenario)
{
    var readinessPanel = (Panel)typeof(MainForm)
        .GetField("_readinessPanel", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!
        .GetValue(form)!;
    var description = (Label)typeof(MainForm)
        .GetField("_readinessDescription", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!
        .GetValue(form)!;
    var readinessLayout = (TableLayoutPanel)description.Parent!;
    var selectedLayout = (TableLayoutPanel)typeof(MainForm)
        .GetField("_selectedLayout", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!
        .GetValue(form)!;
    var need = TextRenderer.MeasureText(
        description.Text,
        description.Font,
        new Size(Math.Max(1, description.Width), int.MaxValue),
        TextFormatFlags.WordBreak);
    var contentBottom = description.Parent!.Top + description.Bottom + readinessPanel.Padding.Bottom;
    Assert(need.Height <= description.Height + 2,
        $"{scenario}: readiness description needs {need.Height}px but is {description.Height}px.");
    var descriptionRow = readinessLayout.GetPositionFromControl(description).Row;
    var descriptionRowHeight = readinessLayout.GetRowHeights()[descriptionRow];
    Assert(readinessLayout.RowStyles[descriptionRow].SizeType == SizeType.Absolute,
        $"{scenario}: readiness description row must be content-driven Absolute before layout.");
    Assert(descriptionRowHeight >= need.Height - 1,
        $"{scenario}: readiness description row is {descriptionRowHeight}px but wrapped text needs {need.Height}px.");
    Assert(contentBottom <= readinessPanel.ClientSize.Height + 1,
        $"{scenario}: readiness outer container is {readinessPanel.Height}px but its wrapped content needs at least {contentBottom}px.");
    var row = selectedLayout.GetPositionFromControl(readinessPanel).Row;
    Assert(selectedLayout.GetRowHeights()[row] >= readinessPanel.Height - 1,
        $"{scenario}: selectedLayout row {row} did not propagate readiness height {readinessPanel.Height}px.");
}

static void LayoutKeepsCardsComparableAndPrimaryObvious()
{
    using var form = MainForm.CreateSyntheticSmoke();
    ForceLayout(form, new Size(960, 820));
    var cards = AllControls(form).OfType<ProfileCard>().ToArray();
    Assert(cards.Length == 2, "Synthetic smoke must show Stable and Preview cards.");
    Assert(cards[0].Width == cards[1].Width && cards[0].Height == cards[1].Height,
        $"Stable/Preview cards must share one footprint for glance comparison, found {cards[0].Size} vs {cards[1].Size}.");
    var allButtons = AllControls(form).OfType<Button>().Where(button => OwnVisible(button)).Select(button => button.Text + "=" + button.FlatAppearance.BorderSize.ToString() + (button.Enabled ? "+en" : "-dis")).ToArray();
    var emphasized = AllControls(form).OfType<Button>().Where(button => OwnVisible(button) && button.FlatAppearance.BorderSize == 2).ToArray();
    Assert(emphasized.Length == 1 && emphasized[0].Text == "Запустить" && emphasized[0].Enabled,
        "Ready state must emphasize exactly one primary CTA ('Запустить'); secondary actions stay BorderSize 1. Got: " + string.Join(" | ", allButtons));
}

static MainForm LayoutNeedsPreparationForm()
{
    var form = MainForm.CreateSyntheticSmoke();
    var configField = typeof(MainForm).GetField("_config", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
    var config = (LauncherConfig)configField.GetValue(form)!;
    var stable = config.Profiles.First(profile => profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase));
    var validated = new ValidatedProfile(stable, stable.Checkout, stable.DataDir, stable.Database, "abc", "production", new DependencyStatus(false, false, "needs preparation", "needs preparation"));
    var apply = typeof(MainForm).GetMethod("ApplyValidated", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
    apply.Invoke(form, [validated]);
    return form;
}

static void ForceLayout(Form form, Size client)
{
    form.ClientSize = client;
    _ = form.Handle; // force handle creation so layout runs without showing
    form.PerformLayout();
}

static void ScaleLayoutForDpi(Form form, float factor, Size client)
{
    foreach (var control in new[] { form }.Concat(AllControls(form)))
    {
        control.Font = new Font(control.Font.FontFamily, control.Font.Size * factor, control.Font.Style);
    }
    // Snapshot: changing a font re-runs layout synchronously, and the layout
    // handlers replace Absolute row styles — never iterate the live collection.
    foreach (var table in new[] { form }.Concat(AllControls(form)).OfType<TableLayoutPanel>().ToArray())
    {
        foreach (RowStyle row in table.RowStyles.Cast<RowStyle>().ToArray())
        {
            if (row.SizeType == SizeType.Absolute)
            {
                row.Height *= factor;
            }
        }
        foreach (ColumnStyle column in table.ColumnStyles)
        {
            if (column.SizeType == SizeType.Absolute)
            {
                column.Width *= factor;
            }
        }
    }
    form.MinimumSize = new Size((int)(form.MinimumSize.Width * factor), (int)(form.MinimumSize.Height * factor));
    ForceLayout(form, client);
}

static void AssertLayoutClean(Form form, string scenario)
{
    // NOTE: Control.Visible is false for every control of a never-shown form
    // (it folds ancestors in), so headless checks use OwnVisible instead —
    // otherwise every assertion below would vacuous-pass on empty sets.
    AssertContained(form, form.ClientRectangle, scenario);
    foreach (var flow in AllControls(form).OfType<FlowLayoutPanel>().Where(OwnVisible))
    {
        var kids = flow.Controls.Cast<Control>().Where(OwnVisible).ToArray();
        for (var i = 0; i < kids.Length; i++)
        {
            for (var j = i + 1; j < kids.Length; j++)
            {
                var overlap = Rectangle.Intersect(kids[i].Bounds, kids[j].Bounds);
                Assert(overlap.Width <= 1 && overlap.Height <= 1,
                    $"{scenario}: '{DescribeControl(kids[i])}' overlaps '{DescribeControl(kids[j])}' in a flow panel.");
            }
        }
    }
    foreach (var control in AllControls(form).Where(OwnVisible))
    {
        if (control is Button button)
        {
            AssertButtonFits(button, scenario);
        }
        else if (control is Label label)
        {
            AssertLabelFits(label, scenario);
        }
    }
}

static void AssertContained(Control parent, Rectangle area, string scenario)
{
    // A scrolling panel does not clip: its content must start inside the
    // viewport and remain reachable (fitting or with the scrollbar engaged).
    // Everywhere else containment is strict — escaping means overlap/clipping.
    var autoScroll = parent is ScrollableControl scroller && scroller.AutoScroll;
    var viewport = autoScroll ? parent.ClientRectangle : area;
    foreach (Control child in parent.Controls)
    {
        if (!OwnVisible(child))
        {
            continue;
        }
        if (autoScroll)
        {
            var scroll = (ScrollableControl)parent;
            var anchored = child.Left >= viewport.Left + Math.Min(0, child.Margin.Left) - 1
                && child.Top >= viewport.Top + Math.Min(0, child.Margin.Top) - 1;
            var reachableX = child.Right <= viewport.Right + 1 || scroll.HorizontalScroll.Visible;
            var reachableY = child.Bottom <= viewport.Bottom + 1 || scroll.VerticalScroll.Visible;
            Assert(anchored && reachableX && reachableY,
                $"{scenario}: {DescribeControl(child)} at {child.Bounds} is not reachable in scrolling {parent.GetType().Name} {viewport}.");
        }
        else
        {
            // Intentional negative margins (edge-bleed panels) expand the allowed
            // area; anything else escaping its parent is clipping/overlap.
            var allowed = Rectangle.FromLTRB(
                viewport.Left + Math.Min(0, child.Margin.Left),
                viewport.Top + Math.Min(0, child.Margin.Top),
                viewport.Right - Math.Min(0, child.Margin.Right),
                viewport.Bottom - Math.Min(0, child.Margin.Bottom));
            Assert(allowed.Contains(child.Bounds),
                $"{scenario}: {DescribeControl(child)} at {child.Bounds} escapes {parent.GetType().Name} {viewport}.");
        }
        var childArea = child is ScrollableControl scrollable ? scrollable.DisplayRectangle : child.ClientRectangle;
        AssertContained(child, childArea, scenario);
    }
}

static void AssertButtonFits(Button button, string scenario)
{
    if (string.IsNullOrEmpty(button.Text))
    {
        return;
    }
    var need = TextRenderer.MeasureText(button.Text, button.Font, new Size(int.MaxValue, int.MaxValue), TextFormatFlags.SingleLine | TextFormatFlags.NoPadding);
    Assert(need.Width <= button.Width - 8 && need.Height <= button.Height - 6,
        $"{scenario}: button '{button.Text}' needs {need} but is {button.Size}; Russian labels must not clip.");
}

static void AssertLabelFits(Label label, string scenario)
{
    var text = label.Text;
    if (string.IsNullOrEmpty(text) || label.AutoEllipsis)
    {
        return; // AutoEllipsis = by-design truncation (paths, status values)
    }
    if (label.AutoSize && label.Dock == DockStyle.None && label.MaximumSize.IsEmpty)
    {
        return; // fits by construction; parent overflow is caught by containment
    }
    if (text.Contains((char)10) || text.Contains((char)13) || !label.MaximumSize.IsEmpty)
    {
        var need = TextRenderer.MeasureText(text, label.Font, new Size(Math.Max(50, label.Width), int.MaxValue), TextFormatFlags.WordBreak);
        Assert(need.Height <= label.Height + 2,
            $"{scenario}: wrapped label '{ShortText(text)}' needs height {need.Height} but is {label.Height}; text clips.");
    }
    else
    {
        var need = TextRenderer.MeasureText(text, label.Font, new Size(int.MaxValue, int.MaxValue), TextFormatFlags.SingleLine | TextFormatFlags.NoPadding);
        Assert(need.Width <= label.Width + 1,
            $"{scenario}: label '{ShortText(text)}' needs width {need.Width} but is {label.Width}; text clips.");
    }
}

static string DescribeControl(Control control) => $"{control.GetType().Name} '{ShortText(control.Text)}'";

static string ShortText(string text) => text.Length <= 48 ? text : string.Concat(text.AsSpan(0, 48), "…");

// The control's own Visible flag (Control.Visible folds ancestors in, so it
// is useless for never-shown headless forms). STATE_VISIBLE = 0x2.
static System.Reflection.MethodInfo ControlGetStateMethod() =>
    typeof(Control).GetMethod("GetState", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;

static bool OwnVisible(Control control)
{
    // Own flags up the chain (stopping at the never-shown form itself): a
    // control inside an own-hidden panel (e.g. closed diagnostics) is hidden.
    var getState = ControlGetStateMethod();
    for (var current = control; current is not null && current is not Form; current = current.Parent)
    {
        if (!(bool)getState.Invoke(current, [2])!)
        {
            return false;
        }
    }
    return true;
}

static class NativeMethods
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    internal static extern bool CreateHardLink(string fileName, string existingFileName, IntPtr securityAttributes);
}
