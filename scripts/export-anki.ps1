<#
.SYNOPSIS
  Export per-chapter Anki flashcard decks from Interview-ready summaries.

.DESCRIPTION
  Walks every topic file. From each "Interview-ready summary" section,
  extracts top-level bullet items as flashcards:

      Front:  the bold-prefixed term (or first sentence if no bold)
      Back:   the rest of the bullet, plus the source file as a tag

  Anki's plain-text import format: tab-separated, one card per line, with
  optional tags column. We emit:

      <front><TAB><back><TAB><tag>

  Output: decks/<chapter>.tsv (Anki-importable; tab is the field separator).

  How to import:
    1. Open Anki desktop.
    2. File → Import → choose decks/<chapter>.tsv.
    3. Set field separator to "tab", deck name to your choice, tags column = 3.
    4. Import.
#>

$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\mastery-guide')
$decksDir = Join-Path (Split-Path $root -Parent) 'decks'
if (-not (Test-Path $decksDir)) {
    New-Item -ItemType Directory -Path $decksDir -Force | Out-Null
}

function Extract-Section {
    param([string]$Content, [string]$HeadingName)
    $pattern = "(?ms)^##\s+$([regex]::Escape($HeadingName))\s*$\r?\n(.*?)(?=^#{1,2}\s|\z)"
    if ($Content -match $pattern) {
        return $matches[1].TrimEnd()
    }
    return $null
}

# Extract top-level bullets from a markdown section (only "- " or "* " at column 0
# or column 2). Skip nested bullets, code blocks, blank lines.
function Get-TopLevelBullets {
    param([string]$SectionText)
    $bullets = @()
    $current = $null
    $inFence = $false
    foreach ($line in ($SectionText -split "`n")) {
        $line = $line -replace "`r$", ''
        if ($line -match '^```') { $inFence = -not $inFence; continue }
        if ($inFence) {
            if ($current) { $current += "`n$line" }
            continue
        }
        # New top-level bullet
        if ($line -match '^[\-\*]\s+(.+)$') {
            if ($current) { $bullets += $current }
            $current = $matches[1]
        }
        # Continuation indented
        elseif ($line -match '^\s{2,}(.+)$' -and $current) {
            $current += ' ' + $matches[1].Trim()
        }
        # Blank line ends the current bullet
        elseif ($line.Trim() -eq '' -and $current) {
            $bullets += $current
            $current = $null
        }
        # Other non-bullet line (e.g. a paragraph between bullets) — flush
        elseif ($current -and $line.Trim() -ne '') {
            $bullets += $current
            $current = $null
        }
    }
    if ($current) { $bullets += $current }
    return $bullets
}

# Split a bullet into Front (term) and Back (definition).
# Heuristic: if the bullet starts with **bold text**, that's the Front;
# the remainder (with the bold stripped) is the Back. Otherwise, take the
# first sentence as the Front.
function Split-FrontBack {
    param([string]$Bullet)
    if ($Bullet -match '^\*\*([^*]+?)\*\*\s*[—\-\:]?\s*(.*)$') {
        $front = $matches[1].Trim().TrimEnd('.', ':')
        $back = $matches[2].Trim()
        return @{ Front = $front; Back = $back }
    }
    if ($Bullet -match '^\*\*([^*]+?)\*\*\s*(.*)$') {
        $front = $matches[1].Trim().TrimEnd('.', ':')
        $back = $matches[2].Trim()
        return @{ Front = $front; Back = $back }
    }
    # Fallback: split on first period or colon
    if ($Bullet -match '^([^\.:]{5,80})[\.:]\s+(.+)$') {
        return @{ Front = $matches[1].Trim(); Back = $matches[2].Trim() }
    }
    # Otherwise: front is the bullet, back is empty
    return @{ Front = $Bullet.Trim(); Back = '' }
}

# Collapse newlines/tabs in a field (Anki TSV is one card per line)
function Sanitize-Field {
    param([string]$Text)
    if ($null -eq $Text) { return '' }
    $t = $Text -replace '\s+', ' '
    $t = $t -replace '`', ''            # markdown backticks add no value in flashcards
    return $t.Trim()
}

# Build per-chapter card lists
$cardsByChapter = [ordered]@{}

Get-ChildItem $root -Recurse -Filter *.md |
    Where-Object {
        $_.FullName -notmatch '\\_templates\\' -and
        $_.FullName -notmatch '\\_reports\\' -and
        $_.Name -ne 'README.md' -and
        $_.Name -ne 'INTERVIEW_INDEX.md'
    } |
    Sort-Object FullName |
    ForEach-Object {
        $file = $_.FullName
        $rel = $file.Substring($root.Path.Length + 1).Replace('\','/')
        $chapter = ($rel -split '/')[0]
        $content = Get-Content $file -Raw -Encoding UTF8

        $summary = Extract-Section $content 'Interview-ready summary'
        if (-not $summary) { return }

        $bullets = Get-TopLevelBullets $summary
        if ($bullets.Count -eq 0) { return }

        # Tag = source file basename (replace dashes/digits with no-prefix)
        $stem = [IO.Path]::GetFileNameWithoutExtension($file)
        $tag = "mastery::$($chapter)::$stem"

        if (-not $cardsByChapter.Contains($chapter)) {
            $cardsByChapter[$chapter] = @()
        }

        foreach ($bullet in $bullets) {
            $split = Split-FrontBack $bullet
            $front = Sanitize-Field $split.Front
            $back = Sanitize-Field $split.Back
            if ([string]::IsNullOrWhiteSpace($front)) { continue }
            if ([string]::IsNullOrWhiteSpace($back)) {
                # Skip cards with no Back (would be useless in Anki)
                continue
            }
            $cardsByChapter[$chapter] += [pscustomobject]@{
                Front = $front
                Back = $back
                Tag = $tag
            }
        }
    }

# Write per-chapter TSV files
$totalCards = 0
foreach ($entry in $cardsByChapter.GetEnumerator()) {
    $deckPath = Join-Path $decksDir "$($entry.Key).tsv"
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.AppendLine("# Anki deck: $($entry.Key)")
    [void]$sb.AppendLine("# Format: Front<TAB>Back<TAB>Tag")
    [void]$sb.AppendLine("# Import in Anki: File > Import, separator = tab, tags col = 3.")
    foreach ($c in $entry.Value) {
        $line = "{0}`t{1}`t{2}" -f $c.Front, $c.Back, $c.Tag
        [void]$sb.AppendLine($line)
    }
    [System.IO.File]::WriteAllText($deckPath, $sb.ToString(), (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "  $($entry.Key): $($entry.Value.Count) cards -> $deckPath"
    $totalCards += $entry.Value.Count
}

Write-Host ""
Write-Host "Total cards: $totalCards across $($cardsByChapter.Count) chapters." -ForegroundColor Green
