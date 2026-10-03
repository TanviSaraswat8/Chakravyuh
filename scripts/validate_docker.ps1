# Chakravyuh: full local Docker validation (Windows PowerShell 5.1+, or PowerShell 7 on any OS).
#
#   powershell -ExecutionPolicy Bypass -File scripts\validate_docker.ps1      (Windows)
#   pwsh scripts/validate_docker.ps1                                         (macOS / Linux / CI)
#
# Runs from the repo root. Needs only Docker Desktop and Git: every Python check runs inside the
# API container, so no Python is needed on Windows. Builds the real images, starts the real stack
# (PostgreSQL + API + nginx web) from a clean state, waits until every container is healthy, and
# only then runs the checks. If a container fails to start, the script stops, prints the
# container's real error (state, exit code, restarts, last log lines) and exits 1.
# Writes validation-report.txt (summary) and validation-build.log (every command and its output).
# Exit code 0 = every check passed.

param(
    [int]$StartTimeout = 300,   # seconds to wait for all containers to become healthy
    [switch]$SkipBuild,         # reuse images already built
    [switch]$NoPull             # test the checked-out commit as-is (CI); default pulls the latest first
)

$ErrorActionPreference = "Continue"   # docker writes progress to stderr; we check exit codes instead
# Windows PowerShell 5.1 has no $IsWindows; there it is always Windows.
$OnWindows = ($PSVersionTable.PSEdition -eq "Desktop") -or [bool]$IsWindows
Set-Location (Split-Path -Parent $PSScriptRoot)
$Report = Join-Path (Get-Location) "validation-report.txt"
$Log = Join-Path (Get-Location) "validation-build.log"
$results = New-Object System.Collections.ArrayList
$diagnosis = New-Object System.Collections.ArrayList
$Services = @("db", "api", "web")
Set-Content -Path $Log -Value "Chakravyuh validation log $(Get-Date -Format s)" -Encoding UTF8

