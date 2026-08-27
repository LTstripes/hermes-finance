using HermesFinance.Launcher;
using System.Text.Json;

var tests = new (string Name, Action Run)[]
{
    ("rejects unknown config fields", RejectsUnknownConfigFields),
    ("requires exactly one stable profile", RequiresExactlyOneStableProfile),
    ("rejects preview aliases to the production database before startup", RejectsUnsafeTupleAliases),
    ("constructs a PowerShell -File command without splitting spaces", ConstructsQuotedStartCommand),
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
        Console.Error.WriteLine($"FAIL {test.Name}: {exception.Message}");
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
                new LauncherProfile { Id = "preview", DisplayName = "Preview", Type = "preview", Checkout = preview, ExpectedRef = "HEAD", DataDir = Path.Combine(preview, "data"), Database = Path.Combine(stable, "data", "finance.db"), OpenBrowser = false },
            ],
        };
        AssertThrows<LauncherValidationException>(() => ProfileValidator.Validate(config, config.Profiles[1]));
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
}
