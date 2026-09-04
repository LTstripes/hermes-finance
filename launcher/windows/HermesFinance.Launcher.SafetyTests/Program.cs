using HermesFinance.Launcher;
using System.ComponentModel;
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
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
    ("updates only Preview to unreleased origin main and preserves its data", UpdatesPreviewAndPreservesData),
    ("rejects dirty, conflicted, and unexpected Preview checkouts", RejectsUnsafePreviewUpdateStates),
    ("rejects Stable as an update target", RejectsStableUpdate),
    ("shows Stable pinned release identity and production data", ShowsStablePinnedIdentity),
    ("shows Preview main SHA as unreleased with isolated data", ShowsPreviewUnreleasedIdentity),
    ("offers launcher-owned action for identity mismatch", OffersActionableMismatch),
    ("exposes exactly one primary CTA per state", ExposesSinglePrimaryCta),
    ("summarizes health alembic deps checkout in plain language", SummarizesChecksPlainLanguage),
    ("missing config fails closed without placeholder", MissingConfigFailsClosedWithoutPlaceholder),
    ("strips real unknown fields or fails closed", StripsRealUnknownFieldsOrFailsClosed),
    ("leaves stale Stable ref untouched when checkout is off release", LeavesStaleStableRefUntouchedWhenCheckoutOffRelease),
    ("migrates stale Stable ref only when checkout proves release", MigratesStaleStableRefOnlyWhenCheckoutProvesRelease),
    ("offers Refresh not Stop for external port collision", PortCollisionOffersRefreshNotStop),
    ("marks Stable identity mismatch recovery-only", StableMismatchIsRecoveryOnly),
    ("Preview current offers Start primary", PreviewCurrentStartsPrimary),
    ("Preview behind offers Update primary", PreviewBehindUpdatesPrimary),
    ("Preview behind with missing deps offers a single safe primary", PreviewBehindMissingDepsOffersSingleSafePrimary),
    ("Stable Ready offers Start primary", StableReadyStartsPrimary),
    ("setup flow creates concrete config from owner selections", SetupFlowCreatesConcreteConfig),
    ("setup rejects Stable off the v0.8.1 release commit", SetupRejectsStableOffRelease),
    ("setup rejects Preview without origin/main", SetupRejectsPreviewWithoutOriginMain),
    ("setup rejects Preview sharing Stable git dir", SetupRejectsPreviewSharingStableGitDir),
    ("prepared setup passes the next preflight identity stage", PreparedSetupPassesPreflightIdentity),
    ("configuration failure offers executable setup action", ConfigFailureOffersSetupAction),
    ("layout keeps the default window free of overlap and clipping", LayoutKeepsDefaultWindowClean),
    ("layout fits Russian labels at 100, 125, and 150 percent scaling", LayoutFitsRussianLabelsWhenScaled),
    ("layout survives narrow and wide resizes", LayoutSurvivesCommonResizes),
    ("layout keeps cards comparable with one obvious primary CTA", LayoutKeepsCardsComparableAndPrimaryObvious),
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
    Assert(config.Profiles[0].ExpectedRef == "refs/tags/v0.8.1", "The stable profile expected ref must be v0.8.1.");
    Assert(config.Profiles[0].DataDir == "<absolute-stable-data-dir>", "The stable profile data directory must use the documented JSON name.");
    Assert(config.Profiles[0].Database == "<absolute-stable-database>", "The stable profile database must use the documented JSON name.");
    Assert(config.Profiles[0].OpenBrowser, "The stable profile browser setting must use the documented JSON name.");
    Assert(config.Profiles[1].Id == "preview", "Preview profile id must be preview.");
    Assert(config.Profiles[1].ExpectedRef == "refs/remotes/origin/main", "Preview expected_ref must be origin/main for #279.");
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
    // Repair remains as explicit recovery action — enabled via secondary when Ready
    Assert(buttons.Any(button => button.Text == "Исправить"), "Repair button must exist as explicit recovery action.");
    Assert(buttons.Any(button => button.Text == "Остановить" && !button.Enabled), "Stop must be disabled before a runtime is launched.");
    Assert(buttons.Any(button => button.Text == "Открыть Hermes" && !button.Enabled), "Open Hermes must stay disabled until health probes pass.");
    Assert(buttons.Any(button => button.Text == "Диагностика и логи"), "Raw diagnostics must have a dedicated details action.");
    Assert(labels.Any(label => label.Text == "STABLE  ·  PRODUCTION"), "The Stable owner badge is missing.");
    Assert(labels.Any(label => label.Text == "PREVIEW  ·  ISOLATED"), "The Preview owner badge is missing.");
    Assert(labels.Any(label => label.Text.Contains("Release v0.8.1", StringComparison.Ordinal) || label.Text.Contains("UNRELEASED", StringComparison.Ordinal)), "Profile cards must show Stable pinned release or Preview UNRELEASED badge.");

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
    Assert(labels.Any(label => label.Text.Contains("SHA", StringComparison.Ordinal) || label.Text.Contains("Release", StringComparison.Ordinal)), "The owner surface must show Stable release/SHA and Preview main/SHA identity labels.");
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