# --- helpers ---------------------------------------------------------------------------------------
function Section($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan; Write-Log "`n=== $t ===" }
function Write-Log($text) { Add-Content -Path $Log -Value $text -Encoding UTF8 }
function Record($name, $status, $detail) {
    # status: $true / $false / "SKIP"
    $s = if ($status -is [string]) { $status } elseif ($status) { "PASS" } else { "FAIL" }
    [void]$results.Add([pscustomobject]@{ Check = $name; Result = $s; Detail = "$detail" })
    $color = @{ PASS = "Green"; FAIL = "Red"; SKIP = "Yellow" }[$s]
    Write-Host ("  {0} {1}  {2}" -f $s, $name, $detail) -ForegroundColor $color
    Write-Log ("RESULT {0} {1} :: {2}" -f $s, $name, $detail)
}
# Run a native command through cmd (stderr merged, never raised as a PowerShell error), stream it
# to the screen and the log, and return exit code + output. Never returns $null.
function Run($cmdline, [switch]$Quiet) {
    Write-Log "`n>>> $cmdline"
    $lines = New-Object System.Collections.ArrayList
    $shellCmd = if ($OnWindows) { { cmd /c "$cmdline 2>&1" } } else { { sh -c "$cmdline 2>&1" } }
    & $shellCmd | ForEach-Object {
        $l = "$_"; [void]$lines.Add($l); Write-Log $l
        if (-not $Quiet) { Write-Host $l }
    }
    $code = $LASTEXITCODE
    Write-Log "<<< exit $code"
    return [pscustomobject]@{ Code = $code; Out = (($lines -join "`n").Trim()) }
}
# Run a command and return its trimmed output ("" on any failure), retrying a few times.
function Out-Of($cmdline, [int]$Tries = 3) {
    for ($i = 1; $i -le $Tries; $i++) {
        $r = Run $cmdline -Quiet
        if ($r.Code -eq 0) { return $r.Out }
        Start-Sleep -Seconds 2
    }
    return ""
}
function Sql($query) { return Out-Of ("docker compose exec -T db psql -U chakravyuh -d chakravyuh -tAc ""{0}""" -f $query) }
function Is-Int($s) { return ("$s" -match '^\s*\d+\s*$') }
# The lines of a command's output that say what went wrong (Docker puts the reason there, not in exit codes).
function Err-Lines($out, [int]$Max = 6) {
    return @("$out" -split "`n" | Where-Object { $_ -match "error|failed|forbidden|denied|allocated|not found|no such|refused|unauthorized|timeout|unhealthy|exited" } |
             ForEach-Object { $_.Trim() } | Select-Object -Unique -Last $Max)
}
function Note-Errors($label, $out) {
    $lines = Err-Lines $out
    if ($lines.Count -gt 0) {
        [void]$diagnosis.Add("${label}:")
        foreach ($l in $lines) { [void]$diagnosis.Add("    $l"); Write-Host "    $l" -ForegroundColor Yellow }
    }
    return ($lines | Select-Object -Last 1)
}
function Wait-Http($url, $seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 $url; if ($r.StatusCode -eq 200) { return $true } } catch { }
        Start-Sleep -Seconds 2
    }
    return $false
}
function Container-Id($svc) { return (Out-Of "docker compose ps -a -q $svc" 1) }
function Container-State($svc) {
    $id = Container-Id $svc
    if (-not $id) { return [pscustomobject]@{ Id = ""; Status = "missing"; Health = ""; Exit = ""; Restarts = ""; Error = "" } }
    $f = Out-Of "docker inspect -f ""{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.RestartCount}}|{{.State.Error}}"" $id" 1
    $p = ("$f" + "||||").Split("|")
    return [pscustomobject]@{ Id = $id; Status = $p[0]; Health = $p[1]; Exit = $p[2]; Restarts = $p[3]; Error = $p[4] }
}
# Wait until every service is running+healthy. Fails fast if one exits. Returns $true/$false.
function Wait-Healthy($svcs, $seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        $ok = $true
        foreach ($s in $svcs) {
            $st = Container-State $s
            if ($st.Status -in @("exited", "dead", "missing")) { Write-Host "  '$s' is $($st.Status) (exit $($st.Exit))" -ForegroundColor Red; return $false }
            if (-not ($st.Status -eq "running" -and $st.Health -eq "healthy")) { $ok = $false }
        }
        if ($ok) { return $true }
        Start-Sleep -Seconds 3
    }
    return $false
}
# Print and record the real reason each container is not healthy.
function Diagnose($why) {
    Section "Diagnosis: $why"
    Run "docker compose ps -a" | Out-Null
    foreach ($s in $Services) {
        $st = Container-State $s
        $line = "${s}: status=$($st.Status) health=$($st.Health) exit=$($st.Exit) restarts=$($st.Restarts) $($st.Error)".Trim()
        Write-Host "  $line" -ForegroundColor Yellow
        [void]$diagnosis.Add($line)
        if ($st.Id) {
            $logs = Run "docker compose logs --no-color --tail 200 $s" -Quiet
            $key = @($logs.Out -split "`n" | Where-Object { $_ -match "error|exception|traceback|fatal|failed|refused|exited|allocated|denied|killed|out of memory" } | Select-Object -Last 8)
            foreach ($k in $key) { Write-Host "    $k"; [void]$diagnosis.Add("    $k") }
        }
    }
}
function Port-Busy([int]$p) {
    $busy = $false
    try { if (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction Stop) { $busy = $true } } catch { }
    if (-not $busy) {
        try { $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $p); $l.Start(); $l.Stop() } catch { $busy = $true }
    }
    return $busy
}
function Port-Owner([int]$p) {
    $c = Out-Of "docker ps --format ""{{.Names}} {{.Ports}}""" 1
    $hit = @($c -split "`n" | Where-Object { $_ -match ":$p->" })
    if ($hit.Count -gt 0) { return "Docker container " + ($hit[0] -split " ")[0] }
    try {
        $conn = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction Stop | Select-Object -First 1
        return "process " + (Get-Process -Id $conn.OwningProcess -ErrorAction Stop).ProcessName
    } catch { return "another program" }
}
function Free-Port([int]$preferred) {
    for ($p = $preferred; $p -lt $preferred + 50; $p++) { if (-not (Port-Busy $p)) { return $p } }
    return 0
}
# Copy the check scripts into the API container. Needed again after the container is recreated
# (e.g. restarted with different environment), because a new container starts without them.
function Copy-Scripts {
    $ok = $true
    foreach ($f in @("smoke_test.py", "e2e_checks.py")) {
        $r = Run "docker compose cp scripts/$f api:/tmp/$f" -Quiet
        if ($r.Code -ne 0) { $ok = $false; Note-Errors "docker compose cp $f" $r.Out | Out-Null }
    }
    return $ok
}
function Skip-Rest($reason) {
    foreach ($n in @("smoke test (16 checks, via nginx)", "Customs hold", "flat deposit not held", "attacker evolution (arena)",
                     "adapt refused without model-engineer sign-in", "defender adapts", "emerging-campaign detection", "data persists across API restart",
                     "privacy mode checks (API)", "privacy mode in PostgreSQL", "pytest (all suites, PostgreSQL)")) {
        Record $n "SKIP" "not run: $reason"
    }
}
function Finish {
    Section "Report"
    $sha = (git rev-parse HEAD 2>$null)
    $failed = @($results | Where-Object { $_.Result -eq "FAIL" }).Count
    $skipped = @($results | Where-Object { $_.Result -eq "SKIP" }).Count
    $passed = @($results | Where-Object { $_.Result -eq "PASS" }).Count
    $verdict = if ($failed -eq 0 -and $skipped -eq 0) { "ALL PASSED ($passed checks)" } else { "NOT PASSED: $failed failed, $skipped skipped, $passed passed" }
    $lines = @(
        "Chakravyuh local Docker validation",
        "Date:    $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')",
        "Machine: $env:COMPUTERNAME",
        "Commit:  $sha",
        "Ports:   web http://localhost:$WebPort   API http://localhost:$ApiPort",
        "Result:  $verdict",
        ""
    ) + ($results | Format-Table -AutoSize -Wrap | Out-String -Width 220).TrimEnd()
    if ($diagnosis.Count -gt 0) { $lines += @("", "Container diagnosis:") + $diagnosis }
    $lines += @(
        "",
        "Images:",
        (((Out-Of "docker images --format ""  {{.Repository}}:{{.Tag}}  {{.ID}}  {{.Size}}""" 1) -split "`n" | Where-Object { $_ -match "chakravyuh|postgres" }) -join "`n"),
        "",
        "Containers:",
        (Out-Of "docker compose ps -a --format ""  {{.Name}}  {{.Status}}  {{.Ports}}""" 1),
        "",
        "Full command log: validation-build.log"
    )
    $lines | Set-Content $Report -Encoding UTF8
    Get-Content $Report | Out-Host
    Write-Host "`nReport written to $Report"
    if ($failed -eq 0 -and $skipped -eq 0) {
        Write-Host "Stack left running: web http://localhost:$WebPort  API docs http://localhost:$ApiPort/docs  (stop: docker compose down)"
        exit 0
    }
    exit 1
}

