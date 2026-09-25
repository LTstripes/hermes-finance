Set-StrictMode -Version 2.0

function Throw-HermesRecoveryReadinessFailure {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet(
            "port_conflict",
            "backend_exit",
            "readiness_probe_defect",
            "months_response_invalid",
            "dashboard_http_status",
            "listener_not_owned",
            "recovery_identity_mismatch",
            "api_http_status",
            "startup_http_unavailable",
            "readiness_timeout"
        )]
        [string]$Classification
    )

    $exception = New-Object System.InvalidOperationException("Recovery readiness failed.")
    $exception.Data["HermesRecoveryReadinessClassification"] = $Classification
    throw $exception
}

function Get-HermesRecoveryReadinessClassification {
    param(
        [Parameter(Mandatory = $true)]
        [System.Management.Automation.ErrorRecord]$ErrorRecord
    )

    $exception = $ErrorRecord.Exception
    while ($null -ne $exception) {
        $classification = $exception.Data["HermesRecoveryReadinessClassification"]
        if (
            $null -ne $classification -and
            @(
                "port_conflict",
                "backend_exit",
                "readiness_probe_defect",
                "months_response_invalid",
                "dashboard_http_status",
                "listener_not_owned",
                "recovery_identity_mismatch",
                "api_http_status",
                "startup_http_unavailable",
                "readiness_timeout"
            ) -contains [string]$classification
        ) {
            return [string]$classification
        }

        $innerExceptionProperty = $exception.PSObject.Properties["InnerException"]
        if ($null -eq $innerExceptionProperty) {
            break
        }
        $exception = $innerExceptionProperty.Value
    }

    return $null
}

function Get-HermesRecoveryHttpStatusCode {
    param(
        [Parameter(Mandatory = $true)]
        [System.Exception]$Exception
    )

    $current = $Exception
    while ($null -ne $current) {
        $responseProperty = $current.PSObject.Properties["Response"]
        if ($null -ne $responseProperty -and $null -ne $responseProperty.Value) {
            $statusProperty = $responseProperty.Value.PSObject.Properties["StatusCode"]
            if ($null -ne $statusProperty -and $null -ne $statusProperty.Value) {
                try {
                    return [int]$statusProperty.Value
                }
                catch {
                    return $null
                }
            }
        }

        $innerExceptionProperty = $current.PSObject.Properties["InnerException"]
        if ($null -eq $innerExceptionProperty) {
            break
        }
        $current = $innerExceptionProperty.Value
    }

    return $null
}

function Test-HermesRecoveryTransientRequestFailure {
    param(
        [Parameter(Mandatory = $true)]
        [System.Exception]$Exception
    )

    $current = $Exception
    while ($null -ne $current) {
        if ($current -is [System.Net.WebException]) {
            if (
                @(
                    "ConnectFailure",
                    "NameResolutionFailure",
                    "ProxyNameResolutionFailure",
                    "Timeout",
                    "ReceiveFailure",
                    "SendFailure",
                    "ConnectionClosed",
                    "KeepAliveFailure"
                ) -contains [string]$current.Status
            ) {
                return $true
            }
        }

        $innerExceptionProperty = $current.PSObject.Properties["InnerException"]
        if ($null -eq $innerExceptionProperty) {
            break
        }
        $current = $innerExceptionProperty.Value
    }

    return $false
}

function Test-RecoveryListenerOwned {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Backend
    )

    try {
        $listeners = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction Stop)
    }
    catch {
        if ($_.FullyQualifiedErrorId -like "CmdletizationQuery_NotFound,*") {
            return $false
        }
        throw
    }
    $processRows = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    return Test-HermesLoopbackListenerOwnership -RootProcessId $Backend.Id -Listeners $listeners -ProcessRows $processRows
}

