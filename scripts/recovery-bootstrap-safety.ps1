Set-StrictMode -Version 2.0

if ($null -eq ("HermesRecoveryBootstrapNative" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public sealed class HermesRecoveryBootstrapNative : IDisposable
{
    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public UInt64 ReadOperationCount;
        public UInt64 WriteOperationCount;
        public UInt64 OtherOperationCount;
        public UInt64 ReadTransferCount;
        public UInt64 WriteTransferCount;
        public UInt64 OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public Int64 PerProcessUserTimeLimit;
        public Int64 PerJobUserTimeLimit;
        public UInt32 LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public UInt32 ActiveProcessLimit;
        public UIntPtr Affinity;
        public UInt32 PriorityClass;
        public UInt32 SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_ACCOUNTING_INFORMATION
    {
        public Int64 TotalUserTime;
        public Int64 TotalKernelTime;
        public Int64 ThisPeriodTotalUserTime;
        public Int64 ThisPeriodTotalKernelTime;
        public UInt32 TotalPageFaultCount;
        public UInt32 TotalProcesses;
        public UInt32 ActiveProcesses;
        public UInt32 TotalTerminatedProcesses;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FILETIME
    {
        public UInt32 LowDateTime;
        public UInt32 HighDateTime;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct BY_HANDLE_FILE_INFORMATION
    {
        public UInt32 FileAttributes;
        public FILETIME CreationTime;
        public FILETIME LastAccessTime;
        public FILETIME LastWriteTime;
        public UInt32 VolumeSerialNumber;
        public UInt32 FileSizeHigh;
        public UInt32 FileSizeLow;
        public UInt32 NumberOfLinks;
        public UInt32 FileIndexHigh;
        public UInt32 FileIndexLow;
    }

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateJobObject(IntPtr attributes, string name);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern IntPtr OpenJobObject(UInt32 desiredAccess, bool inherit, string name);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool IsProcessInJob(IntPtr process, IntPtr job, out bool result);

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetCurrentProcess();

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(
        IntPtr job,
        int informationClass,
        IntPtr information,
        UInt32 informationLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool TerminateJobObject(IntPtr job, UInt32 exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool QueryInformationJobObject(
        IntPtr job,
        int informationClass,
        IntPtr information,
        UInt32 informationLength,
        IntPtr returnLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateFile(
        string fileName,
        UInt32 desiredAccess,
        UInt32 shareMode,
        IntPtr securityAttributes,
        UInt32 creationDisposition,
        UInt32 flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool DeleteFile(string fileName);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(
        IntPtr file,
        out BY_HANDLE_FILE_INFORMATION information);

    private const UInt32 JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
    private const UInt32 JOB_OBJECT_QUERY = 0x0004;
    private const UInt32 FILE_READ_ATTRIBUTES = 0x00000080;
    private const UInt32 FILE_SHARE_READ = 0x00000001;
    private const UInt32 FILE_SHARE_WRITE = 0x00000002;
    private const UInt32 FILE_SHARE_DELETE = 0x00000004;
    private const UInt32 OPEN_EXISTING = 3;
    private const UInt32 FILE_FLAG_BACKUP_SEMANTICS = 0x02000000;
    private const UInt32 FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000;
    private const UInt32 FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400;
    private static readonly IntPtr INVALID_HANDLE_VALUE = new IntPtr(-1);

    private IntPtr jobHandle;
    private IntPtr directoryHandle;
    private IntPtr containmentHandle;
    private UInt32 volumeSerial;
    private UInt64 fileIndex;
    private string directoryPath;
    private string containmentPath;

    public string Path { get { return directoryPath; } }

    private HermesRecoveryBootstrapNative() {}

    private static string GetJobName(string ownershipToken)
    {
        if (ownershipToken == null || ownershipToken.Length != 64)
            throw new InvalidOperationException("invalid ownership token");
        for (int index = 0; index < ownershipToken.Length; index++)
        {
            char value = ownershipToken[index];
            if (!((value >= '0' && value <= '9') || (value >= 'a' && value <= 'f')))
                throw new InvalidOperationException("invalid ownership token");
        }
        return "Local\\HermesRecoveryBootstrap-" + ownershipToken;
    }

    public static HermesRecoveryBootstrapNative CreateJob(string ownershipToken)
    {
        HermesRecoveryBootstrapNative owner = new HermesRecoveryBootstrapNative();
        owner.jobHandle = CreateJobObject(IntPtr.Zero, GetJobName(ownershipToken));
        if (owner.jobHandle == IntPtr.Zero)
            throw new Win32Exception(Marshal.GetLastWin32Error());
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION information =
            new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        information.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        IntPtr pointer = Marshal.AllocHGlobal(Marshal.SizeOf(information));
        try
        {
            Marshal.StructureToPtr(information, pointer, false);
            if (!SetInformationJobObject(
                owner.jobHandle, 9, pointer, (UInt32)Marshal.SizeOf(information)))
                throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        catch
        {
            owner.Dispose();
            throw;
        }
        finally
        {
            Marshal.FreeHGlobal(pointer);
        }
        return owner;
    }

    public static bool IsCurrentProcessOwned(string ownershipToken)
    {
        string jobName;
        try
        {
            jobName = GetJobName(ownershipToken);
        }
        catch
        {
            return false;
        }
        IntPtr job = OpenJobObject(JOB_OBJECT_QUERY, false, jobName);
        if (job == IntPtr.Zero)
            return false;
        try
        {
            bool assigned;
            if (!IsProcessInJob(GetCurrentProcess(), job, out assigned) || !assigned)
                return false;
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION information =
                new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            IntPtr pointer = Marshal.AllocHGlobal(Marshal.SizeOf(information));
            try
            {
                if (!QueryInformationJobObject(
                    job, 9, pointer, (UInt32)Marshal.SizeOf(information), IntPtr.Zero))
                    return false;
                information = (JOBOBJECT_EXTENDED_LIMIT_INFORMATION)
                    Marshal.PtrToStructure(
                        pointer, typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
                return (
                    information.BasicLimitInformation.LimitFlags &
                    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE) != 0;
            }
            finally
            {
                Marshal.FreeHGlobal(pointer);
            }
        }
        finally
        {
            CloseHandle(job);
        }
    }

    public static HermesRecoveryBootstrapNative OpenDirectory(string path)
    {
        HermesRecoveryBootstrapNative guard = new HermesRecoveryBootstrapNative();
        guard.directoryHandle = CreateFile(
            path,
            FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            IntPtr.Zero,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
            IntPtr.Zero);
        if (guard.directoryHandle == INVALID_HANDLE_VALUE)
        {
            guard.directoryHandle = IntPtr.Zero;
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        try
        {
            BY_HANDLE_FILE_INFORMATION information = guard.ReadInformation(guard.directoryHandle);
            if ((information.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
                throw new InvalidOperationException("directory is a reparse point");
            guard.volumeSerial = information.VolumeSerialNumber;
            guard.fileIndex = ((UInt64)information.FileIndexHigh << 32) | information.FileIndexLow;
            guard.directoryPath = path;
            guard.containmentPath =
                path + ":hermes-recovery-containment-" + Guid.NewGuid().ToString("N");
            guard.containmentHandle = CreateFile(
                guard.containmentPath,
                0x80000000 | 0x40000000,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                IntPtr.Zero,
                4,
                0,
                IntPtr.Zero);
            if (guard.containmentHandle == INVALID_HANDLE_VALUE)
            {
                guard.containmentHandle = IntPtr.Zero;
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            return guard;
        }
        catch
        {
            guard.Dispose();
            throw;
        }
    }

    public static UInt32 GetLinkCount(string path)
    {
        IntPtr handle = CreateFile(
            path,
            FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            IntPtr.Zero,
            OPEN_EXISTING,
            FILE_FLAG_OPEN_REPARSE_POINT,
            IntPtr.Zero);
        if (handle == INVALID_HANDLE_VALUE)
            throw new Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            BY_HANDLE_FILE_INFORMATION information = ReadStaticInformation(handle);
            if ((information.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
                throw new InvalidOperationException("file is a reparse point");
            return information.NumberOfLinks;
        }
        finally
        {
            CloseHandle(handle);
        }
    }

    public void Assign(IntPtr processHandle)
    {
        if (jobHandle == IntPtr.Zero || !AssignProcessToJobObject(jobHandle, processHandle))
            throw new Win32Exception(Marshal.GetLastWin32Error());
    }

    public void AssertDirectoryIdentity(string path)
    {
        if (directoryHandle == IntPtr.Zero)
            throw new InvalidOperationException("directory guard is closed");
        BY_HANDLE_FILE_INFORMATION held = ReadInformation(directoryHandle);
        UInt64 heldIndex = ((UInt64)held.FileIndexHigh << 32) | held.FileIndexLow;
        if ((held.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0 ||
            held.VolumeSerialNumber != volumeSerial || heldIndex != fileIndex)
            throw new InvalidOperationException("directory identity changed");
        IntPtr inspected = CreateFile(
            path,
            FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            IntPtr.Zero,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
            IntPtr.Zero);
        if (inspected == INVALID_HANDLE_VALUE)
            throw new Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            BY_HANDLE_FILE_INFORMATION current = ReadInformation(inspected);
            UInt64 currentIndex = ((UInt64)current.FileIndexHigh << 32) | current.FileIndexLow;
            if ((current.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0 ||
                current.VolumeSerialNumber != volumeSerial || currentIndex != fileIndex)
                throw new InvalidOperationException("directory identity changed");
        }
        finally
        {
            CloseHandle(inspected);
        }
    }

    public UInt32 ActiveProcesses()
    {
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION information =
            new JOBOBJECT_BASIC_ACCOUNTING_INFORMATION();
        IntPtr pointer = Marshal.AllocHGlobal(Marshal.SizeOf(information));
        try
        {
            if (!QueryInformationJobObject(
                jobHandle, 1, pointer, (UInt32)Marshal.SizeOf(information), IntPtr.Zero))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            information = (JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)
                Marshal.PtrToStructure(pointer, typeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION));
            return information.ActiveProcesses;
        }
        finally
        {
            Marshal.FreeHGlobal(pointer);
        }
    }

    public void Terminate()
    {
        if (jobHandle == IntPtr.Zero || !TerminateJobObject(jobHandle, 1))
            throw new Win32Exception(Marshal.GetLastWin32Error());
    }

    private BY_HANDLE_FILE_INFORMATION ReadInformation(IntPtr handle)
    {
        return ReadStaticInformation(handle);
    }

    private static BY_HANDLE_FILE_INFORMATION ReadStaticInformation(IntPtr handle)
    {
        BY_HANDLE_FILE_INFORMATION information;
        if (!GetFileInformationByHandle(handle, out information))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        return information;
    }

    public void Dispose()
    {
        if (containmentHandle != IntPtr.Zero)
        {
            CloseHandle(containmentHandle);
            containmentHandle = IntPtr.Zero;
            if (containmentPath != null)
                DeleteFile(containmentPath);
        }
        if (directoryHandle != IntPtr.Zero)
        {
            CloseHandle(directoryHandle);
            directoryHandle = IntPtr.Zero;
        }
        if (jobHandle != IntPtr.Zero)
        {
            CloseHandle(jobHandle);
            jobHandle = IntPtr.Zero;
        }
    }
}
'@
}

function ConvertTo-HermesNativeArgument {
    param([Parameter(Mandatory = $true)][string]$Value)

    if ($Value -notmatch '[\s"]') {
        return $Value
    }
    $builder = New-Object Text.StringBuilder
    $null = $builder.Append('"')
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $slashes++
            continue
        }
        if ($character -eq '"') {
            $null = $builder.Append(('\' * (($slashes * 2) + 1)))
            $null = $builder.Append('"')
        }
        else {
            $null = $builder.Append(('\' * $slashes))
            $null = $builder.Append($character)
        }
        $slashes = 0
    }
    $null = $builder.Append(('\' * ($slashes * 2)))
    $null = $builder.Append('"')
    return $builder.ToString()
}

function Invoke-HermesOwnedRecoveryBootstrap {
    param(
        [Parameter(Mandatory = $true)][string]$BoundaryScript,
        [Parameter(Mandatory = $true)][string]$RecoveryScript,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [switch]$ForceCleanupFailure
    )

    $tokenBytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($tokenBytes)
    $token = ([BitConverter]::ToString($tokenBytes)).Replace('-', '').ToLowerInvariant()
    $argumentsJson = ConvertTo-Json -InputObject $Arguments -Compress
    $owner = $null
    $readyEvent = $null
    $process = $null
    $completed = $false
    $exitCode = 1
    $cleanupFailed = $false
    try {
        $owner = [HermesRecoveryBootstrapNative]::CreateJob($token)
        $readyEventName = "Local\HermesRecoveryBootstrapReady-$token"
        $createdNew = $false
        $readyEvent = [Threading.EventWaitHandle]::new(
            $false,
            [Threading.EventResetMode]::ManualReset,
            $readyEventName,
            [ref]$createdNew
        )
        if (-not $createdNew) {
            throw "bootstrap-ownership"
        }
        $powerShell = Join-Path $PSHOME "powershell.exe"
        $startInfo = New-Object Diagnostics.ProcessStartInfo
        $startInfo.FileName = $powerShell
        $startInfo.Arguments = @(
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-File',
            (ConvertTo-HermesNativeArgument -Value $BoundaryScript)
        ) -join ' '
        $startInfo.WorkingDirectory = [IO.Path]::GetDirectoryName($RecoveryScript)
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $startInfo.EnvironmentVariables['HERMES_RECOVERY_BOOTSTRAP_SCRIPT'] = $RecoveryScript
        $startInfo.EnvironmentVariables['HERMES_RECOVERY_BOOTSTRAP_ARGUMENTS_JSON'] = $argumentsJson
        $startInfo.EnvironmentVariables['HERMES_RECOVERY_BOOTSTRAP_OWNERSHIP_TOKEN'] = $token
        $process = New-Object Diagnostics.Process
        $process.StartInfo = $startInfo
        if (-not $process.Start()) {
            throw "bootstrap-launch"
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        try {
            $owner.Assign($process.Handle)
        }
        catch {
            try { $process.Kill() } catch {}
            throw "bootstrap-ownership"
        }
        if (-not $readyEvent.Set()) {
            throw "bootstrap-ownership"
        }
        $completed = $process.WaitForExit($TimeoutSeconds * 1000)
        if ($completed) {
            $exitCode = $process.ExitCode
        }
    }
    finally {
        if ($null -ne $owner) {
            try {
                $owner.Terminate()
                $deadline = [DateTime]::UtcNow.AddSeconds(5)
                while ($owner.ActiveProcesses() -ne 0 -and [DateTime]::UtcNow -lt $deadline) {
                    Start-Sleep -Milliseconds 50
                }
                if ($owner.ActiveProcesses() -ne 0) {
                    $cleanupFailed = $true
                }
            }
            catch {
                $cleanupFailed = $true
            }
        }
        if ($null -ne $process) {
            try { $process.WaitForExit(5000) | Out-Null } catch { $cleanupFailed = $true }
        }
        if ($null -ne $owner) {
            $owner.Dispose()
        }
        if ($null -ne $readyEvent) {
            $readyEvent.Dispose()
        }
    }
    if ($ForceCleanupFailure) {
        $cleanupFailed = $true
    }
    if ($cleanupFailed) {
        throw "bootstrap-cleanup"
    }
    if (-not $completed) {
        throw "bootstrap-timeout"
    }
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $null = $stderrTask.GetAwaiter().GetResult()
    return [pscustomobject]@{
        ExitCode = $exitCode
        StandardOutput = $stdout
    }
}

function Open-HermesRecoveryDirectoryGuard {
    param([Parameter(Mandatory = $true)][string]$Path)

    return [HermesRecoveryBootstrapNative]::OpenDirectory($Path)
}

function Get-HermesRecoveryLinkCount {
    param([Parameter(Mandatory = $true)][string]$Path)

    return [HermesRecoveryBootstrapNative]::GetLinkCount($Path)
}