$ApiPort = 8000; $WebPort = 8080

# 1. Docker access ---------------------------------------------------------------------------------
Section "1. Docker access"
$r = Run "docker version"; Record "docker version (client + engine)" ($r.Code -eq 0) "exit $($r.Code)"
$r = Run "docker compose version"; Record "docker compose available" ($r.Code -eq 0) "exit $($r.Code)"
$r = Run "docker info --format ""{{.ServerVersion}} {{.OperatingSystem}} cpus={{.NCPU}} mem={{.MemTotal}}"""
Record "docker engine reachable" ($r.Code -eq 0) "$($r.Out)"
if ($r.Code -ne 0) { Write-Host "Docker Engine is not reachable. Start Docker Desktop and run again." -ForegroundColor Red; Skip-Rest "Docker Engine not reachable"; Finish }

# 2-3. Repository state ----------------------------------------------------------------------------
Section "2-3. Repository"
$branch = (git rev-parse --abbrev-ref HEAD 2>$null)
$dirty = (git status --porcelain 2>$null | Measure-Object).Count
Record "on a git branch" ([bool]$branch) "branch '$branch', $dirty uncommitted file(s)"
if (-not $NoPull) {
    $r = Run "git pull --ff-only"
    Record "pulled latest from GitHub" ($r.Code -eq 0) "exit $($r.Code) (fast-forward only; local changes are never overwritten)"
}
Record "commit under test" $true "$(git rev-parse --short HEAD 2>$null)"

