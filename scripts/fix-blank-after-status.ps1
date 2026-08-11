<#
  One-shot repair: insert blank line between status-block value row and the
  next heading where it was eaten by add-review-dates.ps1's first run.
#>
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\mastery-guide')
$fixed = 0

Get-ChildItem $root -Recurse -Filter *.md |
    Where-Object { $_.FullName -notmatch '\\_templates\\' -and $_.FullName -notmatch '\\_reports\\' } |
    ForEach-Object {
        $file = $_.FullName
        $content = Get-Content $file -Raw -Encoding UTF8
        # Look for: a 4-column status value row immediately followed by ## or ### (no blank line)
        $pattern = '(?m)^(\|\s*[^|]+?\s*\|\s*[^|]+?\s*\|\s*[^|]+?\s*\|\s*\d{4}-\d{2}-\d{2}\s*\|)\s*\r?\n(#{1,6}\s)'
        if ($content -match $pattern) {
            $new = [regex]::Replace($content, $pattern, "`$1`r`n`r`n`$2")
            [System.IO.File]::WriteAllText($file, $new, (New-Object System.Text.UTF8Encoding($false)))
            $fixed++
        }
    }

Write-Host "Inserted missing blank line in $fixed files." -ForegroundColor Green
