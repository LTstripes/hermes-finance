Set-StrictMode -Version 2.0

function Test-HermesProcessTreeContains {
    param(
        [Parameter(Mandatory = $true)]
        [int]$RootProcessId,
        [Parameter(Mandatory = $true)]
        [int]$CandidateProcessId,
        [Parameter(Mandatory = $true)]
        [object[]]$ProcessRows
    )

    $parents = @{}
    foreach ($row in $ProcessRows) {
        $parents[[int]$row.ProcessId] = [int]$row.ParentProcessId
    }
    $visited = @{}
    $current = $CandidateProcessId
    while ($current -gt 0 -and -not $visited.ContainsKey($current)) {
        if ($current -eq $RootProcessId) {
            return $true
        }
        $visited[$current] = $true
        if (-not $parents.ContainsKey($current)) {
            break
        }
        $current = [int]$parents[$current]
    }
    return $false
}

function Test-HermesLoopbackListenerOwnership {
    param(
        [Parameter(Mandatory = $true)]
        [int]$RootProcessId,
        [Parameter(Mandatory = $true)]
        [object[]]$Listeners,
        [Parameter(Mandatory = $true)]
        [object[]]$ProcessRows
    )

    $loopbackListeners = @(
        $Listeners | Where-Object {
            $_.State -eq "Listen" -and
            [int]$_.LocalPort -eq 8000 -and
            $_.LocalAddress -eq "127.0.0.1"
        }
    )
    if ($loopbackListeners.Count -ne 1) {
        return $false
    }
    return Test-HermesProcessTreeContains `
        -RootProcessId $RootProcessId `
        -CandidateProcessId ([int]$loopbackListeners[0].OwningProcess) `
        -ProcessRows $ProcessRows
}

function Test-HermesRecoveryHeaders {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Response,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedToken,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedDatabaseIdentity,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedCheckoutSha
    )

    return (
        [string]::Equals(
            [string]$Response.Headers["X-Hermes-Recovery-Token"],
            $ExpectedToken,
            [StringComparison]::Ordinal
        ) -and
        [string]::Equals(
            [string]$Response.Headers["X-Hermes-Recovery-Database-Identity"],
            $ExpectedDatabaseIdentity,
            [StringComparison]::Ordinal
        ) -and
        [string]::Equals(
            [string]$Response.Headers["X-Hermes-Recovery-Checkout-SHA"],
            $ExpectedCheckoutSha,
            [StringComparison]::Ordinal
        )
    )
}