# 4. Configuration and a clean start ---------------------------------------------------------------
Section "4. Compose configuration and clean start"
$r = Run "docker compose config -q"
Record "docker-compose.yml valid" ($r.Code -eq 0) "exit $($r.Code)"
# Stop any previous Chakravyuh stack (data volume kept) so stale containers cannot interfere.
$r = Run "docker compose down --remove-orphans --timeout 20"
Record "previous stack stopped" ($r.Code -eq 0) "exit $($r.Code) (database volume kept)"
# Host ports: use 8000/8080 if free, otherwise the next free port. PostgreSQL publishes no host port.
foreach ($pair in @(@("API_HOST_PORT", 8000), @("WEB_HOST_PORT", 8080))) {
    $var = $pair[0]; $want = [int]$pair[1]
    $set = [Environment]::GetEnvironmentVariable($var)
    if ($set) { $want = [int]$set }
    if (Port-Busy $want) {
        $owner = Port-Owner $want
        $alt = Free-Port ($want + 1)
        if ($alt -eq 0) { Record "host port for $var" $false "port $want used by $owner and no free port nearby"; Skip-Rest "no free host port"; Finish }
        [Environment]::SetEnvironmentVariable($var, "$alt", "Process")
        Record "host port for $var" $true "$want is used by $owner, using $alt instead"
        $want = $alt
    } else {
        [Environment]::SetEnvironmentVariable($var, "$want", "Process")
        Record "host port for $var" $true "$want free"
    }
    if ($var -eq "API_HOST_PORT") { $ApiPort = $want } else { $WebPort = $want }
}
$Api = "http://localhost:$ApiPort"; $Web = "http://localhost:$WebPort"

# 5. Build -----------------------------------------------------------------------------------------
Section "5. Build images (first build downloads ~1 GB, allow 5-15 minutes)"
if ($SkipBuild) { Record "images built" "SKIP" "-SkipBuild given, reusing existing images" }
else {
    $t = Get-Date
    $r = Run "docker compose build --progress plain"
    $why = if ($r.Code -ne 0) { Note-Errors "docker compose build" $r.Out } else { "" }
    Record "images built" ($r.Code -eq 0) (("exit $($r.Code) in {0:N0}s" -f ((Get-Date) - $t).TotalSeconds) + $(if ($why) { ": $why" } else { "" }))
    if ($r.Code -ne 0) { Diagnose "build failed"; Skip-Rest "image build failed"; Finish }
}

