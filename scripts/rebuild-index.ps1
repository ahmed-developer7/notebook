<#
.SYNOPSIS
  Regenerate the master dashboard and Learning Path icons from topic files.

.DESCRIPTION
  Walks every topic .md under mastery-guide/, parses the status block, and:

  1. Rewrites the master README's progress dashboard table between
     <!-- AUTO-GENERATED:dashboard START --> ... END --> markers.
  2. Updates each Learning Path entry's status icon (✅ 🟢 🟡 ⚪) to
     reflect the current status of the linked file.

  Source of truth = each topic file's status block. Chapter READMEs and
  the master dashboard table are derived. Run after any status change.

.NOTES
  Status mapping:
    Done, Done (deep-dive), Reference → ✅
    Started                            → 🟢
    Partial                            → 🟡
    Not Started                        → ⚪
#>

$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\mastery-guide')

# --- 1. Walk topic files and build a lookup ---

# Map: full path -> hashtable { Status, Priority, Phase, Date, Chapter }
$topics = @{}

# Map: chapter-folder -> hashtable { Total, Done, Started, Partial, NotStarted }
$chapterCounts = [ordered]@{}

function Init-Counts {
    return @{ Total = 0; Done = 0; Started = 0; Partial = 0; NotStarted = 0 }
}

# Pattern: 4-column status block. Captures status / priority / phase / date.
# Header row + separator row + value row, in that order.
$statusPattern = '(?m)^\|\s*Status\s*\|\s*Priority\s*\|\s*Phase\s*\|\s*Last reviewed\s*\|[ \t]*\r?\n\|\s*-+\s*\|\s*-+\s*\|\s*-+\s*\|\s*-+\s*\|[ \t]*\r?\n\|\s*([^|\r\n]+?)\s*\|\s*([^|\r\n]+?)\s*\|\s*([^|\r\n]+?)\s*\|\s*([^|\r\n]+?)\s*\|'

function Get-StatusCategory {
    param([string]$Status)
    $s = $Status.Trim().ToLowerInvariant()
    if ($s -like 'done*' -or $s -eq 'reference') { return 'Done' }
    if ($s -eq 'started')                        { return 'Started' }
    if ($s -eq 'partial')                        { return 'Partial' }
    if ($s -eq 'not started')                    { return 'NotStarted' }
    return 'NotStarted'  # unknown → conservative
}

function Get-StatusIcon {
    param([string]$Category)
    switch ($Category) {
        'Done'       { return [string]::new([char]0x2705) }            # ✅
        'Started'    { return [string]::new([char]0xD83D, [char]0xDFE2) }  # 🟢
        'Partial'    { return [string]::new([char]0xD83D, [char]0xDFE1) }  # 🟡
        'NotStarted' { return [string]::new([char]0x26AA) }            # ⚪
        default      { return [string]::new([char]0x26AA) }
    }
}

# Build chapter-name lookup (top-level folders under mastery-guide, excluding _* and root README)
$chapterFolders = Get-ChildItem $root -Directory |
    Where-Object { $_.Name -notmatch '^_' } |
    Sort-Object Name

foreach ($cf in $chapterFolders) {
    $chapterCounts[$cf.Name] = Init-Counts
}

Get-ChildItem $root -Recurse -Filter *.md |
    Where-Object {
        $_.FullName -notmatch '\\_templates\\' -and
        $_.FullName -notmatch '\\_reports\\' -and
        $_.Name -ne 'README.md'
    } |
    ForEach-Object {
        $file = $_.FullName
        $content = Get-Content $file -Raw -Encoding UTF8
        $rel = $file.Substring($root.Path.Length + 1)
        $chapter = ($rel -split '[\\/]')[0]

        if ($content -match $statusPattern) {
            $status = $matches[1].Trim()
            $priority = $matches[2].Trim()
            $phase = $matches[3].Trim()
            $date = $matches[4].Trim()

            $cat = Get-StatusCategory $status
            $topics[$file] = @{
                Status = $status
                Category = $cat
                Priority = $priority
                Phase = $phase
                Date = $date
                Chapter = $chapter
            }

            if ($chapterCounts.Contains($chapter)) {
                $chapterCounts[$chapter].Total++
                $chapterCounts[$chapter][$cat]++
            }
        }
    }

# --- 2. Build the dashboard table ---

# Friendly chapter names from the top-level folder's README H1 (if present)
function Get-ChapterTitle {
    param([string]$ChapterFolder)
    $readme = Join-Path $root "$ChapterFolder\README.md"
    if (Test-Path $readme) {
        $first = (Get-Content $readme -TotalCount 1 -Encoding UTF8)
        if ($first -match '^#\s+(.+?)\s*$') { return $matches[1] }
    }
    return $ChapterFolder
}

$emoji_done       = [string]::new([char]0x2705)              # ✅
$emoji_started    = [string]::new(@([char]0xD83D, [char]0xDFE2))  # 🟢
$emoji_partial    = [string]::new(@([char]0xD83D, [char]0xDFE1))  # 🟡
$emoji_notstarted = [string]::new([char]0x26AA)              # ⚪