static void ShowsStablePinnedIdentity()
{
    var stable = new LauncherProfile
    {
        Id = "stable",
        DisplayName = "Hermes Finance — Stable",
        Type = "stable",
        Checkout = "C:\\synthetic\\stable",
        ExpectedRef = "refs/tags/v0.8.1",
        DataDir = "C:\\synthetic\\stable\\data",
        Database = "C:\\synthetic\\stable\\data\\finance.db",
        OpenBrowser = false,
    };
    // Stable must show pinned release tag/SHA + production data identity without manual JSON
    var label = LauncherUi.StableIdentityLabel(stable, "d04f46696a991ea59066b59d4870980ac4b69089");
    Assert(label.Contains("v0.8.1", StringComparison.Ordinal), "Stable identity must show pinned release version/tag.");
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
    var labelBehind = LauncherUi.PreviewIdentityLabel(preview, "aaaaaaa1111111111111111111111111111111111", "bbbbbbb2222222222222222222222222222222222");
    Assert(labelBehind.Contains("main", StringComparison.OrdinalIgnoreCase), "Preview must show main.");
    Assert(labelBehind.Contains("UNRELEASED", StringComparison.Ordinal), "Preview must be clearly marked UNRELEASED.");
    Assert(labelBehind.Contains("Isolated", StringComparison.OrdinalIgnoreCase) || labelBehind.Contains("isolated", StringComparison.OrdinalIgnoreCase), "Preview must show isolated data identity.");
    var labelCurrent = LauncherUi.PreviewIdentityLabel(preview, "cccccccc33333333333333333333333333333333333", "cccccccc33333333333333333333333333333333333");
    Assert(labelCurrent.Contains("UNRELEASED", StringComparison.Ordinal), "Preview at origin/main is still UNRELEASED code.");
    // Card data boundary for preview must be distinct from stable
    Assert(LauncherUi.DataBoundary("preview") != LauncherUi.DataBoundary("stable"), "Preview and Stable data boundaries must differ.");
}

static void OffersActionableMismatch()
{
    var preview = new LauncherProfile { Id = "preview", DisplayName = "Preview", Type = "preview", Checkout = "C:\\p", ExpectedRef = "HEAD", DataDir = "C:\\p\\data", Database = "C:\\p\\data\\finance.db", OpenBrowser = false };
    var stable = new LauncherProfile { Id = "stable", DisplayName = "Stable", Type = "stable", Checkout = "C:\\s", ExpectedRef = "refs/tags/v0.8.1", DataDir = "C:\\s\\data", Database = "C:\\s\\data\\finance.db", OpenBrowser = false };

    var mismatch = new LauncherValidationException("Checkout identity does not match this profile.");
    var planPreview = LauncherUi.PlanPrimaryAction(LauncherReadinessState.Blocked, null, preview, mismatch);
    Assert(planPreview.Primary == LauncherPrimaryAction.Update, "Identity mismatch on Preview must offer Update as primary launcher-owned action, not dead-end.");

    var planBlockedGeneric = LauncherUi.PlanPrimaryAction(LauncherReadinessState.Blocked, null, stable, mismatch);
    Assert(planBlockedGeneric.Primary != LauncherPrimaryAction.None, "Blocked state must offer at least one actionable CTA.");

    var human = LauncherUi.OwnerFacingFailure(mismatch.Message);
    Assert(human.Contains("Обновить Preview", StringComparison.Ordinal) || human.Contains("expected_ref", StringComparison.OrdinalIgnoreCase) || human.Contains("Code identity", StringComparison.OrdinalIgnoreCase), "Human failure must explain mismatch and hint correct launcher action.");
    Assert(!human.Contains("C:\\", StringComparison.Ordinal), "Human message must not leak raw paths.");
}

