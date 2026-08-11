<#
  One-shot: insert a status block in the 17 inherited .NET deep-dive files
  that don't have one yet. All 17 are already complete content (Done).
  We insert the block between the breadcrumb line and the next section.
#>
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\mastery-guide')

# Phase mapping per file (based on Learning Path placement)
$phaseMap = @{
    '01-net-fundamentals.md'         = 'Phase 1 — Language & Runtime Fluency'
    '02-dependency-injection.md'     = 'Phase 2 — Concurrency & DI'
    '03-async-and-threading.md'      = 'Phase 2 — Concurrency & DI'
    '04-middleware.md'               = 'Phase 3 — ASP.NET Core Fundamentals'
    '05-data-access.md'              = 'Phase 5 — Data & Persistence'
    '06-apis-and-microservices.md'   = 'Phase 3 — ASP.NET Core Fundamentals'
    '07-testing.md'                  = 'Phase 6 — API Mastery'
    '08-patterns-and-best-practices.md' = 'Phase 7 — Architecture & Patterns'
    '09-security.md'                 = 'Phase 4 — Auth & API Security'
    '10-caching.md'                  = 'Phase 5 — Data & Persistence'
    '11-signalr.md'                  = 'Phase 8 — Microservices & Messaging'
    '12-modern-csharp.md'            = 'Phase 1 — Language & Runtime Fluency'
    '13-exception-handling.md'       = 'Phase 6 — API Mastery'
    '14-httpclient-resilience.md'    = 'Phase 6 — API Mastery'
    '15-configuration.md'            = 'Phase 3 — ASP.NET Core Fundamentals'
    '16-interview-prep.md'           = 'Phase 11 — Craft & Interview Prep'
    '17-taskflow-mini-project.md'    = 'Phase 11 — Craft & Interview Prep'
    '18-version-history.md'          = 'Reference'
}

$deepDiveDir = Join-Path $root '01-foundations\01-net-core-deep-dive'
$today = (Get-Date).ToString('yyyy-MM-dd')

Get-ChildItem $deepDiveDir -Filter *.md | Where-Object { $_.Name -ne 'README.md' } | ForEach-Object {
    $file = $_.FullName
    $content = Get-Content $file -Raw -Encoding UTF8

    if ($content -match '(?m)^\|\s*Status\s*\|') {
        Write-Host "  - $($_.Name) (already has block)"
        return
    }

    $phase = $phaseMap[$_.Name]
    if (-not $phase) {
        Write-Host "  ? $($_.Name) (no phase mapping; skipping)" -ForegroundColor Yellow
        return
    }

    # Get last commit date
    $rawDate = & git log -1 --format=%cs -- $file 2>$null
    if ($rawDate) { $date = "$rawDate".Trim() } else { $date = $today }
    if ([string]::IsNullOrWhiteSpace($date)) { $date = $today }

    $statusValue = if ($_.Name -eq '18-version-history.md') { 'Reference' } else { 'Done' }
    $priority    = if ($_.Name -eq '17-taskflow-mini-project.md' -or $_.Name -eq '16-interview-prep.md') { 'Medium' } else { 'High' }

    $block = @"

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| $statusValue | $priority | $phase | $date |

"@

    # Insert after the breadcrumb line (the line starting with '> [Mastery Guide]')
    # If breadcrumb not found, insert after the H1.
    $newContent = [regex]::Replace($content, '(?m)^(> \[Mastery Guide\][^\r\n]*)\r?\n', "`$1`r`n$block", 1)
    if ($newContent -eq $content) {
        # Fallback: insert after H1 line
        $newContent = [regex]::Replace($content, '(?m)^(# [^\r\n]+)\r?\n', "`$1`r`n$block", 1)
    }

    [System.IO.File]::WriteAllText($file, $newContent, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "  + $($_.Name) -> $statusValue / $priority / $date"
}
