using HermesFinance.Launcher;
using System.Text.Json;

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
    ("presents the minimal owner launcher surface", PresentsMinimalOwnerSurface),
    ("keeps Stable and Preview data boundaries visibly distinct", KeepsProfileBoundariesDistinct),
    ("shows exact Stable and isolated Preview identity", ShowsConfiguredIdentity),
    ("sanitizes raw paths from owner-facing blockers", SanitizesOwnerFacingBlockers),
    ("requires exactly one stable profile", RequiresExactlyOneStableProfile),
    ("returns Start for a ready prepared profile", ReadyProfileStarts),
    ("returns Prepare when dependencies are missing", MissingDependenciesPrepare),
    ("returns Refresh for identity mismatch", IdentityMismatchRefreshes),
    ("returns Stop only for a running profile", RunningProfileStops),
    ("does not expose updater or follow-main copy", NoUpdaterCopy),
    ("parses the runtime application version", ParsesApplicationVersion),
    ("builds an offline dependency check for the selected checkout", BuildsDependencyCheck),
    ("keeps package/install scripts free of Git mutation", PackageScriptsRemainGuarded),
    ("keeps package/install smoke script present", PackageSmokeRemainsPresent),
};

var failures = 0;
foreach (var test in tests)
{
    try { test.Run(); Console.WriteLine($"PASS {test.Name}"); }
    catch (Exception exception) { failures++; Console.Error.WriteLine($"FAIL {test.Name}: {exception}"); }
}
return failures == 0 ? 0 : 1;

static void LoadsCanonicalConfigExample()
{
    var config = LauncherConfig.Load(Path.Combine(AppContext.BaseDirectory, "config.example.json"));
    Assert(config.Version == 1, "config version must be 1");
    Assert(config.Profiles.Count == 2, "canonical example must contain Stable and Preview");
    Assert(config.Profiles.Any(profile => profile.Type == "stable"), "Stable profile is required");
    Assert(config.Profiles.Any(profile => profile.Type == "preview"), "Preview profile is required");
}

static void RejectsUnknownConfigFields()
{
    const string json = """{"version":1,"canonical_production":{"checkout":"C:\\s","data_dir":"C:\\s\\data","database":"C:\\s\\data\\finance.db"},"profiles":[],"token":"forbidden"}""";
    AssertThrows<JsonException>(() => JsonSerializer.Deserialize<LauncherConfig>(json, LauncherConfig.JsonOptions));
}

static void PresentsMinimalOwnerSurface()
{
    using var form = MainForm.CreateSyntheticSmoke();
    var buttons = AllControls(form).OfType<Button>().Select(button => button.Text).ToArray();
    foreach (var obsolete in new[] { "Обновить Preview", "Обновить и запустить", "Обновить Stable" })
    {
        Assert(!buttons.Contains(obsolete, StringComparer.Ordinal), $"obsolete CTA remains: {obsolete}");
    }
    Assert(buttons.Contains("Запустить") && buttons.Contains("Остановить") && buttons.Contains("Открыть Hermes"), "Start/Stop/Open must remain available");
    Assert(buttons.Contains("Обновить проверку") && buttons.Contains("Диагностика и логи"), "refresh and diagnostics must remain available");
}

static void KeepsProfileBoundariesDistinct()
{
    Assert(LauncherUi.TypeBadge("stable") != LauncherUi.TypeBadge("preview"), "badges must differ");
    Assert(LauncherUi.DataBoundary("stable") == "Canonical production data", "Stable boundary must be production");
    Assert(LauncherUi.DataBoundary("preview") == "Isolated UAT / synthetic data", "Preview boundary must be isolated");
    Assert(LauncherUi.AccentFor("stable") != LauncherUi.AccentFor("preview"), "accents must differ");
}

static void ShowsConfiguredIdentity()
{
    var stable = StableProfile("refs/tags/v0.9.0");
    var preview = PreviewProfile();
    var stableLabel = LauncherUi.StableIdentityLabel(stable, "d04f46696a991ea59066b59d4870980ac4b69089");
    var previewLabel = LauncherUi.PreviewIdentityLabel(preview, "aaaaaaa1111111111111111111111111111111111");
    Assert(stableLabel.Contains("v0.9.0") && stableLabel.Contains("d04f466"), "Stable must show configured release and exact SHA");
    Assert(stableLabel.Contains("production", StringComparison.OrdinalIgnoreCase), "Stable must show production boundary");
    Assert(previewLabel.Contains("main") && previewLabel.Contains("UNRELEASED") && previewLabel.Contains("isolated", StringComparison.OrdinalIgnoreCase), "Preview must show current main identity and isolated boundary");
}

static void SanitizesOwnerFacingBlockers()
{
    var message = LauncherUi.OwnerFacingFailure("database C:\\owner\\private\\finance.db aliases production");
    Assert(!message.Contains("C:\\owner", StringComparison.OrdinalIgnoreCase) && !message.Contains("finance.db", StringComparison.OrdinalIgnoreCase), "private paths must not reach owner copy");
}