static void ExposesSinglePrimaryCta()
{
    var stable = StableProfile("C:\\synthetic\\stable", "C:\\synthetic\\stable\\data", "C:\\synthetic\\stable\\data\\finance.db", "refs/tags/v0.8.1");
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
    var primaryReady = buttonsReady.Where(b => b.Enabled && (b.Text == "Запустить" || b.Text == "Подготовить" || b.Text == "Обновить Preview" || b.Text == "Открыть Hermes" || b.Text == "Остановить")).ToList();
    Assert(primaryReady.Count == 1 && primaryReady[0].Text == "Запустить", $"Ready state must have exactly one primary CTA 'Запустить', found {string.Join(",", primaryReady.Select(b=>b.Text))}.");

    using var formNeeds = new MainForm(config);
    var validatedNeeds = new ValidatedProfile(stable, stable.Checkout, stable.DataDir, stable.Database, "abc", "production", new DependencyStatus(false, false, "needs preparation", "needs preparation"));
    apply.Invoke(formNeeds, [validatedNeeds]);
    var buttonsNeeds = AllControls(formNeeds).OfType<Button>().ToArray();
    Assert(buttonsNeeds.Single(b=>b.Text=="Подготовить").Enabled, "NeedsPreparation must have Prepare as primary CTA.");
    Assert(!buttonsNeeds.Single(b=>b.Text=="Запустить").Enabled, "Start must not be primary when preparation needed.");

    // Blocked identity mismatch on Preview should have Update as primary
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
    applyBlocked.Invoke(formBlocked, [preview, new LauncherValidationException("Checkout identity does not match this profile."), false, false]);
    var buttonsBlocked = AllControls(formBlocked).OfType<Button>().ToArray();
    Assert(buttonsBlocked.Single(b=>b.Text=="Обновить Preview").Enabled, "Blocked Preview identity mismatch must enable Update as actionable primary.");
}

static void SummarizesChecksPlainLanguage()
{
    // Human checks must be plain language, raw diagnostics secondary
    var stable = StableProfile("C:\\s", "C:\\s\\data", "C:\\s\\data\\finance.db", "refs/tags/v0.8.1");
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
                new LauncherProfile { Id = "stable", DisplayName = "Stable", Type = "stable", Checkout = checkout, ExpectedRef = "refs/tags/v0.8.1", DataDir = dataDir, Database = database, OpenBrowser = false },
            ],
        };
        var node = System.Text.Json.Nodes.JsonNode.Parse(JsonSerializer.Serialize(valid)) as System.Text.Json.Nodes.JsonObject
            ?? throw new InvalidOperationException("Could not build unknown-field fixture.");
        node["token"] = "forbidden";
        (node["canonical_production"] as System.Text.Json.Nodes.JsonObject)!["extra_canonical"] = "strip-me";
        (node["profiles"] as System.Text.Json.Nodes.JsonArray)![0]!["unknown_field"] = 123;
        File.WriteAllText(configPath, node.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));

        var stripped = LauncherConfig.LoadOrCreate(configPath, out var diag);
        Assert(stripped.Profiles.Count == 1 && stripped.Profiles[0].ExpectedRef == "refs/tags/v0.8.1", "Stripped config must keep known fields intact.");
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

