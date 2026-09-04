using System.Diagnostics;
using System.ComponentModel;
using System.Net;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace HermesFinance.Launcher;

internal sealed record LauncherOwnershipMarker
{
    public required int Version { get; init; }
    public required string ProfileId { get; init; }
    public required string ProfileType { get; init; }
    public required string Checkout { get; init; }
    public required string DataDir { get; init; }
    public required string Database { get; init; }
    public required string Head { get; init; }
    public required int ProcessId { get; init; }
    public required long ProcessStartTimeUtcTicks { get; init; }
    public required string ExecutablePath { get; init; }
    public required string WorkingDirectory { get; init; }
    public required string[] Arguments { get; init; }
    public required string CommandFingerprint { get; init; }
    public required bool Ready { get; init; }
}

internal sealed record RecoveredLauncherProcess(Process Process, LauncherOwnershipMarker Marker);

internal sealed class LauncherProcessOwnership
{
    private const int MarkerVersion = 1;
    private const string OwnershipDirectoryName = "ownership";
    private static readonly JsonSerializerOptions MarkerJsonOptions = new()
    {
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        WriteIndented = true,
    };

    private readonly string _directory;

    internal LauncherProcessOwnership(string? directory = null)
    {
        _directory = directory ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "HermesFinance",
            "launcher",
            OwnershipDirectoryName);
    }

    internal string GetMarkerPath(ValidatedProfile profile)
    {
        var identity = string.Join(
            "\0",
            profile.Profile.Id,
            profile.Profile.Type,
            profile.Checkout,
            profile.DataDir,
            profile.Database);
        var key = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(identity))).ToLowerInvariant();
        return Path.Combine(_directory, $"{key}.json");
    }

    internal void Write(ValidatedProfile profile, Process process)
    {
        var existing = ReadMarker(profile);
        if (existing is not null)
        {
            try
            {
                using var existingProcess = Process.GetProcessById(existing.ProcessId);
                if (MatchesProcess(profile, existing, existingProcess, requireReady: false))
                {
                    throw new LauncherValidationException("A launcher-owned Hermes process is already running for this profile.");
                }
            }
            catch (ArgumentException)
            {
                DeleteMarker(profile);
            }
            catch (InvalidOperationException)
            {
                DeleteMarker(profile);
            }
            catch (Win32Exception)
            {
                DeleteMarker(profile);
            }
        }

        var startInfo = process.StartInfo;
        var executable = Path.GetFullPath(startInfo.FileName);
        var marker = new LauncherOwnershipMarker
        {
            Version = MarkerVersion,
            ProfileId = profile.Profile.Id,
            ProfileType = profile.Profile.Type,
            Checkout = profile.Checkout,
            DataDir = profile.DataDir,
            Database = profile.Database,
            Head = profile.Head,
            ProcessId = process.Id,
            ProcessStartTimeUtcTicks = process.StartTime.ToUniversalTime().Ticks,
            ExecutablePath = executable,
            WorkingDirectory = Path.GetFullPath(startInfo.WorkingDirectory),
            Arguments = startInfo.ArgumentList.ToArray(),
            CommandFingerprint = Fingerprint(executable, startInfo.WorkingDirectory, startInfo.ArgumentList),
            Ready = false,
        };
        WriteMarker(profile, marker);
    }

    internal bool MarkReady(ValidatedProfile profile, Process process)
    {
        var marker = ReadMarker(profile);
        if (marker is null || !MatchesProcess(profile, marker, process, requireReady: false))
        {
            return false;
        }

        WriteMarker(profile, marker with { Ready = true });
        return true;
    }

    internal RecoveredLauncherProcess? TryRecover(ValidatedProfile profile)
    {
        var marker = ReadMarker(profile);
        if (marker is null)
        {
            return null;
        }

        if (!MatchesProfile(profile, marker))
        {
            DeleteMarker(profile);
            return null;
        }

        if (!marker.Ready)
        {
            try
            {
                using var startingProcess = Process.GetProcessById(marker.ProcessId);
                if (MatchesProcess(profile, marker, startingProcess, requireReady: false))
                {
                    return null;
                }
            }
            catch (ArgumentException)
            {
            }
            catch (InvalidOperationException)
            {
            }
            catch (Win32Exception)
            {
            }
            DeleteMarker(profile);
            return null;
        }

        Process? process = null;
        try
        {
            process = Process.GetProcessById(marker.ProcessId);
            if (!MatchesProcess(profile, marker, process, requireReady: true)
                || !IsLoopbackPortOwnedByProcessTree(process.Id))
            {
                process.Dispose();
                DeleteMarker(profile);
                return null;
            }
            process.EnableRaisingEvents = true;
            return new RecoveredLauncherProcess(process, marker);
        }
        catch (ArgumentException)
        {
            process?.Dispose();
            DeleteMarker(profile);
            return null;
        }
        catch (InvalidOperationException)
        {
            process?.Dispose();
            DeleteMarker(profile);
            return null;
        }
        catch (Win32Exception)
        {
            process?.Dispose();
            DeleteMarker(profile);
            return null;
        }
    }

    internal bool ProvesOwnership(ValidatedProfile profile, Process process)
    {
        var marker = ReadMarker(profile);
        return marker is not null && MatchesProfile(profile, marker) && MatchesProcess(profile, marker, process, requireReady: false);
    }

    internal void RemoveIfOwned(ValidatedProfile profile, Process process, long? knownStartTimeUtcTicks = null)
    {
        var marker = ReadMarker(profile);
        if (marker is not null
            && MatchesProfile(profile, marker)
            && marker.ProcessId == process.Id
            && (knownStartTimeUtcTicks == marker.ProcessStartTimeUtcTicks
                || MatchesProcess(profile, marker, process, requireReady: false, requireRunning: false, requireExecutable: false)))
        {
            DeleteMarker(profile);
        }
    }

    private LauncherOwnershipMarker? ReadMarker(ValidatedProfile profile)
    {
        var path = GetMarkerPath(profile);
        if (!File.Exists(path))
        {
            return null;
        }

        try
        {
            return JsonSerializer.Deserialize<LauncherOwnershipMarker>(File.ReadAllText(path), MarkerJsonOptions);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or JsonException)
        {
            DeleteMarker(profile);
            return null;
        }
    }

    private void WriteMarker(ValidatedProfile profile, LauncherOwnershipMarker marker)
    {
        var path = GetMarkerPath(profile);
        Directory.CreateDirectory(_directory);
        var temporary = path + $".{Guid.NewGuid():N}.tmp";
        try
        {
            File.WriteAllText(temporary, JsonSerializer.Serialize(marker, MarkerJsonOptions), new UTF8Encoding(false));
            File.Move(temporary, path, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporary))
            {
                File.Delete(temporary);
            }
        }
    }

    private void DeleteMarker(ValidatedProfile profile)
    {
        try
        {
            File.Delete(GetMarkerPath(profile));
        }
        catch (IOException)
        {
            // A stale marker is fail-closed even when a transient cleanup error
            // prevents deletion; the next recovery attempt will ignore it again.
        }
        catch (UnauthorizedAccessException)
        {
            // Do not turn cleanup failure into permission to infer ownership.
        }
    }

    private static bool MatchesProfile(ValidatedProfile profile, LauncherOwnershipMarker marker)
    {
        try
        {
            return marker.Version == MarkerVersion
                && string.Equals(marker.ProfileId, profile.Profile.Id, StringComparison.Ordinal)
                && string.Equals(marker.ProfileType, profile.Profile.Type, StringComparison.OrdinalIgnoreCase)
                && SamePath(marker.Checkout, profile.Checkout)
                && SamePath(marker.DataDir, profile.DataDir)
                && SamePath(marker.Database, profile.Database)
                && string.Equals(marker.Head, profile.Head, StringComparison.OrdinalIgnoreCase);
        }
        catch (ArgumentException)
        {
            return false;
        }
    }

    private static bool MatchesProcess(
        ValidatedProfile profile,
        LauncherOwnershipMarker marker,
        Process process,
        bool requireReady,
        bool requireRunning = true,
        bool requireExecutable = true)
    {
        if (!MatchesProfile(profile, marker) || (requireReady && !marker.Ready) || process.Id != marker.ProcessId)
        {
            return false;
        }

        try
        {
            if (requireRunning && process.HasExited)
            {
                return false;
            }
            if (process.StartTime.ToUniversalTime().Ticks != marker.ProcessStartTimeUtcTicks)
            {
                return false;
            }

            if (!requireExecutable)
            {
                return true;
            }

            var executable = process.MainModule?.FileName;
            if (string.IsNullOrWhiteSpace(executable) || !SamePath(executable, marker.ExecutablePath))
            {
                return false;
            }

            var expected = ProfileValidator.BuildStartCommand(profile);
            return SamePath(expected.FileName, marker.ExecutablePath)
                && SamePath(expected.WorkingDirectory, marker.WorkingDirectory)
                && expected.ArgumentList.SequenceEqual(marker.Arguments, StringComparer.Ordinal)
                && string.Equals(
                    Fingerprint(expected.FileName, expected.WorkingDirectory, expected.ArgumentList),
                    marker.CommandFingerprint,
                    StringComparison.Ordinal);
        }
        catch (InvalidOperationException)
        {
            return false;
        }
        catch (Win32Exception)
        {
            return false;
        }
    }

    private static string Fingerprint(string executable, string workingDirectory, IEnumerable<string> arguments)
    {
        var command = string.Join("\0", new[] { executable, workingDirectory }.Concat(arguments));
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(command))).ToLowerInvariant();
    }

    private static bool SamePath(string left, string right) =>
        string.Equals(
            Path.TrimEndingDirectorySeparator(Path.GetFullPath(left)),
            Path.TrimEndingDirectorySeparator(Path.GetFullPath(right)),
            StringComparison.OrdinalIgnoreCase);

    internal static bool IsLoopbackPortOwnedByProcessTree(int rootPid)
    {
        if (!OperatingSystem.IsWindows())
        {
            return false;
        }

        var processParents = ReadProcessParents();
        foreach (var listenerPid in ReadLoopbackListenerPids())
        {
            var current = listenerPid;
            var visited = new HashSet<int>();
            while (current > 0 && visited.Add(current))
            {
                if (current == rootPid)
                {
                    return true;
                }
                if (!processParents.TryGetValue(current, out current))
                {
                    break;
                }
            }
        }
        return false;
    }

    private static IEnumerable<int> ReadLoopbackListenerPids()
    {
        const int afInet = 2;
        const int tcpTableOwnerPidListener = 3;
        const uint errorInsufficientBuffer = 122;
        var size = 0;
        var result = GetExtendedTcpTable(IntPtr.Zero, ref size, true, afInet, tcpTableOwnerPidListener, 0);
        if (result != errorInsufficientBuffer || size <= 0)
        {
            yield break;
        }

        var buffer = Marshal.AllocHGlobal(size);
        try
        {
            result = GetExtendedTcpTable(buffer, ref size, true, afInet, tcpTableOwnerPidListener, 0);
            if (result != 0)
            {
                yield break;
            }

            var count = Marshal.ReadInt32(buffer);
            var rowSize = Marshal.SizeOf<MibTcpRowOwnerPid>();
            var loopback = IPAddress.Loopback.GetAddressBytes();
            for (var index = 0; index < count; index++)
            {
                var row = Marshal.PtrToStructure<MibTcpRowOwnerPid>(buffer + sizeof(int) + (index * rowSize));
                var localAddress = BitConverter.GetBytes(row.LocalAddress);
                var port = (ushort)IPAddress.NetworkToHostOrder((short)(row.LocalPort & 0xffff));
                if (row.State == 2 && port == 8000 && localAddress.SequenceEqual(loopback))
                {
                    yield return unchecked((int)row.OwningPid);
                }
            }
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }

    private static Dictionary<int, int> ReadProcessParents()
    {
        const uint snapshotFlags = 0x00000002 | 0x00000004;
        var parents = new Dictionary<int, int>();
        var snapshot = CreateToolhelp32Snapshot(snapshotFlags, 0);
        if (snapshot == IntPtr.Zero || snapshot == new IntPtr(-1))
        {
            return parents;
        }

        try
        {
            var entry = new ProcessEntry32 { Size = (uint)Marshal.SizeOf<ProcessEntry32>() };
            if (!Process32First(snapshot, ref entry))
            {
                return parents;
            }
            do
            {
                parents[unchecked((int)entry.ProcessId)] = unchecked((int)entry.ParentProcessId);
            }
            while (Process32Next(snapshot, ref entry));
        }
        finally
        {
            CloseHandle(snapshot);
        }
        return parents;
    }

    [DllImport("iphlpapi.dll", SetLastError = true)]
    private static extern uint GetExtendedTcpTable(
        IntPtr tcpTable,
        ref int size,
        bool sort,
        int ipVersion,
        int tableClass,
        uint reserved);

    [StructLayout(LayoutKind.Sequential)]
    private struct MibTcpRowOwnerPid
    {
        public uint State;
        public uint LocalAddress;
        public uint LocalPort;
        public uint RemoteAddress;
        public uint RemotePort;
        public uint OwningPid;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint processId);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool Process32First(IntPtr snapshot, ref ProcessEntry32 entry);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool Process32Next(IntPtr snapshot, ref ProcessEntry32 entry);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct ProcessEntry32
    {
        public uint Size;
        public uint Usage;
        public uint ProcessId;
        public IntPtr DefaultHeapId;
        public uint ModuleId;
        public uint Threads;
        public uint ParentProcessId;
        public int BasePriority;
        public uint Flags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
        public string ExeFile;
    }
}
