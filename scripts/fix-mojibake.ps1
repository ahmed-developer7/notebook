<#
  Fix mojibake from the previous status-block insertion.
  Em-dash (U+2014) bytes E2 80 94 written as UTF-8 but read as Win-1252
  display as three chars: U+00E2, U+20AC, U+0094 (or sometimes U+201D in
  variant code pages).
#>
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\mastery-guide')

# Build the mojibake patterns from char codes (avoid literal non-ASCII in source)
$mojibakePatterns = @(
    [string]::new(@([char]0x00E2, [char]0x20AC, [char]0x0094)),  # â€" (most common)
    [string]::new(@([char]0x00E2, [char]0x20AC, [char]0x201D))   # â€" alt
)
$emdash = [string]::new([char]0x2014)

$fixed = 0
Get-ChildItem $root -Recurse -Filter *.md |
    Where-Object { $_.FullName -notmatch '\\_templates\\' -and $_.FullName -notmatch '\\_reports\\' } |
    ForEach-Object {
        $file = $_.FullName
        $content = Get-Content $file -Raw -Encoding UTF8
        $changed = $false
        foreach ($p in $mojibakePatterns) {
            if ($content.Contains($p)) {
                $content = $content.Replace($p, $emdash)
                $changed = $true
            }
        }
        if ($changed) {
            [System.IO.File]::WriteAllText($file, $content, (New-Object System.Text.UTF8Encoding($false)))
            $fixed++
            Write-Host "  fixed: $($_.Name)"
        }
    }

Write-Host ""
Write-Host "Fixed mojibake in $fixed files." -ForegroundColor Green