static void LeavesStaleStableRefUntouchedWhenCheckoutOffRelease()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-stable-nomigrate-{Guid.NewGuid():N}");
    var checkout = Path.Combine(root, "checkout");
    var dataDir = Path.Combine(root, "data");
    try
    {
        CreateRuntimeLayout(checkout);
        Directory.CreateDirectory(dataDir);
        RunGit(checkout, "init");
        RunGit(checkout, "config", "--local", "user.name", "Hermes Safety Test");
        RunGit(checkout, "config", "--local", "user.email", "hermes-safety-test");
        RunGit(checkout, "add", ".");
        RunGit(checkout, "commit", "-m", "synthetic stable at old release");
        RunGit(checkout, "tag", "v0.6.3");
        // No v0.8.1 tag exists and HEAD is not on v0.8.1: migration must not fire.
        var configPath = Path.Combine(root, "launcher", "config.json");
        Directory.CreateDirectory(Path.GetDirectoryName(configPath)!);
        var config = new LauncherConfig
        {
            Version = 1,
            CanonicalProduction = new CanonicalProduction { Checkout = checkout, DataDir = dataDir, Database = Path.Combine(dataDir, "finance.db") },
            Profiles =
            [
                new LauncherProfile { Id = "stable", DisplayName = "Stable", Type = "stable", Checkout = checkout, ExpectedRef = "refs/tags/v0.6.3", DataDir = dataDir, Database = Path.Combine(dataDir, "finance.db"), OpenBrowser = false },
            ],
        };
        File.WriteAllText(configPath, JsonSerializer.Serialize(config, new JsonSerializerOptions { WriteIndented = true }));
        var before = File.ReadAllText(configPath);

        var loaded = LauncherConfig.LoadOrCreate(configPath, out var diag);
        Assert(loaded.Profiles[0].ExpectedRef == "refs/tags/v0.6.3", "Stale Stable ref must NOT be rewritten when the checkout is not proven at v0.8.1.");
        Assert(File.ReadAllText(configPath) == before, "Config file must be byte-identical when migration is blocked.");
        Assert(diag.Contains("blocked", StringComparison.OrdinalIgnoreCase), "Blocked migration must be diagnosable.");
    }
    finally
    {
        DeleteSyntheticTree(root);
    }
}

static void MigratesStaleStableRefOnlyWhenCheckoutProvesRelease()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-stable-migrate-{Guid.NewGuid():N}");
    var checkout = Path.Combine(root, "checkout");
    var dataDir = Path.Combine(root, "data");
    try
    {
        CreateRuntimeLayout(checkout);
        Directory.CreateDirectory(dataDir);
        RunGit(checkout, "init");
        RunGit(checkout, "config", "--local", "user.name", "Hermes Safety Test");
        RunGit(checkout, "config", "--local", "user.email", "hermes-safety-test");
        RunGit(checkout, "add", ".");
        RunGit(checkout, "commit", "-m", "synthetic stable at old release");
        RunGit(checkout, "tag", "v0.6.3");
        File.WriteAllText(Path.Combine(checkout, "release-marker.txt"), "synthetic v0.8.1 release");
        RunGit(checkout, "add", "release-marker.txt");
        RunGit(checkout, "commit", "-m", "synthetic stable at v0.8.1");
        RunGit(checkout, "tag", "v0.8.1");
        var configPath = Path.Combine(root, "launcher", "config.json");
        Directory.CreateDirectory(Path.GetDirectoryName(configPath)!);
        var config = new LauncherConfig
        {
            Version = 1,
            CanonicalProduction = new CanonicalProduction { Checkout = checkout, DataDir = dataDir, Database = Path.Combine(dataDir, "finance.db") },
            Profiles =
            [
                new LauncherProfile { Id = "stable", DisplayName = "Stable", Type = "stable", Checkout = checkout, ExpectedRef = "refs/tags/v0.8.0", DataDir = dataDir, Database = Path.Combine(dataDir, "finance.db"), OpenBrowser = false },
            ],
        };
        File.WriteAllText(configPath, JsonSerializer.Serialize(config, new JsonSerializerOptions { WriteIndented = true }));

        var loaded = LauncherConfig.LoadOrCreate(configPath, out var diag);
        Assert(loaded.Profiles[0].ExpectedRef == "refs/tags/v0.8.1", "Stale Stable ref must migrate once HEAD is proven at the v0.8.1 release commit.");
        Assert(diag.Contains("migrated", StringComparison.OrdinalIgnoreCase), "Proven migration must be diagnosable.");
        Assert(File.ReadAllText(configPath).Contains("refs/tags/v0.8.1", StringComparison.Ordinal), "Migrated file must persist the new expected_ref.");
    }
    finally
    {
        DeleteSyntheticTree(root);
    }
}

