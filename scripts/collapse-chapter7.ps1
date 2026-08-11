# Collapse pass for Chapter 7 - wraps heavy sections in <details>
# Idempotent: detects already-wrapped sections and skips them.

$ErrorActionPreference = 'Stop'

$chapter = "d:\projects\whenthenonboarding\mastery-guide\07-frontend-integration"

$book   = [char]::ConvertFromUtf32(0x1F4D6)
$puzzle = [char]::ConvertFromUtf32(0x1F9E9)
$books  = [char]::ConvertFromUtf32(0x1F4DA)
$emdash = [char]0x2014

$sections = @(
    @{ HeadingPattern = '^## Interview Cross-Questioning Drill$';   Summary = "$book Click to expand $emdash cross-question chains (~15-20 min, cover answers and write cold)" },
    @{ HeadingPattern = '^## Walkthrough([ \t].*)?$';               Summary = "$book Click to expand $emdash worked walkthrough scenario" },
    @{ HeadingPattern = '^## Code & diagrams$';                     Summary = "$puzzle Click to expand $emdash code samples and diagrams" },
    @{ HeadingPattern = '^## Sources$';                             Summary = "$books Click to expand $emdash sources and further reading" }
)

function Wrap-Section {
    param([string]$content, [string]$headingPattern, [string]$summary)

    $lines = $content -split "`r?`n"
    $result = New-Object System.Collections.Generic.List[string]
    $i = 0
    $modified = $false

    while ($i -lt $lines.Count) {
        $line = $lines[$i]
        if ($line -match $headingPattern) {
            $result.Add($line) | Out-Null
            $i++

            while ($i -lt $lines.Count -and $lines[$i] -eq '') {
                $result.Add('') | Out-Null
                $i++
            }

            if ($i -lt $lines.Count -and $lines[$i] -match '^<details>') {
                continue
            }

            $sectionStart = $i
            while ($i -lt $lines.Count -and $lines[$i] -notmatch '^## ') {
                $i++
            }
            $sectionEnd = $i

            while ($sectionEnd -gt $sectionStart -and $lines[$sectionEnd - 1] -eq '') {
                $sectionEnd--
            }

            if ($sectionEnd -le $sectionStart) {
                continue
            }

            $result.Add('<details>') | Out-Null
            $result.Add("<summary>$summary</summary>") | Out-Null
            $result.Add('') | Out-Null
            for ($j = $sectionStart; $j -lt $sectionEnd; $j++) {
                $result.Add($lines[$j]) | Out-Null
            }
            $result.Add('') | Out-Null
            $result.Add('</details>') | Out-Null
            $result.Add('') | Out-Null
            $modified = $true
            continue
        }
        $result.Add($line) | Out-Null
        $i++
    }

    return @{ Content = ($result -join "`r`n"); Modified = $modified }
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$files = Get-ChildItem -Path $chapter -Filter "*.md" -Recurse | Where-Object { $_.Name -ne 'README.md' }

$report = @()

foreach ($file in $files) {
    $content = [System.IO.File]::ReadAllText($file.FullName, $utf8NoBom)
    $original = $content
    $changes = @()

    foreach ($s in $sections) {
        $r = Wrap-Section -content $content -headingPattern $s.HeadingPattern -summary $s.Summary
        if ($r.Modified) {
            $changes += $s.HeadingPattern
            $content = $r.Content
        }
    }

    $relPath = $file.FullName.Replace($chapter + '\', '')
    if ($content -ne $original) {
        [System.IO.File]::WriteAllText($file.FullName, $content, $utf8NoBom)
        $report += [pscustomobject]@{ File = $relPath; Status = 'updated'; Changes = ($changes -join '; ') }
    } else {
        $report += [pscustomobject]@{ File = $relPath; Status = 'no-change'; Changes = '' }
    }
}

$report | Format-Table -AutoSize | Out-String -Width 200 | Write-Host
