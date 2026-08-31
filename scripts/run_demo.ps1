param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [switch]$IncludeBenchmark
)

$ErrorActionPreference = "Stop"

$health = Invoke-RestMethod -Method Get "$BaseUrl/health"
if ($health.status -ne "ok") {
    throw "IntentPay API health check failed."
}

$scenarioIds = @(
    "normal-purchase",
    "meaningful-tradeoff",
    "budget-stretch",
    "unauthorized-subscription",
    "timeout-and-duplicate"
)

foreach ($scenarioId in $scenarioIds) {
    Write-Host "Running demo scenario: $scenarioId"
    $result = Invoke-RestMethod `
        -Method Post `
        "$BaseUrl/demo/scenarios/$scenarioId/run"
    $result | ConvertTo-Json -Depth 12

    if (-not $result.passed) {
        throw "Demo scenario '$scenarioId' did not match its expected outcome."
    }
}

if ($IncludeBenchmark) {
    Write-Host "Running the 500-case synthetic benchmark"
    $report = Invoke-RestMethod `
        -Method Post `
        "$BaseUrl/evaluations/run"
    $report | ConvertTo-Json -Depth 8
}