static void PortCollisionOffersRefreshNotStop()
{
    var stable = StableProfile("C:\\synthetic\\stable", "C:\\synthetic\\stable\\data", "C:\\synthetic\\stable\\data\\finance.db", "refs/tags/v0.8.1");
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
    applyBlocked.Invoke(form, [stable, portEx, false, false]);
    var buttons = AllControls(form).OfType<Button>().ToArray();
    Assert(!buttons.Single(button => button.Text == "Остановить").Enabled, "Stop must be disabled for an external port collision the launcher cannot stop.");
    Assert(buttons.Single(button => button.Text == "Обновить проверку").Enabled, "Refresh must be enabled for an external port collision.");
}

static void StableMismatchIsRecoveryOnly()
{
    var stable = StableProfile("C:\\s", "C:\\s\\data", "C:\\s\\data\\finance.db", "refs/tags/v0.8.1");
    var preview = new LauncherProfile { Id = "preview", DisplayName = "Preview", Type = "preview", Checkout = "C:\\p", ExpectedRef = "HEAD", DataDir = "C:\\p\\data", Database = "C:\\p\\data\\finance.db", OpenBrowser = false };
    var mismatch = new LauncherValidationException("Checkout identity does not match this profile.");

    var planStable = LauncherUi.PlanPrimaryAction(LauncherReadinessState.Blocked, null, stable, mismatch);
    Assert(planStable.Primary == LauncherPrimaryAction.Refresh, $"Stable identity mismatch must be recovery-only Refresh, not {planStable.Primary}. No launcher-owned fix may be promised.");
    var human = LauncherUi.OwnerFacingFailure(mismatch.Message);
    Assert(!human.Contains("C:\\", StringComparison.Ordinal), "Human message must not leak raw paths.");
    Assert(human.Contains("expected_ref", StringComparison.OrdinalIgnoreCase) || human.Contains("Обновить проверку", StringComparison.Ordinal), "Stable mismatch guidance must point at released-tag verification plus Refresh.");

    // No regression for Preview: its mismatch stays launcher-owned Update.
    var planPreview = LauncherUi.PlanPrimaryAction(LauncherReadinessState.Blocked, null, preview, mismatch);
    Assert(planPreview.Primary == LauncherPrimaryAction.Update, "Preview identity mismatch must keep launcher-owned Update.");
}

static string[] PrimaryCtaTexts() =>
[
    "Запустить", "Подготовить", "Обновить Preview", "Обновить и запустить", "Открыть Hermes", "Остановить",
];

static List<string> EnabledPrimaries(MainForm form) =>
    AllControls(form).OfType<Button>().Where(button => button.Enabled && PrimaryCtaTexts().Contains(button.Text)).Select(button => button.Text).ToList();

static LauncherProfile PreviewProfileForCta() => new()
{
    Id = "preview",
    DisplayName = "Preview",
    Type = "preview",
    Checkout = "C:\\p",
    ExpectedRef = "refs/remotes/origin/main",
    DataDir = "C:\\p\\data",
    Database = "C:\\p\\data\\finance.db",
    OpenBrowser = false,
};

