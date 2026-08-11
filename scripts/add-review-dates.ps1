<#
.SYNOPSIS
  Add a 'Last reviewed' column to every topic file's status block.

.DESCRIPTION
  Walks every *.md in mastery-guide/. For each file with a status block of
  the form:

      | Status | Priority | Phase |
      |---|---|---|
      | <s> | <p> | <ph> |

  Adds a fourth column 'Last reviewed' populated with the file's last
  git commit date (YYYY-MM-DD). Files already containing a 4-column block
  are left alone (idempotent).

  Files without a status block are skipped silently.

.OUTPUT
  Reports updated/skipped counts.
#>

$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\mastery-guide')

# Pattern: 3-column status block (header / separator / value lines).
# We accept any whitespace between cells.
$blockPattern = @'
(?m)^\|\s*Status\s*\|\s*Priority\s*\|\s*Phase\s*\|[ \t]*\r?\n\|\s*-+\s*\|\s*-+\s*\|\s*-+\s*\|[ \t]*\r?\n\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|[ \t]*$
'@

$updated = 0
$skipped = 0
$alreadyDone = 0

Get-ChildItem $root -Recurse -Filter *.md |
    Where-Object { $_.FullName -notmatch '\\_templates\\' -and $_.FullName -notmatch '\\_reports\\' } |
    ForEach-Object {
        $file = $_.FullName
        $content = Get-Content $file -Raw -Encoding UTF8

        # Skip if 4-column block already present
        if ($content -match '(?m)^\|\s*Status\s*\|\s*Priority\s*\|\s*Phase\s*\|\s*Last reviewed\s*\|') {
            $alreadyDone++
            return
        }

        if ($content -notmatch $blockPattern) {
            $skipped++
            return
        }

        # Get file's last git commit date in ISO short form (YYYY-MM-DD)
        $rawDate = & git log -1 --format=%cs -- $file 2>$null
        if ($rawDate) { $date = "$rawDate".Trim() } else { $date = '' }
        if ([string]::IsNullOrWhiteSpace($date)) {
            # Untracked or new file — fall back to today
            $date = (Get-Date).ToString('yyyy-MM-dd')
        }

        # Replace the 3-col block with a 4-col block
        $newContent = [regex]::Replace($content, $blockPattern, {
            param($m)
            $s = $m.Groups[1].Value.Trim()
            $p = $m.Groups[2].Value.Trim()
            $ph = $m.Groups[3].Value.Trim()
            "| Status | Priority | Phase | Last reviewed |`r`n|---|---|---|---|`r`n| $s | $p | $ph | $date |"
        })

        # Write back as UTF-8 without BOM
        [System.IO.File]::WriteAllText($file, $newContent, (New-Object System.Text.UTF8Encoding($false)))
        $updated++
        Write-Host "  + $($_.Name) -> $date"
    }

Write-Host ""
Write-Host "Updated: $updated" -ForegroundColor Green
Write-Host "Already 4-column: $alreadyDone"
Write-Host "Skipped (no status block): $skipped"