static void RequiresExactlyOneStableProfile()
{
    var config = new LauncherConfig { Version = 1, CanonicalProduction = new CanonicalProduction { Checkout = "C:\\s", DataDir = "C:\\s\\data", Database = "C:\\s\\data\\finance.db" }, Profiles = [PreviewProfile(), PreviewProfile("preview-2")] };
    AssertThrows<LauncherValidationException>(() => ProfileValidator.ValidateConfiguration(config));
}

static void ReadyProfileStarts()
{
    var plan = LauncherUi.PlanPrimaryAction(LauncherReadinessState.Ready, null, StableProfile("refs/tags/v0.9.0"));
    Assert(plan.Primary == LauncherPrimaryAction.Start, "ready profile must start");
}

static void MissingDependenciesPrepare()
{
    var profile = StableProfile("refs/tags/v0.9.0");
    var validated = new ValidatedProfile(profile, profile.Checkout, profile.DataDir, profile.Database, "abc", "production", new DependencyStatus(false, false, "needs", "needs"));
    var plan = LauncherUi.PlanPrimaryAction(LauncherReadinessState.NeedsPreparation, validated, profile);
    Assert(plan.Primary == LauncherPrimaryAction.Prepare, "missing dependencies must offer Prepare");
}

static void IdentityMismatchRefreshes()
{
    var plan = LauncherUi.PlanPrimaryAction(LauncherReadinessState.Blocked, null, PreviewProfile(), new LauncherValidationException("Checkout identity does not match this profile."));
    Assert(plan.Primary == LauncherPrimaryAction.Refresh, "identity mismatch must remain read-only Refresh");
}

static void RunningProfileStops()
{
    var plan = LauncherUi.PlanPrimaryAction(LauncherReadinessState.Running, null, StableProfile("refs/tags/v0.9.0"));
    Assert(plan.Primary == LauncherPrimaryAction.Stop, "running profile must offer Stop");
}

static void NoUpdaterCopy()
{
    var sourceRoot = Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..");
    foreach (var file in new[] { "MainForm.cs", "LauncherUi.cs", "ProfileValidator.cs", "LauncherConfig.cs" })
    {
        var source = File.ReadAllText(Path.Combine(sourceRoot, "HermesFinance.Launcher", file));
        Assert(!source.Contains("PreviewUpdateService", StringComparison.Ordinal) && !source.Contains("StableReleaseService", StringComparison.Ordinal), $"{file} must not call updater services");
        Assert(!source.Contains("Обновить Preview", StringComparison.Ordinal) && !source.Contains("Обновить Stable", StringComparison.Ordinal), $"{file} must not expose updater CTAs");
    }
}

static void ParsesApplicationVersion()
{
    Assert(ProfileValidator.ParseApplicationVersion("__version__ = '0.9.0'\n") == "0.9.0", "version parser must preserve runtime identity");
    Assert(ProfileValidator.ParseApplicationVersion("__version__ = 'unknown'\n") is null, "invalid version must remain unknown");
}

static void BuildsDependencyCheck()
{
    var command = DependencyValidator.BuildPreparationCommand("C:\\synthetic\\checkout");
    Assert(command.WorkingDirectory.EndsWith("checkout", StringComparison.OrdinalIgnoreCase), "dependency check must use selected checkout");
}

static void PackageScriptsRemainGuarded()
{
    var root = Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "..");
    foreach (var name in new[] { "package.ps1", "install.ps1" })
    {
        var source = File.ReadAllText(Path.Combine(root, "launcher", "windows", name));
        Assert(!source.Contains("git pull", StringComparison.OrdinalIgnoreCase) && !source.Contains("git switch", StringComparison.OrdinalIgnoreCase), $"{name} must not mutate Git");
    }
}

static void PackageSmokeRemainsPresent()
{
    var root = Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "..");
    Assert(File.Exists(Path.Combine(root, "scripts", "tests", "test-windows-launcher-package.ps1")), "package/install smoke must remain part of retained verification");
}

static LauncherProfile StableProfile(string expectedRef, string id = "stable") => new()
{
    Id = id, DisplayName = "Hermes Finance — Stable", Type = "stable", Checkout = "C:\\synthetic\\stable", ExpectedRef = expectedRef,
    DataDir = "C:\\synthetic\\stable\\data", Database = "C:\\synthetic\\stable\\data\\finance.db", OpenBrowser = false,
};

static LauncherProfile PreviewProfile(string id = "preview") => new()
{
    Id = id, DisplayName = "Hermes Finance — Preview", Type = "preview", Checkout = "C:\\synthetic\\preview", ExpectedRef = "refs/remotes/origin/main",
    DataDir = "C:\\synthetic\\preview\\data", Database = "C:\\synthetic\\preview\\data\\finance.db", OpenBrowser = false,
};

static IEnumerable<Control> AllControls(Control root)
{
    foreach (Control child in root.Controls)
    {
        yield return child;
        foreach (var nested in AllControls(child)) yield return nested;
    }
}

static void AssertThrows<TException>(Action action) where TException : Exception
{
    try { action(); }
    catch (TException) { return; }
    throw new InvalidOperationException($"Expected {typeof(TException).Name}.");
}

static void Assert(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
}