static void ApplyValidatedOn(MainForm form, ValidatedProfile validated)
{
    var apply = typeof(MainForm).GetMethod("ApplyValidated", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
        ?? throw new InvalidOperationException("Could not find ApplyValidated for CTA planning.");
    apply.Invoke(form, [validated]);
}

static void PreviewCurrentStartsPrimary()
{
    var preview = PreviewProfileForCta();
    var stable = StableProfile("C:\\s", "C:\\s\\data", "C:\\s\\data\\finance.db", "refs/tags/v0.8.1");
    using var form = new MainForm(new LauncherConfig
    {
        Version = 1,
        CanonicalProduction = new CanonicalProduction { Checkout = stable.Checkout, DataDir = stable.DataDir, Database = stable.Database },
        Profiles = [stable, preview],
    });
    var validated = new ValidatedProfile(
        preview, preview.Checkout, preview.DataDir, preview.Database, "cur1234",
        "preview", new DependencyStatus(true, true, "ready", "ready"),
        new PreviewUpdateStatus("cur1234", "cur1234"));
    ApplyValidatedOn(form, validated);
    var primaries = EnabledPrimaries(form);
    Assert(primaries.Count == 1 && primaries[0] == "Запустить", $"Preview current + deps ready must have exactly one primary CTA 'Запустить', found [{string.Join(",", primaries)}].");
}

static void PreviewBehindUpdatesPrimary()
{
    var preview = PreviewProfileForCta();
    var stable = StableProfile("C:\\s", "C:\\s\\data", "C:\\s\\data\\finance.db", "refs/tags/v0.8.1");
    using var form = new MainForm(new LauncherConfig
    {
        Version = 1,
        CanonicalProduction = new CanonicalProduction { Checkout = stable.Checkout, DataDir = stable.DataDir, Database = stable.Database },
        Profiles = [stable, preview],
    });
    var validated = new ValidatedProfile(
        preview, preview.Checkout, preview.DataDir, preview.Database, "cur1111",
        "preview", new DependencyStatus(true, true, "ready", "ready"),
        new PreviewUpdateStatus("cur1111", "tgt2222"));
    ApplyValidatedOn(form, validated);
    var primaries = EnabledPrimaries(form);
    Assert(primaries.Count == 2 && primaries.Contains("Обновить Preview") && primaries.Contains("Обновить и запустить"),
        $"Preview behind + deps ready must offer Update primaries, found [{string.Join(",", primaries)}].");
    var buttons = AllControls(form).OfType<Button>().ToArray();
    Assert(!buttons.Single(button => button.Text == "Запустить").Enabled, "Start must not be offered while a prepared Preview update is pending.");
    var plan = LauncherUi.PlanPrimaryAction(LauncherReadinessState.Ready, validated, preview, null);
    Assert(plan.Primary == LauncherPrimaryAction.Update, $"Preview behind + deps ready must plan Update primary, got {plan.Primary}.");
}

static void PreviewBehindMissingDepsOffersSingleSafePrimary()
{
    var preview = PreviewProfileForCta();
    var stable = StableProfile("C:\\s", "C:\\s\\data", "C:\\s\\data\\finance.db", "refs/tags/v0.8.1");
    using var form = new MainForm(new LauncherConfig
    {
        Version = 1,
        CanonicalProduction = new CanonicalProduction { Checkout = stable.Checkout, DataDir = stable.DataDir, Database = stable.Database },
        Profiles = [stable, preview],
    });
    var validated = new ValidatedProfile(
        preview, preview.Checkout, preview.DataDir, preview.Database, "cur1111",
        "preview", new DependencyStatus(false, false, "needs preparation", "needs preparation"),
        new PreviewUpdateStatus("cur1111", "tgt2222"));
    ApplyValidatedOn(form, validated);
    var primaries = EnabledPrimaries(form);
    Assert(primaries.Count == 1 && primaries[0] == "Обновить и запустить",
        $"Preview behind + deps missing must offer exactly one primary CTA 'Обновить и запустить', found [{string.Join(",", primaries)}].");
    var buttons = AllControls(form).OfType<Button>().ToArray();
    Assert(!buttons.Single(button => button.Text == "Подготовить").Enabled, "Prepare must not compete with the update-first chain when Preview is behind.");
    Assert(!buttons.Single(button => button.Text == "Запустить").Enabled, "Start must stay disabled until update + preparation complete.");
    var plan = LauncherUi.PlanPrimaryAction(LauncherReadinessState.NeedsPreparation, validated, preview, null);
    Assert(plan.Primary == LauncherPrimaryAction.UpdateAndStart, $"Preview behind + deps missing must plan UpdateAndStart primary, got {plan.Primary}.");
}

static void StableReadyStartsPrimary()
{
    var stable = StableProfile("C:\\synthetic\\stable", "C:\\synthetic\\stable\\data", "C:\\synthetic\\stable\\data\\finance.db", "refs/tags/v0.8.1");
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
        RunGit(stableCheckout, "tag", "v0.8.1");
        CreateRuntimeLayout(previewCheckout);
        Directory.CreateDirectory(previewData);
        RunGit(previewCheckout, "init");
        RunGit(previewCheckout, "config", "--local", "user.name", "Hermes Safety Test");
        RunGit(previewCheckout, "config", "--local", "user.email", "hermes-safety-test");
        RunGit(previewCheckout, "add", ".");
        RunGit(previewCheckout, "commit", "-m", "synthetic preview at origin/main");
        RunGit(previewCheckout, "update-ref", "refs/remotes/origin/main", "HEAD");

        // Synthetic owner selections become a concrete valid config — no manual JSON.
        var config = LauncherSetup.BuildConfig(stableCheckout, stableData, previewCheckout, previewData);
        Assert(config.Profiles[0].ExpectedRef == "refs/tags/v0.8.1", "Setup must pin Stable to the v0.8.1 release.");
        Assert(config.Profiles[1].ExpectedRef == "refs/remotes/origin/main", "Setup must point Preview at origin/main.");
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

static void InitSyntheticRepo(string checkout, string commitMessage)
{
    RunGit(checkout, "init");
    RunGit(checkout, "config", "--local", "user.name", "Hermes Safety Test");
    RunGit(checkout, "config", "--local", "user.email", "hermes-safety-test");
    RunGit(checkout, "add", ".");
    RunGit(checkout, "commit", "-m", commitMessage);
}

static void CommitSyntheticFile(string checkout, string fileName, string content, string commitMessage)
{
    File.WriteAllText(Path.Combine(checkout, fileName), content);
    RunGit(checkout, "add", fileName);
    RunGit(checkout, "commit", "-m", commitMessage);
}

static void SetupRejectsStableOffRelease()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-setup-stale-{Guid.NewGuid():N}");
    var stableCheckout = Path.Combine(root, "stable");
    var stableData = Path.Combine(root, "stable-data");
    var previewCheckout = Path.Combine(root, "preview");
    var previewData = Path.Combine(root, "preview-data");
    try
    {
        CreateRuntimeLayout(stableCheckout);
        Directory.CreateDirectory(stableData);
        InitSyntheticRepo(stableCheckout, "synthetic stable at release");
        RunGit(stableCheckout, "tag", "v0.8.1");
        // Tag exists, but HEAD moved past the release commit.
        CommitSyntheticFile(stableCheckout, "post-release.txt", "drifted past v0.8.1", "synthetic post-release drift");
        CreateRuntimeLayout(previewCheckout);
        Directory.CreateDirectory(previewData);
        InitSyntheticRepo(previewCheckout, "synthetic preview at origin/main");
        RunGit(previewCheckout, "update-ref", "refs/remotes/origin/main", "HEAD");

        try
        {
            LauncherSetup.BuildConfig(stableCheckout, stableData, previewCheckout, previewData);
            throw new InvalidOperationException("Setup must reject a Stable checkout off the v0.8.1 release commit.");
        }
        catch (LauncherValidationException exception)
        {
            Assert(exception.Message.Contains("Stable", StringComparison.Ordinal), "Stable rejection must name the Stable checkout.");
        }
    }
    finally
    {
        DeleteSyntheticTree(root);
    }
}

static void SetupRejectsPreviewWithoutOriginMain()
{
    var root = Path.Combine(Path.GetTempPath(), $"hermes-launcher-setup-no-main-{Guid.NewGuid():N}");
    var stableCheckout = Path.Combine(root, "stable");
    var stableData = Path.Combine(root, "stable-data");
    var previewCheckout = Path.Combine(root, "preview");
    var previewData = Path.Combine(root, "preview-data");
    try
    {
        CreateRuntimeLayout(stableCheckout);
        Directory.CreateDirectory(stableData);
        InitSyntheticRepo(stableCheckout, "synthetic stable at release");
        RunGit(stableCheckout, "tag", "v0.8.1");
        CreateRuntimeLayout(previewCheckout);
        Directory.CreateDirectory(previewData);
        // A plain git repo: no refs/remotes/origin/main exists.
        InitSyntheticRepo(previewCheckout, "synthetic preview without origin/main");

        try
        {
            LauncherSetup.BuildConfig(stableCheckout, stableData, previewCheckout, previewData);
            throw new InvalidOperationException("Setup must reject a Preview checkout without refs/remotes/origin/main.");
        }
        catch (LauncherValidationException exception)
        {
            Assert(exception.Message.Contains("Preview", StringComparison.Ordinal), "Preview rejection must name the Preview checkout.");
        }
    }
    finally
    {
        DeleteSyntheticTree(root);
    }
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
        RunGit(stableCheckout, "tag", "v0.8.1");
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
        RunGit(stableCheckout, "tag", "v0.8.1");
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
    var stable = StableProfile("C:\\s", "C:\\s\\data", "C:\\s\\data\\finance.db", "refs/tags/v0.8.1");
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