$rows = @()
$totals = Init-Counts
foreach ($entry in $chapterCounts.GetEnumerator()) {
    $name = Get-ChapterTitle $entry.Key
    $c = $entry.Value
    $rows += "| [$name](./$($entry.Key)/README.md) | $($c.Total) | $($c.Done) | $($c.Started) | $($c.Partial) | $($c.NotStarted) |"
    $totals.Total += $c.Total
    $totals.Done += $c.Done
    $totals.Started += $c.Started
    $totals.Partial += $c.Partial
    $totals.NotStarted += $c.NotStarted
}

$tableLines = @(
    "| Chapter | Topics | $emoji_done Done | $emoji_started Started | $emoji_partial Partial | $emoji_notstarted Not Started |"
    "|---|---:|---:|---:|---:|---:|"
)
$tableLines += $rows
$tableLines += "| **Total** | **$($totals.Total)** | **$($totals.Done)** | **$($totals.Started)** | **$($totals.Partial)** | **$($totals.NotStarted)** |"
$dashboardTable = $tableLines -join "`r`n"

# --- 3. Splice into master README between markers ---

$masterPath = Join-Path $root 'README.md'
$master = Get-Content $masterPath -Raw -Encoding UTF8

$dashPattern = '(?s)(<!-- AUTO-GENERATED:dashboard START -->\r?\n)(.*?)(\r?\n<!-- AUTO-GENERATED:dashboard END -->)'
if ($master -match $dashPattern) {
    $master = [regex]::Replace($master, $dashPattern, "`$1$dashboardTable`$3")
    Write-Host "Dashboard regenerated." -ForegroundColor Green
} else {
    Write-Host "WARNING: AUTO-GENERATED:dashboard markers not found in master README. Add them around the dashboard table." -ForegroundColor Yellow
}

# --- 4. Update Learning Path icons ---

# Each Learning Path entry looks like:
#   42. ✅ [Title](./path/to/file.md#optional-anchor)
# We update the icon based on the linked file's current status.
$lpPattern = '(?m)^(\s*\d+\.\s+)([^\s\[]+)(\s+\[[^\]]+\]\(\.\/(.+?)(?:#[^\)]*)?\))'

$icons = @($emoji_done, $emoji_started, $emoji_partial, $emoji_notstarted)
$iconClass = '(' + (($icons | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')'
$lpPatternFinal = "(?m)^(\s*\d+\.\s+)$iconClass(\s+\[[^\]]+\]\(\.\/([^)\#]+?)(?:#[^)]*)?\))"

$lpUpdates = 0
$master = [regex]::Replace($master, $lpPatternFinal, {
    param($m)
    $prefix = $m.Groups[1].Value
    $relPath = $m.Groups[3].Value.Trim()
    $rest = $m.Groups[2].Value  # we'll rebuild
    # Actually we need group order: 1=prefix, 2=icon, 3=link-section incl. relPath, 4=relPath
    $prefix = $m.Groups[1].Value
    $oldIcon = $m.Groups[2].Value
    $linkSection = $m.Groups[3].Value
    $relPath = $m.Groups[4].Value

    # If the link points at a sub-folder/README.md or is a sub-chapter pointer, look up via that path
    $absPath = Join-Path $root $relPath.Replace('/', [IO.Path]::DirectorySeparatorChar)
    if ($absPath.EndsWith([IO.Path]::DirectorySeparatorChar + 'README.md')) {
        # Sub-chapter: aggregate all child topics. ✅ if all done; 🟢 if any started; 🟡 if any partial; ⚪ if all not started
        $folder = Split-Path $absPath -Parent
        $children = $topics.GetEnumerator() | Where-Object { $_.Key.StartsWith($folder + [IO.Path]::DirectorySeparatorChar) }
        if ($children.Count -eq 0) {
            $newIcon = $oldIcon  # leave unchanged
        } else {
            $cats = @($children | ForEach-Object { $_.Value.Category })
            if ($cats -contains 'Started')  { $newIcon = $emoji_started }
            elseif ($cats -contains 'Partial') { $newIcon = $emoji_partial }
            elseif (($cats | Where-Object { $_ -ne 'Done' }).Count -eq 0) { $newIcon = $emoji_done }
            else { $newIcon = $emoji_notstarted }
        }
    } elseif ($topics.ContainsKey($absPath)) {
        $newIcon = Get-StatusIcon $topics[$absPath].Category
    } else {
        $newIcon = $oldIcon  # unknown — don't change
    }

    if ($newIcon -ne $oldIcon) { $script:lpUpdates++ }
    return "$prefix$newIcon$linkSection"
})

# --- 5. Write back ---
[System.IO.File]::WriteAllText($masterPath, $master, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ""
Write-Host "Topics indexed: $($topics.Count)"
Write-Host "Total: $($totals.Total) | Done: $($totals.Done) | Started: $($totals.Started) | Partial: $($totals.Partial) | Not Started: $($totals.NotStarted)"
Write-Host "Learning Path icon updates: $lpUpdates"
