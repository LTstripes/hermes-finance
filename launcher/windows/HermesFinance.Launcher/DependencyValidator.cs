using System.ComponentModel;
using System.Diagnostics;
using System.Text.Json;

namespace HermesFinance.Launcher;

public sealed record DependencyStatus(
    bool BackendReady,
    bool FrontendReady,
    string BackendDetail,
    string FrontendDetail)
{
    public bool Ready => BackendReady && FrontendReady;
    public bool RequiresPreparation => !Ready;
}

internal static class DependencyValidator
{
    public static DependencyStatus Check(string checkout)
    {
        var backend = Path.Combine(checkout, "backend");
        var frontend = Path.Combine(checkout, "frontend");
        RequireFile(Path.Combine(backend, "pyproject.toml"), "Backend project metadata is missing.");
        RequireFile(Path.Combine(backend, "uv.lock"), "Backend lockfile is missing.");
        RequireFile(Path.Combine(frontend, "package.json"), "Frontend project metadata is missing.");
        RequireFile(Path.Combine(frontend, "package-lock.json"), "Frontend lockfile is missing.");

        var backendCheck = RunCommand("uv", backend, "sync", "--locked", "--dry-run", "--offline");
        if (backendCheck.ExitCode != 0)
        {
            throw new LauncherValidationException(
                $"Backend dependency check failed: {OneLine(backendCheck.StandardError, backendCheck.StandardOutput)}");
        }

        var backendOutput = $"{backendCheck.StandardOutput}\n{backendCheck.StandardError}";
        var backendNeedsPreparation = System.Text.RegularExpressions.Regex.IsMatch(
            backendOutput,
            @"(?im)^\s*Would\s+(create|download|install|remove|uninstall|update|reinstall|build)\b");
        var backendDetail = backendNeedsPreparation
            ? $"needs preparation: {OneLine(backendOutput, "uv reports a pending environment change.")}"
            : "ready (locked environment is synchronized)";

        var nodeModules = Path.Combine(frontend, "node_modules");
        DependencyCommandResult frontendCheck;
        if (!Directory.Exists(nodeModules))
        {
            frontendCheck = new DependencyCommandResult(2, "", "node_modules is missing.");
        }
        else
        {
            frontendCheck = RunCommand(
                "npm.cmd",
                frontend,
                "ls",
                "--all",
                "--depth=0",
                "--json",
                "--omit=optional");
        }

        var frontendNeedsPreparation = !Directory.Exists(nodeModules);
        var frontendDetail = frontendNeedsPreparation
            ? "needs preparation: frontend/node_modules is missing"
            : ParseNpmStatus(frontendCheck, out frontendNeedsPreparation);

        return new DependencyStatus(
            !backendNeedsPreparation,
            !frontendNeedsPreparation,
            backendDetail,
            frontendDetail);
    }

    internal static ProcessStartInfo BuildPreparationCommand(string checkout, bool repair = false)
    {
        var powershell = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Windows),
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
        if (!File.Exists(powershell))
        {
            powershell = "powershell.exe";
        }

        var helper = Path.Combine(AppContext.BaseDirectory, "prepare-runtime-dependencies.ps1");
        if (!File.Exists(helper))
        {
            throw new LauncherValidationException("Dependency preparation is unavailable: helper is missing.");
        }

        var command = new ProcessStartInfo
        {
            FileName = powershell,
            WorkingDirectory = checkout,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        command.ArgumentList.Add("-NoProfile");
        command.ArgumentList.Add("-ExecutionPolicy");
        command.ArgumentList.Add("Bypass");
        command.ArgumentList.Add("-File");
        command.ArgumentList.Add(helper);
        command.ArgumentList.Add("-Checkout");
        command.ArgumentList.Add(checkout);
        command.ArgumentList.Add(repair ? "-Repair" : "-Prepare");
        return command;
    }

