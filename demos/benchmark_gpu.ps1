# Optional Windows GPU sampler. The Python coordinator supplies its output folder.
$ErrorActionPreference = 'Stop'
$statePath = Join-Path $env:TINYTOUCH_BENCH_DIR 'current-job.json'
try {
    while ($true) {
        $summaryPath = Join-Path $env:TINYTOUCH_BENCH_DIR 'summary.json'
        if (Test-Path -LiteralPath $summaryPath) {
            $summaryState = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
            if ($summaryState.campaign_complete) { break }
        }
        # Recreate the wildcard query so GPU instances of new worker processes
        # are included; a single continuous query misses later-created PIDs.
        Get-Counter '\GPU Engine(*)\Utilization Percentage' -MaxSamples 2 -SampleInterval 1 -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            $jobState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            $prefix = 'pid_' + $jobState.pid + '_'
            $engines = @($_.CounterSamples | Where-Object { $_.Status -eq 0 -and $_.InstanceName.StartsWith($prefix) } | ForEach-Object {
                @{ name = $_.InstanceName; percent = $_.CookedValue }
            })
            @{ pid = $jobState.pid; phase = $jobState.phase; engines = $engines; utc = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json -Compress -Depth 5
        } catch {
            # The coordinator atomically replaces the state between jobs.
            Write-Warning $_.Exception.Message
        }
        }
    }
} catch {
    Write-Error $_
    exit 1
}