function Get-HermesRecoveryResponseFailureClassification {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Backend,
        [Parameter(Mandatory = $true)]
        [object]$Response,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedRecoveryToken,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedDatabaseIdentity,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedCheckoutSha
    )

    if (-not (Test-RecoveryListenerOwned -Backend $Backend)) {
        return "listener_not_owned"
    }
    if (
        -not (Test-HermesRecoveryHeaders -Response $Response -ExpectedToken $ExpectedRecoveryToken -ExpectedDatabaseIdentity $ExpectedDatabaseIdentity -ExpectedCheckoutSha $ExpectedCheckoutSha)
    ) {
        return "recovery_identity_mismatch"
    }
    return $null
}

function Get-HermesRecoveryMonthIds {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Json
    )

    try {
        $months = ConvertFrom-Json -InputObject $Json -ErrorAction Stop
    }
    catch {
        Throw-HermesRecoveryReadinessFailure -Classification "months_response_invalid"
    }
    if ($months -isnot [Array]) {
        Throw-HermesRecoveryReadinessFailure -Classification "months_response_invalid"
    }

    $monthIds = New-Object "System.Collections.Generic.List[long]"
    $integerTypeNames = @(
        "System.Byte",
        "System.SByte",
        "System.Int16",
        "System.UInt16",
        "System.Int32",
        "System.UInt32",
        "System.Int64",
        "System.UInt64"
    )
    foreach ($month in $months) {
        if ($null -eq $month -or $month -is [Array]) {
            Throw-HermesRecoveryReadinessFailure -Classification "months_response_invalid"
        }
        $idProperty = $month.PSObject.Properties["id"]
        if ($null -eq $idProperty -or $null -eq $idProperty.Value) {
            Throw-HermesRecoveryReadinessFailure -Classification "months_response_invalid"
        }
        if ($integerTypeNames -notcontains $idProperty.Value.GetType().FullName) {
            Throw-HermesRecoveryReadinessFailure -Classification "months_response_invalid"
        }

        try {
            $monthId = [Convert]::ToInt64($idProperty.Value, [Globalization.CultureInfo]::InvariantCulture)
        }
        catch {
            Throw-HermesRecoveryReadinessFailure -Classification "months_response_invalid"
        }
        if ($monthId -le 0) {
            Throw-HermesRecoveryReadinessFailure -Classification "months_response_invalid"
        }
        $monthIds.Add($monthId)
    }

    return [pscustomobject]@{
        MonthIds = [long[]]$monthIds.ToArray()
        Count = $monthIds.Count
    }
}

function Invoke-HermesRecoveryDashboardProbe {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$MonthsJson,
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Backend,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedRecoveryToken,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedDatabaseIdentity,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedCheckoutSha
    )

    $parsedMonths = Get-HermesRecoveryMonthIds -Json $MonthsJson
    if ($parsedMonths.Count -eq 0) {
        return [pscustomobject]@{
            Status = "skipped"
            MonthCount = 0
        }
    }

    $monthId = $parsedMonths.MonthIds[0]
    try {
        $dashboard = Invoke-WebRequest -Uri ("http://127.0.0.1:8000/api/months/{0}/dashboard" -f $monthId) -UseBasicParsing -TimeoutSec 2
    }
    catch {
        if ($null -ne (Get-HermesRecoveryHttpStatusCode -Exception $_.Exception)) {
            Throw-HermesRecoveryReadinessFailure -Classification "dashboard_http_status"
        }
        throw
    }
    if ($dashboard.StatusCode -ne 200) {
        Throw-HermesRecoveryReadinessFailure -Classification "dashboard_http_status"
    }

    $ownershipFailure = Get-HermesRecoveryResponseFailureClassification -Backend $Backend -Response $dashboard -ExpectedRecoveryToken $ExpectedRecoveryToken -ExpectedDatabaseIdentity $ExpectedDatabaseIdentity -ExpectedCheckoutSha $ExpectedCheckoutSha
    if ($null -ne $ownershipFailure) {
        Throw-HermesRecoveryReadinessFailure -Classification $ownershipFailure
    }

    return [pscustomobject]@{
        Status = "verified"
        MonthCount = $parsedMonths.Count
    }
}