    private static string ParseNpmStatus(DependencyCommandResult result, out bool needsPreparation)
    {
        if (string.IsNullOrWhiteSpace(result.StandardOutput))
        {
            throw new LauncherValidationException(
                $"Frontend dependency check returned no result: {OneLine(result.StandardError, "npm returned no JSON status.")}");
        }

        try
        {
            using var document = JsonDocument.Parse(result.StandardOutput);
            if (document.RootElement.TryGetProperty("problems", out var problems)
                && problems.ValueKind == JsonValueKind.Array
                && problems.GetArrayLength() > 0)
            {
                needsPreparation = true;
                var first = problems.EnumerateArray().FirstOrDefault().GetString();
                return $"needs preparation: {first ?? "npm reports an inconsistent dependency tree."}";
            }
        }
        catch (JsonException exception)
        {
            throw new LauncherValidationException($"Frontend dependency check returned invalid JSON: {exception.Message}");
        }

        if (result.ExitCode != 0)
        {
            needsPreparation = true;
            return $"needs preparation: {OneLine(result.StandardError, "npm reports an inconsistent dependency tree.")}";
        }

        needsPreparation = false;
        return "ready (package-lock dependency tree is present)";
    }

    private static DependencyCommandResult RunCommand(string fileName, string workingDirectory, params string[] arguments)
    {
        var resolvedFileName = ResolveCommand(fileName, workingDirectory);
        var command = new ProcessStartInfo
        {
            FileName = resolvedFileName,
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var argument in arguments)
        {
            command.ArgumentList.Add(argument);
        }

        try
        {
            using var process = Process.Start(command)
                ?? throw new LauncherValidationException($"Could not start dependency '{fileName}'.");
            var standardOutput = process.StandardOutput.ReadToEnd();
            var standardError = process.StandardError.ReadToEnd();
            process.WaitForExit();
            return new DependencyCommandResult(process.ExitCode, standardOutput, standardError);
        }
        catch (Win32Exception exception)
        {
            throw new LauncherValidationException(
                $"Dependency check cannot run '{fileName}' resolved as '{resolvedFileName}': {exception.Message}");
        }
    }

    internal static string ResolveCommand(string fileName, string workingDirectory)
    {
        if (string.IsNullOrWhiteSpace(fileName))
        {
            throw new LauncherValidationException("Dependency command name is empty.");
        }

        if (Path.IsPathRooted(fileName))
        {
            if (File.Exists(fileName))
            {
                return Path.GetFullPath(fileName);
            }

            throw MissingDependency(fileName);
        }

        var searchDirectories = new List<string> { workingDirectory };
        var path = Environment.GetEnvironmentVariable("PATH");
        if (!string.IsNullOrWhiteSpace(path))
        {
            searchDirectories.AddRange(path.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries));
        }

        var extensions = CommandExtensions(fileName);
        foreach (var directory in searchDirectories)
        {
            foreach (var extension in extensions)
            {
                var candidate = Path.Combine(directory, fileName + extension);
                if (File.Exists(candidate))
                {
                    return Path.GetFullPath(candidate);
                }
            }
        }

        throw MissingDependency(fileName);
    }

    private static string[] CommandExtensions(string fileName)
    {
        if (!OperatingSystem.IsWindows() || !string.IsNullOrEmpty(Path.GetExtension(fileName)))
        {
            return [string.Empty];
        }

        var pathExtensions = Environment.GetEnvironmentVariable("PATHEXT");
        return string.IsNullOrWhiteSpace(pathExtensions)
            ? [".COM", ".EXE", ".BAT", ".CMD"]
            : pathExtensions.Split(';', StringSplitOptions.RemoveEmptyEntries);
    }

    private static LauncherValidationException MissingDependency(string fileName)
    {
        var hint = fileName.Equals("npm.cmd", StringComparison.OrdinalIgnoreCase)
            ? "Install Node.js and ensure npm.cmd is on PATH."
            : $"Install '{fileName}' and ensure it is on PATH.";
        return new LauncherValidationException(
            $"Missing dependency '{fileName}' required for {(fileName.Equals("npm.cmd", StringComparison.OrdinalIgnoreCase) ? "frontend" : "backend")} dependency validation. {hint}");
    }

    private static void RequireFile(string path, string message)
    {
        if (!File.Exists(path))
        {
            throw new LauncherValidationException(message);
        }
    }

    private static string OneLine(string preferred, string fallback)
    {
        var value = string.IsNullOrWhiteSpace(preferred) ? fallback : preferred;
        return value.ReplaceLineEndings(" ").Trim();
    }

    private sealed record DependencyCommandResult(int ExitCode, string StandardOutput, string StandardError);
}
