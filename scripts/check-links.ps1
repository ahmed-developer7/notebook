<#
.SYNOPSIS
  Validate every relative markdown link and anchor in mastery-guide/.

.DESCRIPTION
  Walks every *.md file under mastery-guide/. For each [text](path) or
  [text](path#anchor) link:
    - Skips external (http/https) and mailto: links.
    - Resolves the file path relative to the source.
    - If a fragment is present, slugifies all H1-H6 headings in the target
      file (GitHub-flavored rules) and checks the fragment matches one.

  Reports each broken link as: <source>:<line>: <link> -> <reason>.
  Exits 0 if clean, 1 if any broken links found.

.NOTES
  GitHub anchor slug rules used here:
    - lowercase
    - non-alphanumerics (except - and _) removed
    - spaces collapsed to single -
    - emoji/unicode kept lowercased
    - ` - ` between words becomes ---
#>

$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\mastery-guide')

function ConvertTo-GhSlug {
    param([string]$Heading)
    $s = $Heading.ToLowerInvariant()
    # Strip leading hashes + space
    $s = $s -replace '^#+\s*', ''
    # Decode HTML entities BEFORE stripping punctuation. A heading written as
    # `Progress&lt;T&gt;` renders as `Progress<T>`, which GitHub slugifies to
    # `progresst`. Stripping first instead yields `progresslttgt` and reports a
    # correct link as broken.
    $s = $s -replace '&lt;', '<' -replace '&gt;', '>' -replace '&quot;', '"' -replace '&#39;', "'" -replace '&amp;', '&'
    # Remove punctuation except space, -, _
    $s = $s -replace '[^\p{L}\p{Nd}\s\-_]', ''
    # Each whitespace char becomes a separate hyphen (GitHub keeps double-dashes from " & ", " - " etc.)
    $s = ($s -replace '\s', '-').Trim('-')
    return $s
}

function Get-FileSlugs {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return @() }
    $slugs = New-Object System.Collections.Generic.HashSet[string]
    $inFence = $false
    Get-Content $Path -Encoding UTF8 | ForEach-Object {
        $line = $_
        if ($line -match '^```') { $inFence = -not $inFence; return }
        if ($inFence) { return }
        if ($line -match '^(#{1,6})\s+(.+?)\s*$') {
            [void]$slugs.Add((ConvertTo-GhSlug $matches[2]))
        }
    }
    return $slugs
}

# Cache slugs per file (avoid re-parsing target files repeatedly)
$slugCache = @{}

function Get-CachedSlugs {
    param([string]$Path)
    $resolved = Resolve-Path -LiteralPath $Path -ErrorAction SilentlyContinue
    if (-not $resolved) { return $null }
    $key = $resolved.Path
    if (-not $slugCache.ContainsKey($key)) {
        $slugCache[$key] = Get-FileSlugs $key
    }
    return $slugCache[$key]
}

# Match markdown links: [text](url) — exclude images ![..]() if you want; for now include both
# Use a simple regex; not bulletproof for nested brackets but adequate for prose.
$linkPattern = '(?<!\!)\[(?<text>[^\]]+)\]\((?<url>[^)\s]+?)(?:\s+"[^"]*")?\)'

$broken = New-Object System.Collections.Generic.List[object]

Get-ChildItem $root -Recurse -Filter *.md |
    Where-Object { $_.FullName -notmatch '\\_templates\\' -and $_.FullName -notmatch '\\_reports\\' } |
    ForEach-Object {
    $sourceFile = $_.FullName
    $sourceDir  = $_.Directory.FullName
    $lineNum = 0
    $inFence = $false
    Get-Content $sourceFile -Encoding UTF8 | ForEach-Object {
        $lineNum++
        $line = $_
        if ($line -match '^```') { $inFence = -not $inFence; return }
        if ($inFence) { return }

        $rxMatches = [regex]::Matches($line, $linkPattern)
        foreach ($m in $rxMatches) {
            $url = $m.Groups['url'].Value
            # Skip external + mailto + tel + protocol-relative
            if ($url -match '^(https?:|mailto:|tel:|//)') { continue }

            # Split path and fragment
            $hashIx = $url.IndexOf('#')
            if ($hashIx -ge 0) {
                $path = $url.Substring(0, $hashIx)
                $frag = $url.Substring($hashIx + 1)
            } else {
                $path = $url
                $frag = $null
            }

            # Resolve target file
            if ([string]::IsNullOrEmpty($path)) {
                # Pure anchor — same file
                $targetFile = $sourceFile
            } else {
                # Strip query string if any
                $cleanPath = $path -replace '\?.*$', ''
                $targetFile = Join-Path $sourceDir $cleanPath
                try {
                    $targetFile = (Resolve-Path -LiteralPath $targetFile -ErrorAction Stop).Path
                } catch {
                    $broken.Add([pscustomobject]@{
                        Source = $sourceFile
                        Line   = $lineNum
                        Link   = $url
                        Reason = "target file not found: $cleanPath"
                    })
                    continue
                }
            }

            # If the target is a directory, look for README.md
            if (Test-Path $targetFile -PathType Container) {
                $readme = Join-Path $targetFile 'README.md'
                if (Test-Path $readme) {
                    $targetFile = $readme
                } else {
                    $broken.Add([pscustomobject]@{
                        Source = $sourceFile
                        Line   = $lineNum
                        Link   = $url
                        Reason = "directory has no README.md: $targetFile"
                    })
                    continue
                }
            }

            # Validate anchor if present
            if ($frag) {
                $slugs = Get-CachedSlugs $targetFile
                if (-not $slugs.Contains($frag)) {
                    $broken.Add([pscustomobject]@{
                        Source = $sourceFile
                        Line   = $lineNum
                        Link   = $url
                        Reason = "anchor '#$frag' not found in target"
                    })
                }
            }
        }
    }
}

if ($broken.Count -eq 0) {
    Write-Host "All links resolve cleanly." -ForegroundColor Green
    exit 0
} else {
    Write-Host "Broken links: $($broken.Count)" -ForegroundColor Red
    $broken | ForEach-Object {
        $relSource = $_.Source.Replace($root.Path + [IO.Path]::DirectorySeparatorChar, '')
        Write-Host "$relSource`:$($_.Line): $($_.Link) -> $($_.Reason)"
    }
    exit 1
}