# 6-7. Start the stack and wait for health ---------------------------------------------------------
Section "6-7. Start stack and wait until every container is healthy"
$t = Get-Date
$up = Run "docker compose up -d --wait --wait-timeout $StartTimeout"
$healthy = ($up.Code -eq 0) -and (Wait-Healthy $Services 30)
$why = if (-not $healthy) { Note-Errors "docker compose up" $up.Out } else { "" }
Record "stack started and healthy (db, api, web)" $healthy (("exit $($up.Code) in {0:N0}s" -f ((Get-Date) - $t).TotalSeconds) + $(if ($why) { ": $why" } else { "" }))
foreach ($s in $Services) {
    $st = Container-State $s
    Record "container '$s'" ($st.Status -eq "running" -and $st.Health -eq "healthy") "status=$($st.Status) health=$($st.Health) restarts=$($st.Restarts)"
}
if (-not $healthy) {
    if ($up.Out -match "port is already allocated|address already in use") {
        Write-Host "A host port is already in use; see the diagnosis below." -ForegroundColor Red
    }
    Diagnose "stack did not become healthy"
    Skip-Rest "stack not healthy"
    Finish
}
$apiState = Container-State "api"
Record "API started once (no crash loop)" ($apiState.Restarts -eq "0") "restarts=$($apiState.Restarts)"

$h = $null
try { $h = Invoke-RestMethod "$Api/health" -TimeoutSec 10 } catch { }
Record "API health on host :$ApiPort" ($null -ne $h -and $h.status -eq "ok") "$Api/health"
Record "models loaded in container" ($null -ne $h -and $h.model.loaded) "mode=$($h.model.mode) trained_at=$($h.model.trained_at)"
Record "web app on host :$WebPort" (Wait-Http "$Web/" 60) "$Web/"
Record "web -> API proxy (nginx)" (Wait-Http "$Web/health" 60) "$Web/health"
$arts = Out-Of "docker compose exec -T api python -c ""import os; print(' '.join(sorted(os.listdir('artifacts'))))"""
$need = @("campaigns.json", "fusion.pkl", "meta.json", "payee_scores.json", "policy.json", "scamseq.pt", "tagger.pkl")
$missing = @($need | Where-Object { $arts -notmatch [regex]::Escape($_) })
Record "model artifacts in API image" ($missing.Count -eq 0) $(if ($missing.Count) { "missing: $($missing -join ', ')" } else { $arts })
$envOk = Out-Of "docker compose exec -T api python -c ""import os; print(os.environ.get('DATABASE_URL','').split('@')[-1])"""
Record "API configured for PostgreSQL" ($envOk -eq "db:5432/chakravyuh") "DATABASE_URL host=$envOk"
$dbv = Sql "select version()"
Record "PostgreSQL reachable" ([bool]$dbv) "$dbv"
$tables = Sql "select string_agg(table_name, ',' order by table_name) from information_schema.tables where table_schema='public'"
$needT = @("alerts", "events", "sessions")
$missT = @($needT | Where-Object { $tables -notmatch "\b$_\b" })
Record "database tables created by API" ($missT.Count -eq 0) "$tables"

# 8. Smoke test, through nginx (exercises the web container's proxy too) -----------------------------
Section "8. Smoke test"
if (-not (Copy-Scripts)) { Diagnose "could not copy test scripts into the API container"; Skip-Rest "test scripts not copied"; Finish }
$r = Run "docker compose exec -T api python /tmp/smoke_test.py http://web"
# smoke_test.py prints "  ok   <check>" for each passing check and "  FAIL <check>" otherwise.
$n = ([regex]::Matches($r.Out, "(?m)^\s*ok\s")).Count
$bad = @($r.Out -split "`n" | Where-Object { $_ -match "^\s*FAIL\s" } | ForEach-Object { $_.Trim() })
Record "smoke test (16 checks, via nginx)" (($r.Code -eq 0) -and ($n -eq 16)) ("exit $($r.Code), $n of 16 checks passed" + $(if ($bad) { ": " + ($bad -join "; ") } else { "" }))

