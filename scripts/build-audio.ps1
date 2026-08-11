<#
.SYNOPSIS
  Turn mastery-guide markdown into listenable MP3s for offline study.

.DESCRIPTION
  Bootstraps a local .venv (gitignored), installs edge-tts + mutagen on first
  run, then hands off to scripts/md_to_audio.py.

  The guide is ~35% code blocks and ASCII diagrams, and most of its value sits
  inside collapsed <details> blocks. Browser read-aloud reads the diagrams as
  noise and skips the collapsed content. This strips the former and unwraps
  the latter.

  Output: audio/<chapter>/<topic>.mp3 with ID3 tags, plus a .txt sidecar of
  exactly what was spoken.

.PARAMETER File
  One markdown file.

.PARAMETER Chapter
  Chapter number prefix, e.g. 05.

.PARAMETER IndexOnly
  INTERVIEW_INDEX.md only -- summaries and pitfalls for the whole guide,
  ~65k words / ~7.3 h. The best place to start.

.PARAMETER All
  Every topic file. ~104 hours, ~2.1 GB, hours of wall clock.

.PARAMETER Samples
  Generate the same passage across candidate voices and speaking rates,
  then exit. Default voice is en-IN-PrabhatNeural.

.PARAMETER UrduPilot
  Generate one passage three ways -- Urdu voice on the untranslated English,
  a full Urdu translation, and Urdu-with-English-technical-terms -- then exit.
  An Urdu voice alone does not produce Urdu audio; the content has to be
  translated, and this is the cheap way to decide whether that is worth it.

.PARAMETER DryRun
  Write .txt sidecars only. No TTS calls, instant. Use this to tune the
  stripping rules by reading rather than listening.

.EXAMPLE
  pwsh scripts/build-audio.ps1 -Samples
.EXAMPLE
  pwsh scripts/build-audio.ps1 -File mastery-guide/05-microservices-and-messaging/06-kafka.md -DryRun
.PARAMETER SpeakFile
  Synthesize an already-prepared .txt verbatim, rather than stripping a
  markdown file. This is how the Urdu tracks are built: the English run emits
  a .txt of exactly what gets spoken, that file is translated, and the
  translation is fed back in here. Pair with -Voice ur-PK-AsadNeural.

.EXAMPLE
  pwsh scripts/build-audio.ps1 -IndexOnly -Voice en-GB-RyanNeural
.EXAMPLE
  pwsh scripts/build-audio.ps1 -SpeakFile audio/ur/06-kafka.txt `
       -Out audio/ur/05-microservices-and-messaging/06-kafka.mp3 `
       -Voice ur-PK-AsadNeural -Title 'Kafka (Urdu)' -Album 'Microservices and Messaging'
#>

[CmdletBinding(DefaultParameterSetName = 'Index')]
param(
    [Parameter(ParameterSetName = 'File')]     [string] $File,
    [Parameter(ParameterSetName = 'Chapter')]  [string] $Chapter,
    [Parameter(ParameterSetName = 'Index')]    [switch] $IndexOnly,
    [Parameter(ParameterSetName = 'All')]      [switch] $All,
    [Parameter(ParameterSetName = 'Samples')]  [switch] $Samples,
    [Parameter(ParameterSetName = 'Urdu')]     [switch] $UrduPilot,
    [Parameter(ParameterSetName = 'Speak')]    [string] $SpeakFile,
    [Parameter(ParameterSetName = 'Speak')]    [string] $Out,
    [Parameter(ParameterSetName = 'Speak')]    [string] $Title,
    [Parameter(ParameterSetName = 'Speak')]    [string] $Album,
    [Parameter(ParameterSetName = 'Speak')]    [int]    $Track = 1,

    # en-IN-PrabhatNeural chosen by ear over Ryan / Sonia / Andrew.
    [string] $Voice = 'en-IN-PrabhatNeural',
    [string] $Rate  = '-10%',
    [switch] $DryRun,
    [switch] $Force
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path $PSScriptRoot -Parent
$venv     = Join-Path $repoRoot '.venv'
$venvPy   = Join-Path $venv 'Scripts\python.exe'
$worker   = Join-Path $PSScriptRoot 'md_to_audio.py'

# The 'python' / 'python3' names are Microsoft Store stubs on this machine and
# fail with a Store redirect. The py launcher is the only reliable entry point.
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "The 'py' launcher was not found. Install Python from python.org."
}

if (-not (Test-Path $venvPy)) {
    Write-Host "Creating virtualenv at $venv ..." -ForegroundColor Cyan
    & py -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed." }
}

# Cheap presence check so we only pay for pip on the first run. Deliberately
# written so it never touches stderr -- redirecting a native command's stderr
# under ErrorActionPreference=Stop surfaces as a terminating NativeCommandError.
$probe = & $venvPy -c "import importlib.util as u; print('OK' if u.find_spec('edge_tts') and u.find_spec('mutagen') else 'MISSING')"
if ($probe -ne 'OK') {
    Write-Host "Installing edge-tts and mutagen ..." -ForegroundColor Cyan
    & $venvPy -m pip install --quiet --upgrade pip
    & $venvPy -m pip install --quiet edge-tts mutagen
    if ($LASTEXITCODE -ne 0) { throw "Dependency install failed." }
}

$argv = @()
switch ($PSCmdlet.ParameterSetName) {
    'File'    { $argv += @('--file', $File) }
    'Chapter' { $argv += @('--chapter', $Chapter) }
    'Index'   { $argv += '--index-only' }
    'All'     { $argv += '--all' }
    'Samples' { $argv += '--samples' }
    'Urdu'    { $argv += '--urdu-pilot' }
    'Speak'   {
        $argv += @('--speak-file', $SpeakFile, '--track', "$Track")
        if ($Out)   { $argv += @('--out', $Out) }
        if ($Title) { $argv += @('--title', $Title) }
        if ($Album) { $argv += @('--album', $Album) }
    }
}
$argv += @('--voice', $Voice, '--rate', $Rate)
if ($DryRun) { $argv += '--dry-run' }
if ($Force)  { $argv += '--force' }

& $venvPy $worker @argv
exit $LASTEXITCODE
