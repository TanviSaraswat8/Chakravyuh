# Chakravyuh: full local Docker validation (Windows PowerShell 5.1+ or PowerShell 7).
#
#   powershell -ExecutionPolicy Bypass -File scripts\validate_docker.ps1
#
# Runs from the repo root. Needs only Docker Desktop and Git: every Python check runs inside the
# API container, so no Python is needed on Windows. Builds the real images, starts the real stack
# (PostgreSQL + API + nginx web), and checks it end to end. Writes validation-report.txt.
# Exit code 0 = everything passed.

$ErrorActionPreference = "Continue"   # docker writes progress to stderr; we check exit codes instead
Set-Location (Split-Path -Parent $PSScriptRoot)
$Report = Join-Path (Get-Location) "validation-report.txt"
$Log = Join-Path (Get-Location) "validation-build.log"
$results = New-Object System.Collections.ArrayList
"" | Set-Content $Log

function Section($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }
function Record($name, $ok, $detail) {
    [void]$results.Add([pscustomobject]@{ Check = $name; Result = $(if ($ok) { "PASS" } else { "FAIL" }); Detail = $detail })
    $color = if ($ok) { "Green" } else { "Red" }
    Write-Host ("  {0} {1}  {2}" -f $(if ($ok) { "PASS" } else { "FAIL" }), $name, $detail) -ForegroundColor $color
}
# Run a native command through cmd so stderr progress is captured in the log, not raised as errors.
function Run($cmdline) {
    Add-Content $Log "`n>>> $cmdline"
    cmd /c "$cmdline 2>&1" | Tee-Object -FilePath $Log -Append | Out-Host
    return $LASTEXITCODE
}
function Wait-Http($url, $seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 $url; if ($r.StatusCode -eq 200) { return $true } } catch { }
        Start-Sleep -Seconds 3
    }
    return $false
}
function Finish {
    Section "Report"
    $sha = (git rev-parse HEAD 2>$null)
    $failed = @($results | Where-Object { $_.Result -eq "FAIL" }).Count
    $lines = @(
        "Chakravyuh local Docker validation",
        "Date:    $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')",
        "Machine: $env:COMPUTERNAME",
        "Commit:  $sha",
        "Result:  $(if ($failed -eq 0) { 'ALL PASSED' } else { "$failed FAILED" })",
        ""
    ) + ($results | Format-Table -AutoSize -Wrap | Out-String -Width 220).TrimEnd() + @(
        "",
        "Images:",
        (docker images --format "  {{.Repository}}:{{.Tag}}  {{.ID}}  {{.Size}}" 2>$null | Select-String "chakravyuh|postgres" | Out-String).TrimEnd(),
        "",
        "Containers:",
        (docker compose ps --format "  {{.Name}}  {{.Image}}  {{.Status}}" 2>$null | Out-String).TrimEnd(),
        "",
        "Full build and command log: validation-build.log"
    )
    $lines | Set-Content $Report -Encoding UTF8
    Get-Content $Report | Out-Host
    Write-Host "`nReport written to $Report"
    Write-Host "Stack left running: web http://localhost:8080  API docs http://localhost:8000/docs  (stop: docker compose down)"
    exit $(if ($failed -eq 0) { 0 } else { 1 })
}

# 1. Docker access ---------------------------------------------------------------------------------
Section "1. Docker access"
$code = Run "docker version"
Record "docker version (client + engine)" ($code -eq 0) "exit $code"
$code = Run "docker compose version"
Record "docker compose available" ($code -eq 0) "exit $code"
$code = Run "docker info --format ""{{.ServerVersion}} {{.OperatingSystem}} cpus={{.NCPU}} mem={{.MemTotal}}"""
Record "docker engine reachable" ($code -eq 0) "exit $code"
if ($code -ne 0) { Write-Host "Docker Engine is not reachable. Start Docker Desktop and run again." -ForegroundColor Red; Finish }

# 2-3. Repository state ----------------------------------------------------------------------------
Section "2-3. Repository"
$branch = (git rev-parse --abbrev-ref HEAD 2>$null)
$dirty = (git status --porcelain 2>$null | Measure-Object).Count
Record "on a git branch" ([bool]$branch) "branch '$branch', $dirty uncommitted file(s)"
$code = Run "git pull --ff-only"
Record "pulled latest from GitHub" ($code -eq 0) "exit $code (fast-forward only; local changes are never overwritten)"

# 4. Configuration ---------------------------------------------------------------------------------
Section "4. Compose configuration"
$code = Run "docker compose config -q"
Record "docker-compose.yml valid" ($code -eq 0) "exit $code"
foreach ($p in @(5432, 8000, 8080)) {
    $busy = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    $ours = (docker compose ps -q 2>$null | Measure-Object).Count -gt 0
    if ($busy -and -not $ours) {
        Record "port $p free" $false "in use by another program. Set DB_HOST_PORT / API_HOST_PORT / WEB_HOST_PORT and rerun"
    }
}

# 5. Build -----------------------------------------------------------------------------------------
Section "5. Build images (first build downloads ~1 GB, allow 5-15 minutes)"
$t = Get-Date
$code = Run "docker compose build --progress plain"
Record "images built" ($code -eq 0) ("exit $code in {0:N0}s" -f ((Get-Date) - $t).TotalSeconds)
if ($code -ne 0) { Write-Host "Build failed; see validation-build.log" -ForegroundColor Red; Finish }