# 9-10. End to end: regression checks, evolution, campaigns, persistence --------------------------
Section "9-10. End to end"
if (-not (Wait-Healthy $Services 60)) { Diagnose "a container became unhealthy during the smoke test"; Skip-Rest "stack unhealthy"; Finish }
$r = Run "docker compose exec -T api python /tmp/e2e_checks.py http://web"
$customs = ($r.Out -split "`n" | Where-Object { $_ -match "Customs scam held" } | Select-Object -First 1)
$flat = ($r.Out -split "`n" | Where-Object { $_ -match "Genuine flat deposit" } | Select-Object -First 1)
Record "Customs hold" ("$customs" -match "^\s*PASS") $(if ($customs) { "$customs".Trim() -replace "; trace.*$", "" } else { "no result, exit $($r.Code)" })
Record "flat deposit not held" ("$flat" -match "^\s*PASS") $(if ($flat) { "$flat".Trim() } else { "no result, exit $($r.Code)" })

try {
    $arena = Invoke-RestMethod -Method Post -Uri "$Api/v1/demo/arena" -ContentType "application/json" `
        -Body '{"generations":4,"population":24,"per_genome":2,"fresh":true}' -TimeoutSec 600
    $rates = ($arena.history | ForEach-Object { "{0:P0}" -f $_.detection_rate }) -join " -> "
    Record "attacker evolution (arena)" ($arena.history.Count -eq 4) "detection by generation: $rates"
    # Updating the live defender needs a MODEL_ENGINEER account. Create a throwaway one inside the API
    # container (password passed through the environment, never on a command line) and sign in.
    $code = 0
    try { Invoke-RestMethod -Method Post -Uri "$Api/v1/demo/arena/adapt" -TimeoutSec 60 | Out-Null }
    catch { $code = [int]$_.Exception.Response.StatusCode }
    Record "adapt refused without model-engineer sign-in" ($code -eq 401) "anonymous request got HTTP $code (expected 401)"
    $engEmail = "validator-engineer-{0}@example.com" -f ([guid]::NewGuid().ToString("N").Substring(0, 8))
    $env:CHAKRAVYUH_NEW_USER_PASSWORD = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
    $r = Run "docker compose exec -T -e CHAKRAVYUH_NEW_USER_PASSWORD api python -m app.manage create-user --email $engEmail --role MODEL_ENGINEER"
    $script:Web = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $script:Csrf = @{}
    try {
        $login = Invoke-RestMethod -Method Post -Uri "$Api/v1/auth/login" -ContentType "application/json" -WebSession $script:Web `
            -Body (@{ email = $engEmail; password = $env:CHAKRAVYUH_NEW_USER_PASSWORD } | ConvertTo-Json) -TimeoutSec 30
        $script:Csrf = @{ "X-CSRF-Token" = $login.csrf_token }
    } catch { Note-Errors "model engineer sign-in (create-user exit $($r.Code))" "$($_.Exception.Message)`n$($r.Out)" | Out-Null }
    Remove-Item Env:\CHAKRAVYUH_NEW_USER_PASSWORD -ErrorAction SilentlyContinue
    try {
        $d = Invoke-RestMethod -Method Post -Uri "$Api/v1/demo/arena/adapt" -WebSession $script:Web -Headers $script:Csrf -TimeoutSec 900
        Record "defender adapts" ($null -ne $d.detection_after) ("caught {0:P0} -> {1:P0}, false alarms {2:P1}, shipped={3}" -f `
            $d.detection_before, $d.detection_after, $d.legit_false_alarm_after, $d.accepted)
    } catch { Record "defender adapts" $false "$($_.Exception.Message)"; Diagnose "defender update request failed" }
} catch { Record "attacker evolution (arena)" $false "$($_.Exception.Message)"; Record "defender adapts" "SKIP" "arena failed"; Diagnose "arena request failed" }

try {
    $c = Invoke-RestMethod -Method Post -Uri "$Api/v1/campaigns/refresh" -WebSession $script:Web -Headers $script:Csrf -TimeoutSec 300
    Record "emerging-campaign detection" ($c.created -ge 1) "$($c.created) campaign(s) from $($c.unknown_sessions) unexplained sessions"
} catch { Record "emerging-campaign detection" $false "$($_.Exception.Message)"; Diagnose "campaign refresh failed" }

$before = Sql "select count(*) from sessions"
$r = Run "docker compose restart api"
$back = Wait-Healthy @("api") 180
$after = Sql "select count(*) from sessions"
$viaApi = -1
try { $viaApi = (Invoke-RestMethod "$Api/v1/metrics" -TimeoutSec 15).sessions } catch { }
$persistOk = $back -and (Is-Int $before) -and ([int]$before -gt 0) -and ($before -eq $after) -and ("$viaApi" -eq "$after")
Record "data persists across API restart" $persistOk "api healthy again=$back, sessions before=$before after=$after, via API=$viaApi"
if (-not $back) { Diagnose "API did not come back after restart"; Skip-Rest "API not healthy after restart"; Finish }

# Privacy mode: recreate the API with STORE_MESSAGE_TEXT=false and check the database itself.
$env:STORE_MESSAGE_TEXT = "false"
$r = Run "docker compose up -d --wait --wait-timeout 180 api"
$mode = Out-Of "docker compose exec -T api printenv STORE_MESSAGE_TEXT"
if ($r.Code -ne 0 -or -not (Wait-Healthy $Services 60) -or $mode -ne "false") {
    Record "privacy mode checks (API)" $false "API not healthy in privacy mode (exit $($r.Code), STORE_MESSAGE_TEXT=$mode)"
    Record "privacy mode in PostgreSQL" "SKIP" "API not in privacy mode"
    Diagnose "API failed to start in privacy mode"
} else {
    $since = Sql "select now()"
    if (-not (Copy-Scripts)) { Diagnose "could not copy test scripts into the recreated API container" }
    $r = Run "docker compose exec -T api python /tmp/e2e_checks.py http://localhost:8000 --privacy"
    $why = if ($r.Code -ne 0) { Note-Errors "privacy checks" $r.Out } else { "" }
    Record "privacy mode checks (API)" ($r.Code -eq 0) ("exit $($r.Code), STORE_MESSAGE_TEXT=$mode" + $(if ($why) { ": $why" } else { "" }))
    $leaked = Sql "select count(*) from events where created_at >= '$since' and type = 'MSG_RECV' and text is not null"
    $kept = Sql "select count(*) from events where created_at >= '$since' and (attrs::jsonb) ? '_client_tags'"
    Record "privacy mode in PostgreSQL" ((Is-Int $leaked) -and ([int]$leaked -eq 0) -and (Is-Int $kept) -and ([int]$kept -gt 0)) `
        "message texts stored=$leaked, derived tag rows kept=$kept"
}
Remove-Item Env:\STORE_MESSAGE_TEXT -ErrorAction SilentlyContinue
$r = Run "docker compose up -d --wait --wait-timeout 180 api"
if ($r.Code -ne 0 -or -not (Wait-Healthy $Services 60)) { Diagnose "API failed to come back in normal mode"; Record "pytest (all suites, PostgreSQL)" "SKIP" "stack unhealthy"; Finish }

# 11. Full test suite inside the API image, against the PostgreSQL container ---------------------
Section "11. Test suite (in the API image, against PostgreSQL)"
$exists = Sql "select 1 from pg_database where datname = 'chakravyuh_test'"
if ($exists -ne "1") { Run "docker compose exec -T db psql -U chakravyuh -d chakravyuh -c ""CREATE DATABASE chakravyuh_test""" | Out-Null }
$r = Run "docker compose exec -T -e TEST_DATABASE_URL=postgresql+psycopg://chakravyuh:chakravyuh@db:5432/chakravyuh_test api python -m pytest -q"
$summary = ($r.Out -split "`n" | Where-Object { $_ -match "passed|failed|error" } | Select-Object -Last 1)
Record "pytest (all suites, PostgreSQL)" ($r.Code -eq 0) "exit $($r.Code): $summary"

Finish