# 6-7. Start the stack and wait for health ---------------------------------------------------------
Section "6-7. Start stack"
$code = Run "docker compose up -d --wait --wait-timeout 300"
Record "stack started and healthy (db, api, web)" ($code -eq 0) "exit $code"
Run "docker compose ps" | Out-Null
foreach ($svc in @("db", "api", "web")) {
    $state = (docker compose ps $svc --format "{{.State}} {{.Health}}" 2>$null)
    Record "container '$svc'" ($state -match "running healthy") "$state"
}
Record "API health on :8000" (Wait-Http "http://localhost:8000/health" 60) "http://localhost:8000/health"
Record "web app on :8080" (Wait-Http "http://localhost:8080/" 60) "http://localhost:8080/"
Record "web -> API proxy (nginx)" (Wait-Http "http://localhost:8080/health" 60) "http://localhost:8080/health"
$h = try { Invoke-RestMethod http://localhost:8000/health } catch { $null }
Record "models loaded in container" ($h -and $h.model.loaded) "mode=$($h.model.mode) trained_at=$($h.model.trained_at)"
$dbv = (docker compose exec -T db psql -U chakravyuh -tAc "select version()" 2>$null)
Record "PostgreSQL reachable" ([bool]$dbv) "$dbv"

# 8. Smoke test, through nginx (exercises the web container's proxy too) -----------------------------
Section "8. Smoke test"
docker compose cp scripts/smoke_test.py api:/tmp/smoke_test.py | Out-Null
docker compose cp scripts/e2e_checks.py api:/tmp/e2e_checks.py | Out-Null
$code = Run "docker compose exec -T api python /tmp/smoke_test.py http://web"
Record "smoke test (14 checks, via nginx)" ($code -eq 0) "exit $code"

# 9-10. End to end: regression checks, evolution, persistence ------------------------------------
Section "9-10. End to end"
$code = Run "docker compose exec -T api python /tmp/e2e_checks.py http://web"
Record "Customs hold + flat-deposit checks" ($code -eq 0) "exit $code"

try {
    $arena = Invoke-RestMethod -Method Post -Uri http://localhost:8000/v1/demo/arena -ContentType "application/json" `
        -Body '{"generations":4,"population":24,"per_genome":2,"fresh":true}' -TimeoutSec 600
    $rates = ($arena.history | ForEach-Object { "{0:P0}" -f $_.detection_rate }) -join " -> "
    Record "attacker evolution (arena)" ($arena.history.Count -eq 4) "detection by generation: $rates"
    $d = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/v1/demo/arena/adapt" -TimeoutSec 900
    Record "defender adapts" ($null -ne $d.detection_after) ("caught {0:P0} -> {1:P0}, false alarms {2:P1}, shipped={3}" -f `
        $d.detection_before, $d.detection_after, $d.legit_false_alarm_after, $d.accepted)
} catch { Record "attacker/defender evolution" $false "$($_.Exception.Message)" }

try {
    $c = Invoke-RestMethod -Method Post -Uri http://localhost:8000/v1/campaigns/refresh -TimeoutSec 300
    Record "emerging-campaign detection" ($c.created -ge 1) "$($c.created) campaign(s) from $($c.unknown_sessions) unexplained sessions"
} catch { Record "emerging-campaign detection" $false "$($_.Exception.Message)" }

$before = (docker compose exec -T db psql -U chakravyuh -tAc "select count(*) from sessions" 2>$null).Trim()
Run "docker compose restart api" | Out-Null
Wait-Http "http://localhost:8000/health" 120 | Out-Null
$after = (docker compose exec -T db psql -U chakravyuh -tAc "select count(*) from sessions" 2>$null).Trim()
$viaApi = try { (Invoke-RestMethod http://localhost:8000/v1/metrics).sessions } catch { -1 }
Record "data persists across API restart" (([int]$before -gt 0) -and ($before -eq $after) -and ([int]$viaApi -eq [int]$after)) `
    "sessions in db before=$before after=$after, via API=$viaApi"

# Privacy mode: restart the API with STORE_MESSAGE_TEXT=false and check the database itself.
$env:STORE_MESSAGE_TEXT = "false"
$code = Run "docker compose up -d --wait api"
$since = (docker compose exec -T db psql -U chakravyuh -tAc "select now()" 2>$null).Trim()
docker compose cp scripts/e2e_checks.py api:/tmp/e2e_checks.py | Out-Null
$code = Run "docker compose exec -T api python /tmp/e2e_checks.py http://localhost:8000 --privacy"
Record "privacy mode checks (API)" ($code -eq 0) "exit $code"
$leaked = (docker compose exec -T db psql -U chakravyuh -tAc "select count(*) from events where created_at >= '$since' and type = 'MSG_RECV' and text is not null" 2>$null).Trim()
$kept = (docker compose exec -T db psql -U chakravyuh -tAc "select count(*) from events where created_at >= '$since' and (attrs::jsonb) ? '_client_tags'" 2>$null).Trim()
Record "privacy mode in PostgreSQL" (($leaked -eq "0") -and ([int]$kept -gt 0)) "message texts stored=$leaked, derived tag rows kept=$kept"
Remove-Item Env:\STORE_MESSAGE_TEXT
Run "docker compose up -d --wait api" | Out-Null

# 11. Full test suite inside the API image, against the PostgreSQL container ---------------------
Section "11. Test suite (in the API image, against PostgreSQL)"
docker compose exec -T db psql -U chakravyuh -c "CREATE DATABASE chakravyuh_test" 2>$null | Out-Null
$code = Run "docker compose exec -T -e TEST_DATABASE_URL=postgresql+psycopg://chakravyuh:chakravyuh@db:5432/chakravyuh_test api python -m pytest -q"
Record "pytest (all suites, PostgreSQL)" ($code -eq 0) "exit $code"

Finish
